#!/usr/bin/env bash
# Build the Meorav desktop .deb:  desktop/build-deb.sh  ->  desktop/dist/meorav_<version>-1_amd64.deb
#
# /usr/lib/meorav/meorav/ holds the Python app (pure Python: no python3 minor pin) and two builds
# of libmeorav.so (qwentts.cpp + ggml, CPU only, static libstdc++, needs only glibc):
#   lib/v3/  AVX2 + FMA + F16C   (Haswell 2013+, Zen 2017+)
#   lib/v2/  SSE4.2              (older CPUs; chosen at run time from /proc/cpuinfo)
# Qt, numpy and sounddevice come from apt. The voice (1.44 or 2.33 GB) is downloaded by the app
# from cdn.hebrish.app on first use, never at install time.
# The package does not ship the Hebrish APT sources/keyring: the `hebrish` package owns those
# conffiles, and two packages may not own one path. Users enrol with
# `curl -fsSL https://cdn.hebrish.app/apt/setup.sh | sudo sh -s meorav`.
# Needs: cmake, g++, dpkg-deb, the qwentts.cpp submodule checked out.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
PKG=meorav
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' meorav/__init__.py)
DEB_REVISION=${DEB_REVISION:-1}
ARCH=$(dpkg --print-architecture)
[ "$ARCH" = amd64 ] || { echo "only amd64 is supported (got $ARCH)" >&2; exit 1; }
[ -f ../third_party/qwentts.cpp/src/qwen.h ] || { echo "qwentts.cpp submodule missing: git submodule update --init --recursive" >&2; exit 1; }
JOBS=${JOBS:-$(nproc)}

for level in v3 v2; do
    cmake -S native -B "build/$level" -DMEORAV_X86_LEVEL=$level -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "build/$level" -j "$JOBS" --target meorav >/dev/null
    strip --strip-unneeded "build/$level/libmeorav.so"
done

BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
ROOT="$BUILD/root"
LIB="$ROOT/usr/lib/$PKG"
mkdir -p "$ROOT/DEBIAN" "$LIB" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/512x512/apps" "$ROOT/usr/share/doc/$PKG"
cp -r meorav "$LIB/"
find "$LIB" -name '__pycache__' -type d -prune -exec rm -rf {} +
for level in v3 v2; do
    install -Dm644 "build/$level/libmeorav.so" "$LIB/meorav/lib/$level/libmeorav.so"
done
install -m755 packaging/meorav "$ROOT/usr/bin/"
install -m644 packaging/meorav.desktop "$ROOT/usr/share/applications/"
install -m644 ../docs/icon-512.png "$ROOT/usr/share/icons/hicolor/512x512/apps/meorav.png"
install -m644 README.md "$ROOT/usr/share/doc/$PKG/"
install -m644 ../LICENSE "$ROOT/usr/share/doc/$PKG/copyright"
cat > "$ROOT/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VERSION-$DEB_REVISION
Architecture: $ARCH
Section: sound
Priority: optional
Installed-Size: $(du -sk "$ROOT/usr" | cut -f1)
Maintainer: Hebrish <info@hebrish.app>
Homepage: https://github.com/Hebrish-ASR/Meorav-App
Depends: libc6 (>= 2.35), python3 (>= 3.10), python3-pyside6.qtwidgets, python3-numpy, python3-sounddevice, libportaudio2
Description: Meorav (beta): text to speech in Daniel Rosehill's voice
 Experimental public test. Type text and hear it spoken in Daniel Rosehill's
 cloned voice (Irish-accented English with Hebrew words), generated on your
 computer's CPU with qwentts.cpp (Qwen3-TTS-12Hz-1.7B fine-tune). The voice
 (1.44 GB, or 2.33 GB at higher quality) is downloaded on first use. Speech
 can be slower than real time. Play the result or save it as WAV, or run
 "meorav --say TEXT -o out.wav" in a terminal.
 The app is MIT; the voice model is licensed for non-commercial use.
CTRL
mkdir -p dist
OUT="dist/${PKG}_${VERSION}-${DEB_REVISION}_${ARCH}.deb"
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "$OUT" >/dev/null
echo "Built: $OUT ($(du -h "$OUT" | cut -f1))"
