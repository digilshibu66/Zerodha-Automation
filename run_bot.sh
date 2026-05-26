#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Ensure npm global binaries (openclaw) are in PATH
NPM_PREFIX=$(npm config get prefix 2>/dev/null || echo "$HOME/.npm-global")
if [ -d "$NPM_PREFIX/bin" ]; then
    export PATH="$NPM_PREFIX/bin:$PATH"
fi

# Ensure ~/.local/bin is in PATH (contains google-chrome symlink on Arch/CachyOS)
if [ -d "$HOME/.local/bin" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d "venv" ]; then
    echo "ERROR: Virtual environment not found. Run setup.sh first." >&2
    exit 1
fi

source venv/bin/activate
python core/runtime.py "$@"
