@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    echo Premier lancement : creation de l'environnement Python...
    python -m venv .venv
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, jinja2, dotenv" >nul 2>&1
if errorlevel 1 (
    echo Installation des dependances...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)
echo.
echo Ouvrez http://localhost:8000 dans votre navigateur.
echo Pour arreter l'application, appuyez sur Ctrl+C.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
exit /b
:error
echo.
echo Echec de l'installation. Verifiez Python et votre connexion Internet.
pause
exit /b 1
