# Plan de arranque del Backend – Sistema Unificado

Estado: FASE 1 IMPLEMENTADA (80 tests en verde, lint limpio, auditoría de dependencias sin vulnerabilidades).
Desviaciones respecto al plan: ver la sección "Cambios de implementación" al final.

## 1. Entorno virtual y dependencias

Python: **3.12** (obligatorio). Se crea el entorno con ese intérprete: `py -3.12 -m venv env`.
Ubicación: `Sistema_Unido\backend\env`.
Activación en PowerShell: `.\env\Scripts\Activate.ps1`.

Archivos de requisitos (según tu estructura `requirements/{base,dev,prod}.txt`):

| Archivo | Paquetes |
|---|---|
| base.txt | Django 5.x, djangorestframework, djangorestframework-simplejwt, psycopg[binary] (PostgreSQL), django-redis, redis, celery, django-environ, django-cors-headers, django-filter, drf-spectacular, cryptography (credenciales SUNAT cifradas), pyotp (MFA, fase 5), argon2-cffi (hash de contraseñas) |
| dev.txt | -r base.txt, pytest, pytest-django, pytest-cov, factory-boy, django-debug-toolbar, black, ruff |
| prod.txt | -r base.txt, gunicorn, sentry-sdk |

Versiones: se fijan al instalar (`pip freeze`) para que sea reproducible.
`env/` irá en `.gitignore`.
Base de datos: **PostgreSQL** instalado con su gestor (pgAdmin).

| Dato | Valor |
|---|---|
| Base de datos | `tienda` |
| Usuario | `postgres` |
| Contraseña | `root` |
| Host / puerto | `localhost` / `5432` |

**Credenciales en un solo lugar**: todas (base de datos, Redis, SECRET_KEY, clave de cifrado SUNAT, JWT, CORS, etc.) se leen de un único archivo `backend/.env`.
- `.env` NO se sube al repositorio (va en `.gitignore`).
- `.env.example` se sube con los nombres de las variables y valores de ejemplo, sin secretos reales.
- Ningún valor sensible queda escrito en el código ni en `settings`.
- Nota: `postgres`/`root` es válido solo para tu máquina de desarrollo. En el VPS se cambian por un usuario propio con contraseña fuerte, editando solo el `.env`.

## 2. Estructura que se crea (Fase 1)

```
Sistema_Unido/
├── backend/
│   ├── env/
│   ├── manage.py
│   ├── config/
│   │   ├── settings/{base,dev,prod}.py
│   │   ├── urls.py, celery.py, wsgi.py, asgi.py
│   ├── apps/
│   │   ├── core/          (clases base, tenant, paginación, throttles, excepciones, crypto)
│   │   └── organizacion/  (Organizacion, Empresa, Sucursal, ConfiguracionEmpresa)
│   ├── requirements/{base,dev,prod}.txt
│   ├── .env.example
│   └── docker/            (después)
└── frontend/              (ver sección 2.1)
```

### 2.1 Frontend (React) – solo estructura lista, sin programar pantallas

Se crea el proyecto base y las carpetas vacías de tu diseño, para que luego solo se programe:

```
frontend/
├── apps/panel-admin/           (React + Vite, JavaScript/JSX)
│   └── src/
│       ├── core/    api/  auth/  router/
│       ├── shared/  contexts/  hooks/  components/  layouts/
│       └── modules/seguridad/pages/
├── apps/tienda-web/            (tienda virtual, Next.js; carpeta reservada, futuro)
└── packages/{api-client,validators,ui}   (carpetas reservadas)
```

- Dependencias iniciales de `admin`: react, react-dom, react-router-dom, axios, @tanstack/react-query. Más adelante se suman lo que haga falta.
- Se configura el proxy de Vite hacia el backend (`/api/v1`) y CORS en Django para desarrollo.
- Requisito: Node.js 20 LTS o superior (se verifica al instalar).
- No se crean pantallas ni lógica; solo el esqueleto, un `App` mínimo que arranca y la carpeta con archivos `.gitkeep`.

La app `seguridad` (usuarios, roles, permisos) se crea en las Fases 2 y 3, no ahora.

## 3. Alcance de la Fase 1 (Fundamentos)

1. Proyecto Django con settings separados (base/dev/prod) y variables en `.env`.
2. Conexión a PostgreSQL (`tienda`) y Redis (caché) ya configuradas en settings, leyendo todo del `.env`.
3. Celery configurado con Redis como broker (sin tareas aún).
3.1. `docker-compose.yml` en la raíz (solo para usarlo en el VPS, no se ejecuta en tu PC) y `docs/DESPLIEGUE_VPS.md` con los pasos para subir al VPS.
4. `core`:
   - `OrganizacionScopedModel` y `EmpresaScopedModel` (clases base abstractas).
   - Managers que filtran automáticamente por organización / empresas habilitadas.
   - Contexto de tenant por request (sin "empresa por defecto": toda creación declara empresa).
   - Paginación: **25 por página por defecto**, el cliente puede pedir 10, 25, 50 o 100 (`page_size`, máximo 100). Cursor para tablas que crecen sin fin, también de 25. Throttles base, manejo uniforme de errores.
   - Utilidad de cifrado para credenciales SUNAT.
5. `organizacion`: modelos Organizacion, Empresa (RUC único), Sucursal, ConfiguracionEmpresa.
6. Prefijo `/api/v1/` y OpenAPI con drf-spectacular.
7. Comandos: `crear_organizacion`.

### 3.2 Mejoras de seguridad incorporadas a la Fase 1 (tocan las clases base)

1. **Trazabilidad y borrado lógico**: las clases base incluyen `creado_en`, `actualizado_en`, `creado_por`, `actualizado_por`, `eliminado_en`. Los managers ocultan por defecto lo eliminado. Nada con valor contable se borra físicamente.
2. **Documentos inmutables**: clase base `DocumentoInmutable` para comprobantes y movimientos: una vez emitidos no se editan ni se eliminan, solo se anulan o se corrigen con nota de crédito (se bloquea en el modelo, no solo en la vista). El cierre de períodos se construye en los módulos contables.
3. **Cifrado con versión de clave**: `core/crypto.py` guarda el identificador de versión de la clave junto al dato cifrado y trae un comando `rotar_clave_cifrado` para re-cifrar si la clave cambia.
4. **Zona horaria y dinero**: `TIME_ZONE = America/Lima`, `USE_TZ = True`. Todo importe con `DecimalField` (nunca float), con helpers de redondeo en `core/utils/dinero.py`.
5. **Idempotencia**: utilidad `core/idempotencia.py` y cabecera `Idempotency-Key` para operaciones críticas (cobros, emisión), guardada con su resultado para que un reintento o doble clic no duplique. Se deja lista aquí y se usa desde el módulo de ventas.

### 3.3 Mejoras que entran en las fases ya previstas (no cambian la estructura)

| Mejora | Fase |
|---|---|
| Desactivar usuario revoca sus sesiones al instante y conserva su historial | 2 |
| Bloqueo de login con `django-axes` (o equivalente), además del throttle | 2 |
| Logging estructurado con `request_id` en todos los logs (middleware ya previsto) | 1 (base) y 5 |
| Políticas de retención de auditoría y sesiones, con tarea de limpieza | 5 |
| `django-csp`, cabeceras seguras y `pip-audit` de dependencias | 5 |
| Backups con `pg_dump` programado y prueba de restauración en otra máquina, documentados en `docs/DESPLIEGUE_VPS.md` | 5 (guía base en Fase 1) |

Se mantienen fuera por ahora: microservicios y particiones tempranas (no hacen falta para decenas a ~200 usuarios); RLS de PostgreSQL sigue como opcional en la Fase 5.

## 4. Criterio de terminado

- Dos modelos de prueba (uno por ámbito) y tests que demuestran que **nunca cruzan datos** entre organizaciones ni entre empresas.
- Un test falla si un listado no pagina.
- Tests de las mejoras: el borrado lógico oculta registros, un documento inmutable rechaza editar/eliminar, el cifrado descifra tras rotar la clave, y repetir una petición con la misma `Idempotency-Key` no crea un segundo registro.
- `pytest` en verde y `python manage.py check` sin errores.

## 5. Fases siguientes (referencia, sin tocar aún)

2 Identidad (usuario, accesos, JWT, sesiones) → 3 RBAC → 4 Gestión → 5 Auditoría y endurecimiento → 6 Tienda y app.

## 6. Decisiones ya tomadas

- Python 3.12.
- Entorno virtual: `env`.
- Base de datos: PostgreSQL con su gestor (sin SQLite). Base `tienda`, usuario `postgres`, contraseña `root`.
- Credenciales: todas en `backend/.env` (no se sube al repositorio) más `.env.example`.
- Redis: se configura desde la Fase 1 pero queda apagado en tu PC (sin Docker); se activa en el VPS cambiando el `.env` (ver sección 7).
- Idioma del código: español.
- Frontend: React (Vite), solo estructura en esta etapa.
- Paginación: 25 por defecto (opciones 10/25/50/100, máximo 100). Recomiendo 25 sobre 20: en tablas de ventas, productos o clientes muestra más filas sin hacer pesada la consulta, y los múltiplos 25/50/100 son cómodos para el selector.

- Idioma del código: nombres de modelos y campos en español (Organizacion, Empresa, Sucursal…).

## 7. Redis: cómo se maneja (VPS y restauración)

Redis aquí es solo **caché y cola de tareas**. La información real vive en PostgreSQL. Por eso:

- **Restaurar en otra máquina**: solo se restaura PostgreSQL (backup/`pg_dump`). Redis arranca vacío y se vuelve a llenar solo; no hay nada que migrar.
- **Subir a un VPS (Linux)**: es simple. Se instala con `apt install redis-server` y se configura contraseña y acceso solo local. Otra opción es un `docker-compose` con Postgres + Redis + backend, que se levanta igual en cualquier máquina con un solo comando.
**Decisión: Redis se configura ya, en la Fase 1**, para que en el VPS solo cambien valores del `.env`.

Qué se deja listo:
- `django-redis` como caché y Redis como broker/resultados de Celery, con `REDIS_URL` en el `.env` (ej. `redis://localhost:6379/0`, y bases separadas: 0 caché, 1 Celery, 2 throttling).
- Settings de `dev` y `prod` ya apuntando a Redis (en prod con contraseña y `rediss://` si aplica).
- `docker-compose.yml` con Redis (y PostgreSQL opcional) para levantar todo con `docker compose up -d` en tu PC o en el VPS.
- `docs/DESPLIEGUE_VPS.md`: instalación de Redis con `apt`, contraseña, bind a localhost, persistencia opcional, y variables del `.env` a cambiar.
- Comando de verificación (`manage.py check_servicios`) que prueba la conexión a PostgreSQL y Redis.

**En tu PC (Windows) NO se ejecuta Redis ni Docker.** Queda configurado pero apagado en desarrollo, con un interruptor en el `.env`:

| Variable (`.env` de desarrollo) | Valor en tu PC | Valor en el VPS |
|---|---|---|
| `USAR_REDIS` | `False` | `True` |
| `REDIS_URL` | (vacío) | `redis://:CLAVE@localhost:6379/0` |
| `CELERY_TASK_ALWAYS_EAGER` | `True` (las tareas corren al instante, sin worker) | `False` |

- Con `USAR_REDIS=False`: caché en memoria local y Celery ejecutando tareas en el mismo proceso. El sistema funciona completo, sin instalar nada extra.
- En el VPS: se instala Redis, se cambian esas variables y listo; no se toca código.
- Limitaciones aceptadas en desarrollo: la caché no se comparte entre procesos y el throttling se reinicia al reiniciar el servidor. No afecta el desarrollo con un solo proceso.
- Los tests de permisos con Redis real se ejecutan en el VPS o en CI cuando exista.

## 8. Pendiente de confirmar

Nada pendiente que bloquee. Con tu visto bueno empiezo la Fase 1.

Cuando me des el visto bueno y las respuestas, ejecuto la Fase 1.

## Cambios de implementación (Fase 1)

- **Python 3.12.16** instalado con `uv` dentro de `backend/env` (el sistema solo tenía 3.13).
- **Usuario mínimo** (`seguridad.Usuario`, UUID, correo único, organización): Django exige definir el modelo de usuario antes de la primera migración. La Fase 2 lo amplía.
- **Auditoría sin clave foránea**: `creado_por_id`, `actualizado_por_id`, `anulado_por_id` guardan el UUID del usuario (evita dependencias circulares entre apps y conserva la huella).
- **Fail-closed**: sin contexto de tenant, los gestores lanzan error en vez de devolver datos. El acceso sin aislamiento es explícito con `.sin_ambito()`.
- **`REDIS_URL`** va sin número de base (`redis://:CLAVE@localhost:6379`); las bases 0/1/2 se asignan solas.
- El admin de Django es de solo lectura para organización/empresa/sucursal; las altas se hacen con servicios o el comando `crear_organizacion`.
- `requirements/lock.txt` contiene las versiones exactas instaladas.

## Fase 2 – Identidad (implementada)

- Modelos: `Usuario` ampliado, `AccesoEmpresa`, `AccesoSucursal`, `Sesion`, `HistorialPassword`.
- API `/api/v1/seguridad/`: `auth/login`, `auth/refresh`, `auth/logout`, `auth/logout-global`, `auth/cambiar-password`, `me`, `sesiones`, `sesiones/{id}` (DELETE).
- Access 15 min con `org_id` y `empresas`; refresh rotativo con detección de reutilización (revoca la sesión) y ventana de gracia de 10 s para dos pestañas.
- Web: refresh en cookie HttpOnly + SameSite=Strict; móvil: refresh en el cuerpo.
- Bloqueo progresivo por identificador (también para usuarios inexistentes) + throttle por IP.
- Un access token de una sesión revocada se rechaza al instante (marca en caché); revocar sesiones al desactivar un usuario es automático (señal).
- Comandos: `crear_admin_plataforma`, `crear_usuario`.
- Frontend: cliente con refresh en cola, `AuthProvider`, `RequireAuth`, pantalla de login.
- Límite conocido: las `empresas` del access token se refrescan en cada refresh (≤ 15 min de desfase si se quita un acceso).

## Fase 3 – RBAC (implementada)

- Modelos: `Permiso`, `Modulo` (globales), `Rol`, `RolPermiso`, `UsuarioRol` (empresa opcional), `UsuarioPermiso` (ALLOW/DENY con motivo).
- Catálogo único en `permisos_catalogo.py` (57 permisos, menú y 8 roles plantilla) + `sync_permisos` idempotente.
- Motor `tiene_permiso(usuario, codigo, empresa)`: acceso vigente → admin plataforma → DENY → ALLOW/roles (alcance más amplio). Caché por (usuario, empresa) con invalidación por versión; permisos temporales acortan el TTL.
- Operaciones mixtas: `exigir_permiso_en_empresas` verifica cada empresa y rechaza todo si falta una.
- DRF: `PermisoRBAC` (fail-closed si la vista no declara permiso) y `ScopedQuerysetMixin` (PROPIO/ASIGNADO/SUCURSAL/EMPRESA/ORGANIZACION).
- Anti-escalada, roles de sistema intocables, último administrador protegido, separación de funciones (utilidad).
- API: `permisos/catalogo/`, `permisos/mios/?empresa=`, `menu/`.
- Frontend: `EmpresasContext`, `PermisosContext`, `Can`, `RequirePermiso`, `ChipsEmpresa`, `DashboardLayout` con menú dinámico.
- Convención: en vistas de modelos con ámbito se declara `modelo = X`, nunca `queryset = X.objects.all()` a nivel de clase.
- Fuera de esta fase (Fase 4): pantallas y endpoints CRUD de roles/usuarios/accesos (los servicios ya existen y están probados).

## Fase 4 – Gestión (implementada)

**API (`/api/v1/`)**
- `seguridad/usuarios/` (listado con `?q&activo&empresa&rol`, alta, detalle, `PATCH`), `…/{id}/desactivar|reactivar/`, `…/{id}/accesos/{empresa}/` (PUT/DELETE), `…/{id}/roles/` (POST) y `…/roles/{asignacion}/` (DELETE), `…/{id}/excepciones/` (POST) y `…/excepciones/{id}/` (DELETE).
- `seguridad/roles/` (CRUD sin editar roles de sistema) y `…/{id}/permisos/` (GET matriz, PUT reemplaza).
- `organizacion/` (GET/PATCH), `organizacion/empresas/`, `organizacion/sucursales/` (`?empresa=`). Empresas e sucursales no se eliminan: se inactivan.

**Reglas que hace cumplir el servidor** (`services/gestion_usuarios.py`, `organizacion/services/gestion.py`)
- Un usuario solo ve a quienes comparten una empresa donde su alcance llega a la empresa entera (más sí mismo y usuarios sin accesos); fuera de eso, 404.
- No se modifica (correo, desactivación, restricción de acceso) a quien tenga más permisos que uno mismo; nadie opera sobre su propia cuenta en desactivar/accesos.
- Dar acceso a una empresa exige poseer los roles globales del destinatario (si no, serviría para escalar).
- El RUC es inmutable; la organización conserva al menos una empresa activa; empresa nueva = sucursal "001" + configuración + acceso del creador.
- Las empresas inactivas siguen listadas para quien tiene acceso, para poder reactivarlas.

**Frontend** (`modules/seguridad`, `modules/organizacion`): usuarios (lista, alta, ficha con accesos/roles/excepciones), roles (lista, ficha, matriz), empresas, sucursales, mis sesiones, cambio de contraseña (obligatorio si la clave es temporal). Kit compartido: `useDebounce`, `useListado`, `useMutacion`, avisos, `Paginacion`, `Modal`, `Campo`, `EstadoConsulta`.

**Pendiente / límites**
- La clave temporal se fuerza solo en la interfaz; el bloqueo en la API va en la Fase 5.
- Un acceso quitado o una empresa creada se refleja en el token al renovarlo (≤15 min; el front renueva al crear/cambiar empresa).
- Administrador de plataforma: se gestiona por comandos/Django admin, no por este panel.
- Sin auditoría de estos cambios todavía (Fase 5): por ahora solo hay logs estructurados.

## Fase 5 – Auditoría, segundo factor, recuperación y endurecimiento (implementada)

**Auditoría** (`apps/auditoria`): tabla de solo-agregar (el modelo y el QuerySet impiden editar/borrar; solo la purga por
retención borra). `registrar(accion, …)` se encola en Celery tras el COMMIT (lo revertido no deja evento); los intentos de
acceso se guardan aunque la operación falle; si el broker cae se inserta directo y, si tampoco se puede, queda en el log
como CRITICAL. Se sanean secretos. Cubre ingresos/fallos/bloqueos/reuso de refresh, contraseñas, MFA, usuarios, accesos,
roles, matriz de permisos, excepciones, empresas, sucursales y organización. Consulta: `GET /api/v1/auditoria/eventos/`
(cursor; filtros `accion` por prefijo, `usuario`, `recurso_*`, `empresa`, `exito`, `desde`, `hasta`).

**Segundo factor TOTP**: secreto cifrado, anti-repetición del código, 10 códigos de recuperación (solo huella),
bloqueo tras `MFA_MAX_FALLOS`. Login en dos pasos (`auth/mfa/verificar/`; sin sesión hasta validar el código). Política
`Organizacion.mfa_obligatorio`. Un administrador puede restablecer el factor de otro (exige cubrir sus permisos, cierra sus
sesiones y queda auditado).

**Recuperación de contraseña**: respuesta idéntica exista o no la cuenta; el token se genera dentro de la tarea; vence,
un solo uso, huella SHA-256; exige código si hay MFA; cierra todas las sesiones y levanta el bloqueo.

**Endurecimiento**: la API bloquea (no solo la interfaz) clave temporal y MFA obligatorio sin activar; cabeceras de
seguridad en la API; retención de auditoría y sesiones (Celery beat); `pip-audit` y `npm audit` limpios.

**No incluido**: RLS de PostgreSQL (opcional), auditoría de lecturas, alertas automáticas ante eventos sospechosos,
WebAuthn/passkeys. Ver `docs/DESPLIEGUE_VPS.md` sección 10 para lo que debe configurarse en el VPS.

**Cambio posterior (paginación de la auditoría):** la consulta de auditoría pasó de cursor a paginación por número de página
(`PaginaAuditoria`: 20 filas por defecto, tamaños 10/20/50/100, con total), igual que el resto de listados. Los demás
listados siguen en 25 por defecto (10/25/50/100). "Mis sesiones" también pagina por número (20 por defecto, 10/20/50/100); ya no queda ninguna pantalla con cursor. Si la tabla de auditoría llegara a
millones de filas, el conteo total se vuelve lento: en ese caso volver al cursor o contar de forma aproximada.


### Restablecer contraseña por un administrador (usuario sin acceso a su correo)

- `POST /api/v1/seguridad/usuarios/{id}/restablecer-password/` → `{"password_temporal": "..."}` (una sola vez, `Cache-Control: no-store`).
- Permiso propio y crítico `SEGURIDAD.USUARIOS.RESTABLECER_CLAVE` (SUPERADMIN y ADMIN). En despliegues existentes, el rol ADMIN es editable y `sync_permisos` no lo toca: hay que marcar el permiso en la matriz del rol Administrador (o asignarlo por script).
- Reglas: misma organización, nunca sobre la propia cuenta, el actor debe poseer todo lo que posee el objetivo (un ADMIN no restablece a un SUPERADMIN).
- Efectos: contraseña aleatoria (14 caracteres, sin ambiguos, cumple los validadores), `debe_cambiar_password=True`, entra al historial, cierra todas las sesiones (motivo `CLAVE_RESTABLECIDA`) y audita `password.restablecida_admin` sin guardar la clave.
- Panel: botón «Restablecer contraseña» en la ficha del usuario (modo edición).

## Mantenimiento – Personal, Clientes y Proveedores (implementado)

- App `apps/mantenimiento`; API en `/api/v1/mantenimiento/{personal,clientes,proveedores}/` (listado paginado con `q`, `estado`, `orden`; alta, `PATCH`, baja lógica con `DELETE`).
- **Permisos renombrados** a `MANTENIMIENTO.<SUBMÓDULO>.<ACCIÓN>` con acciones `VER`, `CREAR`, `EDITAR`, `ELIMINAR` (`ELIMINAR` es crítico). `PRODUCTOS` quedó renombrado y listo (`PRECIOS.CAMBIAR` → `MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO`), sin pantalla aún.
- **Migración de permisos:** `sync_permisos` aplica `RENOMBRES` (permisos_catalogo.py): el permiso viejo conserva sus roles y excepciones con el nombre nuevo, y `*.GESTIONAR` pasa a `EDITAR` + `CREAR` (copia los roles que lo tenían). Es idempotente. Los roles editables (p. ej. ADMIN) no reciben automáticamente los permisos realmente nuevos (`PERSONAL.*`, `*.ELIMINAR`): asignarlos en la matriz del rol o por script tras desplegar.
- **Ámbito:** clientes y proveedores son de la organización (alcance ORGANIZACION); personal es de cada empresa (la empresa viaja en el cuerpo al crear y es inmutable).
- **Documento** (DNI 8 dígitos, RUC con dígito verificador, CE, pasaporte, otro): se normaliza y es único por organización (clientes/proveedores) o por empresa (personal) mientras no esté eliminado.
- **Consulta RENIEC/SUNAT (Decolecta):** `GET /api/v1/mantenimiento/consultas/{dni,ruc}/<número>/`. Permiso `MANTENIMIENTO.CONSULTAS.USAR`, límite de 20/min por usuario (`THROTTLE_CONSULTAS`), formato validado antes de llamar, timeout de 8 s, caché de 6 h y auditoría `documento.consultado`. El token va solo en `backend/.env` (`DECOLECTA_TOKEN`; `DECOLECTA_URL` opcional). El plan gratuito trae 100 consultas al mes (no 1 000; se corrigió con el perfil de Decolecta). Sin token el endpoint responde 503 y el formulario sigue funcionando a mano.
- **Vínculo Personal ↔ Usuario:** campo opcional `usuario` en el trabajador (uno a uno, misma organización); exige poder ver usuarios; al eliminar al trabajador el usuario queda libre. La ficha del usuario muestra «Trabajador: …».
- **Asesor del cliente:** `Cliente.asesor` (usuario). Al registrar queda quien lo crea; solo quien tiene `MANTENIMIENTO.CLIENTES.ASIGNAR_ASESOR` (Superadmin y Administrador) puede elegir o cambiar a otro (el intento de otros se ignora). Filtro `?asesor=<id>`, el alcance «propio» de un cliente es el de su asesor, los clientes anteriores quedaron con quien los registró. En despliegues existentes, dar el permiso al rol Administrador.
- **Trabajador:** campo opcional `fecha_nacimiento` (entre 1900 y hoy; el ingreso no puede ser anterior).
- **Pendiente:** importación masiva, crear el usuario desde la ficha del trabajador, y la pantalla de Productos.

### Cambiar el nombre de usuario (inicio de sesión)

- `PATCH /api/v1/seguridad/usuarios/{id}/` acepta `username`. Exige el permiso crítico `SEGURIDAD.USUARIOS.CAMBIAR_USUARIO` (Superadmin y Administrador; asignable a otros roles), nunca sobre la propia cuenta, y el solicitante debe cubrir los privilegios del objetivo.
- Mismas reglas que al crear (sin espacios ni «@») y sin repetirse **ni con otras mayúsculas** (el ingreso busca sin distinguir mayúsculas). Esta última regla también se aplica ahora al crear usuarios.
- Auditoría `usuario.username_cambiado` con el nombre anterior y el nuevo. No cierra sesiones abiertas; la persona debe usar el nombre nuevo en su próximo ingreso. En despliegues existentes, dar el permiso al rol Administrador.

### Proveedores: cuenta bancaria y productos de referencia

- `Proveedor.cuenta_bancaria` (5–30 letras, números o guiones; se normalizan los espacios) y `productos_referencia` (texto libre hasta 1 000 caracteres, entra en la búsqueda `?q=`).
- La cuenta es un dato financiero: solo la devuelve la API a quien puede **editar** proveedores (quien solo consulta la recibe en `null`) y la auditoría registra que cambió, no su valor.

### Menú: Clientes en Ventas y Proveedores en Compras

- Clientes → **Ventas › Clientes** (`/ventas/clientes`); Proveedores → **Compras › Proveedores** (`/compras/proveedores`). Compras pasó de entrada suelta a grupo (con «Compras» en `/compras/registro`). Mantenimiento conserva Personal y Productos (y lo que se configura una vez). Los permisos siguen siendo `MANTENIMIENTO.CLIENTES.*` y `MANTENIMIENTO.PROVEEDORES.*`.
- Las direcciones antiguas `/mantenimiento/clientes` y `/mantenimiento/proveedores` (con o sin `/:id`) redirigen a las nuevas conservando `?modo=` y `#`.
- «Historial de ventas» pasó a `/ventas/historial` para no chocar con el prefijo `/ventas/…` al resaltar el ítem activo del menú.

### Mantenimiento: Familias, categorías y marcas (catálogos de la organización)

- Compartidos por **todas las empresas de la organización** (alcance ORGANIZACION): lo que crea una tienda lo ve la otra. Nombres únicos sin distinguir mayúsculas ni espacios de más (marcas y familias por organización; categorías por familia, con el mismo nombre permitido en otra familia). Dos niveles: **Familia › Categoría**.
- API `/api/v1/mantenimiento/{familias,categorias,marcas}/` (listado paginado, `?q=`, `?estado=`, y `?familia=` en categorías; `n_categorias` en familias). Una categoría se puede mover de familia; una familia inactiva no recibe categorías nuevas; no se elimina una familia con categorías (409 `familia_con_categorias`). Baja lógica: el nombre queda libre.
- Permisos `MANTENIMIENTO.CLASIFICACION.*` (familias y categorías) y `MANTENIMIENTO.MARCAS.*` con Ver/Crear/Editar/Eliminar. El Almacenero recibe Ver. En despliegues existentes, asignar los nuevos al rol Administrador.
- Pantallas: «Familias y categorías» (familias a la izquierda, categorías de la familia elegida a la derecha) y «Marcas» (lista y ficha como los demás maestros), ambas en el menú Mantenimiento.

### Mantenimiento: Almacenes y centros de costo

- **Almacenes** (por empresa): código y nombre únicos dentro de la empresa (sin distinguir mayúsculas), sucursal activa de la misma empresa, tipo (principal, exhibición, servicio técnico, mermas, otro), «se vende desde aquí», dirección y responsable opcional (Personal de la misma empresa). La empresa no cambia. API `/api/v1/mantenimiento/almacenes/` (`?empresa=`, `?tipo=`, `?q=`). El Almacenero recibe Ver (alcance empresa).
- **Centros de costo** (de la organización, compartidos por las empresas): código y nombre únicos, dos niveles (grupo › centro), no se elimina un grupo con centros dentro (409 `centro_con_hijos`). API `/api/v1/mantenimiento/centros-costo/` (`?padre=ninguno|ID`, `n_hijos`).
- Permisos `MANTENIMIENTO.ALMACENES.*` y `MANTENIMIENTO.CENTROS_COSTO.*` (Ver/Crear/Editar/Eliminar). En despliegues existentes, asignarlos al rol Administrador.
- El stock y los movimientos por almacén llegan con el módulo de Almacén; aquí solo se definen los lugares.

### Importación masiva y crear usuario desde un trabajador

- **Importación** de clientes y proveedores desde Excel (`.xlsx`, con `openpyxl` en modo solo lectura) o CSV: `GET .../clientes|proveedores/plantilla/` (CSV con BOM y fila de ejemplo) y `POST .../importar/` (multipart `archivo` + `modo=validar|importar`). Límites: 2 MB, 2 000 filas, 20 importaciones por hora y usuario (`THROTTLE_IMPORTACIONES`). Permiso crítico propio `MANTENIMIENTO.CLIENTES.IMPORTAR` / `MANTENIMIENTO.PROVEEDORES.IMPORTAR` (Superadmin y Administrador; en despliegues existentes, asignarlo al rol Administrador).
- Flujo en dos pasos: `validar` informa (válidas, errores por fila, repetidos) sin guardar nada; `importar` vuelve a validar y crea solo las válidas en una transacción con `bulk_create`. Nunca sobrescribe: un documento que ya existe se omite. Encabezados con otros nombres y sin tildes se reconocen; se deduce el tipo de documento por el largo y se reponen los ceros de los DNI que Excel pierde. Quien importa queda como asesor de los clientes. Un solo evento de auditoría (`cliente.importado` / `proveedor.importado`) con los totales. Se instala `openpyxl` (añadido a `requirements/base.txt` y `lock.txt`).
- **Crear usuario desde la ficha del trabajador:** botón «Crear usuario» (si el trabajador no tiene usuario y quien lo usa puede crear usuarios): abre «Nuevo usuario» con sus datos copiados y un usuario sugerido (inicial + primer apellido); al crearlo se vincula solo.
- **Pendiente:** completar clientes/proveedores solo con una lista de DNI/RUC consultando a SUNAT/RENIEC (consume cuota; conviene como tarea en segundo plano) y aclarar qué se espera del «SBS» de Personal.

### Mantenimiento: Tipo de cambio (SUNAT y SBS)

- `TipoCambio` (por organización): fecha, compra, venta (soles por dólar, 4 decimales) y fuente `SUNAT`, `SBS` (promedio), `SBS_CONTABLE` (un solo valor: compra = venta) o `MANUAL`. Único por fecha y fuente. Cada tasa oficial se guarda con la **fecha que devuelve el servicio** (la SBS publica con un día de retraso).
- Servicio `apps/mantenimiento/tipo_cambio.py` (Decolecta: `/v1/tipo-cambio/sunat`, `/sbs/average`, `/sbs/accounting`): token solo del entorno, timeout, y si una fuente falla las demás se guardan igual. `vigente(organizacion, fecha, fuente)` devuelve la tasa de ese día o, si no hay (feriado), la anterior: es lo que usarán Ventas, Compras y Caja.
- Tarea programada `mantenimiento.actualizar_tipo_cambio` (Celery beat, lunes a sábado 9:30 hora de Lima) para todas las organizaciones activas; requiere el proceso `celery beat` en el VPS. También hay botón «Actualizar ahora» (`POST .../tipo-cambio/actualizar/`, consume cuota).
- API `/api/v1/mantenimiento/tipo-cambio/` (`?fuente=`, `?desde=`, `?hasta=`, `resumen/`). Las filas oficiales no se editan ni se borran (409 `tipo_cambio_oficial`); las manuales sí, con validaciones (> 0, venta ≥ compra y no desmedida, sin fecha futura). Permisos `MANTENIMIENTO.TIPO_CAMBIO.*`; Vendedor, Cajero, Almacenero y Contador reciben Ver.

### Cuota de Decolecta (plan gratuito: 100 consultas al mes)

- Cada consulta que sale (DNI, RUC o tipo de cambio) se cuenta en `ConsumoApi` (por mes). El sistema se detiene al llegar al límite (`DECOLECTA_LIMITE_MENSUAL`, 100): responde 429 `cuota_agotada` y todo sigue funcionando a mano. El proveedor no entrega su contador por API: la cuenta es propia y se calibra con `manage.py consumo_decolecta --fijar N` (cifra de https://decolecta.com/profile). `GET /api/v1/mantenimiento/consultas/uso/` y `tipo-cambio/resumen/` muestran el uso; la pantalla de Tipo de cambio lo enseña.
- **Tipo de cambio: la actualización diaria viene APAGADA** (`TIPO_CAMBIO_AUTOMATICO=False`). Por defecto «Actualizar» trae solo SUNAT (1 consulta); SBS se pide aparte (2). No se vuelve a consultar lo que ya se tiene ni lo consultado hace menos de 6 horas. Si se activa lo automático, usa solo `TIPO_CAMBIO_FUENTES_AUTOMATICAS` y se detiene al pasar el `TIPO_CAMBIO_UMBRAL_AUTOMATICO` (60 %) de la cuota.

### Almacén: Productos, unidades de medida y listas de precios

- El menú «Inventario» pasa a llamarse **Almacén** y empieza con **Productos** (`/almacen/productos`); en Mantenimiento se agregan **Unidades de medida** y **Listas de precios**. Catálogo único de la organización, compartido por sus empresas.
- **Unidades de medida** (`/api/v1/mantenimiento/unidades/`): nombre y abreviatura únicos, código SUNAT opcional; `POST sembrar/` carga las 10 más comunes sin duplicar. **Listas de precios** (`/listas-precio/`): los nombres son configurables (por defecto Público, Descuento, Técnico, Crédito con `POST sembrar/`); la primera es la **principal** y no se desactiva ni se elimina. Una unidad, lista, categoría o marca que algún producto usa no se elimina (409 `registro_en_uso`): se desactiva.
- **Productos** (`/productos/`; `?q=` nombre, código, barras o código del fabricante; `?estado=`, `?tipo=`, `?familia=`, `?categoria=`, `?marca=`): código interno automático (`000001…`, correlativo por organización con bloqueo de fila), tipo Bien/Servicio (un servicio nunca lleva stock ni serie), categoría (de ahí sale la familia), marca opcional, unidad, código de barras único por organización (si falta se usa el interno en etiquetas), stock mínimo y los interruptores controlar stock, serie/IMEI y precio editable. Primera etapa: **solo unidad base** (sin presentaciones) y **todo en soles**.
- **Precios:** `precio = costo × (1 + utilidad/100)`. El precio es lo que se guarda; la utilidad se deriva (si llega solo la utilidad, se calcula el precio). Si cambia el costo, los precios no se mueven y se recalcula la utilidad. Poner o cambiar costo y precios exige `MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO` (403 si no); sin ese permiso el costo y la utilidad ni se devuelven. Los precios de una lista desactivada se conservan al editar. Cambios de precio quedan en la auditoría (valor anterior y nuevo).
- **Fotos** (hasta 8 por producto, la primera es la principal) pensadas para reutilizarlas en la tienda virtual: el archivo se valida con Pillow (solo JPG/PNG/WEBP, ≤ 5 MB, tope de píxeles contra «bombas»), se corrige la rotación, se **re-codifica a WebP** (grande ≤ 1600 px y miniatura ≤ 400 px; así se pierden metadatos como el GPS) y se guarda en `MEDIA_ROOT/productos/<org>/<producto>/` con nombre aleatorio. **No son públicas:** se sirven por la API (`GET .../productos/ID/fotos/FOTO/imagen/?tam=mini`) con sesión y permiso; el panel las pide con el token. Endpoints: `GET|POST .../fotos/`, `POST .../fotos/FOTO/principal/`, `DELETE .../fotos/FOTO/`. Para la tienda pública se publicarán después las versiones aprobadas por una vía aparte.
- Permisos nuevos `MANTENIMIENTO.UNIDADES.*` y `MANTENIMIENTO.LISTAS_PRECIO.*` (Ver/Crear/Editar/Eliminar); el Almacenero recibe Productos (Ver/Crear/Editar), Unidades y Listas (Ver), sin `CAMBIAR_PRECIO`. En despliegues existentes, ejecutar `manage.py sync_permisos` y asignar los nuevos al rol Administrador.
- **Pendiente:** presentaciones (varias unidades con conversión), stock por almacén y movimientos, etiquetas de código de barras, importación masiva de productos, precios en dólares, IGV según el régimen (a definir con los dueños), y servir las fotos desde almacenamiento de objetos (S3 o similar) en producción.
