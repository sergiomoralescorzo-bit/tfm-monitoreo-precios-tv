# Captura diaria local (Etapa 2): corre los cinco sitios y genera el informe de la corrida.
#
# Programarla a las 06:00 con el Programador de tareas de Windows (una sola vez, en PowerShell):
#   schtasks /Create /TN "TFM Captura diaria" /SC DAILY /ST 06:00 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"<ruta>\scripts\captura_diaria.ps1`""
#
# Modo: los domingos, "completo" (descubre fichas nuevas); los demás días, "seguimiento".
# Para guardar los datos fuera de OneDrive, defina la variable de usuario TFM_DATOS (p. ej. C:\TFM_datos).

$ErrorActionPreference = "Stop"
$proyecto = Split-Path -Parent $PSScriptRoot
Set-Location $proyecto

$modo = if ((Get-Date).DayOfWeek -eq "Sunday") { "completo" } else { "seguimiento" }
$datos = if ($env:TFM_DATOS) { $env:TFM_DATOS } else { Join-Path $proyecto "data" }
$logs = Join-Path $datos "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs ("captura_{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))

$python = Join-Path $proyecto ".venv\Scripts\python.exe"
& $python -m src.extraccion.ejecutar --modo $modo *>> $log
$codigo = $LASTEXITCODE
& $python -m src.extraccion.informe *>> $log
exit $codigo
