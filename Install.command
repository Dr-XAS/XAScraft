#!/bin/bash
# Per-user installation. Does not change shell profiles or system Python/Node.
set -euo pipefail
SOURCE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) TARGET=aarch64-apple-darwin; HASH=cfe454573412ff7380d15fc7dae5997ab53ffce72fce0a78e91ddbc84001acd2 ;;
  Darwin-x86_64) TARGET=x86_64-apple-darwin; HASH=bb7b805bdcf3d0bc8c74ceb94569e6b3e8aa35bd492acdbb9d46bf46d9d4ff6b ;;
  Linux-x86_64) TARGET=x86_64-unknown-linux-gnu; HASH=eadd9d27c134ab5ac1ffd4473b97a741407f3ea238288f03121fc4deddf90220 ;;
  *) echo "Supported: macOS (Intel/Apple Silicon) and Linux x86-64. Windows: use Install Windows.cmd."; exit 1 ;;
esac
if [[ "$(uname -s)" == Darwin ]]; then
  INSTALL_ROOT="${XASCRAFT_INSTALL_ROOT:-$HOME/Library/Application Support/XAScraft}"
else
  INSTALL_ROOT="${XASCRAFT_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/XAScraft}"
fi
umask 077
mkdir -p "$INSTALL_ROOT/runtime/uv" "$INSTALL_ROOT/cache"
UV="$INSTALL_ROOT/runtime/uv/uv"
if [[ ! -x "$UV" ]]; then
  BOOTSTRAP="$(mktemp -d "$INSTALL_ROOT/cache/bootstrap.XXXXXX")"
  trap 'rm -rf -- "$BOOTSTRAP"' EXIT
  echo "Preparing the private installer…"
  curl --fail --location --retry 3 --output "$BOOTSTRAP/uv.tar.gz" "https://github.com/astral-sh/uv/releases/download/0.13.1/uv-$TARGET.tar.gz"
  if command -v shasum >/dev/null 2>&1; then
    ACTUAL="$(shasum -a 256 "$BOOTSTRAP/uv.tar.gz" | cut -d ' ' -f 1)"
  else
    ACTUAL="$(sha256sum "$BOOTSTRAP/uv.tar.gz" | cut -d ' ' -f 1)"
  fi
  [[ "$ACTUAL" == "$HASH" ]] || { echo "Installer checksum verification failed."; exit 1; }
  tar -xzf "$BOOTSTRAP/uv.tar.gz" -C "$BOOTSTRAP"
  cp "$BOOTSTRAP/uv-$TARGET/uv" "$UV"
  chmod 700 "$UV"
fi
export UV_PYTHON_INSTALL_DIR="$INSTALL_ROOT/runtime/python"
export UV_CACHE_DIR="$INSTALL_ROOT/cache/uv"
export UV_NO_CONFIG=1
"$UV" python install --no-bin 3.12.14
PYTHON_BIN="$("$UV" python find --managed-python 3.12.14)"
"$PYTHON_BIN" "$SOURCE_DIR/installers/local/run.py" --root "$INSTALL_ROOT" install --source "$SOURCE_DIR" --uv "$UV" "$@"
echo "Installation complete. Open XAScraft from your applications."
