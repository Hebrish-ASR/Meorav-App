#!/usr/bin/env bash
# End-to-end check of a built .deb in a clean container (heavy: downloads 1.4 GB once and runs the
# model; use a build machine, never Daniel's laptop).
#   desktop/test-deb.sh desktop/dist/meorav_0.1.0_amd64.deb [ubuntu:24.04] [model-cache-dir]
# Installs the .deb with apt (so Depends must resolve), lists the catalogue, downloads Q4_K_M into
# the cache dir (kept between runs), synthesizes a code-switching line on the CPU, checks the WAV
# is long enough and not silent, and starts the GTK window under Xvfb for a screenshot.
set -euo pipefail
DEB=$(readlink -f "$1"); IMG=${2:-ubuntu:24.04}; CACHE=$(readlink -f "${3:-$HOME/.cache/meorav-test}")
mkdir -p "$CACHE" "$(dirname "$DEB")/test-out"
OUT=$(readlink -f "$(dirname "$DEB")/test-out")
GPU=(); [ -e /dev/dri ] && GPU=(--device /dev/dri)
docker run --rm "${GPU[@]}" -e HOST_UID="$(id -u)" -v "$DEB":/pkg/meorav.deb:ro -v "$CACHE":/data -v "$OUT":/out "$IMG" bash -c '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive XDG_DATA_HOME=/data
apt-get update -qq >/dev/null
apt-get install -y -qq /pkg/meorav.deb >/dev/null
apt-get install -y -qq xvfb x11-apps imagemagick sox >/dev/null
dpkg -s meorav | grep -E "^(Version|Depends):"
meorav-say --version
meorav-say --list
/usr/bin/time -v meorav-say "Yalla, tachles: Bituach Leumi wants the form by Thursday." -o /out/cpu.wav -d cpu 2> /out/cpu.log || { tail -30 /out/cpu.log; exit 1; }
grep -E "s of speech|Maximum resident" /out/cpu.log
soxi -D /out/cpu.wav; sox /out/cpu.wav -n stat 2>&1 | grep -E "RMS +amplitude|Maximum amplitude"
python3 - <<PY
import wave, struct, math
w = wave.open("/out/cpu.wav"); n = w.getnframes(); sr = w.getframerate()
d = struct.unpack("<%dh" % n, w.readframes(n)); rms = math.sqrt(sum(x*x for x in d) / n) / 32768
sec = n / sr; print(f"duration {sec:.2f} s, rms {rms:.4f}")
assert 2.0 < sec < 15.0, "duration not sane"; assert rms > 0.01, "silent"
PY
meorav-say "Yalla, tachles: Bituach Leumi wants the form by Thursday." -o /out/auto.wav -v 2> /out/auto.log; grep -E "s of speech|Vulkan|device" /out/auto.log | head -8 || true
(xvfb-run -s "-screen 0 800x700x24" bash -c "meorav & sleep 12; xwd -root -silent | convert xwd:- /out/window.png; kill %1") 2>/out/gui.log || true
ls -l /out
chown -R $HOST_UID /out /data
'
