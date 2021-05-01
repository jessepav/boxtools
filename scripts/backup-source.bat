@echo off
pushd %~dp0..
echo Packaging source...
call scripts\package-source.bat 1> NUL 2>&1
echo Uploading source...
call boxtools.cmd -put version 576502560816 boxtools-src.7z
popd
