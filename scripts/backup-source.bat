@echo off
pushd %~dp0..
call scripts\package-source.bat
call boxtools.cmd -put version 576502560816 boxtools-src.7z
popd
