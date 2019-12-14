@echo off
pushd %~dp0..
del boxtools-src.7z
"c:\Program Files\7-Zip\7z.exe" a boxtools-src.7z @scripts\srclist.txt -bb -xr!.*.marks -xr!.svn -xr!*.jar
popd
