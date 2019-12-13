@echo off
pushd %~dp0..
call scripts\package-source.bat
call boxput.cmd boxtools-src.7z "/Code/Projects/Current Projects/BoxTools"
popd
