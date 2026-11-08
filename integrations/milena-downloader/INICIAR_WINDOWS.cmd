@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto failure
)
if not exist ".venv\.milena-ready-01" (
    echo Instalando os componentes do baixador...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failure
    echo ready>".venv\.milena-ready-01"
)
".venv\Scripts\python.exe" bootstrap.py
if errorlevel 1 goto failure
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failure
exit /b 0
:failure
echo.
echo Nao foi possivel iniciar. Envie o erro acima no chat para verificarmos.
pause
exit /b 1
