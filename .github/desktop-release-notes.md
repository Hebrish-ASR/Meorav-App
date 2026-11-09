**0.1.0** · first Linux build of Meorav (beta), experimental public testing.

Type text and hear it in Daniel Rosehill's cloned voice (Irish-accented English with Hebrew words), generated on your computer's CPU with qwentts.cpp. Same voice and engine as the Android app: Meorav v2.2, Q4_K_M (1.44 GB, default) or Q8_0 (2.33 GB), downloaded on first use and checked by SHA-256.

- Speak, Stop, Play, Save WAV; real-time factor shown after each run.
- Command line: `meorav --say "text" -o out.wav`.
- Two CPU builds in one package: AVX2 for most machines since 2013, SSE4.2 for older ones, picked automatically.
- Expect speech to take longer than it lasts on most laptops. About 4 GB of RAM while speaking (Q4_K_M).

Install (Ubuntu 26.04, amd64): `curl -fsSL https://cdn.hebrish.app/apt/setup.sh | sudo sh -s meorav`, or download the `.deb` below and `sudo apt install ./meorav_0.1.0-1_amd64.deb`.

The app is MIT-licensed. The voice model is for non-commercial use (https://hebrish.app/terms).
