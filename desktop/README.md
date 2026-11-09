# Meorav (beta) for Linux

Desktop version of the Meorav test app: type text, and it is spoken in Daniel Rosehill's cloned
voice (Irish-accented English with Hebrew words), generated **on the computer's CPU** with
[qwentts.cpp](https://github.com/ServeurpersoCom/qwentts.cpp). It uses the same engine, GGUF voice files
and catalogue (`catalog/catalog.json`, served at `https://cdn.hebrish.app/models/meorav/catalog.json`)
as the Android app. First release 0.1.0, 2026-11-09.

| | |
| --- | --- |
| Package | `meorav` (`.deb`, amd64), built for Ubuntu 26.04 |
| Distribution | The Hebrish APT repository (`https://cdn.hebrish.app/apt`, suite `stable`), next to `hebrish`; and GitHub releases `desktop-v<version>` of this repo |
| Install | `curl -fsSL https://cdn.hebrish.app/apt/setup.sh \| sudo sh -s meorav`, or `sudo apt install meorav` on a machine that already has the Hebrish repo |
| Voice | Downloaded on first use to `~/.local/share/meorav/models/<voice-id>/<quant>/`: Q4_K_M 1.44 GB (default) or Q8_0 2.33 GB, resumable, SHA-256 checked |
| Settings | `~/.config/meorav/config.json` (chosen quant, last text) |
| CLI | `meorav --say "text" -o out.wav [--quant Q8_0]`, `meorav --selftest` |

## Layout

- `native/meorav_c.cpp`: a flat C API (`meorav_init`, `meorav_synthesize`, `meorav_cancel`,
  `meorav_progress_frames`, ...) over `qwen.h`, the same call sequence as the Android JNI
  bridge, so Python never mirrors qwen.h's structs (their layout changes with `QT_ABI_VERSION`).
- `native/CMakeLists.txt`: builds `libmeorav.so` from the submodule's three core sources plus
  ggml, static, CPU only, `GGML_NATIVE=OFF`, static libstdc++ (the `.so` needs only glibc).
  `MEORAV_X86_LEVEL=v3` (AVX2/FMA/F16C) or `v2` (SSE4.2). The package ships both and
  `engine.cpu_level()` picks one from `/proc/cpuinfo`: a v3 build on a CPU without AVX2 would
  die with SIGILL, so it is never tried.
- `meorav/engine.py` (ctypes), `meorav/models.py` (catalogue, download, verify),
  `meorav/app.py` (PySide6 window), `meorav/__main__.py` (CLI).
- `build-deb.sh`: compiles both library builds and packages `/usr/lib/meorav`, `/usr/bin/meorav`,
  the desktop file and icon. Qt, numpy and sounddevice come from apt; the app is pure Python, so
  unlike `hebrish` there is no python3 minor pin.
- The package does **not** ship `/etc/apt/sources.list.d/hebrish.sources` or the keyring: the
  `hebrish` package owns those conffiles, and dpkg refuses two packages owning one path. That is
  why `setup.sh` takes the package name (`sh -s meorav`; default `hebrish`).

## Development

```
git submodule update --init --recursive
cmake -S desktop/native -B desktop/build/v3 -DMEORAV_X86_LEVEL=v3 && cmake --build desktop/build/v3 -j4
cd desktop && python3 -m meorav            # finds desktop/build/<level>/libmeorav.so
python3 -m pytest -q tests                  # download/resume/SHA tests, no model, no network
```

Do not run a synthesis on Daniel's laptop (daniellaptop): it is resource-constrained and model
inference is off limits there. The end-to-end check (download the Q4_K_M pair, speak one line,
report the real-time factor) runs in CI, job `deb`, step "Speak one line".

## Releasing

1. Bump `__version__` in `desktop/meorav/__init__.py`, write `.github/desktop-release-notes.md`
   (first line `**<version>**`), commit to `main`.
2. `git tag -a desktop-v<version> -m "Meorav (beta) for Linux <version>" && git push origin main desktop-v<version>`.
   Workflow `desktop.yml` builds the `.deb` in `ubuntu:26.04`, installs it, runs `--selftest`,
   speaks one line with the real voice, attests the `.deb` and creates the GitHub release with
   `--latest=false` (the Android release stays "Latest"; F-Droid only reads `vX.Y.Z` tags, so
   `desktop-v*` releases are invisible to it).
3. Publish to APT from the Hebrish-App repo (`Hebrish-ASR/Hebrish-App`, local
   `~/repos/github/audio-dictation/Hebrish-Dictation`):
   `gh release download desktop-v<ver> -R Hebrish-ASR/Meorav-App -p "*.deb" -D dist` then
   `with-secrets desktop/scripts/publish-apt.sh dist/meorav_<ver>-1_amd64.deb`. The script keeps
   the newest 3 versions **per package**, so `hebrish` and `meorav` never prune each other.

New voice versions need no desktop release: they arrive through the catalogue, as on Android.

## Verified / not verified

See the root README, "Verified / not verified", section "Desktop".
