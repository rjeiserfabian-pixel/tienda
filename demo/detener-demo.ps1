<#
.SYNOPSIS
  Apaga lo que haya quedado de la demostración (backend, frontend y túnel de ngrok).
  Úsalo si cerraste la ventana sin apagar con Enter, o si «iniciar-demo» dice que un puerto está ocupado.
#>
foreach ($puerto in @(8000, 4173, 3100)) {
    Get-NetTCPConnection -State Listen -LocalPort $puerto -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "Cerrando el proceso $($_.OwningProcess) del puerto $puerto"
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}
# El túnel: ngrok escucha su panel en 4040.
Get-NetTCPConnection -State Listen -LocalPort 4040 -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Cerrando ngrok (proceso $($_.OwningProcess))"
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
Write-Host 'Listo.' -ForegroundColor Green
# El túnel de la tienda (Cloudflare), si quedó abierto.
Get-Process -Name cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Cerrando cloudflared (proceso $($_.Id))"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
