# Despliegue de la Etapa 3 en Azure (Azure for Students, West US).
#
# Requisitos: Azure CLI (`winget install Microsoft.AzureCLI`), Docker Desktop encendido y `az login`.
# Uso (desde la raíz del proyecto):
#   powershell -ExecutionPolicy Bypass -File infra\desplegar.ps1                 # todos los pasos
#   powershell -ExecutionPolicy Bypass -File infra\desplegar.ps1 -Pasos imagen   # solo publicar la imagen
#
# Pasos: acr, imagen, imagen-medallon, entorno, job, job-medallon, roles, pool, lago, notificaciones, avisos, synapse, vigilancia.
# Se pueden repetir sin duplicar recursos.
# El disparador (06:00 de Colombia: pl_orquestador_diario, que encadena captura y medallón) va en el paso aparte
# `disparadores`, que no está en la lista por defecto (activos desde el 17-oct-2026; medallón diario desde el 19-oct).
# Correos de aviso: -Correos a@dominio,b@dominio o la variable de entorno TFM_CORREOS_AVISO.
# Notificaciones: la URL del flujo de Teams se pasa en la variable de entorno TFM_TEAMS_WEBHOOK (no se guarda en el repo).
param(
    [string[]]$Pasos = @("acr", "imagen", "imagen-medallon", "entorno", "job", "job-medallon", "roles", "pool", "lago", "notificaciones", "avisos", "synapse", "vigilancia"),
    [string]$Version = "0.7",
    [string]$VersionMedallon = "0.8",
    [string[]]$Correos = @("$env:TFM_CORREOS_AVISO"),   # correos de aviso separados por comas (parámetro o variable de entorno)
    # Nombres de los recursos de Azure. Los valores por defecto son los del despliegue del TFM; quien despliegue
    # en otra suscripción los cambia aquí o al llamar el script (p. ej. -Grupo RG-OTRO -Acr acrotro).
    [string]$Grupo       = "RG-TFM-WEBSCRAPING",
    [string]$Region      = "westus",
    [string]$Synapse     = "syn-tfm-webscraping",
    [string]$Cuenta      = "sttfmwebscraping",
    [string]$Contenedor  = "datalake-tfm",
    [string]$Acr         = "acrtfmwebscraping",        # nombre global único: si ya existe en otra suscripción, cambiarlo
    [string]$Entorno     = "cae-tfm-webscraping",
    [string]$Job         = "caj-tfm-captura",
    [string]$JobMedallon = "caj-tfm-medallon",          # Spark local (opción B de la sección 9.2 de la Etapa 3)
    [string]$Identidad   = "id-tfm-captura",            # identidad asignada por el usuario del job (AcrPull + lago)
    [string]$Pool        = "sptfm",
    [string]$LogicAppNotificaciones = "la-tfm-notificaciones",   # avisos de fallos (correo y Teams)
    [string]$LogicAppAvisos         = "la-tfm-avisos",           # resumen diario y alertas comerciales
    [string]$LogicAppVigilancia     = "la-tfm-vigilancia",       # revisión de las 09:30
    [string]$CarpetaAzCli = "$env:ProgramFiles\Microsoft SDKs\Azure\CLI2\wbin"   # se usa solo si az no está en el PATH
)

$ErrorActionPreference = "Continue"   # en PS 5.1 las advertencias de az en stderr serían errores; se valida $LASTEXITCODE
$Pasos = $Pasos -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }   # -File pasa "a,b" como un texto
$Imagen      = "$Acr.azurecr.io/tfm-captura:$Version"
$ImagenMedallon = "$Acr.azurecr.io/tfm-medallon:$VersionMedallon"
$Proyecto    = Split-Path -Parent $PSScriptRoot

$cli = $CarpetaAzCli
if (-not (Get-Command az -ErrorAction SilentlyContinue) -and (Test-Path $cli)) { $env:PATH = "$cli;$env:PATH" }

function AzOk { & az.cmd @args; if ($LASTEXITCODE -ne 0) { throw "Falló: az $args" } }
function Rol([string]$objeto, [string]$tipo, [string]$rol, [string]$ambito) {
    $ya = az role assignment list --assignee $objeto --role $rol --scope $ambito --query "[0].id" -o tsv
    if ($ya) { Write-Host "  ya existe: $rol"; return $false }
    AzOk role assignment create --assignee-object-id $objeto --assignee-principal-type $tipo `
        --role $rol --scope $ambito -o none
    Write-Host "  asignado: $rol"
    return $true
}
function Paso([string]$nombre) { $Pasos -contains $nombre }

$suscripcion = az account show --query id -o tsv
if (-not $suscripcion) { throw "Inicie sesión primero: az login" }
Write-Host "Suscripción: $suscripcion" -ForegroundColor Cyan
$idCuenta = "/subscriptions/$suscripcion/resourceGroups/$Grupo/providers/Microsoft.Storage/storageAccounts/$Cuenta"

if (Paso "acr") {
    Write-Host "== Azure Container Registry Basic" -ForegroundColor Cyan
    az extension add --name containerapp --upgrade --only-show-errors
    AzOk provider register --namespace Microsoft.App --wait
    AzOk provider register --namespace Microsoft.OperationalInsights --wait
    AzOk provider register --namespace Microsoft.ContainerRegistry --wait
    AzOk acr create -g $Grupo -n $Acr --sku Basic -l $Region --admin-enabled false -o none
}

if (Paso "imagen") {
    Write-Host "== Construir y publicar $Imagen" -ForegroundColor Cyan
    AzOk acr login -n $Acr
    docker build -t $Imagen $Proyecto; if ($LASTEXITCODE -ne 0) { throw "docker build" }
    docker push $Imagen;               if ($LASTEXITCODE -ne 0) { throw "docker push" }
}

if (Paso "imagen-medallon") {
    Write-Host "== Construir y publicar $ImagenMedallon" -ForegroundColor Cyan
    AzOk acr login -n $Acr
    docker build -f "$Proyecto\medallon.Dockerfile" -t $ImagenMedallon $Proyecto; if ($LASTEXITCODE -ne 0) { throw "docker build" }
    docker push $ImagenMedallon;                                              if ($LASTEXITCODE -ne 0) { throw "docker push" }
}

if (Paso "entorno") {
    Write-Host "== Entorno de Container Apps (plan de consumo)" -ForegroundColor Cyan
    # Modo WorkloadProfiles (perfil Consumption): el modo Express, que la CLI usa por defecto, no admite jobs.
    # Se reutiliza el Log Analytics del grupo si ya existe, para no crear uno nuevo en cada intento.
    $existe = az containerapp env show -n $Entorno -g $Grupo --query name -o tsv 2>$null
    if (-not $existe) {
        $la = az monitor log-analytics workspace list -g $Grupo --query "[0].{id:customerId, n:name}" -o json | ConvertFrom-Json
        $logs = @()
        if ($la) {
            $clave = az monitor log-analytics workspace get-shared-keys -g $Grupo -n $la.n --query primarySharedKey -o tsv
            $logs = @("--logs-workspace-id", $la.id, "--logs-workspace-key", $clave)
        }
        AzOk containerapp env create -n $Entorno -g $Grupo -l $Region --environment-mode WorkloadProfiles @logs -o none
    }
}

if (Paso "job") {
    Write-Host "== Container Apps Job (disparo manual; lo inicia la pipeline)" -ForegroundColor Cyan
    # Identidad asignada por el usuario: existe antes que el job, así puede tener AcrPull al crearlo.
    $mi = az identity show -n $Identidad -g $Grupo -o json 2>$null | ConvertFrom-Json
    if (-not $mi) { $mi = az identity create -n $Identidad -g $Grupo -l $Region -o json | ConvertFrom-Json }
    $recAcr = az acr show -n $Acr --query id -o tsv
    $nuevo = (Rol $mi.principalId ServicePrincipal "AcrPull" $recAcr)
    $nuevo = (Rol $mi.principalId ServicePrincipal "Storage Blob Data Contributor" $idCuenta) -or $nuevo
    if ($nuevo) { Write-Host "  esperando 90 s a que se propaguen los permisos..."; Start-Sleep -Seconds 90 }

    $existe = az containerapp job show -n $Job -g $Grupo --query name -o tsv 2>$null
    if ($existe) {
        # 2 vCPU / 4 GiB desde el 18-nov-2026: con 2 GiB, Scrapling (Chromium) agotó la memoria y Azure cortó el job.
        AzOk containerapp job update -n $Job -g $Grupo --image $Imagen --cpu 2.0 --memory 4.0Gi -o none
    } else {
        AzOk containerapp job create -n $Job -g $Grupo --environment $Entorno `
            --trigger-type Manual --replica-timeout 7200 --replica-retry-limit 0 `
            --parallelism 1 --replica-completion-count 1 `
            --image $Imagen --cpu 2.0 --memory 4.0Gi `
            --mi-user-assigned $mi.id --registry-server "$Acr.azurecr.io" --registry-identity $mi.id `
            --env-vars "TFM_ADLS_CUENTA=$Cuenta" "TFM_ADLS_CONTENEDOR=$Contenedor" "AZURE_CLIENT_ID=$($mi.clientId)" -o none
    }
}

if (Paso "job-medallon") {
    Write-Host "== Container Apps Job del medallón (Spark local, disparo manual)" -ForegroundColor Cyan
    # Misma identidad que la captura (AcrPull + lago, asignados en el paso job).
    $mi = az identity show -n $Identidad -g $Grupo -o json | ConvertFrom-Json
    if (-not $mi) { throw "Falta la identidad $($Identidad); ejecute primero el paso job" }
    $existe = az containerapp job show -n $JobMedallon -g $Grupo --query name -o tsv 2>$null
    if ($existe) {
        AzOk containerapp job update -n $JobMedallon -g $Grupo --image $ImagenMedallon -o none
    } else {
        AzOk containerapp job create -n $JobMedallon -g $Grupo --environment $Entorno `
            --trigger-type Manual --replica-timeout 3600 --replica-retry-limit 0 `
            --parallelism 1 --replica-completion-count 1 `
            --image $ImagenMedallon --cpu 2.0 --memory 4.0Gi `
            --mi-user-assigned $mi.id --registry-server "$Acr.azurecr.io" --registry-identity $mi.id `
            --env-vars "TFM_ADLS_CUENTA=$Cuenta" "TFM_ADLS_CONTENEDOR=$Contenedor" "AZURE_CLIENT_ID=$($mi.clientId)" `
                       "TFM_SPARK_MEMORIA=3g" -o none
    }
}

if (Paso "roles") {
    Write-Host "== Permisos de Synapse y del usuario" -ForegroundColor Cyan
    $recJob = az containerapp job show -n $Job -g $Grupo --query id -o tsv
    $idSyn  = az synapse workspace show -n $Synapse -g $Grupo --query identity.principalId -o tsv
    $idYo   = az ad signed-in-user show --query id -o tsv
    # Synapse lee/escribe el lago e inicia el job; el usuario sube el maestro y el código.
    [void](Rol $idSyn ServicePrincipal "Storage Blob Data Contributor" $idCuenta)
    [void](Rol $idSyn ServicePrincipal "Contributor" $recJob)
    $recJobMed = az containerapp job show -n $JobMedallon -g $Grupo --query id -o tsv 2>$null
    if ($recJobMed) { [void](Rol $idSyn ServicePrincipal "Contributor" $recJobMed) }
    [void](Rol $idYo  User             "Storage Blob Data Contributor" $idCuenta)
    Write-Host "Los permisos de datos pueden tardar unos minutos en aplicarse."
}

if (Paso "pool") {
    Write-Host "== Spark pool $Pool (Small x 3 = 12 vCores, autopausa 5 min)" -ForegroundColor Cyan
    $existe = az synapse spark pool show -n $Pool --workspace-name $Synapse -g $Grupo --query name -o tsv 2>$null
    if (-not $existe) {
        AzOk synapse spark pool create -n $Pool --workspace-name $Synapse -g $Grupo `
            --spark-version 3.4 --node-size Small --node-count 3 `
            --enable-auto-scale false --enable-auto-pause true --delay 5 -o none
    }
}

if (Paso "lago") {
    Write-Host "== Maestro y código de Spark al lago" -ForegroundColor Cyan
    $python = Join-Path $Proyecto ".venv\Scripts\python.exe"
    Push-Location $Proyecto
    try {
        & $python -m src.nube.lago maestro; if ($LASTEXITCODE -ne 0) { throw "subir maestro" }
        & $python -m src.nube.lago codigo;  if ($LASTEXITCODE -ne 0) { throw "subir código" }
    } finally { Pop-Location }
}

if (Paso "notificaciones") {
    Write-Host "== Notificaciones de fallos (Logic App $LogicAppNotificaciones + alerta de respaldo)" -ForegroundColor Cyan
    $Correos = $Correos -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    if (-not $Correos) { throw "Faltan los correos de aviso: use -Correos o TFM_CORREOS_AVISO." }
    $param = @{ correos = @{ value = @($Correos) }; teamsWebhook = @{ value = "$env:TFM_TEAMS_WEBHOOK" };
                synapse = @{ value = $Synapse }; ubicacion = @{ value = $Region }; nombreLogicApp = @{ value = $LogicAppNotificaciones } }
    $tmp = Join-Path $env:TEMP "parametros_notificaciones.json"
    [IO.File]::WriteAllText($tmp, (@{ '$schema' = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#";
        contentVersion = "1.0.0.0"; parameters = $param } | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
    try {
        AzOk deployment group create -g $Grupo -n notificaciones --template-file "$Proyecto\infra\notificaciones.json" `
            --parameters "@$tmp" -o none
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
    if (-not $env:TFM_TEAMS_WEBHOOK) { Write-Host "  Sin TFM_TEAMS_WEBHOOK: no se publica en Teams (solo correo)." -ForegroundColor Yellow }
    Write-Host "  Falta autorizar una vez la conexión office365-tfm en el portal (Conexiones de API > Editar > Autorizar)." -ForegroundColor Yellow
}

if (Paso "avisos") {
    # Resumen diario y alertas comerciales (src/servicios/avisos.py). El job del medallón los envía a esta
    # Logic App; su URL (con firma) se guarda como secreto del job, nunca en el repositorio.
    Write-Host "== Avisos comerciales (Logic App $LogicAppAvisos)" -ForegroundColor Cyan
    $Correos = $Correos -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    if (-not $Correos) { throw "Faltan los correos de aviso: use -Correos o TFM_CORREOS_AVISO." }
    $param = @{ correos = @{ value = @($Correos) }; teamsWebhook = @{ value = "$env:TFM_TEAMS_WEBHOOK" };
                ubicacion = @{ value = $Region }; nombreLogicApp = @{ value = $LogicAppAvisos } }
    $tmp = Join-Path $env:TEMP "parametros_avisos.json"
    [IO.File]::WriteAllText($tmp, (@{ '$schema' = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#";
        contentVersion = "1.0.0.0"; parameters = $param } | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
    try {
        AzOk deployment group create -g $Grupo -n avisos --template-file "$Proyecto\infra\avisos.json" --parameters "@$tmp" -o none
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
    # La URL lleva '&', que az.cmd corta: el secreto se guarda por REST desde un archivo.
    python "$Proyecto\infra\secreto_avisos.py" $Grupo $JobMedallon $LogicAppAvisos; if ($LASTEXITCODE -ne 0) { throw "secreto_avisos.py" }
    AzOk containerapp job update -n $JobMedallon -g $Grupo --set-env-vars "TFM_URL_AVISOS=secretref:url-avisos" -o none
    if (-not $env:TFM_TEAMS_WEBHOOK) { Write-Host "  Sin TFM_TEAMS_WEBHOOK: los avisos salen solo por correo." -ForegroundColor Yellow }
}

if (Paso "synapse") {
    Write-Host "== Notebook y pipelines de Synapse (sin disparadores)" -ForegroundColor Cyan
    AzOk synapse notebook import --workspace-name $Synapse --name nb_medallon_semanal `
        --file "@$Proyecto\synapse\notebooks\nb_medallon_semanal.ipynb" --spark-pool-name $Pool -o none
    # URL con firma de la Logic App: se pide en cada despliegue y solo queda en la pipeline (entrada segura).
    $urlAviso = az rest --method post -o tsv --query value `
        --uri "https://management.azure.com/subscriptions/$suscripcion/resourceGroups/$Grupo/providers/Microsoft.Logic/workflows/$LogicAppNotificaciones/triggers/manual/listCallbackUrl?api-version=2019-05-01"
    if (-not $urlAviso) { throw "Falta la Logic App ${LogicAppNotificaciones}: ejecute primero el paso notificaciones" }
    $reemplazos = @{ "__SUSCRIPCION__" = $suscripcion; "__GRUPO__" = $Grupo; "__JOB__" = $Job; "__JOB_MEDALLON__" = $JobMedallon;
                     "__CUENTA__" = $Cuenta; "__CONTENEDOR__" = $Contenedor; "__POOL__" = $Pool; "__URL_NOTIFICACION__" = $urlAviso }
    # pl_notificar_fallo va primero: las demás la llaman desde su rama de fallo. pl_orquestador_diario va al final:
    # encadena la captura y el medallón. pl_medallon_synapse usa el pool sptfm: solo con la cuota de Spark (opción A).
    foreach ($nombre in "pl_notificar_fallo", "pl_captura_diaria", "pl_medallon_diario", "pl_medallon_synapse", "pl_orquestador_diario") {
        $texto = Get-Content -Raw -Encoding UTF8 "$Proyecto\synapse\pipelines\$nombre.json"
        foreach ($k in $reemplazos.Keys) { $texto = $texto.Replace($k, $reemplazos[$k]) }
        $tmp = Join-Path $env:TEMP "$nombre.json"
        [IO.File]::WriteAllText($tmp, $texto, (New-Object Text.UTF8Encoding $false))
        try { AzOk synapse pipeline create --workspace-name $Synapse --name $nombre --file "@$tmp" -o none }
        finally { Remove-Item $tmp -ErrorAction SilentlyContinue }   # lleva la URL firmada de la Logic App
    }
}

if (Paso "vigilancia") {
    Write-Host "== Vigilancia diaria de ejecuciones (Logic App $LogicAppVigilancia, 09:30 de Colombia)" -ForegroundColor Cyan
    # Avisa por $LogicAppNotificaciones si la captura (y el medallón) no terminó bien: cubre que no se ejecute.
    $urlAviso = az rest --method post -o tsv --query value `
        --uri "https://management.azure.com/subscriptions/$suscripcion/resourceGroups/$Grupo/providers/Microsoft.Logic/workflows/$LogicAppNotificaciones/triggers/manual/listCallbackUrl?api-version=2019-05-01"
    if (-not $urlAviso) { throw "Falta la Logic App ${LogicAppNotificaciones}: ejecute primero el paso notificaciones" }
    $tmp = Join-Path $env:TEMP "parametros_vigilancia.json"
    [IO.File]::WriteAllText($tmp, (@{ '$schema' = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#";
        contentVersion = "1.0.0.0"; parameters = @{ urlAviso = @{ value = $urlAviso }; synapse = @{ value = $Synapse };
            ubicacion = @{ value = $Region }; nombreLogicApp = @{ value = $LogicAppVigilancia } } } | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
    try {
        $idVig = az deployment group create -g $Grupo -n vigilancia --template-file "$Proyecto\infra\vigilancia.json" `
            --parameters "@$tmp" --query properties.outputs.principalId.value -o tsv
        if ($LASTEXITCODE -ne 0 -or -not $idVig) { throw "Falló el despliegue de vigilancia" }
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }   # lleva la URL firmada
    # Rol de Synapse (no de Azure) para leer las ejecuciones de pipelines.
    $ya = az synapse role assignment list --workspace-name $Synapse --assignee $idVig --role "Synapse Monitoring Operator" --query "[0].id" -o tsv 2>$null
    if (-not $ya) {
        AzOk synapse role assignment create --workspace-name $Synapse --role "Synapse Monitoring Operator" `
            --assignee-object-id $idVig --assignee-principal-type ServicePrincipal -o none
        Write-Host "  asignado: Synapse Monitoring Operator"
    } else { Write-Host "  ya existe: Synapse Monitoring Operator" }
}

if (Paso "disparadores") {
    Write-Host "== Disparadores de Synapse (se crean y se inician)" -ForegroundColor Cyan
    # Desde el 19-oct un solo disparador inicia pl_orquestador_diario (captura -> medallón). Se retiran los anteriores.
    foreach ($viejo in "tr_captura_diaria", "tr_medallon_semanal") {
        $ya = az synapse trigger show --workspace-name $Synapse --name $viejo --query "properties.runtimeState" -o tsv 2>$null
        if ($ya) {
            if ($ya -eq "Started") { AzOk synapse trigger stop --workspace-name $Synapse --name $viejo -o none }
            AzOk synapse trigger delete --workspace-name $Synapse --name $viejo --yes -o none
            Write-Host "  $viejo retirado"
        }
    }
    foreach ($nombre in "tr_orquestador_diario") {
        $ya = az synapse trigger show --workspace-name $Synapse --name $nombre --query "properties.runtimeState" -o tsv 2>$null
        if ($ya -eq "Started") { AzOk synapse trigger stop --workspace-name $Synapse --name $nombre -o none }   # no se edita uno iniciado
        AzOk synapse trigger create --workspace-name $Synapse --name $nombre --file "@$Proyecto\synapse\triggers\$nombre.json" -o none
        AzOk synapse trigger start --workspace-name $Synapse --name $nombre -o none
        Write-Host "  $nombre iniciado"
    }
}

Write-Host "Listo. Pruebas sugeridas:" -ForegroundColor Green
Write-Host "  az containerapp job start -n $Job -g $Grupo"
Write-Host "  az synapse pipeline create-run --workspace-name $Synapse --name pl_medallon_diario"
