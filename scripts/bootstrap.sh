#!/usr/bin/env sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"
python_bin=${PYTHON:-python3}
"$python_bin" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
if [ ! -x .venv/bin/python ]; then "$python_bin" -m venv .venv; fi
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m trailer_studio doctor
printf '%s\n' 'Ready. Run .venv/bin/trailer-studio --help'
