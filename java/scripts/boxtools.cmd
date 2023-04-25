@echo off

SETLOCAL ENABLEEXTENSIONS

set BOXTOOLSDIR=%~dp0..

java -cp "%BOXTOOLSDIR%\build\boxtools;%BOXTOOLSDIR%\lib\*" ^
     com.elektrika.boxtools.BoxTools "%BOXTOOLSDIR%\config\sample-boxtools.properties" %*

ENDLOCAL
