# Meorav-App — notes for the next agent

Experimental Android TTS app ("Meorav (beta)", `app.hebrish.meorav`) that speaks typed text in
Daniel Rosehill's cloned voice on-device via qwentts.cpp. Read `README.md` first: it has the
model files, CDN keys, catalogue format, native build design, release steps and traps.

- Public repo (ships through the public Hebrish F-Droid repo). Never commit the keystore,
  passwords, R2 credentials or GGUFs (`.gitignore` blocks `*.jks`, `*.gguf`).
- Release only via `scripts/release-tag.sh <ver> --push`; releases must NOT be prereleases.
- New model version: CDN upload to a new immutable folder + `catalog/catalog.json` (voice first)
  + upload the catalogue to `models/meorav/catalog.json` (max-age=300). No app release needed.
  CDN uploads follow the `r2-upload` skill (Voice-Model-Training-Plugin) exactly.
- Moving the qwentts.cpp submodule: update the `QWEN_VERSION` string in
  `android/app/src/main/cpp/CMakeLists.txt`, re-check `qwen.h` (QT_ABI_VERSION 6 at 5916bf7),
  and re-run a local `./gradlew assembleRelease`.
- Don't touch the Hebrish dictation app (Hebrish-ASR/Hebrish-App) or its releases. Website and
  changelog changes are Daniel's. Not listed on Obtainium.
- Nothing here has run on a device yet (as of 2026-10-22). Record device results in README
  "Verified / not verified" with dates.
- Python: `uv` only. GitHub API quota is shared: poll CI with `gh run view <id> --json status,conclusion`
  at most once a minute; never `gh run watch` without `--interval 60`.
