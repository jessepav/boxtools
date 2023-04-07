#!/bin/bash

export BOXTOOLS_APP_DIR="$(realpath "$(dirname "$0")")"

export PYTHONPATH="$BOXTOOLS_APP_DIR${PYTHONPATH:+":$PYTHONPATH"}"
"$BOXTOOLS_APP_DIR/venv/bin/python" -m boxtools.cli "$@"
