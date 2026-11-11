<#
.SYNOPSIS
  Pone el sistema a correr con un túnel de ngrok para mostrarlo a otra persona.

.DESCRIPTION
  Levanta cuatro cosas, todas en este equipo, y las apaga al terminar (Ctrl+C o Enter):
    1. El túnel de ngrok  -> la dirección pública (https).
    2. El backend Django  -> solo escucha en 127.0.0.1:8000 (nadie de fuera llega directo).
    3. El frontend compilado (vite preview) en 127.0.0.1:4173, que reenvía /api/v1 al backend.
    4. La tienda virtual (Next.js) en 127.0.0.1:3100, con su propio enlace público de Cloudflare
       (túnel rápido, gratis y sin cuenta; requiere tener instalado cloudflared).
  ngrok apunta SOLO al frontend y cloudflared SOLO a la tienda, así el navegador usa un único origen y /admin queda sin exponer.

  Por defecto usa tu base de DESARROLLO (la de backend\.env): se entra con tus usuarios de
  siempre (p. ej. superadmin) y la persona ve y modifica TUS datos. Para mostrar algo aislado,
  usa -BaseDemo.

.PARAMETER Dominio
  Dominio fijo de tu cuenta de ngrok (p. ej. mi-demo.ngrok-free.app). Sin él, ngrok da uno al azar
  en cada arranque. Se ve en https://dashboard.ngrok.com/domains

.PARAMETER SinTienda
  No levanta la tienda virtual (solo el sistema). Sin cloudflared instalado, la tienda se omite sola.

.PARAMETER BaseDemo
  Usa una base APARTE y vacía (sistema_demo), con una empresa de ejemplo y un usuario «demo»
  con contraseña generada (queda en demo\credenciales-demo.txt). Tus datos no se ven.

.PARAMETER SinCompilar
  No vuelve a compilar el frontend (usa la compilación anterior de frontend/apps/panel-admin/dist-demo).

.PARAMETER SoloPreparar
  Prepara la base y compila el frontend, pero no abre el túnel ni arranca los servidores.

.EXAMPLE
  .\demo\iniciar-demo.ps1
  .\demo\iniciar-demo.ps1 -Dominio mi-demo.ngrok-free.app
#>
param(
    [string]$Dominio = '',
    [switch]$SinTienda,
    [switch]$BaseDemo,
    [switch]$SinCompilar,
    [switch]$SoloPreparar
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $raiz 'backend'
$front = Join-Path $raiz 'frontend\apps\panel-admin'
$python = Join-Path $backend 'env\Scripts\python.exe'
$logs = Join-Path $PSScriptRoot 'logs'
$puertoBackend = 8000
$puertoFront = 4173
$puertoTienda = 3100
$tienda = Join-Path $raiz 'frontend\apps\tienda-web'
$conTienda = -not $SinTienda
$procesos = @()

function Falla($mensaje) { Write-Host "ERROR: $mensaje" -ForegroundColor Red; exit 1 }
function Paso($mensaje) { Write-Host "`n== $mensaje" -ForegroundColor Cyan }

function PuertoLibre($puerto) {
    $uso = Get-NetTCPConnection -State Listen -LocalPort $puerto -ErrorAction SilentlyContinue
    if ($uso) { Falla "El puerto $puerto ya está en uso (proceso $($uso[0].OwningProcess)). Ejecuta .\demo\detener-demo.ps1 o ciérralo." }
}

function Esperar($url, $segundos, $nombre) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        try { Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 | Out-Null; return } catch { Start-Sleep -Milliseconds 700 }
    }
    Falla "$nombre no respondió en $segundos s. Revisa los registros en $logs"
}

# --- 0. Requisitos -------------------------------------------------------------------------
Paso 'Revisando requisitos'
if (-not (Test-Path $python)) { Falla "No existe el entorno virtual del backend ($python)." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Falla 'Node.js no está instalado o no está en el PATH.' }
if ($conTienda -and -not (Test-Path (Join-Path $tienda 'node_modules'))) { Write-Host "AVISO: la tienda no tiene sus dependencias (cd $tienda ; npm install). Se omite la tienda." -ForegroundColor Yellow; $conTienda = $false }
if ($conTienda -and -not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host 'AVISO: no está cloudflared; se muestra solo el sistema. Para ver también la tienda: winget install Cloudflare.cloudflared (y abre una ventana nueva de PowerShell).' -ForegroundColor Yellow
    $conTienda = $false
}
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) { Falla 'ngrok no está instalado o no está en el PATH.' }
if (-not (Test-Path (Join-Path $front 'node_modules'))) { Falla "Falta instalar el frontend: cd $front ; npm install" }
New-Item -ItemType Directory -Force -Path $logs | Out-Null

if (-not $BaseDemo) {
    Write-Host 'AVISO: se muestra tu base de DESARROLLO. Quien entre con un usuario tuyo verá y podrá cambiar tus datos reales de prueba.' -ForegroundColor Yellow
}

# --- 1. Variables de la demostración (mandan sobre backend/.env) ---------------------------------
# Las variables de entorno son de la ventana de PowerShell y se quedan puestas al terminar el
# script. Por eso: (a) se limpia un DB_NAME que una ejecución anterior pudo dejar apuntando a la base
# de demostración (la base la decide backend\.env, o -BaseDemo) y (b) al terminar se devuelve todo
# a como estaba, para no alterar tu ventana de trabajo.
if (-not $BaseDemo -and $env:DB_NAME -eq 'sistema_demo') { Remove-Item Env:DB_NAME }
$variablesDeLaDemo = 'DJANGO_SETTINGS_MODULE', 'DEBUG', 'DOCS_API_HABILITADA', 'ALLOWED_HOSTS', 'COOKIE_REFRESH_SECURE',
    'THROTTLE_LOGIN', 'THROTTLE_USUARIO', 'THROTTLE_ANON', 'VITE_BACKEND_URL', 'DB_NAME', 'FRONTEND_URL', 'CORS_ALLOWED_ORIGINS',
    'API_URL', 'SITE_URL', 'NEXT_DIST_DIR'
$entornoOriginal = @{}
foreach ($v in $variablesDeLaDemo) { $entornoOriginal[$v] = [Environment]::GetEnvironmentVariable($v, 'Process') }
# No se escribe ningún archivo: solo valen para los procesos que arranca este script.
$env:DJANGO_SETTINGS_MODULE = 'config.settings.dev'
$env:DEBUG = 'False'                      # sin páginas de error con detalles internos
$env:DOCS_API_HABILITADA = 'False'        # sin Swagger público
$env:ALLOWED_HOSTS = 'localhost,127.0.0.1'
$env:COOKIE_REFRESH_SECURE = 'True'       # el enlace público es https
$env:THROTTLE_LOGIN = '15/min'            # todos los visitantes llegan con la misma IP local
$env:THROTTLE_USUARIO = '1500/min'
$env:THROTTLE_ANON = '300/min'
$env:VITE_BACKEND_URL = "http://127.0.0.1:$puertoBackend"
if ($BaseDemo) { $env:DB_NAME = 'sistema_demo' }

# --- 2. Base de datos de la demostración ---------------------------------------------------------
if ($BaseDemo) {
    Paso 'Preparando la base de datos de la demostración (sistema_demo)'
    Push-Location $backend
    try { & $python (Join-Path $PSScriptRoot 'preparar_base_demo.py'); if ($LASTEXITCODE -ne 0) { Falla 'No se pudo preparar la base de la demostración.' } } finally { Pop-Location }
}

# --- 3. Frontend compilado ---------------------------------------------------------------------------
$salida = Join-Path $front 'dist-demo'
if (-not $SinCompilar -or -not (Test-Path (Join-Path $salida 'index.html'))) {
    Paso 'Compilando el frontend (tarda unos segundos)'
    Push-Location $front
    try { & npm run build -- --outDir dist-demo --emptyOutDir; if ($LASTEXITCODE -ne 0) { Falla 'Falló la compilación del frontend.' } } finally { Pop-Location }
}

# Tienda compilada en una carpeta aparte (.next-demo) para no pisar a `npm run dev` de la tienda.
$env:API_URL = "http://127.0.0.1:$puertoBackend"
$env:NEXT_DIST_DIR = '.next-demo'
if ($SoloPreparar) { Write-Host "`nListo: base y frontend preparados. No se abrió ningún túnel." -ForegroundColor Green; exit 0 }

PuertoLibre $puertoBackend
PuertoLibre $puertoFront
if ($conTienda) { PuertoLibre $puertoTienda }

try {
    # --- 4. Túnel de ngrok (primero: así el backend conoce la dirección pública) -------------------
    Paso 'Abriendo el túnel de ngrok'
    $argsNgrok = @('http', "$puertoFront", '--log', (Join-Path $logs 'ngrok.log'), '--log-format', 'logfmt')
    if ($Dominio) { $argsNgrok += "--url=$Dominio" }
    $procesos += Start-Process -FilePath 'ngrok' -ArgumentList $argsNgrok -PassThru -WindowStyle Hidden
    $url = $null
    for ($i = 0; $i -lt 30 -and -not $url; $i++) {
        Start-Sleep -Seconds 1
        try {
            $tuneles = (Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3).tunnels
            $url = ($tuneles | Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1).public_url
        } catch { }
    }
    if (-not $url) { Falla "ngrok no abrió el túnel. Revisa $logs\ngrok.log (¿falta 'ngrok config add-authtoken'? ¿ya hay otro túnel abierto?)" }

    # Túnel de la tienda con Cloudflare (la cuenta gratuita de ngrok solo da un dominio).
    $urlTienda = $null
    if ($conTienda) {
        Paso 'Abriendo el túnel de Cloudflare para la tienda'
        $logCf = Join-Path $logs 'cloudflared.log'
        Remove-Item $logCf -ErrorAction SilentlyContinue
        $cf = Start-Process -FilePath 'cloudflared' -ArgumentList @('tunnel', '--no-autoupdate', '--url', "http://127.0.0.1:$puertoTienda", '--logfile', $logCf) -PassThru -WindowStyle Hidden
        $procesos += $cf
        for ($i = 0; $i -lt 40 -and -not $urlTienda -and -not $cf.HasExited; $i++) {
            Start-Sleep -Seconds 1
            if (Test-Path $logCf) {
                $m = [regex]::Match((Get-Content $logCf -Raw -ErrorAction SilentlyContinue), 'https://[a-z0-9-]+\.trycloudflare\.com')
                if ($m.Success) { $urlTienda = $m.Value }
            }
        }
        if (-not $urlTienda) { Write-Host "AVISO: Cloudflare no dio enlace para la tienda (revisa $logCf). Se muestra solo el sistema." -ForegroundColor Yellow; $conTienda = $false }
    }
    $host_publico = ([Uri]$url).Host
    Write-Host "Dirección pública del sistema: $url" -ForegroundColor Green
    if ($urlTienda) { Write-Host "Dirección pública de la tienda: $urlTienda" -ForegroundColor Green }

    # --- 5. Backend ------------------------------------------------------------------------------
    Paso 'Arrancando el backend (solo escucha en este equipo)'
    $env:FRONTEND_URL = $url                      # enlaces de correo y códigos QR del servicio técnico
    $env:CORS_ALLOWED_ORIGINS = $url
    $env:ALLOWED_HOSTS = "localhost,127.0.0.1,$host_publico"
    $procesos += Start-Process -FilePath $python -ArgumentList @('manage.py', 'runserver', "127.0.0.1:$puertoBackend", '--noreload') `
        -WorkingDirectory $backend -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'backend.log') -RedirectStandardError (Join-Path $logs 'backend-errores.log')
    Esperar "http://127.0.0.1:$puertoBackend/api/v1/salud/" 60 'El backend'

    # --- 6. Frontend -------------------------------------------------------------------------------
    Paso 'Sirviendo el frontend'
    $vite = Join-Path $front 'node_modules\vite\bin\vite.js'
    $procesos += Start-Process -FilePath 'node' -ArgumentList @($vite, 'preview', '--outDir', 'dist-demo', '--host', '127.0.0.1', '--port', "$puertoFront", '--strictPort') `
        -WorkingDirectory $front -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs 'frontend.log') -RedirectStandardError (Join-Path $logs 'frontend-errores.log')
    Esperar "http://127.0.0.1:$puertoFront/api/v1/salud/" 30 'El frontend'

    # --- 6b. Tienda ---------------------------------------------------------------------------------
    if ($urlTienda) {
        # La tienda arma sus páginas con datos reales: se compila con el backend ya encendido.
        if (-not $SinCompilar -or -not (Test-Path (Join-Path $tienda '.next-demo\BUILD_ID'))) {
            Paso 'Compilando la tienda (tarda un poco)'
            $env:SITE_URL = $urlTienda
            Push-Location $tienda
            try { & npm run build; if ($LASTEXITCODE -ne 0) { $urlTienda = $null; Write-Host 'AVISO: falló la compilación de la tienda; solo queda el sistema.' -ForegroundColor Yellow } } finally { Pop-Location }
        }
    }
    if ($urlTienda) {
        Paso 'Sirviendo la tienda'
        $env:SITE_URL = $urlTienda
        $next = Join-Path $tienda 'node_modules\next\dist\bin\next'
        $procesos += Start-Process -FilePath 'node' -ArgumentList @($next, 'start', '-H', '127.0.0.1', '-p', "$puertoTienda") `
            -WorkingDirectory $tienda -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logs 'tienda.log') -RedirectStandardError (Join-Path $logs 'tienda-errores.log')
        try { Esperar "http://127.0.0.1:$puertoTienda/" 60 'La tienda' }
        catch { }
    }

    # --- 7. Listo ----------------------------------------------------------------------------------
    Write-Host "`n=======================================================" -ForegroundColor Green
    Write-Host '  EL SISTEMA YA ESTÁ EN LÍNEA' -ForegroundColor Green
    Write-Host "  Sistema (panel):  $url" -ForegroundColor Green
    if ($urlTienda) { Write-Host "  Tienda virtual:   $urlTienda" -ForegroundColor Green }
    $cred = Join-Path $PSScriptRoot 'credenciales-demo.txt'
    if ($BaseDemo -and (Test-Path $cred)) { Write-Host "  Acceso de la demostración (también en demo\credenciales-demo.txt):"; Get-Content $cred | ForEach-Object { Write-Host "    $_" } }
    Write-Host '  Panel de ngrok (peticiones en vivo):  http://127.0.0.1:4040'
    Write-Host '  Con la cuenta gratuita, la primera vez ngrok muestra un aviso: «Visit Site».'
    Write-Host "=======================================================" -ForegroundColor Green
    Write-Host "`nPresiona Enter (o Ctrl+C) para apagar todo."
    [void](Read-Host)
}
finally {
    Paso 'Apagando'
    foreach ($v in $variablesDeLaDemo) { [Environment]::SetEnvironmentVariable($v, $entornoOriginal[$v], 'Process') }
    foreach ($p in $procesos) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    # runserver y vite pueden dejar procesos hijos: se cierra lo que siga escuchando en esos puertos.
    foreach ($puerto in @($puertoBackend, $puertoFront, $puertoTienda)) {
        Get-NetTCPConnection -State Listen -LocalPort $puerto -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    }
    Write-Host 'Todo apagado. El enlace público dejó de funcionar.' -ForegroundColor Green
}
