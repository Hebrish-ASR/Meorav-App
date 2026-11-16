"""Entry point: `meorav` (window), `meorav --selftest` (no model),
`meorav --say TEXT -o out.wav [--voice josh] [--quant Q8_0]`, `meorav --list-voices`."""
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
    from . import voices
    missing = [v for v in voices.AVATARS if not voices.avatar_path(v)]
    print(f"avatars: {len(voices.AVATARS) - len(missing)}/{len(voices.AVATARS)}" + (f" (missing {missing})" if missing else ""))
    print(f"app: {Path(__file__).parent}")
    print("selftest ok")
    return 0


def _pick(cat: dict, voice_id: str | None, model_id: str | None) -> tuple[dict, dict]:
    """(model, speaker) from --voice / --model; default: the first model's first voice."""
    from . import models
    ms = models.models_of(cat)
    if model_id:
        ms = [m for m in ms if m["id"] == model_id]
        if not ms:
            raise SystemExit(f"no model {model_id}; have {[m['id'] for m in models.models_of(cat)]}")
    if voice_id:
        for m in ms:
            s = next((s for s in models.speakers_of(m) if s["id"] == voice_id), None)
            if s:
                return m, s
        raise SystemExit(f"no voice {voice_id}; try --list-voices")
    return ms[0], models.speakers_of(ms[0])[0]


def _list_voices() -> int:
    from . import models
    cat = models.fetch_catalog()
    for m in models.models_of(cat):
        tag = " [proof of concept]" if m.get("poc") else ""
        print(f"{m['id']}: {m['name']}{tag}")
        for s in models.speakers_of(m):
            print(f"  --voice {s['id']:<8} {s['name']}, {s.get('accent', '')}")
    return 0


def _say(text: str, out: str, quant_id: str | None, voice_id: str | None = None,
         model_id: str | None = None) -> int:
    """Synthesises one line from the command line (downloads the model first if needed)."""
    from . import engine, models
    cat = models.fetch_catalog()
    voice, spk = _pick(cat, voice_id, model_id)
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
    ref = engine.load_wav_24k(models.ref_path(voice, spk)) if spk.get("ref") else None
    t0 = time.monotonic()
    audio, sr = eng.synthesize(text, speaker=spk["id"], lang=voice.get("lang", "english"), ref_audio=ref)
    gen = time.monotonic() - t0
    engine.write_wav(out, audio, sr)
    secs = len(audio) / sr
    print(f"{voice['id']} voice {spk['id']} {quant['id']} ({engine.cpu_level()}): {secs:.1f} s audio in "
          f"{gen:.1f} s (RTF {gen / secs:.2f}), load {load:.1f} s -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="meorav", description="Meorav (beta): Hebrish text to speech on the CPU "
                                 "(Daniel Rosehill's voice, or the five Meorav-Multi-Voice voices).")
    ap.add_argument("--version", action="version", version=f"meorav {__version__}")
    ap.add_argument("--selftest", action="store_true", help="check the install (no model needed)")
    ap.add_argument("--say", metavar="TEXT", help="speak TEXT to a WAV file instead of opening the window")
    ap.add_argument("-o", "--output", default="meorav.wav", help="WAV path for --say (default meorav.wav)")
    ap.add_argument("--quant", help="quant id for --say (default: the catalogue default)")
    ap.add_argument("--voice", help="voice for --say: daniel, josh, rivka, nigel, fiona, bazza (see --list-voices)")
    ap.add_argument("--model", help="model id for --say (default: the one that has --voice)")
    ap.add_argument("--list-voices", action="store_true", help="list models and voices from the catalogue")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.list_voices:
        return _list_voices()
    if a.say:
        return _say(a.say, a.output, a.quant, a.voice, a.model)
    from .app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
