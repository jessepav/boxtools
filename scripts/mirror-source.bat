@echo off
pushd %~dp0..
call scripts\package-source.bat
copy /Y boxtools-src.7z w:\Backup\Code\
popd
