#!/usr/bin/env bash
# Scan the full git history with a pinned, checksum-verified gitleaks binary.
# Used by the pre-commit hook and CI, so local and CI scans are identical.
set -euo pipefail

VERSION=8.30.1
case "$(uname -s)_$(uname -m)" in
  Darwin_arm64) PLATFORM=darwin_arm64 SHA256=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
  Linux_x86_64) PLATFORM=linux_x64    SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
  *) echo "gitleaks.sh: unsupported platform $(uname -s)_$(uname -m)" >&2; exit 1 ;;
esac

CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/light-labs/gitleaks-$VERSION"
BIN="$CACHE/gitleaks"

if [ ! -x "$BIN" ]; then
  mkdir -p "$CACHE"
  tarball="gitleaks_${VERSION}_${PLATFORM}.tar.gz"
  curl -sSfL -o "$CACHE/$tarball" \
    "https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${tarball}"
  if command -v sha256sum >/dev/null; then
    echo "$SHA256  $CACHE/$tarball" | sha256sum -c - >/dev/null
  else
    echo "$SHA256  $CACHE/$tarball" | shasum -a 256 -c - >/dev/null
  fi
  tar xzf "$CACHE/$tarball" -C "$CACHE" gitleaks
  rm "$CACHE/$tarball"
fi

exec "$BIN" git --no-banner --redact --exit-code 1 "$@" .
