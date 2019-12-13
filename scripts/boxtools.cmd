@echo off

SETLOCAL ENABLEEXTENSIONS

set BOXTOOLSDIR=c:\Users\JP\Code\Projects\boxtools\trunk\build\dist

java -cp "%BOXTOOLSDIR%\boxtools.jar;%BOXTOOLSDIR%\lib\*" com.elektrika.boxtools.BoxTools %*

ENDLOCAL
