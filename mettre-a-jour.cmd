@echo off
cd /d "%~dp0"
echo Mise a jour du bot padel...
git pull --ff-only || (echo ECHEC du git pull & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
echo Termine.
pause
