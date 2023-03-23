#!/bin/bash

BTDIR="$(realpath "$(dirname "$0")")"

export PYTHONPATH="$BTDIR${PYTHONPATH:+":$PYTHONPATH"}"
"$BTDIR/venv/bin/python" -m boxtools.cli "$@"
