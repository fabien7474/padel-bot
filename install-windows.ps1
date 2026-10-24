# Installation du bot padel sur Windows
# Clic droit > « Exécuter avec PowerShell » (ou : powershell -ExecutionPolicy Bypass -File install-windows.ps1)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "1/4 Python..." -ForegroundColor Cyan
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
$pyw = Join-Path $here ".venv\Scripts\pythonw.exe"
$pye = Join-Path $here ".venv\Scripts\python.exe"

Write-Host "2/4 Dépendances (Playwright, utilise Edge déjà installé)..." -ForegroundColor Cyan
& $pye -m pip install --quiet --upgrade pip
& $pye -m pip install --quiet -r requirements.txt

Write-Host "3/4 Dossier des résultats..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    $default = Join-Path $env:USERPROFILE "My Drive\Annecy Tennis - Bot padel"
    $out = Read-Host "Dossier où écrire les CSV/JSON [$default]"
    if (-not $out) { $out = $default }
    "PADEL_OUT=$out" | Out-File -Encoding utf8 .env
}

Write-Host "4/4 Tâche planifiée (toutes les 10 minutes)..." -ForegroundColor Cyan
$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$here\padel_bot.py`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Bot padel ADOC" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Surveillance des réservations padel Annecy Tennis" -Force | Out-Null

Write-Host "`nIl reste à vous connecter une fois à ADOC :" -ForegroundColor Green
& $pye padel_bot.py --login
Write-Host "`nTerminé. Le bot tourne toutes les 10 minutes (Planificateur de tâches : « Bot padel ADOC »)." -ForegroundColor Green
Read-Host "Entrée pour fermer"
