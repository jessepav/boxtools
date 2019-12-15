@echo off
pushd %~dp0..
call scripts\package-source.bat
call boxput.cmd version 576502560816 boxtools-src.7z
popd
