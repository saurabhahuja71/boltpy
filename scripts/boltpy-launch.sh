#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname -- "${script_dir}")"
cache_dir="${BOLTPY_UV_CACHE_DIR:-${TMPDIR:-/tmp}/boltpy-uv-cache}"

mkdir -p "${cache_dir}"
export UV_CACHE_DIR="${cache_dir}"

exec uv run --project "${project_dir}" boltpy "$@"
