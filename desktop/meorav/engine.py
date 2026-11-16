"""ctypes binding for libmeorav.so / meorav.dll (desktop/native/meorav_c.cpp).

The package ships two builds of the library: ``v3`` (AVX2/FMA/F16C) and ``v2`` (SSE4.2). The
v3 build dies with SIGILL (Windows: illegal instruction) on a CPU without AVX2, so the choice is
made before loading, never by trying: /proc/cpuinfo on Linux, IsProcessorFeaturePresent on Windows.

Two ways to pick a voice, matching the two model kinds in the catalogue:
- custom_voice models (Meorav v2.2, "Meorav-Daniel"): a built-in speaker name (``speaker="daniel"``);
- base models (Meorav-Multi-Voice): a reference clip, 24 kHz mono (``ref_audio=load_wav_24k(...)``),
  used x-vector only (qwen_tts ``x_vector_only_mode=True``), the way the model was trained.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import numpy as np

FRAME_SEC = 0.08  # one qwentts cancel poll = one 12.5 Hz codec frame = 80 ms of audio

_SEARCH = [
    Path(os.environ["MEORAV_LIB_DIR"]) if os.environ.get("MEORAV_LIB_DIR") else None,
    Path(__file__).resolve().parent / "lib",          # installed: /usr/lib/meorav/meorav/lib
    Path(__file__).resolve().parents[1] / "build",    # source checkout: desktop/build/<level>
]


IS_WINDOWS = sys.platform == "win32"
LIB_NAME = "meorav.dll" if IS_WINDOWS else "libmeorav.so"


def cpu_level() -> str:
    if os.environ.get("MEORAV_CPU_LEVEL") in ("v2", "v3"):  # testing the fallback build
        return os.environ["MEORAV_CPU_LEVEL"]
    if IS_WINDOWS:
        # PF_AVX2_INSTRUCTIONS_AVAILABLE = 40 (Windows 10+; also implies OS support for the YMM
        # state). Windows has no FMA/F16C query: every AVX2 CPU shipped by Intel and AMD has both.
        try:
            return "v3" if ctypes.windll.kernel32.IsProcessorFeaturePresent(40) else "v2"
        except (AttributeError, OSError):
            return "v2"
    try:
        flags = next((ln for ln in open("/proc/cpuinfo") if ln.startswith("flags")), "")
    except OSError:
        return "v2"
    have = set(flags.split())
    return "v3" if {"avx2", "fma", "f16c"} <= have else "v2"


def find_library(level: str | None = None) -> Path:
    level = level or cpu_level()
    for base in filter(None, _SEARCH):
        # installed: lib/<level>/; source checkout: build/<level>/ (Linux), build/win-<level>/Release/ (MSVC)
        for cand in (base / level / LIB_NAME, base / f"win-{level}" / "Release" / LIB_NAME):
            if cand.is_file():
                return cand
    raise FileNotFoundError(f"{LIB_NAME} ({level}) not found in {[str(p) for p in _SEARCH if p]}")


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
        L.meorav_synthesize_ref.restype = ctypes.c_int
        L.meorav_synthesize_ref.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
            ctypes.c_longlong, ctypes.POINTER(ctypes.POINTER(ctypes.c_float)), ctypes.POINTER(ctypes.c_int)]
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
                   seed: int = -1, ref_audio: np.ndarray | None = None) -> tuple[np.ndarray, int]:
        """Built-in ``speaker`` (custom_voice models), or ``ref_audio`` (float32 mono 24 kHz, base
        models; ``speaker`` is then ignored)."""
        out = ctypes.POINTER(ctypes.c_float)()
        sr = ctypes.c_int(0)
        if ref_audio is not None:
            ref = np.ascontiguousarray(ref_audio, dtype=np.float32)
            n = self._L.meorav_synthesize_ref(self._h, text.encode(), lang.encode(),
                                              ref.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(ref),
                                              seed, ctypes.byref(out), ctypes.byref(sr))
        else:
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


def load_wav_24k(path: str | Path) -> np.ndarray:
    """Reads a PCM WAV (16-bit, mono or stereo) as float32 mono at 24 kHz, the speaker encoder's
    rate. The catalogue's reference clips are already 24 kHz mono 16-bit; other rates are
    linearly resampled (good enough for an x-vector, not for listening)."""
    import wave
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: need 16-bit PCM WAV")
        ch, sr = w.getnchannels(), w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 24000:
        n = int(round(len(x) * 24000 / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x
