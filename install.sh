#!/usr/bin/env bash
set -Eeuo pipefail

BOLT_STEP="starting"
trap 'status=$?; echo "[Bolt] ERROR during: $BOLT_STEP (exit $status)" >&2' ERR

REPO_URL="${BOLT_REPO_URL:-https://github.com/saurabhahuja71/boltpy.git}"
INSTALL_ROOT="${BOLT_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/bolt}"
BIN_DIR="${BOLT_BIN_DIR:-$HOME/.local/bin}"

python_is_compatible() {
  command -v "$1" >/dev/null 2>&1 &&
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
      >/dev/null 2>&1
}

find_python() {
  local candidate

  # Prefer an explicitly selected interpreter, then versioned names. A bare
  # python3 may point to an older system Python, so do not stop at its name.
  if [ -n "${PYTHON:-}" ]; then
    if python_is_compatible "$PYTHON"; then
      printf '%s\n' "$PYTHON"
      return 0
    fi
    echo "PYTHON=$PYTHON is not Python 3.12 or newer." >&2
    return 1
  fi

  for candidate in python3.15 python3.14 python3.13 python3.12 python3 python; do
    if python_is_compatible "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  # uv can download and manage a compatible Python without sudo.
  if command -v uv >/dev/null 2>&1; then
    echo "No compatible system Python found; installing Python 3.12 with uv..." >&2
    uv python install 3.12 >/dev/null
    candidate="$(uv python find 3.12)"
    if python_is_compatible "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  cat >&2 <<'EOF'
Bolt requires Python 3.12 or newer.
Install Python 3.12+ (or uv from https://docs.astral.sh/uv/) and retry.
You can also select an interpreter explicitly with: PYTHON=/path/to/python bash install.sh
EOF
  return 1
}

BOLT_STEP="detecting Python 3.12+"
PYTHON="$(find_python)"
echo "[Bolt] Using Python: $PYTHON"

BOLT_STEP="creating install directories"
echo "[Bolt] Preparing install directory: $INSTALL_ROOT"
mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
if [ -d "$INSTALL_ROOT/.git" ]; then
  BOLT_STEP="downloading latest Bolt source"
  echo "[Bolt] Updating source (Git may take a few minutes behind a proxy)..."
  git -C "$INSTALL_ROOT" fetch --depth 1 origin main
  git -C "$INSTALL_ROOT" reset --hard FETCH_HEAD
else
  BOLT_STEP="downloading Bolt source"
  echo "[Bolt] Downloading source (Git may take a few minutes behind a proxy)..."
  rm -rf "$INSTALL_ROOT"
  git clone --progress --depth 1 "$REPO_URL" "$INSTALL_ROOT"
fi
BOLT_STEP="creating isolated Python environment"
echo "[Bolt] Creating isolated Python environment..."
"$PYTHON" -m venv "$INSTALL_ROOT/.venv"
BOLT_STEP="upgrading pip"
echo "[Bolt] Upgrading pip..."
PIP_PROGRESS_BAR=on "$INSTALL_ROOT/.venv/bin/python" -m pip install --upgrade pip
BOLT_STEP="installing Bolt dependencies"
echo "[Bolt] Installing Bolt and dependencies (package downloads will be shown)..."
PIP_PROGRESS_BAR=on "$INSTALL_ROOT/.venv/bin/python" -m pip install "$INSTALL_ROOT"
BOLT_STEP="linking bolt executable"
ln -sfn "$INSTALL_ROOT/.venv/bin/bolt" "$BIN_DIR/bolt"
echo "[Bolt] Installed at $BIN_DIR/bolt"
"$BIN_DIR/bolt" --version
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Add this to your shell profile: export PATH=\"$BIN_DIR:$PATH\"" ;;
esac
