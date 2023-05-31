#!/bin/bash

cd "$(realpath $(dirname "$0"))"

[[ ! -d venv ]] && python -m venv venv
[[ -f requirements.txt ]] && ./venv/bin/python -m pip install -r requirements.txt
