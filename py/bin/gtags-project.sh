#!/bin/bash
# Generates tag files for use with GNU Global

PROJDIR=$(realpath $(dirname "$0")/..)

cd $PROJDIR
rg --files -tpy > gtags.files
gtags -vi
