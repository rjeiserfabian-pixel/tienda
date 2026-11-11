---
name: python-secure
description: >-
  Estandares obligatorios de seguridad, rendimiento y estabilidad para escribir codigo Python en proyectos Django/DRF, aplicables a CUALQUIER sistema de gestion empresarial sin importar el rubro (ventas, creditos, boticas, concesionarios, notarias, talleres, inventarios, salud, logistica, etc.), para produccion de largo plazo, con concurrencia moderada (decenas a ~200 usuarios). Usa esta skill SIEMPRE que escribas, generes, edites o revises codigo Python de backend Django: modelos, vistas, endpoints DRF, queries ORM, tareas en background, manejo de errores, autenticacion/autorizacion, o cualquier archivo .py, sin importar el dominio de negocio, incluso si el usuario no lo pide explicitamente. Tambien aplica en code review de Pull Requests o al disenar nuevas funcionalidades. No es opcional; estas reglas se respetan en todo codigo Python generado, no solo cuando el usuario las menciona.
---

# Codigo Python seguro, performante y estable (Django)

Este skill encapsula las reglas que SIEMPRE se deben aplicar al escribir o revisar codigo Python de backend en proyectos Django, **sin importar el rubro o dominio de negocio del sistema** (puede ser ventas, creditos, salud, notarias, inventario, talleres, logistica, cualquier otro). Las reglas son de ingenieria de software, no de negocio, por lo que aplican igual en todos los casos. El objetivo es que el sistema aguante en produccion sin degradarse ni sufrir incidentes de seguridad, sin que el usuario tenga que recordarlo en cada conversacion ni repetir estas reglas para cada proyecto nuevo.

Aplica estas reglas de forma proactiva y por defecto. Si al generar codigo detectas que estas a punto de violar una regla (ej. un except vacio, una query sin limite, una llamada externa sin timeout), corrigelo antes de entregar el codigo, no lo dejes pendiente.

## Contexto de escala del sistema

Estos proyectos son sistemas de gestion empresarial internos/remotos con **entre 30 y ~200 usuarios concurrentes** (personal administrativo, operativo o de campo usando el sistema desde distintas ubicaciones), sin importar el rubro del negocio. Esto es importante para calibrar las recomendaciones:

- Django (WSGI, con Gunicorn/uWSGI + varios workers) es mas que suficiente para esta escala. **No se necesita** async/ASGI, microservicios, ni arquitecturas distribuidas complejas - eso seria sobre-ingenieria para este tamano.
- El foco de rendimiento NO es aguantar miles de conexiones simultaneas, sino: **queries eficientes segun crece el volumen de datos con los anos** (historiales, transacciones, registros que se acumulan con el tiempo en cualquier tipo de sistema), evitar cuellos de botella en reportes, y mantener tiempos de respuesta consistentes segun la base de datos crece.
- Si importan: buenos indices, paginacion, evitar N+1, tareas pesadas en background - todo lo de abajo - porque eso es lo que degrada cualquier sistema de este tipo en el ano 3-5, no la concurrencia.

## 1. Consultas a base de datos (rendimiento)

- **Nunca generes codigo con N+1 queries.** Usa siempre select_related() (relaciones 1-a-1 / FK) y prefetch_related() (relaciones muchos-a-muchos / reversas) cuando el codigo itera sobre relaciones.
- **Nunca uses SELECT * implicito innecesario.** Trae solo los campos que se usan (.only(), .values()) cuando el modelo es grande o el query es de alto volumen.
- **Toda funcion/endpoint/vista que devuelva una lista debe paginar por defecto.** Nunca generes una vista que devuelva .all() sin limite. Usa Paginator de Django o PageNumberPagination/LimitOffsetPagination de DRF, con un maximo razonable por defecto (ej. 25-50).
  - **Si un catalogo se expone a proposito SIN paginar** (porque el frontend necesita la lista completa de una sola vez, ej. un catalogo de permisos, modulos, tipos), hazlo **explicito** con `pagination_class = None` en la vista. Nunca dejes la paginacion por defecto de DRF activa "por accidente" mientras el frontend asume que recibe la lista completa — eso trunca resultados silenciosamente sin ningun error visible (bug real ya visto: un catalogo de ~90 registros se cortaba a 25 porque la vista heredaba `PAGE_SIZE=25` global y el frontend pedia la lista sin recorrer paginas).
  - **Agregar filtros a un endpoint no debe romper su paginacion, ni al reves.** Cuando agregues query params de filtro (estado, fecha, entidad relacionada, etc.) a una vista paginada, verifica que la paginacion se siga aplicando sobre el queryset ya filtrado, y que el frontend siga mandando `page`/`page_size` junto con los filtros.
- **Filtra en la base de datos, no en Python.** Nunca traigas todos los registros para despues filtrarlos con un for o list comprehension en memoria; usa .filter()/WHERE en la query.
- **Senala explicitamente cuando un campo necesita indice.** Si generas un modelo con un campo que se usara en filter(), order_by() o como FK con alto volumen de consultas (ej. fechas, estados, codigos, numeros de documento, cualquier campo de busqueda frecuente), agrega db_index=True (o Meta.indexes para indices compuestos) y mencionalo en tu respuesta.
- **Evita loops anidados sobre colecciones grandes (O(n2)).** Usa set/dict para busquedas en vez de .find()/in sobre listas dentro de loops.
- **Inserciones masivas usan bulk_create()/bulk_update()**, nunca un for con .create() individual (ej. generar decenas o cientos de registros relacionados de una sola vez, sin importar el tipo de dato).

## 2. Tareas pesadas y llamadas externas (estabilidad)

- **Toda llamada HTTP saliente (requests, SDKs externos) debe llevar timeout explicito.** Nunca generes requests.get(url) sin timeout=. Valor por defecto razonable si no se especifica: 5-10 segundos.
- **Cualquier operacion que tarde mas de ~1-2 segundos** (enviar email, generar PDF/reporte pesado, llamar una API externa no critica para la respuesta, procesar archivos grandes) **debe ir a una cola/worker** (Celery + Redis/RabbitMQ es el estandar en Django), nunca bloqueando el request HTTP.
- **Disena operaciones criticas para ser idempotentes** cuando puedan reintentarse (pagos, envio de notificaciones, procesamiento de webhooks). Usa claves de idempotencia o update_or_create/get_or_create en vez de create directo cuando aplique.

## 3. Manejo de errores (estabilidad)

- **Nunca generes un except: desnudo ni un except Exception: pass.** Siempre captura la excepcion especifica cuando sea posible, registrala con logger.error() incluyendo contexto, y decide explicitamente que hacer (reintentar, propagar como error controlado, degradar).
- **Nunca dejes que una excepcion no controlada exponga detalles internos al cliente** (stack traces, nombres de tablas, rutas del servidor). Usa siempre DEBUG=False en produccion; en DRF, usa exception_handler personalizado para devolver mensajes genericos al cliente y loguear el detalle internamente.
- **Operaciones multi-paso que deben ser consistentes entre si van dentro de una transaccion** (transaction.atomic()). Nunca dejes pasos relacionados (ej. registrar una operacion + actualizar el estado de un registro relacionado + generar registros derivados) sin transaccion, sin importar el dominio del sistema.

## 4. Seguridad

- **Nunca concatenes strings del usuario en queries SQL crudas.** Si por algun motivo se necesita SQL crudo, usa siempre parametros (cursor.execute(query, [params])), nunca f-strings o .format() dentro del SQL.
- **Verifica autorizacion a nivel de recurso, no solo autenticacion.** Cuando generes una vista/endpoint que accede a un objeto por ID, el query debe filtrar tambien por el usuario dueno o su permiso/rol, nunca solo Modelo.objects.get(id=id). Usa los permission_classes de DRF y valida ownership explicitamente en el queryset.
- **Nunca hardcodees secretos, API keys, contrasenas o tokens en el codigo.** Siempre usa variables de entorno (django-environ o similar) o un gestor de secretos.
- **Nunca loguees ni devuelvas en respuestas datos sensibles** (contrasenas, tokens, numeros de documento completos, datos personales innecesarios).
- **Usa siempre el hashing seguro de contrasenas del framework** (django.contrib.auth, que usa PBKDF2 por defecto; considera Argon2 con django-argon2 para mayor seguridad). Nunca implementes hashing manual ni MD5/SHA1.
- **Sanitiza/escapa toda salida hacia HTML.** Usa el auto-escapado de templates de Django; nunca construyas HTML concatenando strings de input del usuario. Marca mark_safe/| safe como senal de alerta que requiere justificacion explicita.
- **Rate limiting en endpoints sensibles** (login, recuperacion de contrasena) usando django-ratelimit o el throttling de DRF (AnonRateThrottle, UserRateThrottle), especialmente porque el sistema es de acceso remoto.
- **Configuracion de produccion obligatoria**: DEBUG=False, ALLOWED_HOSTS explicito, SECURE_SSL_REDIRECT=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, headers de seguridad (SECURE_HSTS_SECONDS, X_FRAME_OPTIONS). Menciona esto cuando generes o revises settings.py de produccion.

## 5. Logging y observabilidad

- **Todo log relevante debe ser estructurado y con contexto**, no un print() ni un string plano. Incluye al menos: accion realizada, identificador del recurso afectado, usuario que la ejecuto, y si aplica, un request_id.
- **Nunca uses print() para debugging en codigo que se entrega como final.** Usa el modulo logging configurado.

## 6. Validacion de datos

- **Todo input externo (body de request, query params, formularios) se valida en el borde.** Usa Forms/ModelForms o Serializers de DRF - nunca confies en el tipo o forma del dato sin validarlo primero.
- **Nunca asumas que un campo opcional/anidado existe.** Usa .get() con default o valida explicitamente antes de acceder, en vez de indexado directo que puede lanzar KeyError/AttributeError.

## 7. Cache (guia opcional - NO aplicar por defecto)

A diferencia de las reglas anteriores, el cache **no se aplica automaticamente desde el diseno inicial**. A la escala de estos sistemas (30-200 usuarios), un buen manejo de indices y N+1 (secciones 1 y 2) normalmente es suficiente y el cache no hace falta. Agregar cache sin necesidad real introduce complejidad innecesaria.

**Solo considera/sugiere cache cuando:**
- El usuario reporta o se detecta que una vista, dashboard o reporte especifico es lento.
- Hay datos que casi no cambian pero se consultan en cada request (catalogos, configuracion, roles/permisos, listas de opciones fijas).
- Hay un reporte o dashboard pesado que varios usuarios ven repetidamente en un corto periodo de tiempo sin que los datos cambien.

**Cuando lo sugieras, recomienda:**
- **Redis** como backend (django-redis + django.core.cache), ya que tambien sirve como broker de Celery para tareas en background - una sola pieza de infraestructura, dos usos.
- Tiempos de expiracion (timeout) cortos y explicitos por defecto (ej. minutos, no horas).
- Invalidacion explicita del cache cuando el dato relacionado cambia.
- Cachear sesiones de usuario en Redis en vez de base de datos, como mejora de bajo riesgo si ya se esta usando Redis.

No menciones ni sugieras cache de forma proactiva si no hay una senal concreta de que se necesita.

## 8. Arquitectura y Estructura de Carpetas

- **Modularidad por Dominio (Apps):** En Django, todo el codigo debe estar separado en "apps" independientes por modulo de negocio (ej. `seguridad`, `clientes`, `ordenes`), no agrupado por tipo tecnico.
- **Rutas API limpias:** Las rutas deben estructurarse usando el prefijo `/api/` y el nombre del modulo (ej. `/api/seguridad/...`, `/api/clientes/...`). El archivo `urls.py` principal solo debe incluir los `urls.py` de cada app.

## 9. Operaciones destructivas: preferir anular sobre eliminar

- **Cuando un registro de negocio ya generó efectos secundarios** (movimientos de stock, kardex, cuentas por cobrar/pagar, comprobantes), un `DELETE` fisico (hard delete) **nunca es la operacion correcta** — borra el registro pero deja esos efectos secundarios huerfanos o inconsistentes, y destruye el rastro de auditoria.
- **Modela en su lugar un estado explicito de anulacion** (`Anulado`/`Cancelado`) en el propio modelo, con una accion dedicada (`@action` de DRF, ej. `POST /recurso/{id}/anular/`) que:
  1. Rechace la anulacion si ya se aplicaron pagos, si el stock relacionado ya se consumio/vendio, o si depende de otro proceso que ya avanzo (ej. un documento ya facturado).
  2. Revierta explicitamente los efectos secundarios que sí se puedan revertir (liberar reservas de stock, registrar el movimiento de reversa en el kardex con su propio motivo).
  3. Deje registro en un historial/auditoria (quien anulo, cuando, por que motivo — el motivo debe ser un campo obligatorio en el request).
  4. Nunca borre las lineas/detalles relacionados; el registro y su historial deben sobrevivir para una auditoria futura.
- Ejemplo real ya implementado en este tipo de proyectos: la accion `anular` de un modulo de Compras (revierte stock y kardex, bloquea si ya hay pagos) y la de un modulo de Ordenes de Trabajo (libera reservas de stock, bloquea si hay repuestos ya instalados o un ticket de venta ya generado). Usa ese mismo patron como plantilla cuando el usuario pida "eliminar" o "borrar" un documento de negocio con efectos secundarios — proponle anular en vez de un DELETE simple si detectas que el modelo tiene ese tipo de efectos.

## 10. Al generar codigo, siempre menciona (breve, sin ser pesado)

Cuando el codigo generado tenga una decision relevante de las reglas anteriores, agrega una nota de una linea, por ejemplo:
- Agregue select_related('cliente') para evitar N+1 en este loop.
- Esta vista pagina por defecto (25 registros); ajusta el limite si lo necesitas.
- Agregue permission_classes para que el usuario solo vea sus propios registros.

No hace falta un parrafo largo - una linea de contexto es suficiente.

## Que NO hacer nunca (resumen rapido)

- NO: except: vacio o generico sin log
- NO: Queries dentro de loops (N+1)
- NO: Listas/vistas sin paginar
- NO: Paginacion por defecto activa sin decision explicita en catalogos que el frontend consume completos
- NO: Llamadas HTTP externas sin timeout
- NO: SQL con f-strings/concatenacion
- NO: Buscar por ID sin validar que el recurso pertenece al usuario/rol correcto
- NO: Secretos hardcodeados
- NO: Operaciones multi-paso criticas sin transaccion
- NO: Tareas lentas bloqueando el request HTTP
- NO: print() en vez de logging
- NO: DEBUG=True o ALLOWED_HOSTS abierto en produccion
- NO: DELETE fisico en documentos de negocio con efectos secundarios (usar anulacion con reversion)
