@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" padel_bot.py --forcer
echo Code retour : %errorlevel% (0 = OK, 2 = session ADOC a reconnecter)
pause
