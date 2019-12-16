@echo off

SETLOCAL ENABLEEXTENSIONS

java -cp "%~dp0boxtools.jar;%~dp0lib\*" com.elektrika.boxtools.BoxTools ^
         "%~dp0config\sample-boxtools.properties"  %*

ENDLOCAL
