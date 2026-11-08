"""meorav-say: speak text in the Meorav voice from the command line.

  meorav-say "Yalla, tachles: Bituach Leumi wants the form by Thursday." -o out.wav
  echo "text" | meorav-say - -o out.wav --play
  meorav-say --list                 # voices and quants in the catalogue, and what is downloaded
  meorav-say --download             # fetch the default model only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, core


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="meorav-say", description="Meorav (beta) text to speech, generated on this computer. "
                                 + core.BANNER, epilog="Voice model: non-commercial use, " + core.TERMS_URL)
    ap.add_argument("text", nargs="?", help='text to say, or "-" for stdin')
    ap.add_argument("-o", "--output", default="meorav.wav", help="output WAV (default: meorav.wav)")
    ap.add_argument("-q", "--quant", help="Q4_K_M (default) or Q8_0")
    ap.add_argument("--voice", help="voice id or version from the catalogue (default: the first, the newest)")
    ap.add_argument("-d", "--device", choices=list(core.DEVICES), default="auto",
                    help="auto (GPU via Vulkan if there is one, CPU otherwise), cpu or vulkan")
    ap.add_argument("--no-spell-numbers", action="store_true", help="keep digits as typed")
    ap.add_argument("--play", action="store_true", help="play the WAV when done")
    ap.add_argument("--list", action="store_true", help="list voices and quants, then exit")
    ap.add_argument("--download", action="store_true", help="download the model and exit")
    ap.add_argument("--offline", action="store_true", help="do not fetch the catalogue")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the engine log")
    ap.add_argument("--version", action="version", version=f"meorav-say {__version__}")
    a = ap.parse_args(argv)

    voices, src = core.load_catalog(refresh=not a.offline)
    if a.list:
        print(f"catalogue: {src}; models in {core.data_dir() / 'models'}")
        for v in voices:
            print(f"{v.id}  ({v.name})")
            for q in v.quants:
                state = "downloaded" if core.is_ready(v, q) else f"not downloaded, {core.human(q.total_bytes)}"
                print(f"  {q.id:8} {'default ' if q.default else ''}{state}  {q.note}")
        return 0
    try:
        v = core.find_voice(voices, a.voice)
        q = v.quant(a.quant)
    except KeyError as e:
        print(f"meorav-say: {e.args[0]}", file=sys.stderr)
        return 2

    if not core.is_ready(v, q):
        need = core.remaining_bytes(v, q)
        print(f"Downloading {v.name} {q.id} ({core.human(need)}) to {core.voice_dir(v)} ...", file=sys.stderr)

        def prog(done, total, name):
            print(f"\r  {done * 100 // total:3d}%  {core.human(done)} / {core.human(total)}  {name}   ",
                  end="", file=sys.stderr, flush=True)
        try:
            core.download(v, q, prog)
        except KeyboardInterrupt:
            print("\nInterrupted; run again to resume.", file=sys.stderr)
            return 130
        print("\n  verified (SHA-256)", file=sys.stderr)
    if a.download:
        return 0

    if a.text is None:
        ap.error("text is required (or --list / --download)")
    text = sys.stdin.read() if a.text == "-" else a.text
    print(core.BANNER, file=sys.stderr)
    eng = core.Engine()
    try:
        r = eng.synthesize(v, q, text, Path(a.output), a.device, spell=not a.no_spell_numbers,
                           on_line=(lambda l: print(l, file=sys.stderr)) if a.verbose else None)
    except KeyboardInterrupt:
        eng.stop()
        return 130
    except (RuntimeError, ValueError) as e:
        print(f"meorav-say: {e}", file=sys.stderr)
        return 1
    print(f"{r.wav}: {r.audio_sec:.1f} s of speech in {r.gen_sec:.1f} s ({r.rtf:.2f}x real time, {r.device}, "
          f"{v.name} {q.id})", file=sys.stderr)
    if a.play:
        cmd = core.player_cmd(r.wav)
        if cmd:
            import subprocess
            subprocess.run(cmd)
        else:
            print("no player found (pw-play, paplay, aplay)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
