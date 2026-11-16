# Build the Meorav Windows portable zip:  desktop\build-windows.ps1  ->  desktop\dist\Meorav-<version>-windows-x64.zip
#
# Route (chosen 2026-11-16): the official CPython *embeddable* package plus pip-installed wheels,
# not PyInstaller. The app stays plain .py files next to a stock python.exe/pythonw.exe (no
# frozen bootloader, which antivirus tools often flag; same code path as the Linux .deb).
#
# Layout of the zip (one top folder, Meorav-<version>-windows-x64\):
#   Meorav.bat          starts the window (pythonw.exe, no console)
#   meorav-cli.cmd      the CLI: --say, --voice, --list-voices, --selftest
#   python\             CPython <PY_VERSION> embeddable + Lib\site-packages (PySide6-Essentials, numpy, sounddevice)
#   app\meorav\         the app; app\meorav\lib\v3\meorav.dll (AVX2/FMA/F16C), lib\v2\meorav.dll (SSE4.2)
# meorav.dll: qwentts.cpp + ggml, CPU only, MSVC with the static CRT, so it needs only system DLLs.
# Voices download on first use to %LOCALAPPDATA%\Meorav\models\.
#
# Needs: Visual Studio 2022 (C++), CMake, Python <PY_MINOR> on PATH (for pip --target; wheels must
# match the embedded interpreter's ABI), the qwentts.cpp submodule checked out.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$PY_VERSION = "3.12.10"   # last 3.12 release with a Windows embeddable zip
$PY_MINOR = "312"

$version = (Select-String -Path meorav\__init__.py -Pattern '^__version__ = "(.*)"$').Matches[0].Groups[1].Value
if (-not (Test-Path ..\third_party\qwentts.cpp\src\qwen.h)) { throw "qwentts.cpp submodule missing: git submodule update --init --recursive" }
$pyv = (python -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')")
if ($pyv -ne $PY_MINOR) { throw "need Python 3.12 on PATH for pip --target (got $pyv)" }

foreach ($level in "v3", "v2") {
    cmake -S native -B "build\win-$level" -A x64 "-DMEORAV_X86_LEVEL=$level"
    if ($LASTEXITCODE) { throw "cmake configure $level failed" }
    cmake --build "build\win-$level" --config Release --target meorav -j $env:NUMBER_OF_PROCESSORS
    if ($LASTEXITCODE) { throw "cmake build $level failed" }
}

$name = "Meorav-$version-windows-x64"
$stage = "build\win-stage\$name"
if (Test-Path build\win-stage) { Remove-Item -Recurse -Force build\win-stage }
New-Item -ItemType Directory -Force "$stage\python", "$stage\app" | Out-Null

$embed = "build\python-$PY_VERSION-embed-amd64.zip"
if (-not (Test-Path $embed)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip" -OutFile $embed
}
Expand-Archive $embed -DestinationPath "$stage\python"
# The ._pth file fixes sys.path (the current directory is never on it): stdlib zip, the
# interpreter folder, site-packages and the app folder.
@("python$PY_MINOR.zip", ".", "Lib\site-packages", "..\app", "import site") |
    Set-Content -Encoding ascii "$stage\python\python$PY_MINOR._pth"
python -m pip install --disable-pip-version-check --no-compile --only-binary=:all: `
    --target "$stage\python\Lib\site-packages" PySide6-Essentials numpy sounddevice
if ($LASTEXITCODE) { throw "pip install failed" }

Copy-Item -Recurse meorav "$stage\app\meorav"
Get-ChildItem -Recurse -Directory -Filter __pycache__ "$stage\app" | Remove-Item -Recurse -Force
foreach ($level in "v3", "v2") {
    New-Item -ItemType Directory -Force "$stage\app\meorav\lib\$level" | Out-Null
    Copy-Item "build\win-$level\Release\meorav.dll" "$stage\app\meorav\lib\$level\meorav.dll"
}
Set-Content -Encoding ascii "$stage\Meorav.bat" '@start "" "%~dp0python\pythonw.exe" -m meorav %*'
Set-Content -Encoding ascii "$stage\meorav-cli.cmd" '@"%~dp0python\python.exe" -m meorav %*'
Copy-Item ..\LICENSE "$stage\LICENSE.txt"
@"
Meorav (beta) $version for Windows (x64), portable
===================================================

Experimental Hebrish text to speech on your CPU (qwentts.cpp). No installer: unzip anywhere.

  Meorav.bat        open the window
  meorav-cli.cmd    command line, e.g.
                    meorav-cli.cmd --say "Shabbat shalom, see you after the chag." --voice josh -o out.wav
                    meorav-cli.cmd --list-voices

Voices: Daniel (Meorav v2.2, Daniel Rosehill's own voice) and, as a proof of concept,
Josh, Rivka, Nigel, Fiona and Bazza (Meorav-Multi-Voice). The model (about 1.4 GB, or 2.3 GB
at higher quality) is downloaded on first use to %LOCALAPPDATA%\Meorav\models.
Needs Windows 10 or 11 (64-bit) and 8 GB of RAM. Speech can be slower than real time.

The app is MIT (LICENSE.txt). The voice models are for non-commercial use, under
https://hebrish.app/terms. Source: https://github.com/Hebrish-ASR/Meorav-App
"@ | Set-Content -Encoding utf8 "$stage\README.txt"

New-Item -ItemType Directory -Force dist | Out-Null
$zip = "dist\$name.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
"Built: $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"
