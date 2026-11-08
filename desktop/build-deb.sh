#!/usr/bin/env bash
# Build meorav_<ver>_amd64.deb in a clean ubuntu:24.04 container (so it runs on 24.04 and newer).
# Needs docker. Heavy (compiles ggml, every CPU variant and the Vulkan shaders): run it on a build
# machine, not on Daniel's laptop. Output: desktop/dist/meorav_<ver>_amd64.deb
set -euo pipefail
cd "$(dirname "$0")/.."
git submodule update --init --recursive
mkdir -p desktop/dist
docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -v "$PWD":/src:ro -v "$PWD/desktop/dist":/out ubuntu:24.04 bash /src/desktop/packaging/build-inside.sh
ls -l desktop/dist/*.deb
