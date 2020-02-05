@echo off

SETLOCAL ENABLEEXTENSIONS

set "BOXTOOLS_DIR=%~dp0"

java -cp "%BOXTOOLS_DIR%boxtools.jar;%BOXTOOLS_DIR%lib\*" com.elektrika.boxtools.BoxTools ^
         "%BOXTOOLS_DIR%config\sample-boxtools.properties"  %*

ENDLOCAL
