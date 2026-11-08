#!/usr/bin/env bash
# Runs INSIDE an ubuntu:24.04 container (see ../build-deb.sh). /src = repo (read-only), /out = output.
# Builds qwentts.cpp's qwen-tts with ggml as shared libs: dynamic backends (GGML_BACKEND_DL), every
# x86-64 CPU variant (picked at run time) and Vulkan. Then stages and builds meorav_<ver>_amd64.deb.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq --no-install-recommends build-essential cmake git ca-certificates libvulkan-dev glslc \
  spirv-headers dpkg-dev file >/dev/null

VER=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' /src/desktop/meorav/__init__.py)
B=/out/build-engine
cmake -S /src/third_party/qwentts.cpp -B $B -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON -DGGML_NATIVE=OFF \
  -DGGML_VULKAN=ON -DGGML_OPENMP=OFF -DGGML_CCACHE=OFF \
  -DCMAKE_INSTALL_RPATH='$ORIGIN' -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON > /out/cmake.log 2>&1
cmake --build $B --target qwen-tts -j "$(nproc)" > /out/build.log 2>&1

P=/out/pkg; rm -rf $P
L=$P/usr/lib/meorav
mkdir -p $L $P/usr/bin $P/usr/share/meorav $P/usr/share/applications $P/DEBIAN \
  $P/usr/share/icons/hicolor/512x512/apps $P/usr/share/icons/hicolor/192x192/apps $P/usr/share/doc/meorav
cp $B/qwen-tts $L/
cp -P $B/libggml*.so* $L/
strip --strip-unneeded $L/qwen-tts $L/*.so* 2>/dev/null || true
cp -r /src/desktop/meorav $L/meorav
find $L/meorav -name '__pycache__' -prune -exec rm -rf {} +
install -m755 /src/desktop/packaging/meorav /src/desktop/packaging/meorav-say $P/usr/bin/
install -m644 /src/catalog/catalog.json $P/usr/share/meorav/catalog.json
install -m644 /src/desktop/packaging/app.hebrish.meorav.desktop $P/usr/share/applications/
install -m644 /src/docs/icon-512.png $P/usr/share/icons/hicolor/512x512/apps/app.hebrish.meorav.png
install -m644 /src/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png $P/usr/share/icons/hicolor/192x192/apps/app.hebrish.meorav.png
install -m644 /src/LICENSE $P/usr/share/doc/meorav/copyright
cat >> $P/usr/share/doc/meorav/copyright <<'TXT'

---
App code: MIT (above). Engine: qwentts.cpp (MIT, https://github.com/ServeurpersoCom/qwentts.cpp) and
ggml (MIT). The Meorav voice model is NOT in this package: it is downloaded on first use and is for
non-commercial use only, under the Hebrish terms of use, https://hebrish.app/terms
TXT

# Library deps from the real binaries (libvulkan1 is dlopen'ed by the Vulkan backend: listed too).
mkdir -p /tmp/shl/debian && cd /tmp/shl && printf 'Source: meorav\n\nPackage: meorav\n' > debian/control
SHL=$(dpkg-shlibdeps -O --ignore-missing-info -l$L $L/qwen-tts $L/libggml*.so 2>/dev/null | sed 's/^shlibs:Depends=//')
[ -n "$SHL" ] || { echo "dpkg-shlibdeps found nothing"; exit 1; }
SIZE=$(du -sk $P/usr | cut -f1)
cat > $P/DEBIAN/control <<CTRL
Package: meorav
Version: $VER
Architecture: amd64
Maintainer: Daniel Rosehill <access@hebrish.app>
Installed-Size: $SIZE
Depends: $SHL, python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, libvulkan1
Recommends: pipewire-bin | pulseaudio-utils | alsa-utils, mesa-vulkan-drivers
Section: sound
Priority: optional
Homepage: https://hebrish.app/models/meorav
Description: Meorav (beta) - experimental text to speech in the Meorav voice
 Type text and hear it in Daniel Rosehill's cloned voice (Irish-accented
 English with Hebrew words), generated on this computer by qwentts.cpp
 (CPU, or GPU through Vulkan). Public test build, separate from the Hebrish
 dictation app. Also installs the meorav-say command line tool.
 .
 The voice model (1.4 GB or 2.3 GB) is downloaded from cdn.hebrish.app on
 first use and is for non-commercial use only (https://hebrish.app/terms).
CTRL
chmod -R u=rwX,go=rX $P
dpkg-deb --root-owner-group --build $P /out/meorav_${VER}_amd64.deb
rm -rf $P $B
[ -n "${HOST_UID:-}" ] && chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" /out
echo "DEB /out/meorav_${VER}_amd64.deb"
