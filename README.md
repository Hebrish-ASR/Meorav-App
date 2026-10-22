# Meorav (beta)

Experimental Android text-to-speech app: type text, and it is spoken in Daniel Rosehill's cloned
voice (Irish-accented English with Hebrew words), generated **on the phone**. Public testing
build, separate from the Hebrish dictation (speech-to-text) app. A desktop version is planned,
not started.

| | |
| --- | --- |
| Package | `app.hebrish.meorav`, label "Meorav (beta)" |
| Platforms | Android 9+ (minSdk 28), targetSdk 36, **arm64-v8a only** |
| Distribution | GitHub releases of this repo, and the Hebrish F-Droid repo `https://fdroid.hebrish.app/repo` |
| Signing | the Hebrish app key (cert SHA-256 `5CF6822350D0B2FF124021A0DF10BEC1C63A6E5E6159FA6029507134A1446994`) |
| Engine | [qwentts.cpp](https://github.com/ServeurpersoCom/qwentts.cpp) (MIT), submodule `third_party/qwentts.cpp` pinned at `5916bf7` (2026-10-16), ggml `cc5df49a`, CPU backend |
| Model | Meorav v2.1: Qwen3-TTS-12Hz-1.7B full fine-tune, built-in speaker `daniel`; GGUFs on Hugging Face as `Hebrish/Meorav-GGUF` and on the Hebrish CDN |
| Licence | App code MIT (same as Hebrish-ASR/Hebrish-App). The voice model is non-commercial, under <https://hebrish.app/terms> |

Status (2026-10-22): v0.1.0 released (`Meorav-0.1.0.apk`, 2,990,858 bytes, SHA-256
`42a634df51a8eaef189f8f92912c3d8be0dcf9d4457bf9d7f923f885c89d1d7c`) and live in the Hebrish
F-Droid index. **Not yet run on a device.** See
"Verified / not verified" below.

## What the app does

One screen (`MainActivity.kt`):

- Persistent banner: "Experimental — public testing. Speech is generated on your phone and can be slow."
- Quant picker: Q4_K_M (default, 1.44 GB) or Q8_0 (2.33 GB, labelled "needs 12 GB+ RAM"; the
  app warns, but does not block, when the phone's RAM is below the catalogue's `min_ram_gb`).
- Download (sizes shown first; resumable; SHA-256 verified), Delete model.
- Text box, "Spell out numbers" (on by default: the model was trained on numbers written as
  words; `Numbers.kt`), Speak, Stop.
- After each run: generated seconds, generation time, real-time factor, model load time on the
  first run. Play again, Save WAV (system file picker), Share (WAV through `ShareProvider`).
- About: whose voice it is, non-commercial use, Hebrish terms, HF model link, qwentts.cpp credit.

No AndroidX and no third-party Kotlin dependencies (`android.useAndroidX=false`, like the Hebrish app).

## Model files and the catalogue

A voice is a **matching pair**: talker GGUF + codec (12 Hz tokenizer) GGUF of the same quant.
CDN keys are immutable (`public, max-age=31536000, immutable`); a new model version gets a new
folder, never an overwrite.

| Quant | File | Bytes | SHA-256 |
| --- | --- | --- | --- |
| Q4_K_M | `qwen-talker-1.7b-customvoice-Q4_K_M.gguf` | 1182631104 | `a24e414e8b388a69601bdd2930a235dda7663e782e144668c81cb6e62fdb4a53` |
| Q4_K_M | `qwen-tokenizer-12hz-Q4_K_M.gguf` | 254974752 | `cf3788b4d50aaa665fb6e57c170396aae03a3555fea52d2b5d0cda902d658039` |
| Q8_0 | `qwen-talker-1.7b-customvoice-Q8_0.gguf` | 2042834112 | `473171aeaf3db9edf7b47e79eb2038842389cb6f1b446900374151abdcfceda4` |
| Q8_0 | `qwen-tokenizer-12hz-Q8_0.gguf` | 291150624 | `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94` |

URL: `https://cdn.hebrish.app/models/meorav/v2.1/gguf/<file>` (R2 bucket `hebrish-cdn`, uploaded
2026-10-22 with the `r2-upload` skill in Voice-Model-Training-Plugin).

**Catalogue:** `catalog/catalog.json` (schema 1) lists voices → quants → files (role `talker` /
`codec`, url, size, sha256, `min_ram_gb`). It is

1. copied into the APK's assets at build time (`copyCatalog` task) as the offline fallback, and
2. published at `https://cdn.hebrish.app/models/meorav/catalog.json` (`public, max-age=300`).

On every launch the app fetches the remote copy; if it parses (schema 1, at least one voice) it is
cached in `filesDir/catalog.json` and used. The app uses the **first voice** in the list. So
shipping a new model version = upload its GGUFs to a new `v<x>/gguf/` folder, put it first in
`catalog.json`, upload the catalogue, commit. No APK release. Old files on the phone are not
cleaned up automatically (Delete model removes the current voice's files only).

Files live in `filesDir/models/<voice id>/`. A download goes to `<name>.part`, is hashed while
streaming, and is renamed to `<name>` only after size and SHA-256 match; "final file exists with
the right size" therefore means "verified". Resume uses `Range: bytes=<n>-` (the CDN answers 206,
checked 2026-10-22) after re-hashing the bytes already on disk. The download runs on the app's
worker thread, not a foreground service: if Android kills the app in the background, tap Resume.

## Native layer

`android/app/src/main/cpp/CMakeLists.txt` builds one `libmeorav.so`: ggml (static, CPU only),
qwentts.cpp's three core sources (`qwen.cpp`, `pipeline-tts.cpp`, `pipeline-codec.cpp`, the same
set as its `qwen-core` target) and `meorav_jni.cpp`, against the public C API `src/qwen.h`
(QT_ABI_VERSION 6). Kotlin side: `Native.kt`; threading and state: `Engine.kt` (one worker thread;
the model stays loaded until the quant changes or its files are deleted).

- `qt_init`: `max_batch 1`, `codec_chunk_sec 10` (upstream default 24; smaller bounds peak codec
  decode memory, at a ~-50 dB residual), device NULL (only CPU is compiled in).
- `qt_synthesize`: buffered mode, `lang "english"` (case-insensitive), `speaker "daniel"`, seed -1.
- **Progress without streaming:** qwentts polls `qt_tts_params.cancel` once per Talker decode
  step = one 12.5 Hz codec frame. The JNI counts the polls; frames / 12.5 = seconds generated.
  Checked on the laptop: 87 polls for 6.88 s of audio (6.96 s estimated). The same callback
  returns the Stop flag.
- CPU flags: `GGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16`, no OpenMP, `GGML_NATIVE OFF`. i8mm is
  deliberately off (SIGILL on cores without it; decode is matrix-vector work where it adds
  little). ggml's `GGML_CPU_ALL_VARIANTS` + `GGML_BACKEND_DL` would pick the best variant at
  runtime but needs the variant .so files packaged and found via dlopen search paths; not done.
- Threads: qwentts uses `hardware_concurrency()/2` (4 on an 8-core phone).
- 16 KB page alignment: `-Wl,-z,max-page-size=16384`; `zipalign -c -P 16` passes.

## Build

Prerequisites: JDK 17 or 21, Android SDK with platform 36, NDK `28.0.13004108`, CMake `3.22.1`
(`sdkmanager --install "ndk;28.0.13004108" "cmake;3.22.1"`).

```bash
git clone --recursive https://github.com/Hebrish-ASR/Meorav-App   # or: git submodule update --init --recursive
cd Meorav-App/android
echo "sdk.dir=$ANDROID_HOME" > local.properties
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ./gradlew assembleRelease   # debug-signed unless RELEASE_KEYSTORE is set
```

Signed locally: set `RELEASE_KEYSTORE` (path to the .jks), `RELEASE_KEYSTORE_PASSWORD`,
`RELEASE_KEY_ALIAS`, `RELEASE_KEY_PASSWORD` (same as the store password). A clean build takes
about a minute on the laptop; the APK is ~3 MB.

## Release

1. Edit `.github/release-notes.md`; it must start with `**<version>`.
2. `scripts/release-tag.sh <version> --push`: sets `versionName`, bumps `versionCode`, commits,
   pushes the annotated tag `v<version>`.
3. `.github/workflows/android.yml` builds, checks the APK's signer is the Hebrish key, attests
   provenance, and creates the GitHub release `Meorav (beta) <version>` with `Meorav-<version>.apk`.
   **Not a prerelease**: Hebrish-FDroid skips prereleases.
4. Hebrish-FDroid picks it up within the hour (scheduled check), or at once with
   `gh workflow run publish.yml -R Hebrish-ASR/Hebrish-FDroid`. Verify:
   `curl -s https://fdroid.hebrish.app/repo/index-v2.json | jq '.packages["app.hebrish.meorav"].versions[].manifest.versionName'`.

Secrets on this repo (set 2026-10-22): `RELEASE_KEYSTORE_B64`, `RELEASE_KEYSTORE_PASSWORD`,
`RELEASE_KEY_ALIAS` (`codeswitchvoice`). Source: `~/.android/keystores/codeswitch-voice-release.jks`
on Daniel's laptop; the `.txt` next to it is two labelled lines (`store/key password: …`,
`alias: …`), not a bare password, so extract the value before piping it to `gh secret set`.

## Verified / not verified (2026-10-22)

Verified:
- `libmeorav.so` cross-compiles for arm64 with NDK 28.0 (laptop, CMake directly and through Gradle);
  only system libs needed (`liblog`, `libm`, `libdl`, `libc`); 8 JNI exports.
- The exact C-API call sequence of `meorav_jni.cpp` on the laptop (x86 build of the same commit)
  with the Q4_K_M pair: `custom_voice`, 1 speaker (`daniel`), 10 languages; 6.9 s of audio in
  12.2 s (RTF 1.77), load 2.4 s, peak RSS 4.1 GB.
- All four GGUFs on the CDN: size via ranged GET (206, Content-Range totals match); full
  SHA-256 of the Q4_K_M pair re-downloaded from `cdn.hebrish.app` matches.

- v0.1.0 release: CI passed on the first run; not a prerelease; APK signer SHA-256 `5cf68223…6994`
  (apksigner), label "Meorav (beta)", native code arm64-v8a only; one build-provenance attestation
  (`gh api repos/Hebrish-ASR/Meorav-App/attestations/sha256:<digest>`).
- `https://fdroid.hebrish.app/repo/index-v2.json` lists `app.hebrish.meorav` 0.1.0 with that signer,
  and `/repo/Meorav-0.1.0.apk` is served (200, same size).
- `catalog.json` on the CDN is byte-identical to `catalog/catalog.json`.

Not verified (no arm64 device or emulator here):
- Anything on a phone: load, speed, RAM, download/resume, playback, save/share, UI layout.
- Whether 8 GB phones survive the ~4 GB peak (Android's low-memory killer may end the app).
- Phone speed. Expect several times slower than real time on a Dimensity 9000.

## Traps hit while building

- qwentts.cpp's top-level `CMakeLists.txt` can't be `add_subdirectory`'d: its macro uses
  `${CMAKE_SOURCE_DIR}/src` for includes and it builds a server, httplib and yyjson. Build the
  three core sources directly (see `cpp/CMakeLists.txt`).
- `GGML_MAX_NAME=128` must be defined **before** `add_subdirectory(ggml)`, or ggml and qwentts
  disagree on tensor-name length (tokenizer tensor names exceed 64).
- `version.h` is generated by qwentts' `tools/version.cmake` from git; this build writes it
  directly with the pinned hash. Update it when moving the submodule.
- ggml (`cc5df49a`) is itself a submodule of qwentts.cpp: check out with `--recursive`
  (`actions/checkout` `submodules: recursive`).
- The laptop's `gh` predates `gh attestation` ("unknown command"); check attestations with
  `gh api repos/Hebrish-ASR/Meorav-App/attestations/sha256:$(sha256sum Meorav-X.Y.Z.apk | cut -d' ' -f1)`.
- On the laptop `sdkmanager` exited 2 with "...location of your Java installation" because
  `JAVA_HOME` was unset; run it with `JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`.
