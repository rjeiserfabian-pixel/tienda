// Catálogo del Centro de reportes: solo ENLAZA a los reportes que ya viven en cada módulo.
// Cada reporte conserva su propio permiso; aquí el permiso solo decide si se muestra la tarjeta
// (la autorización real es del servidor).
export const AREAS = [
  { clave: 'ventas', nombre: 'Ventas', icono: 'cart' },
  { clave: 'compras', nombre: 'Compras', icono: 'truck' },
  { clave: 'almacen', nombre: 'Almacén', icono: 'boxes' },
  { clave: 'caja', nombre: 'Caja y bancos', icono: 'wallet' },
  { clave: 'gastos', nombre: 'Gastos', icono: 'coins' },
  { clave: 'rrhh', nombre: 'RR.HH.', icono: 'users' },
  { clave: 'servicio-tecnico', nombre: 'Servicio técnico', icono: 'wrench' },
]

export const REPORTES = [
  { area: 'ventas', nombre: 'Reportes de ventas', ruta: '/ventas/reportes', permiso: 'VENTAS.VER', detalle: 'Lo vendido, neto de anulados y notas de crédito, por periodo, producto y vendedor.' },
  { area: 'ventas', nombre: 'Ventas por cobrar', ruta: '/ventas/por-cobrar', permiso: 'VENTAS.VER', detalle: 'Lo que los clientes todavía deben, con vencimientos.' },
  { area: 'ventas', nombre: 'Historial de ventas', ruta: '/ventas/historial', permiso: 'VENTAS.VER', detalle: 'Todos los comprobantes emitidos.' },
  { area: 'ventas', nombre: 'Notas de crédito', ruta: '/ventas/notas-credito', permiso: 'VENTAS.VER', detalle: 'Devoluciones y descuentos a clientes.' },
  { area: 'ventas', nombre: 'Guías de remisión', ruta: '/ventas/guias-remision', permiso: 'VENTAS.VER', detalle: 'Traslados y entregas emitidos.' },
  { area: 'compras', nombre: 'Registro de compras', ruta: '/compras/registro-compras', permiso: 'COMPRAS.EXPORTAR', detalle: 'Libro de compras para el contador, restando devoluciones.' },
  { area: 'compras', nombre: 'Cuentas por pagar', ruta: '/compras/por-pagar', permiso: 'COMPRAS.VER', detalle: 'Deudas con proveedores y sus vencimientos.' },
  { area: 'compras', nombre: 'Reporte de órdenes', ruta: '/compras/reporte-ordenes', permiso: 'COMPRAS.EXPORTAR', detalle: 'Pendientes de recibir, cumplimiento por proveedor y diferencias de precio.' },
  { area: 'compras', nombre: 'Reporte de devoluciones', ruta: '/compras/reporte-devoluciones', permiso: 'COMPRAS.EXPORTAR', detalle: 'Devoluciones a proveedores, resumen y detalle.' },
  { area: 'compras', nombre: 'Reposición sugerida', ruta: '/compras/ordenes/reposicion', permiso: 'ORDENES_COMPRA.CREAR', detalle: 'Qué pedir según el stock mínimo.' },
  { area: 'almacen', nombre: 'Reportes de almacén', ruta: '/almacen/reportes', permiso: 'INVENTARIO.EXPORTAR', detalle: 'Inventario valorizado, libros y movimientos (Excel).' },
  { area: 'almacen', nombre: 'Kardex', ruta: '/almacen/kardex', permiso: 'INVENTARIO.VER', detalle: 'Entradas, salidas y saldo valorizado por producto.' },
  { area: 'almacen', nombre: 'Stock', ruta: '/almacen/stock', permiso: 'INVENTARIO.VER', detalle: 'Existencias por almacén, bajo mínimo y agotados.' },
  { area: 'almacen', nombre: 'Toma de inventario', ruta: '/almacen/tomas', permiso: 'INVENTARIO.TOMAS.VER', detalle: 'Conteos físicos, diferencias e informe.' },
  { area: 'caja', nombre: 'Reportes de caja', ruta: '/caja/reportes', permiso: 'CAJA.REPORTES.VER', detalle: 'Flujo de caja, libro de caja y bancos, y PLE.' },
  { area: 'caja', nombre: 'Saldos', ruta: '/caja/saldos', permiso: 'CAJA.MOVIMIENTOS.VER', detalle: 'Dinero disponible por cuenta.' },
  { area: 'caja', nombre: 'Conciliación bancaria', ruta: '/caja/conciliacion', permiso: 'CAJA.MOVIMIENTOS.VER', detalle: 'Extracto del banco contra el sistema.' },
  { area: 'gastos', nombre: 'Reportes de gastos', ruta: '/gastos/reportes', permiso: 'GASTOS.VER', detalle: 'Gastos por categoría, centro de costo y periodo.' },
  { area: 'rrhh', nombre: 'Reportes de RR.HH.', ruta: '/rrhh/reportes', permiso: 'RRHH.REPORTES.VER', detalle: 'Planilla, PLAME, T-Registro y resumen anual.' },
  { area: 'servicio-tecnico', nombre: 'Reportes de servicio técnico', ruta: '/servicio-tecnico/reportes', permiso: 'SERVICIOS.REPORTES.VER', detalle: 'Órdenes, tiempos, técnicos y repuestos.' },
]
