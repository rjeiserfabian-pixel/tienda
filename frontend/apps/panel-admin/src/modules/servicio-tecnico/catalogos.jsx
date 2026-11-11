// Catálogos del taller. Usan las mismas pantallas de lista, alta y ficha que los demás maestros:
// aquí solo se describe qué campos y columnas lleva cada uno.
import { ESTADOS } from '../mantenimiento/maestros'

const CATEGORIAS_SERVICIO = [
  ['DIAGNOSTICO', 'Diagnóstico'],
  ['MANTENIMIENTO', 'Mantenimiento'],
  ['REPARACION', 'Reparación'],
  ['OTRO', 'Otro'],
]
const etiqueta = (lista, valor) => lista.find(([v]) => v === valor)?.[1] ?? valor
const ESTADO = { nombre: 'estado', etiqueta: 'Estado', icono: 'settings', tipo: 'select', opciones: ESTADOS, soloEdicion: true }
const requerido = (campo, mensaje) => (f) => (String(f[campo] ?? '').trim() ? {} : { [campo]: mensaje })

const BASE = { deOrganizacion: true, permiso: 'SERVICIOS.CATALOGOS', filtros: [] }

export const TIPOS_EQUIPO = {
  ...BASE,
  clave: 'servicio-tipos-equipo',
  ruta: '/servicio-tecnico/tipos-equipo',
  endpoint: '/servicio-tecnico/tipos-equipo/',
  icono: 'tags',
  titulo: 'Tipos de equipo',
  singular: 'tipo de equipo',
  descripcion: 'Qué clase de equipos recibe el taller: laptop, PC, impresora, celular… Agrega los que repares.',
  buscar: 'Buscar tipo de equipo…',
  tituloFila: (r) => r.nombre,
  subtituloFila: () => 'Tipo de equipo',
  inicial: { nombre: '', estado: 'ACTIVO' },
  columnas: [{ titulo: 'Tipo de equipo', celda: (r) => <strong>{r.nombre}</strong> }],
  campos: [{ nombre: 'nombre', etiqueta: 'Nombre', icono: 'tags', requerido: true, placeholder: 'Ej. Consola de videojuegos', completo: true, maxLength: 80 }, ESTADO],
  validar: requerido('nombre', 'Ingrese el nombre.'),
}

export const ACCESORIOS_EQUIPO = {
  ...BASE,
  clave: 'servicio-accesorios',
  ruta: '/servicio-tecnico/accesorios',
  endpoint: '/servicio-tecnico/accesorios/',
  icono: 'package',
  titulo: 'Accesorios',
  singular: 'accesorio',
  descripcion: 'Lo que el cliente suele dejar junto al equipo: cargador, mouse, maletín… Se marcan al registrar el ingreso.',
  buscar: 'Buscar accesorio…',
  tituloFila: (r) => r.nombre,
  subtituloFila: () => 'Accesorio de equipo',
  inicial: { nombre: '', estado: 'ACTIVO' },
  columnas: [{ titulo: 'Accesorio', celda: (r) => <strong>{r.nombre}</strong> }],
  campos: [{ nombre: 'nombre', etiqueta: 'Nombre', icono: 'package', requerido: true, placeholder: 'Ej. Base enfriadora', completo: true, maxLength: 80 }, ESTADO],
  validar: requerido('nombre', 'Ingrese el nombre.'),
}

export const REVISIONES_INGRESO = {
  ...BASE,
  femenino: true,
  clave: 'servicio-revisiones',
  ruta: '/servicio-tecnico/revisiones',
  endpoint: '/servicio-tecnico/revisiones/',
  icono: 'scan',
  titulo: 'Revisiones de ingreso',
  singular: 'revisión de ingreso',
  descripcion: 'Lo que se comprueba al recibir un equipo: ¿enciende?, ¿pantalla rota?, ¿puertos? Dejan constancia de cómo llegó.',
  buscar: 'Buscar revisión…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => r.tipo_equipo_nombre || 'Todos los equipos',
  inicial: { nombre: '', tipo_equipo: '', orden: '0', estado: 'ACTIVO' },
  columnas: [
    { titulo: 'Revisión', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'Se hace en', suave: true, celda: (r) => r.tipo_equipo_nombre || 'Todos los equipos' },
    { titulo: 'Orden', suave: true, celda: (r) => r.orden },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Qué se revisa', icono: 'scan', requerido: true, placeholder: 'Ej. Bisagras de la pantalla', completo: true, maxLength: 120 },
    {
      nombre: 'tipo_equipo',
      etiqueta: 'Tipo de equipo',
      icono: 'tags',
      tipo: 'remoto',
      vacio: 'Todos los equipos',
      etiquetaDe: 'tipo_equipo_nombre',
      ayuda: 'Déjalo en «Todos» si la revisión vale para cualquier equipo.',
      fuente: () => ({ url: '/servicio-tecnico/tipos-equipo/', params: { estado: 'ACTIVO', page_size: 100 } }),
      etiquetaOpcion: (t) => t.nombre,
    },
    { nombre: 'orden', etiqueta: 'Orden en la lista', icono: 'layers', tipo: 'number', placeholder: '0', ayuda: 'Los números menores salen primero.' },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese qué se revisa.'
    const orden = Number(f.orden)
    if (f.orden === '' || !Number.isInteger(orden) || orden < 0 || orden > 999) errores.orden = 'Use un número entre 0 y 999.'
    return errores
  },
}

export const TIPOS_SERVICIO = {
  ...BASE,
  clave: 'servicio-tipos-servicio',
  ruta: '/servicio-tecnico/tipos-servicio',
  endpoint: '/servicio-tecnico/tipos-servicio/',
  icono: 'wrench',
  titulo: 'Tipos de servicio',
  singular: 'tipo de servicio',
  descripcion: 'Qué se le hace al equipo. La categoría decide por qué estados pasa la orden; la garantía y el precio son una referencia.',
  buscar: 'Buscar tipo de servicio…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => r.categoria_nombre,
  inicial: { nombre: '', categoria: 'REPARACION', garantia_dias: '30', precio_referencial: '0', estado: 'ACTIVO' },
  filtros: [{ nombre: 'categoria', todos: 'Todas las categorías', opciones: CATEGORIAS_SERVICIO }],
  columnas: [
    { titulo: 'Servicio', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'Categoría', suave: true, celda: (r) => etiqueta(CATEGORIAS_SERVICIO, r.categoria) },
    { titulo: 'Garantía', suave: true, celda: (r) => (r.garantia_dias > 0 ? `${r.garantia_dias} días` : 'Sin garantía') },
    { titulo: 'Mano de obra ref.', suave: true, celda: (r) => (Number(r.precio_referencial) > 0 ? `S/ ${Number(r.precio_referencial).toFixed(2)}` : '—') },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre del servicio', icono: 'wrench', requerido: true, placeholder: 'Ej. Cambio de teclado', completo: true, maxLength: 100 },
    { nombre: 'categoria', etiqueta: 'Categoría', icono: 'layers', tipo: 'select', opciones: CATEGORIAS_SERVICIO, ayuda: 'Un mantenimiento no pasa por «En reparación», ni al revés.' },
    { nombre: 'garantia_dias', etiqueta: 'Garantía (días)', icono: 'shield', tipo: 'number', placeholder: '30', ayuda: 'Cero = sin garantía.' },
    { nombre: 'precio_referencial', etiqueta: 'Mano de obra referencial (S/)', icono: 'coins', tipo: 'number', placeholder: '0.00', completo: true, ayuda: 'Opcional. Es una guía para presupuestar; el precio final se define en cada orden.' },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre del servicio.'
    const garantia = Number(f.garantia_dias)
    if (f.garantia_dias === '' || !Number.isInteger(garantia) || garantia < 0 || garantia > 3650) errores.garantia_dias = 'Use un número entero de días (0 si no tiene).'
    const precio = Number(f.precio_referencial)
    if (f.precio_referencial === '' || !Number.isFinite(precio) || precio < 0) errores.precio_referencial = 'Use un monto desde 0.'
    return errores
  },
}

export const CATALOGOS_SERVICIO = [TIPOS_EQUIPO, ACCESORIOS_EQUIPO, REVISIONES_INGRESO, TIPOS_SERVICIO]
