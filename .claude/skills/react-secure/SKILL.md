---
name: react-secure
description: >-
  Estandares obligatorios de seguridad, rendimiento y UX para escribir codigo frontend en React, aplicables a CUALQUIER sistema de gestion empresarial (ventas, creditos, clinicas, talleres, etc.) disenado para comercializacion masiva. Usa esta skill SIEMPRE que escribas, generes, edites o revises codigo React (.js, .jsx, .ts, .tsx), componentes, hooks, peticiones a la API o manejo del estado global. Estas reglas garantizan interfaces rapidas, seguras y profesionales, y deben aplicarse de forma proactiva sin que el usuario lo pida.
---

# Codigo React Seguro, Performante y Profesional

Este skill encapsula las reglas obligatorias para el frontend (React) de sistemas de gestion empresarial. Al igual que en el backend, estas reglas buscan que el sistema sea escalable, rapido y seguro para comercializarse en multiples rubros, evitando que el navegador del cliente se congele, previniendo vulnerabilidades y garantizando una experiencia de usuario (UX) de primer nivel.

Aplica estas reglas por defecto. Nunca entregues codigo que viole estos principios.

## 1. Peticiones a la API y Rendimiento (Red)

- **Cache y minimizacion de peticiones:** Nunca uses un useEffect simple con fetch/axios para llamadas de datos que se consultan frecuentemente. Fomenta el uso de librerias de estado de servidor (como React Query o SWR) o implementa logica para no repetir peticiones si los datos ya estan en memoria.
- **Paginacion e Infinite Scroll — regla concreta, no solo "estar preparado":** Toda pagina de listado (`*Page.jsx` bajo `src/modules/*/pages/`) que pueda crecer sin limite con el tiempo (ordenes, ventas, compras, movimientos, clientes, etc.) DEBE incluir, desde que se crea:
  1. Un componente de paginacion real y visible (ej. `TablePagination` de MUI), conectado a `page`/`rowsPerPage` en el estado y enviado como parametros a la peticion del backend.
  2. Una barra de filtros basica (al menos por los campos mas obvios: estado, rango de fechas, entidad relacionada como proveedor/cliente/mecanico).
  - Replica el patron ya usado en `ComprasPage.jsx` y `OrdenesTrabajoPage.jsx` de este proyecto (filtros + `TablePagination` + `fetchX({ page, ...filtros })`) para cualquier listado nuevo. Nunca renderices miles de registros de golpe en una tabla o lista, y nunca asumas que "ya está preparado para paginar" sin el control de UI real — eso es lo que paso con el listado inicial de Ordenes de Trabajo de este proyecto: no tenia ni filtros ni `TablePagination`, solo pedia la pagina 1 sin forma de ver el resto.
- **Debounce en busquedas:** Toda barra de busqueda o filtro que consulte al backend mientras el usuario escribe DEBE tener un "debounce" (ej. 300-500ms). NUNCA dispares una peticion HTTP por cada tecla presionada.
- **AbortController:** Si un componente se desmonta antes de que termine una peticion (o si el usuario cambia de pagina rapido), la peticion HTTP en curso debe cancelarse usando AbortController para evitar fugas de memoria (memory leaks) y errores de actualizacion de estado en componentes desmontados.

## 2. Optimizacion de Renderizados (Rendimiento del Navegador)

- **Evita re-renders innecesarios:** Si un componente recibe props complejas o funciones desde su padre, y su renderizado es costoso (tablas complejas, graficos), envuelvelo en React.memo.
- **Memorizacion de calculos:** Usa useMemo para operaciones matematicas pesadas o filtrado de listas grandes en el frontend. No lo uses para calculos triviales.
- **Estabilidad de funciones:** Usa useCallback para funciones que se pasan como props a componentes hijos memorizados o que se usan dentro de arreglos de dependencias en useEffect.
- **Listas virtualizadas:** Si por alguna razon de negocio debes mostrar una lista de cientos de elementos (ej. un dropdown gigante), usa virtualizacion (ej. react-window o react-virtualized) en lugar de renderizar todos los nodos en el DOM.

## 3. Experiencia de Usuario (UX) y Manejo de Errores

- **Todo boton o accion visible DEBE tener su handler implementado.** Nunca dejes un `<Button>`/`<IconButton>` sin `onClick` "para despues" — si la accion todavia no esta lista, no muestres el boton (o muestralo deshabilitado con un tooltip explicando por que), en vez de dejarlo ahi sin funcionalidad. Esto ya paso dos veces en este proyecto: el boton "Ver" del listado de Compras y el boton "WhatsApp" del detalle de una Orden de Trabajo, ambos visibles y sin `onClick`, aparentando funcionar sin hacerlo. Antes de dar una pantalla por terminada, revisa que cada boton visible tenga su handler conectado.
- **Feedback visual constante (Loaders/Skeletons):** Nunca dejes la pantalla estatica mientras se espera una respuesta del backend. Muestra "skeletons" (esqueletos de carga) o spinners de forma condicional (isLoading).
- **Estados de error y "Empty States":** Si una peticion falla, muestra un mensaje de error amigable (tipo Toast o Snackbar), nunca un fallo silencioso. Si una lista no tiene datos, muestra un componente de "Empty State" (ej. "No hay registros para mostrar"), no una tabla vacia.
- **Botones deshabilitados al enviar:** Todo boton de formulario debe deshabilitarse (disabled={isSubmitting}) y mostrar un loader interno mientras se procesa el POST/PUT, para evitar envios duplicados si el usuario hace doble clic por desesperacion.
- **Error Boundaries:** Usa componentes Error Boundary para atrapar caidas de React (crashes) en subcomponentes, de modo que si un componente falla, no se ponga la pantalla en blanco (White Screen of Death), sino que muestre un mensaje de error controlado.

## 4. Seguridad en el Frontend

- **Prevencion de XSS:** Nunca uses dangerouslySetInnerHTML a menos que sea estrictamente necesario y el contenido haya sido sanitizado previamente con una libreria como DOMPurify. React escapa el texto por defecto, confia en eso.
- **Cero secretos en el codigo:** Nunca hardcodees API keys privadas, tokens de acceso o credenciales en el codigo fuente de React. Lo que este en el frontend es publico. Usa variables de entorno (REACT_APP_ o VITE_) solo para URLs o claves publicas inofensivas.
- **Validacion doble:** Aunque el backend valide, el frontend DEBE validar tambien los formularios antes de enviar (usando Yup, Zod, o validacion nativa). No hagas peticiones innecesarias al servidor si el dato ya es invalido localmente.

## 5. Estructura y Mantenibilidad

- **Separacion de Logica y UI:** Extrae la logica compleja, llamadas a API y manejo de estados a **Custom Hooks** (ej. useClientes(), useFacturacion()). El componente debe encargarse principalmente de renderizar la vista (UI).
- **Componentes pequenos y reutilizables:** Si un componente pasa de ~200 lineas, es muy probable que deba dividirse en subcomponentes mas pequenos.

## 6. Arquitectura de Carpetas y Modulos

- **Estructura basada en Features (Modulos):** El codigo frontend NO debe agruparse por tipo de archivo (todas las vistas juntas). Debe agruparse por modulo de negocio dentro de `/src/modules/` (ej. `/src/modules/seguridad/`, `/src/modules/clientes/`).
- **Separacion de componentes comunes:** Todos los componentes reutilizables (Botones, Modales genericos) deben ir en `/src/shared/components/`.
- **Rutas Limpias:** Usar React Router para mantener rutas claras organizadas por modulo (ej. `/seguridad/usuarios`, `/clientes`).

## 7. Al generar codigo, siempre menciona (breve)

Cuando apliques estas reglas, incluye una nota de una linea para confirmar la decision tecnica:
- "Agregue un debounce de 500ms al buscador para no saturar el backend."
- "El boton se deshabilita durante la peticion para evitar envios dobles."
- "Use un Custom Hook para mantener la logica separada de la vista."

## Que NO hacer nunca (resumen rapido)
- NO: Peticiones HTTP en bucles o sin dependencias correctas en useEffect.
- NO: Buscadores sin debounce (lanzando peticiones por cada tecla).
- NO: Botones de "Guardar" que no se deshabilitan al hacer clic.
- NO: Botones o acciones visibles sin `onClick`/handler implementado.
- NO: Renderizar listas largas sin paginacion, o sin `TablePagination` visible cuando los registros pueden crecer sin limite.
- NO: dangerouslySetInnerHTML sin sanitizacion.
- NO: Dejar al usuario sin feedback visual (loaders/toasts) durante una peticion.
- NO: Componentes gigantes que mezclan vista, peticiones y logica de negocio.
