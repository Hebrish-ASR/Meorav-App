"""Entry point: `meorav` (window), `meorav --selftest` (no model), `meorav --say TEXT -o out.wav`."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

from . import __version__


def _selftest() -> int:
    """Checks the install without a model: library loads for this CPU, catalogue parses."""
    from . import engine
    level = engine.cpu_level()
    lib = engine.find_library(level)
    import ctypes
    L = ctypes.CDLL(str(lib))
    L.meorav_version.restype = ctypes.c_char_p
    print(f"meorav {__version__}; cpu {level}; lib {lib}; qwentts {L.meorav_version().decode()}")
    import PySide6  # noqa: F401  (the window's dependency)
    try:  # needs a running sound server; without one only playback is lost (Save WAV still works)
        import sounddevice
        print(f"audio: {sounddevice.query_hostapis(0)['name']}")
    except Exception as e:
        print(f"audio: unavailable ({str(e).splitlines()[0][:120]})")
    print(f"app: {Path(__file__).parent}")
    print("selftest ok")
    return 0


def _say(text: str, out: str, quant_id: str | None) -> int:
    """Synthesises one line from the command line (downloads the voice first if needed)."""
    from . import engine, models
    cat = models.fetch_catalog()
    voice = cat["voices"][0]
    quant = next((q for q in voice["quants"] if q["id"] == quant_id), None) if quant_id else \
        next((q for q in voice["quants"] if q.get("default")), voice["quants"][0])
    if quant is None:
        print(f"no quant {quant_id}; have {[q['id'] for q in voice['quants']]}", file=sys.stderr)
        return 2
    if not models.is_installed(voice, quant):
        last = [0.0]

        def prog(done, total, stage):
            if time.monotonic() - last[0] > 5 or done == total:
                last[0] = time.monotonic()
                print(f"  {stage}: {done / 1e6:.0f}/{total / 1e6:.0f} MB", file=sys.stderr)

        models.download(voice, quant, prog)
    t0 = time.monotonic()
    eng = engine.Engine(models.file_path(voice, quant, "talker"), models.file_path(voice, quant, "codec"))
    load = time.monotonic() - t0
    t0 = time.monotonic()
    audio, sr = eng.synthesize(text, speaker=voice.get("speaker", "daniel"), lang=voice.get("lang", "english"))
    gen = time.monotonic() - t0
    engine.write_wav(out, audio, sr)
    secs = len(audio) / sr
    print(f"{voice['id']} {quant['id']} ({engine.cpu_level()}): {secs:.1f} s audio in {gen:.1f} s "
          f"(RTF {gen / secs:.2f}), load {load:.1f} s -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="meorav", description="Meorav (beta): text to speech in Daniel Rosehill's voice, on the CPU.")
    ap.add_argument("--version", action="version", version=f"meorav {__version__}")
    ap.add_argument("--selftest", action="store_true", help="check the install (no model needed)")
    ap.add_argument("--say", metavar="TEXT", help="speak TEXT to a WAV file instead of opening the window")
    ap.add_argument("-o", "--output", default="meorav.wav", help="WAV path for --say (default meorav.wav)")
    ap.add_argument("--quant", help="quant id for --say (default: the catalogue default)")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.say:
        return _say(a.say, a.output, a.quant)
    from .app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
