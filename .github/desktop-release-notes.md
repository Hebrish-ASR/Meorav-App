**0.2.0** · five new voices (proof of concept) and a Windows build of Meorav (beta), experimental public testing.

- **Meorav-Multi-Voice** (proof of concept): Josh (American male), Rivka (American female), Nigel (British male), Fiona (British female) and Bazza (Australian male), from one model, `Hebrish/Meorav-Multi-Voice` v1.0. It was trained on too little data: Hebrew words do not always come out right, and gutturals such as the ch in chag are not always produced. Q4_K_M (about 1.4 GB, default) or Q8_0, downloaded on first use; the codec file is shared with Daniel's voice, so it is not downloaded twice.
- Daniel's voice (Meorav v2.2) is unchanged and stays the default.
- Voice picker with avatars, a model switch, and the command line `meorav --say "text" --voice josh -o out.wav` (`--list-voices` lists them).
- **Windows (x64)**: a portable zip, no installer. Unzip, then run `Meorav.bat` (window) or `meorav-cli.cmd` (command line). Models go to `%LOCALAPPDATA%\Meorav`. Needs Windows 10 or 11 and 8 GB of RAM.

Install on Ubuntu 26.04 (amd64): `curl -fsSL https://cdn.hebrish.app/apt/setup.sh | sudo sh -s meorav`, or `sudo apt install ./meorav_0.2.0-1_amd64.deb`. On Windows: download `Meorav-0.2.0-windows-x64.zip` below.

Expect speech to take longer than it lasts on most laptops. About 4 GB of RAM while speaking (Q4_K_M).

The app is MIT-licensed. The voice models are for non-commercial use (https://hebrish.app/terms).
