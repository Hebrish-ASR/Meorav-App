"""ctypes binding for libmeorav.so (desktop/native/meorav_c.cpp).

The package ships two builds of the library: ``v3`` (AVX2/FMA/F16C) and ``v2`` (SSE4.2). The
v3 build dies with SIGILL on a CPU without AVX2, so the choice is made from /proc/cpuinfo before
loading, never by trying.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

import numpy as np

FRAME_SEC = 0.08  # one qwentts cancel poll = one 12.5 Hz codec frame = 80 ms of audio

_SEARCH = [
    Path(os.environ["MEORAV_LIB_DIR"]) if os.environ.get("MEORAV_LIB_DIR") else None,
    Path(__file__).resolve().parent / "lib",          # installed: /usr/lib/meorav/meorav/lib
    Path(__file__).resolve().parents[1] / "build",    # source checkout: desktop/build/<level>
]


def cpu_level() -> str:
    try:
        flags = next((ln for ln in open("/proc/cpuinfo") if ln.startswith("flags")), "")
    except OSError:
        return "v2"
    have = set(flags.split())
    return "v3" if {"avx2", "fma", "f16c"} <= have else "v2"


def find_library(level: str | None = None) -> Path:
    level = level or cpu_level()
    for base in filter(None, _SEARCH):
        for cand in (base / level / "libmeorav.so", base / f"libmeorav-{level}.so"):
            if cand.is_file():
                return cand
    raise FileNotFoundError(f"libmeorav ({level}) not found in {[str(p) for p in _SEARCH if p]}")


class EngineError(RuntimeError):
    pass


class Cancelled(EngineError):
    pass


class Engine:
    """One loaded voice (talker + codec GGUF pair). One synthesis at a time."""

    def __init__(self, talker: str | Path, codec: str | Path, *, chunk_sec: float = 0.0,
                 lib: Path | None = None, verbose: bool = False):
        self.lib_path = lib or find_library()
        L = ctypes.CDLL(str(self.lib_path))
        L.meorav_version.restype = ctypes.c_char_p
        L.meorav_last_error.restype = ctypes.c_char_p
        L.meorav_set_verbose.argtypes = [ctypes.c_int]
        L.meorav_init.restype = ctypes.c_void_p
        L.meorav_init.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_float]
        L.meorav_free.argtypes = [ctypes.c_void_p]
        L.meorav_n_speakers.argtypes = [ctypes.c_void_p]
        L.meorav_speaker_name.restype = ctypes.c_char_p
        L.meorav_speaker_name.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.meorav_model_type.restype = ctypes.c_char_p
        L.meorav_model_type.argtypes = [ctypes.c_void_p]
        L.meorav_synthesize.restype = ctypes.c_int
        L.meorav_synthesize.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_longlong,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_float)), ctypes.POINTER(ctypes.c_int)]
        L.meorav_free_audio.argtypes = [ctypes.POINTER(ctypes.c_float)]
        self._L = L
        L.meorav_set_verbose(1 if verbose else 0)
        self._h = L.meorav_init(str(talker).encode(), str(codec).encode(), chunk_sec)
        if not self._h:
            raise EngineError(self.last_error())

    @property
    def version(self) -> str:
        return self._L.meorav_version().decode()

    def last_error(self) -> str:
        return (self._L.meorav_last_error() or b"").decode(errors="replace")

    @property
    def model_type(self) -> str:
        return self._L.meorav_model_type(self._h).decode()

    def speakers(self) -> list[str]:
        return [self._L.meorav_speaker_name(self._h, i).decode()
                for i in range(self._L.meorav_n_speakers(self._h))]

    def progress_seconds(self) -> float:
        """Seconds of audio generated so far in the running synthesis (safe from any thread)."""
        return self._L.meorav_progress_frames() * FRAME_SEC

    def cancel(self) -> None:
        self._L.meorav_cancel()

    def synthesize(self, text: str, *, speaker: str = "daniel", lang: str = "english",
                   seed: int = -1) -> tuple[np.ndarray, int]:
        out = ctypes.POINTER(ctypes.c_float)()
        sr = ctypes.c_int(0)
        n = self._L.meorav_synthesize(self._h, text.encode(), lang.encode(), speaker.encode(),
                                      seed, ctypes.byref(out), ctypes.byref(sr))
        if n <= 0:
            err = self.last_error()
            if n == -5 or err.startswith("cancelled"):
                raise Cancelled(err)
            raise EngineError(err or f"synthesis failed ({n})")
        try:
            audio = np.ctypeslib.as_array(out, shape=(n,)).copy()
        finally:
            self._L.meorav_free_audio(out)
        return audio, sr.value

    def close(self) -> None:
        if self._h:
            self._L.meorav_free(self._h)
            self._h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    import wave
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
