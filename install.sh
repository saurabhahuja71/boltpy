#!/usr/bin/env bash
set -euo pipefail

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

PYTHON="$(find_python)"

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
