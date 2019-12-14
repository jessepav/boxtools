pushd %~dp0

java -cp ..\build\boxtools;..\bsh\bsh-2.1.0-SNAPSHOT.jar;..\lib\* bsh.Console 

popd
