#!/usr/bin/env bash
# Usage: scripts/release-tag.sh <version> [--push]
# Sets versionName=<version> and versionCode+1 in android/app/build.gradle.kts, commits that file
# and .github/release-notes.md (which must start with "**<version>"), and creates the annotated
# tag v<version>. CI's "Tag matches version" step rejects a tag that disagrees with versionName.
set -euo pipefail
cd "$(dirname "$0")/.."
VER=${1:?version, e.g. 0.1.1}; PUSH=${2:-}
F=android/app/build.gradle.kts
head -1 .github/release-notes.md | grep -q "^\*\*$VER" || { echo "release-notes.md must start with **$VER"; exit 1; }
code=$(sed -n 's/^ *versionCode = \([0-9]*\)$/\1/p' $F)
cur=$(sed -n 's/^ *versionName = "\(.*\)"$/\1/p' $F)
if [ "$cur" != "$VER" ]; then
  sed -i "s/^\( *versionCode = \)[0-9]*$/\1$((code + 1))/; s/^\( *versionName = \)\".*\"$/\1\"$VER\"/" $F
fi
git add $F .github/release-notes.md
git diff --cached --quiet || git commit -m "Release $VER"
git tag -a "v$VER" -m "Meorav (beta) $VER"
[ "$PUSH" = "--push" ] && git push origin HEAD "v$VER"
echo "tagged v$VER"
