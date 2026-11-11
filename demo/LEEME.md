# Mostrar el sistema con ngrok

Para que otra persona abra el sistema desde su celular o computadora, con un enlace `https://…`,
sin instalar nada. Todo corre en **tu** equipo; ngrok solo abre la puerta mientras lo dejas encendido.

## Cómo se arma

```
 visitante ──https──▶ ngrok ──▶ 127.0.0.1:4173  frontend compilado (vite preview)
                                      │  /api/v1/*  (se reenvía)
                                      ▼
                                127.0.0.1:8000  backend Django ──▶ PostgreSQL (tu base de desarrollo)
```

- ngrok apunta **solo al frontend**. El navegador habla con un único origen, así que no hay CORS
  ni problemas de cookies, y basta **un** túnel (cuenta gratuita incluida).
- El backend solo escucha en tu equipo (`127.0.0.1`): nadie llega a él directo.
- Se sirve el frontend **compilado** (rápido), no el modo desarrollo.
- `/admin` de Django **no** se expone, y la documentación de la API (Swagger) queda apagada.

## Antes de empezar (una sola vez)

1. ngrok instalado y con tu *authtoken* (ya está configurado en este equipo).
2. PostgreSQL encendido (el mismo de siempre).
3. `npm install` hecho en `frontend/apps/panel-admin` (ya lo está).

Opcional pero muy recomendable: tu cuenta gratuita de ngrok tiene **un dominio fijo**
(<https://dashboard.ngrok.com/domains>, algo como `tu-nombre.ngrok-free.dev`). Así el enlace es
siempre el mismo y no tienes que mandarlo de nuevo cada vez.

## Encender

Desde la carpeta del proyecto, en PowerShell:

```powershell
.\demo\iniciar-demo.ps1                                     # dirección al azar
.\demo\iniciar-demo.ps1 -Dominio tu-nombre.ngrok-free.dev   # tu dominio fijo
```

El script compila el frontend, abre el túnel, arranca todo y te muestra el **enlace para
compartir**. **Enter** (o Ctrl+C) lo apaga todo y el enlace deja de funcionar.

Si cerraste la ventana sin apagar, o dice que un puerto está ocupado: `.\demo\detener-demo.ps1`.

**La tienda virtual** sale con su propio enlace, aparte del sistema: el sistema por ngrok y la tienda
por un túnel rápido de Cloudflare (gratis, sin cuenta; el enlace `https://algo.trycloudflare.com`
cambia en cada arranque). Hay que instalar `cloudflared` una vez:

```powershell
winget install Cloudflare.cloudflared      # luego abre una ventana nueva de PowerShell
```

Si no está instalado, el script avisa y muestra solo el sistema. La tienda se compila con el
backend encendido (la primera vez tarda más). `-SinTienda` la omite. No se cambió nada del código de
la tienda: en producción cada una irá en su propio dominio sin ningún ajuste. En otra máquina hay que
instalar `cloudflared` de nuevo.

Otras opciones: `-SinCompilar` (reutiliza la compilación anterior), `-SoloPreparar` (solo compila,
no abre nada) y `-BaseDemo` (base aparte y vacía, ver más abajo).

## Qué verá la otra persona

- Con la cuenta gratuita, **la primera vez** ngrok muestra un aviso con un botón **«Visit Site»**.
  Es normal: se pulsa una vez y listo.
- Entra con **tus usuarios de siempre** (por ejemplo `superadmin`) y ve y puede cambiar **tus datos
  reales de prueba**: es la misma base que usas en desarrollo.

## Seguridad (lee esto antes de compartir)

- **La demostración usa tu base de desarrollo.** Quien entre con un usuario tuyo puede ver y
  modificar clientes, proveedores, compras, ventas, sueldos, etc. Todo lo que haga queda guardado.
- Si prefieres que no toque tus datos, enciende con `-BaseDemo`: crea una base aparte y vacía
  (`sistema_demo`) con un usuario `demo` y una contraseña generada, guardada en
  `demo\credenciales-demo.txt`.
- Cualquiera que tenga el enlace llega a la pantalla de entrada: usa una contraseña **fuerte** en
  el usuario que vayas a prestar y compártela solo con quien quieres. Lo ideal es crear un usuario
  aparte, con solo los permisos necesarios, en vez de prestar `superadmin`.
- La demostración corre con `DEBUG` apagado (sin páginas de error con detalles) y limita los
  intentos de inicio de sesión (15 por minuto en total, porque todos los visitantes llegan con la
  misma dirección local).
- Apaga el túnel cuando termines. Mientras esté encendido, el enlace funciona para quien lo tenga.
- Los códigos QR y enlaces que genera el sistema (consulta pública del servicio técnico, correos)
  usan la dirección pública de esa sesión; con un dominio fijo siempre son los mismos.

## Dónde mirar si algo falla

Registros en `demo\logs\` (`backend.log`, `backend-errores.log`, `frontend.log`, `ngrok.log`).
El panel de ngrok (peticiones en vivo) está en <http://127.0.0.1:4040> mientras está encendido.

| Síntoma | Qué hacer |
|---|---|
| «Blocked request. This host is not allowed» | Usas un dominio que no es de ngrok: ponlo en `VITE_HOSTS_PERMITIDOS` (separados por comas) antes de encender. |
| ngrok no abre el túnel | ¿Ya tienes otro ngrok abierto? La cuenta gratuita permite una sesión. Ciérralo o `.\demo\detener-demo.ps1`. |
| «puerto 8000/4173 en uso» | `.\demo\detener-demo.ps1` |
| «Usuario o contraseña incorrectos» | Esa respuesta la da el backend: revisa usuario y contraseña. Tras 15 intentos fallidos en un minuto hay que esperar. |
| Cargó la página pero no hay datos | Si encendiste con `-BaseDemo`, esa base empieza vacía. |

## Qué se tocó en el proyecto

- `frontend/apps/panel-admin/vite.config.js`: el proxy de `/api/v1` también vale para la versión
  compilada y se aceptan los dominios de ngrok.
- `.gitignore`: ignora las credenciales y los registros de la demostración.
- Esta carpeta `demo/` (scripts y esta guía). Nada de `backend/.env` cambia.
