#!/bin/bash

cd "$(realpath $(dirname "$0"))"

python -m venv venv
./venv/bin/python -m pip install -r requirements.txt
