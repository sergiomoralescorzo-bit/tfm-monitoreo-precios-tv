# Permisos máximos del equipo sobre los recursos del TFM (decisión del equipo, 16-oct-2026).
# Ejecutar con una cuenta Owner de la suscripción, después de `az login`. Se puede repetir sin duplicar.
#
#   Owner                    grupo RG-TFM-WEBSCRAPING: todos los recursos (lago, Synapse, ADF, ACR,
#                            Container Apps, identidad, Log Analytics, alertas)
#   Storage Blob Data Owner  lago sttfmwebscraping: leer y escribir datos (Owner no da acceso a los datos)
#   Synapse Administrator    syn-tfm-webscraping: pipelines, notebooks, Spark y SQL serverless como administrador
#
# El ámbito es el grupo de recursos, no la suscripción: así no se da control sobre el crédito de Azure for Students.
param(
    [Parameter(Mandatory)] [string[]]$Usuarios   # correos de Entra ID de los integrantes, p. ej. -Usuarios a@dominio,b@dominio
)
$ErrorActionPreference = "Stop"
$cli = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (-not (Get-Command az -ErrorAction SilentlyContinue) -and (Test-Path $cli)) { $env:PATH = "$cli;$env:PATH" }

$Grupo   = "RG-TFM-WEBSCRAPING"
$Synapse = "syn-tfm-webscraping"
$rg      = az group show -n $Grupo --query id -o tsv
$lago    = az storage account show -n sttfmwebscraping -g $Grupo --query id -o tsv

foreach ($u in $Usuarios) {
    $id = az ad user show --id $u --query id -o tsv
    if (-not $id) { throw "No existe el usuario $u en el directorio" }
    Write-Host "== $u ($id)" -ForegroundColor Cyan
    foreach ($par in @(@("Owner", $rg), @("Storage Blob Data Owner", $lago))) {
        $ya = az role assignment list --assignee $id --role $par[0] --scope $par[1] --query "[0].id" -o tsv
        if ($ya) { Write-Host "  ya tenía $($par[0])" }
        else {
            az role assignment create --assignee-object-id $id --assignee-principal-type User `
                --role $par[0] --scope $par[1] -o none
            Write-Host "  + $($par[0])"
        }
    }
    $ya = az synapse role assignment list --workspace-name $Synapse --assignee $id --role "Synapse Administrator" --query "[0].id" -o tsv
    if ($ya) { Write-Host "  ya tenía Synapse Administrator" }
    else {
        az synapse role assignment create --workspace-name $Synapse --role "Synapse Administrator" `
            --assignee-object-id $id --assignee-principal-type User -o none
        Write-Host "  + Synapse Administrator"
    }
}
Write-Host "Listo. Los roles pueden tardar unos minutos en propagarse." -ForegroundColor Green
