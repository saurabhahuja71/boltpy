#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${BOLT_REPO_URL:-https://github.com/saurabhahuja71/boltpy.git}"
INSTALL_ROOT="${BOLT_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/bolt}"
BIN_DIR="${BOLT_BIN_DIR:-$HOME/.local/bin}"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Bolt requires Python 3.12 or newer; install Python and retry." >&2
  exit 1
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Bolt requires Python 3.12 or newer." >&2
  exit 1
fi

mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
if [ -d "$INSTALL_ROOT/.git" ]; then
  git -C "$INSTALL_ROOT" fetch --quiet --depth 1 origin main
  git -C "$INSTALL_ROOT" reset --quiet --hard FETCH_HEAD
else
  rm -rf "$INSTALL_ROOT"
  git clone --quiet --depth 1 "$REPO_URL" "$INSTALL_ROOT"
fi
"$PYTHON" -m venv "$INSTALL_ROOT/.venv"
"$INSTALL_ROOT/.venv/bin/python" -m pip install --quiet --upgrade pip
"$INSTALL_ROOT/.venv/bin/python" -m pip install --quiet "$INSTALL_ROOT"
ln -sfn "$INSTALL_ROOT/.venv/bin/bolt" "$BIN_DIR/bolt"
echo "Bolt installed at $BIN_DIR/bolt"
"$BIN_DIR/bolt" --version
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Add this to your shell profile: export PATH=\"$BIN_DIR:$PATH\"" ;;
esac
