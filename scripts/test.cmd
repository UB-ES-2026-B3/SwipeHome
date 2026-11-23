@echo off
setlocal
pushd "%~dp0..\backend" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo Crea primero el entorno virtual en backend\.venv.
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -B -m qa.run %*
set "SWIPEHOME_QA_EXIT=%ERRORLEVEL%"
popd
exit /b %SWIPEHOME_QA_EXIT%
