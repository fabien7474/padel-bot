# Installation du bot padel sur Windows
# Clic droit > « Exécuter avec PowerShell » (ou : powershell -ExecutionPolicy Bypass -File install-windows.ps1)
param([int]$Minutes = 10)   # fréquence des passages, ex. : .\install-windows.ps1 -Minutes 30
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

Write-Host "3/4 Configuration..." -ForegroundColor Cyan
# Par défaut, les résultats vont dans le sous-dossier « resultats » du projet (exclu de Git).
# Pour un autre dossier : copier .env.example en .env et renseigner PADEL_OUT.
if (Test-Path ".env") { Write-Host "   .env présent :"; Get-Content .env | Where-Object { $_ -match "^\s*PADEL_" } | ForEach-Object { Write-Host "   $_" } }
else { Write-Host "   Résultats dans : $here\resultats (modifiable via .env, voir .env.example)" }

Write-Host "4/4 Tâche planifiée (toutes les $Minutes minutes)..." -ForegroundColor Cyan
$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$here\padel_bot.py`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Bot padel ADOC" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Surveillance des réservations padel Annecy Tennis" -Force | Out-Null

if (Test-Path (Join-Path $env:LOCALAPPDATA "padel-bot\session.json")) {
    Write-Host "`nSession ADOC déjà enregistrée : pas besoin de se reconnecter." -ForegroundColor Green
} else {
    Write-Host "`nIl reste à vous connecter une fois à ADOC :" -ForegroundColor Green
    & $pye padel_bot.py --login
}
Write-Host "`nTerminé. Le bot tourne toutes les $Minutes minutes (Planificateur de tâches : « Bot padel ADOC »)." -ForegroundColor Green
Read-Host "Entrée pour fermer"
