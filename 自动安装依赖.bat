@echo off
setlocal EnableExtensions
call "%~dp0scripts\bootstrap.bat" %*
exit /b %errorlevel%
