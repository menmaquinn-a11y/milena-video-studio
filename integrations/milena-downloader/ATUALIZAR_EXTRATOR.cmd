@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Abra INICIAR_WINDOWS.cmd primeiro.
    pause
    exit /b 1
)
echo Atualizando o extrator e os scripts oficiais do YouTube pelo PyPI...
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]"
if errorlevel 1 (
    echo A atualizacao falhou. Confira o erro acima.
    pause
    exit /b 1
)
echo Pronto. Feche e abra novamente o baixador.
pause
