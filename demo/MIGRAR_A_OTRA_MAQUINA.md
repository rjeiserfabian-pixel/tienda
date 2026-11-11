# Pasar el sistema completo a otra máquina (Windows)

Cubre el backend, el panel (frontend) y la tienda virtual, con sus datos. Se hace en tres partes:
**A.** sacar todo de la máquina actual, **B.** preparar la nueva, **C.** restaurar y probar.

> Para un servidor de producción (VPS Ubuntu) no uses esta guía: está en `docs/DESPLIEGUE_VPS.md`.

## Qué hay que llevarse (y qué no)

| Qué | De dónde | Notas |
|---|---|---|
| Código | toda la carpeta `Sistema_Unido` | **Sin** `backend\env`, `node_modules`, `dist*`, `.next*`, `__pycache__` (se regeneran y pesan mucho) |
| Base de datos | PostgreSQL, base `tienda` | Es lo más importante: ahí están todos los datos |
| Archivos subidos | `backend\media` | Fotos y documentos (hoy ~1 MB) |
| Secretos | `backend\.env`, `frontend\apps\tienda-web\.env.local` | **No van en el código.** Cópialos a mano (USB o similar, nunca por correo ni chat) |

**Lo que NO puedes perder:** `CIFRADO_CLAVES` del `.env`. Con ella se descifran las credenciales
guardadas (por ejemplo las de SUNAT). Si cambia, esos datos ya no se pueden leer. También conserva
`SECRET_KEY` y `DECOLECTA_TOKEN`.

---

## A. En la máquina actual

1. **Apaga todo** (cierra la demo con Enter o `.\demo\detener-demo.ps1`) para que nadie escriba datos durante la copia.
2. **Respaldo de la base** (pide la contraseña de `DB_PASSWORD` del `.env`):
   ```powershell
   & "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -U postgres -h localhost -Fc -f "$HOME\Desktop\tienda.dump" tienda
   ```
3. **Empaqueta el código** sin lo pesado:
   ```powershell
   cd C:\Users\JEISER\Desktop
   tar -a -c -f sistema_unido.zip --exclude=env --exclude=node_modules --exclude=dist --exclude=dist-demo --exclude=.next --exclude=.next-demo --exclude=__pycache__ --exclude=.venv Sistema_Unido
   ```
   (Incluye `backend\media`, `demo\` y `docs\`.)
4. **Copia los secretos** a parte: `backend\.env` y `frontend\apps\tienda-web\.env.local`.
5. Lleva a la otra máquina: `tienda.dump`, `sistema_unido.zip` y los dos archivos de secretos.

## B. Preparar la máquina nueva (una sola vez)

Instala, con las mismas versiones o más nuevas:

| Programa | Versión usada aquí | Cómo |
|---|---|---|
| Python | 3.12 | python.org (marca «Add to PATH») |
| Node.js | 24 (sirve 22 o más) | nodejs.org |
| PostgreSQL | 16 (usa 16 o mayor) | postgresql.org; guarda la contraseña del usuario `postgres` |
| ngrok | 3.x | `winget install ngrok.ngrok`, luego `ngrok config add-authtoken TU_TOKEN` |
| cloudflared | cualquiera | `winget install Cloudflare.cloudflared` |

Luego abre una ventana **nueva** de PowerShell para que reconozca todo.

## C. Restaurar y probar

1. **Descomprime** `sistema_unido.zip` en, por ejemplo, `C:\Users\TU_USUARIO\Desktop\` (la ruta puede ser otra: nada está escrito con la ruta antigua).
2. **Secretos:** copia `backend\.env` a `Sistema_Unido\backend\.env` y `.env.local` a `Sistema_Unido\frontend\apps\tienda-web\`. En el `.env` ajusta lo que cambie en esta máquina: `DB_PASSWORD` (y `DB_HOST`/`DB_PORT` si PostgreSQL no está en `localhost:5432`). **No cambies** `CIFRADO_CLAVES` ni `SECRET_KEY`.
3. **Crea la base y restaura los datos:**
   ```powershell
   $pg = "C:\Program Files\PostgreSQL\16\bin"
   & "$pg\createdb.exe" -U postgres -h localhost tienda
   & "$pg\pg_restore.exe" -U postgres -h localhost -d tienda --no-owner --no-privileges "RUTA\tienda.dump"
   ```
   Si el nombre de la base es otro, cámbialo también en `DB_NAME`.
4. **Backend:**
   ```powershell
   cd Sistema_Unido\backend
   python -m venv env
   .\env\Scripts\python.exe -m pip install -r requirements.txt
   .\env\Scripts\python.exe manage.py check
   .\env\Scripts\python.exe manage.py migrate      # no debe aplicar nada nuevo si el respaldo era actual
   ```
5. **Frontend y tienda:**
   ```powershell
   cd ..\frontend\apps\panel-admin ; npm install
   cd ..\tienda-web ; npm install
   ```
6. **Prueba rápida (solo en esa máquina):** en el backend `.\env\Scripts\python.exe manage.py runserver`, en el panel `npm run dev` (http://localhost:5173) y en la tienda `npm run dev` (http://localhost:3000, con el backend encendido).
7. **Para mostrarlo por internet:** `.\demo\iniciar-demo.ps1` desde la carpeta del proyecto, igual que aquí.

## Lista de comprobación al terminar

- [ ] Entras al panel con `superadmin` y ves los datos de siempre (productos, ventas, clientes).
- [ ] Las fotos de productos se ven (confirma que `media` llegó completa).
- [ ] La consulta de DNI/RUC funciona (el `DECOLECTA_TOKEN` está bien copiado).
- [ ] La configuración de SUNAT/facturación se abre sin error (la clave de cifrado es la correcta).
- [ ] La tienda carga en http://localhost:3000 con los productos.
- [ ] `manage.py migrate` no aplicó nada inesperado.

## Cosas a tener en cuenta

- **ngrok gratis permite una sesión a la vez con tu cuenta.** Si lo enciendes en las dos máquinas con el mismo token y dominio, una expulsa a la otra.
- **No uses la máquina vieja y la nueva a la vez con datos distintos:** la copia de la base es una foto de ese momento. Lo que se registre después en la vieja no aparece en la nueva.
- Si falta una librería al instalar el backend, el error dice cuál (algunas piden compilador o pueden variar según la versión de Python): usa Python 3.12.
- Redis no hace falta en una PC de desarrollo (`USAR_REDIS=False`).
- `app-movil` (Flutter) no forma parte de esta guía.
