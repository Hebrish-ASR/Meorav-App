# Meorav (beta) for Linux and Windows

Desktop version of the Meorav test app: type text, and it is spoken with Hebrew words mixed into
English, generated **on the computer's CPU** with [qwentts.cpp](https://github.com/ServeurpersoCom/qwentts.cpp).
It uses the same engine, GGUF files and catalogue (`catalog/catalog.json`, served at
`https://cdn.hebrish.app/models/meorav/catalog.json`) as the Android app. First release 0.1.0
(2026-11-09, Linux, Daniel's voice only); 0.2.0 (2026-11-16) added the five Meorav-Multi-Voice voices
and a Windows build.

| | |
| --- | --- |
| Linux | package `meorav` (`.deb`, amd64), built for Ubuntu 26.04; Hebrish APT repository (`https://cdn.hebrish.app/apt`, suite `stable`), next to `hebrish`. Install: `curl -fsSL https://cdn.hebrish.app/apt/setup.sh \| sudo sh -s meorav` |
| Windows | portable zip `Meorav-<ver>-windows-x64.zip` (Windows 10/11 x64): unzip, run `Meorav.bat` (window) or `meorav-cli.cmd` (CLI). No installer, not signed |
| Releases | GitHub releases `desktop-v<version>` of this repo (`.deb` + Windows zip), never "Latest" |
| Models | Downloaded on first use to `<data>/models/<model-id>/<quant>/` (reference clips: `<model-id>/voices/`), resumable, SHA-256 checked. `<data>` = `~/.local/share/meorav` (Linux), `%LOCALAPPDATA%\Meorav` (Windows); `MEORAV_DATA_DIR` overrides both |
| Settings | `~/.config/meorav/config.json` (Linux), `%LOCALAPPDATA%\Meorav\config.json` (Windows): model, voice per model, quant per model, last text |
| CLI | `meorav --say "text" -o out.wav [--voice josh] [--model <id>] [--quant Q8_0]`, `meorav --list-voices`, `meorav --selftest`. On Windows the same through `meorav-cli.cmd` |

## Models and voices (catalogue)

The catalogue's top-level `"voices"` list is really a list of **models**; the key keeps its name
because the Android app 0.1.0 parses it (`Catalog.kt`) and **uses `voices[0]`**. Two entries since
2026-11-16:

| Model id | Name | Kind | Voices (`--voice`) |
| --- | --- | --- | --- |
| `meorav-v2.2` (first: Android's model) | Meorav-Daniel v2.2 | qwentts `custom_voice`, built-in speaker `"speaker": "daniel"` | `daniel`: Daniel Rosehill, Irish-accented English |
| `meorav-multi-voice` | Meorav-Multi-Voice v1.0 | qwentts `base`, `"mode": "base"`, `"poc": true`; a voice = an x-vector reference clip | `josh` Josh (American male), `rivka` Rivka (American female), `nigel` Nigel (British male), `fiona` Fiona (British female), `bazza` Bazza (Australian male) |

Backward compatibility with Android 0.1.0 (checked against `Catalog.kt`, 2026-11-16): it calls
`getString("id"/"name"/"version"/"speaker")`, `getJSONArray("quants")` and, per file,
`role/name/url/size/sha256` on **every** entry, and a missing key rejects the whole remote file (it
then keeps its cached copy). So the Multi-Voice entry carries all of them (`"speaker": ""`), the new
keys (`mode`, `poc`, `speakers`, `speaker_name`, `speaker_accent`) are ignored by Android, and Daniel's
model stays first. `tests/test_models.py::test_repo_catalogue` checks this.

Each Multi-Voice speaker: `{"id", "name", "accent", "hf_file", "ref": {"name", "url", "size", "sha256"}}`.
The reference clips are the model's own `voices/*.wav` from `Hebrish/Meorav-Multi-Voice` at `50226a5`
(24 kHz, mono, 16-bit, 7–8 s), copied byte for byte to `https://cdn.hebrish.app/models/meorav-multi-voice/voices/`.
Names decided by Daniel on 2026-11-16. Avatars (illustrations, not likenesses) are bundled in
`meorav/assets/voices/<id>.png` (512 px; masters and provenance in Hebrish-Mgmt `brand/voices/`); a
voice without a bundled picture gets a lettered grey placeholder, so the catalogue can add voices
before an app release.

**Proof of concept.** Multi-Voice was trained on too little data: Hebrew code-switching did not
transfer fully, and gutturals (the ch in chag) are not always produced. The window shows a red
"Proof of concept" badge and a note whenever it is selected (`"poc": true` in the catalogue).

The 12 Hz codec GGUFs of Multi-Voice are byte-identical to Meorav v2.2's (the fine-tune does not
touch the codec): `models.download` copies (hard-links where possible) an installed file with the same
name, size and SHA-256 instead of downloading it again (`LOCAL_COPY_MIN` = 64 MB and up).

### Multi-Voice GGUFs (2026-11-16)

From `Hebrish/Meorav-Multi-Voice` at `50226a5` with qwentts.cpp `5916bf7`: unmodified `convert.py`
to F32, then its `quantize` tool (the v2.2 route, per the `Hebrish/Meorav-GGUF` card). Run on Modal,
not the laptop: `MODAL_PROFILE=danielrosehill with-secrets modal run scripts/gguf_modal.py`
(`scripts/gguf_modal.py`; HF token from the Modal secret `huggingface`, R2 keys from `with-secrets`,
uploads with the `r2-upload` skill's commands). CDN folder `models/meorav-multi-voice/` (one fixed folder
per model, `public, max-age=300`, as the skill prescribes).

| File (`https://cdn.hebrish.app/models/meorav-multi-voice/<file>`) | Bytes | SHA-256 |
| --- | --- | --- |
| `qwen-talker-1.7b-base-Q4_K_M.gguf` | 1219245248 | `9cca3ab238395e8707f8c3cc0697e080d76cec89372c843bb378c45129519c3c` |
| `qwen-talker-1.7b-base-Q8_0.gguf` | 2079448256 | `148c87b26929e0f3c8467dc7a37684a3b3451113064430655c3be002c5d6ba28` |
| `qwen-tokenizer-12hz-Q4_K_M.gguf` | 254974752 | `cf3788b4d50aaa665fb6e57c170396aae03a3555fea52d2b5d0cda902d658039` |
| `qwen-tokenizer-12hz-Q8_0.gguf` | 291150624 | `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94` |
| `voices/american-female.wav` | 341804 | `b1be1bc23bec91b2da3e2695c80699bf640442fa73955c8d26440b1eb8721529` |
| `voices/american-male.wav` | 384666 | `5e32e4566ba9c798c9f0046b040bc073835d8e7a1f5807a49582fac96f197c74` |
| `voices/australian-male.wav` | 328844 | `5f0963ac0cb7a1a70dcbfdd9dcc2825994afdc74d9a398814093261d484ff78b` |
| `voices/british-female.wav` | 341804 | `11fdca40eff9dd822dd61ec074dd2720412f23e5350707a1d10f502976ad1a3b` |
| `voices/british-male.wav` | 341804 | `90ab34a013a3b62971ac4d5e80887ae7942e46cf0b5c6a8bd74ff04a3ee04302` |

Checked 2026-11-16: both talkers have `qwen3-tts.model_type` = `base` and 76 `spk_enc.*` tensors (the
ECAPA-TDNN speaker encoder that x-vector cloning needs; the script refuses to upload a base talker
without them). The codec files are byte-identical to Meorav v2.2's (same SHA-256 as in the root
README table). Public `content-length` = local size for all nine objects, `cache-control: public,
max-age=300`; the five clips re-downloaded from the CDN hash to the values above (and match the HF
files). The talkers' SHA-256 were computed in the Modal container on the uploaded files and are
checked again by the app on every download (CI downloads the Q4_K_M pair). Modal run: 325 s on
4 CPU / 24 GiB (download 13 s, convert ~10 s, quantize ~170 s, rest hashing + upload);
not published to Hugging Face as a GGUF repo (only the CDN has them).

## Layout

- `native/meorav_c.cpp`: a flat C API (`meorav_init`, `meorav_synthesize`, `meorav_synthesize_ref`,
  `meorav_cancel`, `meorav_progress_frames`, ...) over `qwen.h`, the same call sequence as the
  Android JNI bridge, so Python never mirrors qwen.h's structs (their layout changes with
  `QT_ABI_VERSION`). `meorav_synthesize` passes a built-in `speaker` (custom_voice models);
  `meorav_synthesize_ref` passes `qt_tts_params.ref_audio_24k` / `ref_n_samples` only, which is
  qwentts' base-mode clone **mode A** (x-vector only; no `ref_text`, no ICL codes), the way
  Multi-Voice was trained (`x_vector_only_mode=True` in qwen_tts). The speaker embedding is
  recomputed from the clip on each call (ECAPA-TDNN over ~8 s, small next to the decode).
  `qt_extract_voice_ref`/`ref_spk_emb` (precomputed embedding) is not used: it also RVQ-encodes
  the clip, which mode A does not need.
- `native/CMakeLists.txt`: builds `libmeorav.so` (Linux) or `meorav.dll` (Windows, MSVC, static CRT
  `/MT`, `/utf-8`) from the submodule's three core sources plus ggml, static, CPU only,
  `GGML_NATIVE=OFF`; Linux links libstdc++ statically (the `.so` needs only glibc).
  `MEORAV_X86_LEVEL=v3` (AVX2/FMA/F16C) or `v2` (SSE4.2). Both are shipped and `engine.cpu_level()`
  picks one before loading: `/proc/cpuinfo` on Linux, `IsProcessorFeaturePresent(40)`
  (`PF_AVX2_INSTRUCTIONS_AVAILABLE`) on Windows; `MEORAV_CPU_LEVEL=v2` forces the fallback. A v3
  build on a CPU without AVX2 would die (SIGILL / illegal instruction), so it is never tried.
- `meorav/engine.py` (ctypes, `load_wav_24k`), `meorav/models.py` (catalogue, models/voices, download,
  verify, local codec copy), `meorav/voices.py` (bundled avatars), `meorav/app.py` (PySide6 window:
  model switch, quality, voice picker with avatar + name + accent, PoC badge), `meorav/__main__.py` (CLI).
- `build-deb.sh`: compiles both library builds and packages `/usr/lib/meorav`, `/usr/bin/meorav`,
  the desktop file and icon. Qt, numpy and sounddevice come from apt; the app is pure Python, so
  unlike `hebrish` there is no python3 minor pin.
- `build-windows.ps1`: compiles both `meorav.dll` builds and packages a portable zip with the
  **CPython 3.12.10 embeddable package** plus wheels installed with `pip --target` (PySide6-Essentials,
  numpy, sounddevice, which bundles PortAudio). Chosen over PyInstaller: no frozen bootloader
  (antivirus false positives), the same plain `.py` code path as Linux, and the CLI keeps a real
  console (`python.exe`) while the window uses `pythonw.exe`. `python312._pth` pins `sys.path`
  (stdlib zip, `Lib\site-packages`, `..\app`), so the current directory never shadows the app.
  `Meorav.bat` is a plain batch launcher (no icon, a console flashes for a moment).
- The `.deb` does **not** ship `/etc/apt/sources.list.d/hebrish.sources` or the keyring: the
  `hebrish` package owns those conffiles, and dpkg refuses two packages owning one path. That is
  why `setup.sh` takes the package name (`sh -s meorav`; default `hebrish`).

## Development

```
git submodule update --init --recursive
cmake -S desktop/native -B desktop/build/v3 -DMEORAV_X86_LEVEL=v3 && cmake --build desktop/build/v3 -j4
cd desktop && python3 -m meorav            # finds desktop/build/<level>/libmeorav.so (Windows: build/win-<level>/Release/meorav.dll)
python3 -m pytest -q tests                  # download/resume/SHA, clips, codec reuse, catalogue; no model, no network
```

Do not run a synthesis on Daniel's laptop (daniellaptop): it is resource-constrained and model
inference is off limits there. The end-to-end checks (download the Q4_K_M models, speak one line,
report the real-time factor) run in CI on tags and manual runs: job `deb` speaks `daniel` and
`josh`, job `windows` speaks `josh`; the WAVs are kept 14 days as artifacts `speak-linux` /
`speak-windows`.

## Releasing

1. Bump `__version__` in `desktop/meorav/__init__.py`, write `.github/desktop-release-notes.md`
   (first line `**<version>**`), commit to `main`.
2. `git tag -a desktop-v<version> -m "Meorav (beta) desktop <version>" && git push origin main desktop-v<version>`.
   Workflow `desktop.yml`: job `deb` builds the `.deb` in `ubuntu:26.04`, installs it, runs
   `--selftest`, speaks; job `windows` (`windows-latest`) builds the zip, unzips it outside the
   checkout, runs `--selftest` (v3 and forced v2), checks the v2 DLL has no `ymm` instructions
   (`dumpbin /disasm`), speaks. Both artifacts are attested; job `release` creates the GitHub
   release with both, `--latest=false` (the Android release stays "Latest"; F-Droid only reads
   `vX.Y.Z` tags, so `desktop-v*` releases are invisible to it).
3. Publish the `.deb` to APT from the Hebrish-App repo (`Hebrish-ASR/Hebrish-App`, local
   `~/repos/github/audio-dictation/Hebrish-Dictation`):
   `gh release download desktop-v<ver> -R Hebrish-ASR/Meorav-App -p "*.deb" -D dist` then
   `with-secrets desktop/scripts/publish-apt.sh dist/meorav_<ver>-1_amd64.deb`. The script keeps
   the newest 3 versions **per package**, so `hebrish` and `meorav` never prune each other.
   The Windows zip is only on the GitHub release (no CDN copy, no winget).

New model versions need no desktop release: they arrive through the catalogue, as on Android. A
new **kind** of model (another qwentts mode, or a non-qwentts engine such as the OmniVoice-based
`Hebrish/Meorav` v3) does: `models.models_of` skips entries it cannot run.

## Verified / not verified

See the root README, "Verified / not verified", section "Desktop".
