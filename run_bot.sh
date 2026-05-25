#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "ERROR: Virtual environment not found. Run setup.sh first." >&2
    exit 1
fi

source venv/bin/activate
python core/runtime.py "$@"
