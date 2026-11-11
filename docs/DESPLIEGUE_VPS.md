# Despliegue en VPS (Ubuntu) y respaldos

Todo se configura por variables en `backend/.env`. El código no cambia entre tu PC y el VPS.

## 1. Requisitos del servidor
- Ubuntu 22.04/24.04, Python 3.12, PostgreSQL 16, Redis 7, Nginx, Node 20+ (solo para compilar el frontend).

## 2. Redis
**Opción A – apt (simple):**
```bash
sudo apt install redis-server
sudo nano /etc/redis/redis.conf   # requirepass <CLAVE_FUERTE> ; bind 127.0.0.1 ; maxmemory 256mb
sudo systemctl restart redis-server
```
**Opción B – Docker:** `docker compose --env-file backend/.env up -d redis`
(define `REDIS_PASSWORD` en el `.env`).

## 3. Variables del `.env` a cambiar en producción
| Variable | Valor en el VPS |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` |
| `DEBUG` | `False` |
| `SECRET_KEY` | nueva, larga y aleatoria |
| `ALLOWED_HOSTS` | tu dominio |
| `DB_USER` / `DB_PASSWORD` | usuario propio con clave fuerte (no `postgres`/`root`) |
| `USAR_REDIS` | `True` |
| `REDIS_URL` | `redis://:CLAVE@localhost:6379` (sin número de base) |
| `CELERY_TASK_ALWAYS_EAGER` | `False` |
| `CORS_ALLOWED_ORIGINS` | `https://tu-dominio` |
| `ADMIN_URL` | una ruta no obvia |
| `DOCS_API_HABILITADA` | `False` |
| `CIFRADO_CLAVES` | claves Fernet NUEVAS (guardarlas aparte: sin ellas no se descifra SUNAT) |

`config.settings.prod` se niega a arrancar si falta `USAR_REDIS=True` o `CIFRADO_CLAVES`.

## 4. Puesta en marcha
```bash
cd backend && python3.12 -m venv env && source env/bin/activate
pip install -r requirements/prod.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check_servicios          # verifica PostgreSQL y Redis
python manage.py crear_organizacion --nombre "..." --razon-social "..." --ruc ...
gunicorn config.wsgi:application --workers 3 --bind 127.0.0.1:8000
celery -A config worker -l info           # worker (servicio systemd)
```
Nginx termina HTTPS y reenvía a Gunicorn con `X-Forwarded-Proto`.

## 5. Rotación de la clave de cifrado
1. Agregar la clave nueva: `CIFRADO_CLAVES=1:<vieja>,2:<nueva>`.
2. Cambiar `CIFRADO_CLAVE_ACTUAL=2`.
3. `python manage.py rotar_clave_cifrado` (usar `--simular` para solo contar).
4. Conservar la clave vieja hasta verificar el resultado.

## 6. Respaldos de PostgreSQL (lo único que hay que respaldar)
```bash
pg_dump -U <usuario> -Fc -f /respaldos/tienda_$(date +%F).dump tienda
# cron diario, por ejemplo a las 02:00, y copia fuera del servidor
```
**Restaurar en otra máquina:**
```bash
createdb -U <usuario> tienda
pg_restore -U <usuario> -d tienda --clean --if-exists tienda_AAAA-MM-DD.dump
```
Redis no se respalda: arranca vacío y se vuelve a llenar. Respalda también el `.env`
(en un lugar seguro y aparte), porque contiene las claves de cifrado.
Una restauración debe PROBARse periódicamente en una máquina distinta.

## 7. Tareas programadas
El calendario vive en `CELERY_BEAT_SCHEDULE` (settings): `core.purgar_idempotencia`, `auditoria.purgar` y
`seguridad.purgar_sesiones`, todas diarias. Requieren DOS procesos además del web: `celery -A config worker` y
`celery -A config beat`. Sin el worker, la auditoría y los correos de recuperación no se procesan
(la auditoría cae a inserción directa si el broker no responde, pero el correo no se envía).

## 8. Identidad (Fase 2): ajustes del VPS
- `NUM_PROXIES=1` en el `.env` cuando Nginx va delante (si no, la IP de login y del throttle será siempre la de Nginx).
  Nginx debe enviar `X-Forwarded-For $remote_addr` y `X-Forwarded-Proto $scheme`.
- El bloqueo progresivo de login y la revocación inmediata de access tokens usan la caché: con varios workers
  necesitan `USAR_REDIS=True` (ya exigido por `settings.prod`).
- Crear el primer administrador: `python manage.py crear_admin_plataforma --username ... --email ...`
  (la contraseña se pide oculta; para automatizar usar la variable `USUARIO_PASSWORD`).
- Crear usuarios de una organización: `python manage.py crear_usuario --organizacion-id N --username ... --email ... --empresa-id 1 --empresa-id 2`.

## 9. Permisos (Fase 3)
- En CADA despliegue, después de `migrate`: `python manage.py sync_permisos`. Copia el catálogo de permisos y el menú
  (definidos en `apps/seguridad/permisos_catalogo.py`) y siembra los roles plantilla que falten en cada organización.
  Es idempotente. No pisa los roles que la organización ya personalizó; sí mantiene SUPERADMIN (rol de sistema) al día.
- Un permiso nuevo se agrega SOLO en `permisos_catalogo.py`. Al sincronizar, SUPERADMIN lo recibe solo; los demás roles
  se ajustan desde la pantalla de roles.
- La caché de permisos usa Redis con invalidación por versión: sin Redis (varios workers) un cambio de rol no se vería
  igual en todos los procesos. `settings.prod` ya exige `USAR_REDIS=True`.
- Primer administrador de una organización:
  `python manage.py crear_usuario --organizacion-id N --username ... --email ... --empresa-id 1 --rol SUPERADMIN`

## 10. Fase 5: auditoría, segundo factor, recuperación y endurecimiento
**Variables nuevas del `.env`** (todas con valor por defecto, salvo el correo en producción):
```
FRONTEND_URL=https://panel.midominio.com      # base de los enlaces de recuperación
EMAIL_HOST=smtp.proveedor.com                  # EMAIL_PORT=587, EMAIL_USE_TLS=True
EMAIL_HOST_USER=...                            # EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL="Sistema Unificado <no-responder@midominio.com>"
AUDITORIA_RETENCION_DIAS=730                   # SESIONES_RETENCION_DIAS=90
```
- **Recuperación de contraseña**: sin SMTP configurado no llega ningún correo. Probar con una cuenta real tras desplegar.
  El enlace va en el fragmento (`#token=`) para no quedar en registros del servidor; el token solo se guarda como huella.
- **Auditoría**: tabla `auditoria_auditoriaevento`, solo se agrega. La aplicación impide editar/borrar, pero el refuerzo
  definitivo es de base de datos: usar un rol de PostgreSQL para la app SIN `UPDATE`/`DELETE` sobre esa tabla y un rol
  aparte (solo para la tarea de purga) con `DELETE`. Ejemplo:
  `REVOKE UPDATE, DELETE ON auditoria_auditoriaevento FROM app_web;`
  Los eventos de intentos de acceso se guardan aunque la operación falle; el resto, solo si la operación se confirma.
- **Segundo factor (TOTP)**: el secreto se cifra con `CIFRADO_CLAVES`; `rotar_clave_cifrado` lo re-cifra junto con
  las credenciales SUNAT (recorre todos los campos cifrados). Si se pierde el `.env` se pierden también los secretos TOTP
  y habrá que restablecer el factor de cada usuario.
- **Política `mfa_obligatorio`** (pantalla Organización): los usuarios sin factor solo pueden configurarlo; la API lo
  hace cumplir (403 `mfa_configuracion_requerida`), igual que la clave temporal (403 `cambio_password_requerido`).
- **Cabeceras**: la API responde con `Content-Security-Policy: default-src 'none'`, `Cache-Control: no-store`, etc.
  El SPA (React) lo sirve Nginx: agregar allí su propia CSP, p. ej.
  `add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'" always;`
  y `Referrer-Policy: no-referrer`. `data:` es necesario para el QR del segundo factor.
- **Pruebas de restauración**: restaurar el último `pg_dump` en otra máquina cada trimestre y verificar que se puede
  iniciar sesión (ver sección 6). Anotar la fecha y el resultado.
- **RLS de PostgreSQL**: NO se implementó (era opcional). El aislamiento entre organizaciones descansa en los gestores
  con ámbito (fail-closed) y sus pruebas. Evaluarlo si algún día otro sistema accede directo a la base.
