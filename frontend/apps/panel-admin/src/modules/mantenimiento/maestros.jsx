// Definición de los maestros de Mantenimiento (clientes, proveedores, personal). Las pantallas de
// lista, alta y ficha son las mismas para los tres: aquí solo cambian los campos y las columnas.

export const TIPOS_DOCUMENTO = [
  ['DNI', 'DNI'],
  ['RUC', 'RUC'],
  ['CE', 'Carné de extranjería'],
  ['PASAPORTE', 'Pasaporte'],
  ['OTRO', 'Otro'],
]
export const ESTADOS = [
  ['ACTIVO', 'Activo'],
  ['INACTIVO', 'Inactivo'],
]
export const BANCOS = [
  ['BCP', 'BCP'],
  ['BBVA', 'BBVA'],
  ['INTERBANK', 'Interbank'],
  ['SCOTIABANK', 'Scotiabank'],
  ['BANCO_NACION', 'Banco de la Nación'],
  ['BANBIF', 'BanBif'],
  ['PICHINCHA', 'Banco Pichincha'],
  ['MIBANCO', 'Mibanco'],
  ['OTRO', 'Otro'],
]
export const TIPOS_ALMACEN = [
  ['PRINCIPAL', 'Principal'],
  ['EXHIBICION', 'Exhibición'],
  ['SERVICIO_TECNICO', 'Servicio técnico'],
  ['MERMAS', 'Mermas o averiados'],
  ['OTRO', 'Otro'],
]
export const ZONAS = [
  ['DENTRO', 'Dentro de la región (Amazonía)'],
  ['FUERA', 'Fuera de la región'],
]
export const USOS_LISTA = [
  ['PUBLICO', 'Precio público (venta normal)'],
  ['DESCUENTO', 'Precio con descuento'],
  ['TECNICO', 'Precio técnico'],
  ['CREDITO', 'Precio a crédito'],
  ['OTRA', 'Otra'],
]
export const TIPOS_MEDIO_PAGO = [
  ['EFECTIVO', 'Efectivo'],
  ['TARJETA', 'Tarjeta'],
  ['TRANSFERENCIA', 'Transferencia o depósito'],
  ['BILLETERA', 'Billetera digital (Yape, Plin…)'],
  ['CHEQUE', 'Cheque'],
  ['OTRO', 'Otro'],
]
export const TIPOS_CONCEPTO_CAJA = [
  ['INGRESO', 'Ingreso'],
  ['EGRESO', 'Egreso'],
]
export const UNIDADES_PERIODO = [
  ['DIAS', 'Días'],
  ['MESES', 'Meses'],
]
export const TIPOS_CUENTA = [
  ['CAJA', 'Caja de efectivo'],
  ['BANCO', 'Cuenta de banco'],
  ['BILLETERA', 'Billetera digital (Yape, Plin…)'],
]
export const MONEDAS_CUENTA = [
  ['PEN', 'Soles'],
  ['USD', 'Dólares'],
]
export const AREAS = [
  ['ADMINISTRACION', 'Administración'],
  ['VENTAS', 'Ventas'],
  ['TECNICO', 'Técnico'],
  ['ALMACEN', 'Almacén'],
  ['OTRO', 'Otro'],
]

const CORREO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const etiqueta = (lista, valor) => lista.find(([v]) => v === valor)?.[1] ?? valor

/** Largo y caracteres del número según el tipo de documento (el backend valida además el RUC). */
export const REGLA_DOCUMENTO = {
  DNI: { largo: 8, soloDigitos: true, ejemplo: 'Ej. 45871236' },
  RUC: { largo: 11, soloDigitos: true, ejemplo: 'Ej. 20123456789' },
  CE: { largo: 12, soloDigitos: false, ejemplo: 'Ej. 001234567' },
  PASAPORTE: { largo: 12, soloDigitos: false, ejemplo: 'Ej. AB123456' },
  OTRO: { largo: 20, soloDigitos: false, ejemplo: 'Ej. ABC123' },
}

export function limpiarDocumento(tipo, valor) {
  const { soloDigitos, largo } = REGLA_DOCUMENTO[tipo] ?? REGLA_DOCUMENTO.OTRO
  const limpio = soloDigitos ? valor.replace(/\D/g, '') : valor.toUpperCase().replace(/[^A-Z0-9]/g, '')
  return limpio.slice(0, largo)
}

function validarDocumento(tipo, numero) {
  if (!numero) return 'Ingrese el número de documento.'
  if (tipo === 'DNI' && !/^\d{8}$/.test(numero)) return 'El DNI debe tener 8 dígitos.'
  if (tipo === 'RUC' && !/^\d{11}$/.test(numero)) return 'El RUC debe tener 11 dígitos.'
  if (tipo === 'CE' && !/^[A-Z0-9]{9,12}$/.test(numero)) return 'Use entre 9 y 12 letras o números.'
  if (tipo === 'PASAPORTE' && !/^[A-Z0-9]{6,12}$/.test(numero)) return 'Use entre 6 y 12 letras o números.'
  if (tipo === 'OTRO' && !/^[A-Z0-9]{3,20}$/.test(numero)) return 'Use entre 3 y 20 letras o números.'
  return ''
}

function validarBase(f, requeridos) {
  const errores = {}
  const doc = validarDocumento(f.tipo_documento, f.numero_documento)
  if (doc) errores.numero_documento = doc
  for (const [campo, mensaje] of requeridos) if (!String(f[campo] ?? '').trim()) errores[campo] = mensaje
  if (f.correo && !CORREO.test(f.correo)) errores.correo = 'Ingrese un correo válido.'
  if (String(f.cuenta_bancaria ?? '').trim() && !f.banco) errores.banco = 'Elija el banco de la cuenta.'
  return errores
}

const DOCUMENTO = [
  { nombre: 'tipo_documento', etiqueta: 'Tipo de documento', icono: 'documento', tipo: 'select', opciones: TIPOS_DOCUMENTO },
  { nombre: 'numero_documento', etiqueta: 'Número de documento', icono: 'documento', requerido: true, documento: true },
]
const CONTACTO = [
  { nombre: 'telefono', etiqueta: 'Teléfono', icono: 'telefono', placeholder: 'Ej. 987 654 321', maxLength: 20 },
  { nombre: 'correo', etiqueta: 'Correo', icono: 'correo', placeholder: 'contacto@empresa.com', tipo: 'email', maxLength: 254 },
  { nombre: 'direccion', etiqueta: 'Dirección', icono: 'building', placeholder: 'Ej. Av. Principal 123, Lima', completo: true, maxLength: 250 },
]
/** Dónde está el cliente o proveedor: de ahí sale el IGV que se propone en la venta o la compra. */
const zona = (ayuda) => ({ nombre: 'zona', etiqueta: 'Zona (para el IGV)', icono: 'ubicacion', tipo: 'select', opciones: ZONAS, vacio: 'Sin definir', completo: true, ayuda })
const celdaZona = (r) => (r.zona ? etiqueta(ZONAS, r.zona).replace(/ \(Amazonía\)$/, '') : '—')
/** El distrito (ubigeo del INEI) de la dirección: opcional; la guía de remisión lo propone. */
const ubigeo = (ayuda) => ({ nombre: 'ubigeo', etiqueta: 'Distrito (ubigeo)', icono: 'ubicacion', tipo: 'ubigeo', completo: true, ayuda })
const ESTADO = { nombre: 'estado', etiqueta: 'Estado', icono: 'settings', tipo: 'select', opciones: ESTADOS, soloEdicion: true }

const celdaDocumento = (r) => (
  <>
    <strong>{r.numero_documento}</strong>
    <br />
    <small className="celda-suave">{etiqueta(TIPOS_DOCUMENTO, r.tipo_documento)}</small>
  </>
)
const celdaNombre = (r) => (
  <>
    {r.nombre}
    {r.nombre_comercial && (
      <>
        <br />
        <small className="celda-suave">{r.nombre_comercial}</small>
      </>
    )}
  </>
)

export const CLIENTES = {
  importar: true, // lista con importación masiva desde Excel o CSV
  clave: 'clientes',
  ruta: '/ventas/clientes',
  endpoint: '/mantenimiento/clientes/',
  permiso: 'MANTENIMIENTO.CLIENTES',
  deOrganizacion: true,
  icono: 'user',
  titulo: 'Clientes',
  singular: 'cliente',
  descripcion: 'Clientes de la organización: los comparten todas tus empresas.',
  buscar: 'Buscar cliente…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `${etiqueta(TIPOS_DOCUMENTO, r.tipo_documento)} ${r.numero_documento}`,
  inicial: { tipo_documento: 'DNI', numero_documento: '', nombre: '', nombre_comercial: '', zona: '', limite_credito: '0', credito_sin_limite: 'true', telefono: '', correo: '', direccion: '', ubigeo: '', asesor: '', estado: 'ACTIVO' },
  filtros: [{ nombre: 'tipo_documento', todos: 'Todos los documentos', opciones: TIPOS_DOCUMENTO }],
  // Qué campos completa la consulta a RENIEC (DNI) y SUNAT (RUC) según el tipo de documento.
  consulta: {
    DNI: (d) => ({ nombre: [d.nombres, d.apellidos].filter(Boolean).join(' ') }),
    RUC: (d) => ({ nombre: d.razon_social, direccion: d.direccion }),
  },
  columnas: [
    { titulo: 'Documento', celda: celdaDocumento },
    { titulo: 'Nombre o razón social', celda: celdaNombre },
    { titulo: 'Zona', celda: celdaZona, suave: true },
    { titulo: 'Teléfono', celda: (r) => r.telefono || '—', suave: true },
    { titulo: 'Correo', celda: (r) => r.correo || '—', suave: true },
    { titulo: 'Asesor', celda: (r) => r.asesor_nombre || '—', suave: true },
  ],
  campos: [
    ...DOCUMENTO,
    { nombre: 'nombre', etiqueta: 'Nombre o razón social', icono: 'user', requerido: true, placeholder: 'Ej. Ana Ruiz Pérez o Comercial Sol S.A.C.', completo: true, maxLength: 250 },
    { nombre: 'nombre_comercial', etiqueta: 'Nombre comercial', icono: 'store', placeholder: 'Ej. Bodega Sol', completo: true, maxLength: 250 },
    zona('Dentro de la región (Tarapoto): la venta sale exonerada. Fuera de la región: con IGV. Puedes cambiarlo en cada venta.'),
    { nombre: 'credito_sin_limite', etiqueta: 'Crédito sin tope', icono: 'coins', tipo: 'booleano', completo: true, soloConPermiso: 'VENTAS.LIMITE_CREDITO', ayuda: 'Elige «Sí» para venderle a crédito sin importar cuánto deba. Elige «No» para ponerle un tope de deuda.' },
    { nombre: 'limite_credito', etiqueta: 'Tope de deuda a crédito (S/)', icono: 'coins', completo: true, soloConPermiso: 'VENTAS.LIMITE_CREDITO', visibleSi: (v) => String(v.credito_sin_limite) === 'false', placeholder: '0.00', ayuda: 'Hasta cuánto puede deber este cliente. En 0 no tiene crédito autorizado.' },
    ...CONTACTO,
    ubigeo('Opcional: la guía de remisión lo propone como destino cuando se le envía mercadería.'),
    {
      nombre: 'asesor',
      etiqueta: 'Asesor',
      icono: 'user',
      tipo: 'usuario',
      completo: true,
      permiso: 'MANTENIMIENTO.CLIENTES.ASIGNAR_ASESOR',
      etiquetaDe: 'asesor_nombre',
      vacio: 'Yo (mi usuario)',
      vacioEdicion: 'Sin asesor',
      ayuda: 'Quien atiende a este cliente. Si no eliges a nadie, será quien lo registra.',
    },
    ESTADO,
  ],
  validar: (f) => validarBase(f, [['nombre', 'Ingrese el nombre o la razón social.']]),
}

export const PROVEEDORES = {
  ...CLIENTES,
  clave: 'proveedores',
  ruta: '/compras/proveedores',
  endpoint: '/mantenimiento/proveedores/',
  permiso: 'MANTENIMIENTO.PROVEEDORES',
  icono: 'handshake',
  titulo: 'Proveedores',
  singular: 'proveedor',
  descripcion: 'Proveedores de la organización: los comparten todas tus empresas.',
  buscar: 'Buscar proveedor…',
  inicial: { ...CLIENTES.inicial, tipo_documento: 'RUC', ciudad: '', contacto: '', banco: '', cuenta_bancaria: '', productos_referencia: '' },
  columnas: [
    { titulo: 'Documento', celda: celdaDocumento },
    { titulo: 'Razón social', celda: celdaNombre },
    { titulo: 'Ciudad', celda: (r) => r.ciudad || '—', suave: true },
    { titulo: 'Zona', celda: celdaZona, suave: true },
    { titulo: 'Contacto', celda: (r) => r.contacto || '—', suave: true },
    { titulo: 'Teléfono', celda: (r) => r.telefono || '—', suave: true },
  ],
  campos: [
    ...DOCUMENTO,
    { nombre: 'nombre', etiqueta: 'Razón social', icono: 'building', requerido: true, placeholder: 'Ej. Distribuidora Andina S.A.C.', completo: true, maxLength: 250 },
    { nombre: 'nombre_comercial', etiqueta: 'Nombre comercial', icono: 'store', placeholder: 'Ej. Andina', completo: true, maxLength: 250 },
    zona('Dentro de la región (Tarapoto): la compra es exonerada. Fuera de la región (por ejemplo, Lima): viene con IGV. Puedes cambiarlo en cada compra.'),
    { nombre: 'ciudad', etiqueta: 'Ciudad', icono: 'ubicacion', placeholder: 'Ej. Lima, Arequipa, Tarapoto', maxLength: 80 },
    { nombre: 'contacto', etiqueta: 'Persona de contacto', icono: 'user', placeholder: 'Ej. Marta Silva', maxLength: 150 },
    ...CONTACTO,
    ubigeo('Opcional: la guía de remisión lo propone como origen cuando se le devuelve mercadería.'),
    { nombre: 'banco', etiqueta: 'Banco', icono: 'building', tipo: 'select', opciones: BANCOS, vacio: 'Elija el banco' },
    { nombre: 'cuenta_bancaria', etiqueta: 'Número de cuenta bancaria', icono: 'wallet', placeholder: 'Ej. 193-12345678-0-12', ayuda: 'Para pagarle. El banco y la cuenta solo los ven quienes pueden editar proveedores.', maxLength: 30 },
    { nombre: 'productos_referencia', etiqueta: 'Productos de referencia', tipo: 'textarea', completo: true, placeholder: 'Ej. Baterías, aceites y filtros para motos', ayuda: 'Qué productos vende. Sirve para encontrarlo al buscar.', maxLength: 1000 },
    ESTADO,
  ],
  validar: (f) => validarBase(f, [['nombre', 'Ingrese la razón social.']]),
}

const sinTildes = (texto) => String(texto ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '')

export const PERSONAL = {
  // Datos del trabajador que se copian al formulario «Nuevo usuario» (el usuario sugerido es inicial + apellido).
  datosUsuario: (r) => ({
    username: `${sinTildes(String(r.nombres).split(' ')[0]).slice(0, 1)}${sinTildes(String(r.apellidos).split(' ')[0])}`.slice(0, 30),
    email: r.correo ?? '',
    nombres: r.nombres ?? '',
    apellidos: r.apellidos ?? '',
    documento_numero: r.tipo_documento === 'DNI' ? r.numero_documento : '',
    telefono: r.telefono ?? '',
    cargo: r.cargo ?? '',
    empresa_ids: [r.empresa],
  }),
  clave: 'personal',
  ruta: '/mantenimiento/personal',
  endpoint: '/mantenimiento/personal/',
  permiso: 'MANTENIMIENTO.PERSONAL',
  deOrganizacion: false,
  porEmpresa: true,
  icono: 'users',
  titulo: 'Personal',
  singular: 'trabajador',
  descripcion: 'Trabajadores de la empresa seleccionada. Pueden tener o no un usuario del sistema.',
  buscar: 'Buscar personal…',
  tituloFila: (r) => r.nombre_completo,
  subtituloFila: (r) => `${etiqueta(TIPOS_DOCUMENTO, r.tipo_documento)} ${r.numero_documento}`,
  inicial: { tipo_documento: 'DNI', numero_documento: '', nombres: '', apellidos: '', area: 'ADMINISTRACION', cargo: '', fecha_nacimiento: '', fecha_ingreso: '', usuario: '', telefono: '', correo: '', direccion: '', estado: 'ACTIVO' },
  filtros: [{ nombre: 'area', todos: 'Todas las áreas', opciones: AREAS }],
  consulta: { DNI: (d) => ({ nombres: d.nombres, apellidos: d.apellidos }) },
  columnas: [
    {
      titulo: 'Trabajador',
      celda: (r) => (
        <>
          {r.nombre_completo}
          <br />
          <small className="celda-suave">
            {etiqueta(TIPOS_DOCUMENTO, r.tipo_documento)} {r.numero_documento}
          </small>
        </>
      ),
    },
    { titulo: 'Área', celda: (r) => <span className="pildora" data-tono="azul">{etiqueta(AREAS, r.area)}</span> },
    { titulo: 'Cargo', celda: (r) => r.cargo || '—', suave: true },
    { titulo: 'Teléfono', celda: (r) => r.telefono || '—', suave: true },
    { titulo: 'Empresa', celda: (r, ctx) => ctx.nombreEmpresa(r.empresa) },
    {
      titulo: 'Usuario',
      celda: (r) =>
        r.usuario_username ? <span className="pildora" data-tono="verde">{r.usuario_username}</span> : <span className="celda-suave">Sin usuario</span>,
    },
  ],
  campos: [
    { nombre: 'empresa', etiqueta: 'Empresa', icono: 'building', tipo: 'select', soloAlta: true, completo: true, empresas: true, requerido: true },
    ...DOCUMENTO,
    { nombre: 'nombres', etiqueta: 'Nombres', icono: 'user', requerido: true, placeholder: 'Ej. Luis Alberto', maxLength: 150 },
    { nombre: 'apellidos', etiqueta: 'Apellidos', icono: 'user', requerido: true, placeholder: 'Ej. Ramos Soto', maxLength: 150 },
    { nombre: 'area', etiqueta: 'Área', icono: 'users', tipo: 'select', opciones: AREAS },
    { nombre: 'cargo', etiqueta: 'Cargo', icono: 'tags', placeholder: 'Ej. Técnico mecánico', maxLength: 100 },
    { nombre: 'fecha_nacimiento', etiqueta: 'Fecha de nacimiento', icono: 'calendario', tipo: 'date', max: 'hoy' },
    { nombre: 'fecha_ingreso', etiqueta: 'Fecha de ingreso', icono: 'calendario', tipo: 'date' },
    { nombre: 'usuario', etiqueta: 'Usuario del sistema', icono: 'key', tipo: 'usuario', completo: true, etiquetaDe: 'usuario_username', ayuda: 'Opcional: vincula al trabajador con su usuario para entrar al sistema.' },
    ...CONTACTO,
    ESTADO,
  ],
  validar: (f) =>
    validarBase(f, [
      ['nombres', 'Ingrese los nombres.'],
      ['apellidos', 'Ingrese los apellidos.'],
    ]),
}

/** Datos a enviar: sin vacíos opcionales, la empresa como número y la fecha vacía como ausente. */
export function datosParaEnviar(config, valores, { alta, registro }) {
  const enviar = {}
  for (const c of config.campos) {
    if (alta ? c.soloEdicion : c.soloAlta) continue
    if (c.visibleSi && !c.visibleSi(valores, registro)) continue // un campo oculto no se envía
    const valor = valores[c.nombre]
    if (valor === '' || valor === undefined) {
      if (!alta && !c.soloConPermiso) enviar[c.nombre] = ['date', 'usuario', 'remoto'].includes(c.tipo) || c.nulable ? null : '' // en edición, vaciar es un cambio
      continue
    }
    if (c.empresas || c.tipo === 'remoto') enviar[c.nombre] = Number(valor)
    else if (c.tipo === 'booleano') enviar[c.nombre] = valor === true || valor === 'true'
    else enviar[c.nombre] = valor
  }
  return enviar
}

const EMPRESA = { nombre: 'empresa', etiqueta: 'Empresa', icono: 'building', tipo: 'select', soloAlta: true, completo: true, empresas: true, requerido: true }

/** Opciones que se piden al servidor según otro campo (la empresa elegida). */
const deLaEmpresa = (url, extra = {}) => (valores, registro) => {
  const empresa = valores.empresa || registro?.empresa
  return empresa ? { url, params: { empresa, estado: 'ACTIVO', page_size: 100, ...extra } } : null
}

export const ALMACENES = {
  clave: 'almacenes',
  ruta: '/mantenimiento/almacenes',
  endpoint: '/mantenimiento/almacenes/',
  permiso: 'MANTENIMIENTO.ALMACENES',
  deOrganizacion: false,
  porEmpresa: true,
  icono: 'boxes',
  titulo: 'Almacenes',
  singular: 'almacén',
  descripcion: 'Lugares donde la empresa seleccionada guarda su mercadería. El stock se cuenta por almacén.',
  buscar: 'Buscar almacén…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `${r.codigo} · ${etiqueta(TIPOS_ALMACEN, r.tipo)}`,
  inicial: { codigo: '', nombre: '', sucursal: '', tipo: 'PRINCIPAL', permite_venta: 'true', direccion: '', ubigeo: '', responsable: '', estado: 'ACTIVO' },
  filtros: [{ nombre: 'tipo', todos: 'Todos los tipos', opciones: TIPOS_ALMACEN }],
  columnas: [
    { titulo: 'Código', celda: (r) => <strong>{r.codigo}</strong> },
    {
      titulo: 'Almacén',
      celda: (r) => (
        <>
          {r.nombre}
          <br />
          <small className="celda-suave">Sucursal {r.sucursal_nombre}</small>
        </>
      ),
    },
    { titulo: 'Tipo', celda: (r) => <span className="pildora" data-tono="azul">{etiqueta(TIPOS_ALMACEN, r.tipo)}</span> },
    { titulo: 'Responsable', celda: (r) => r.responsable_nombre || '—', suave: true },
    { titulo: 'Se vende', celda: (r) => (r.permite_venta ? 'Sí' : 'No'), suave: true },
    { titulo: 'Empresa', celda: (r, ctx) => ctx.nombreEmpresa(r.empresa) },
  ],
  campos: [
    EMPRESA,
    { nombre: 'codigo', etiqueta: 'Código', icono: 'tags', requerido: true, placeholder: 'Ej. ALM-01', ayuda: 'Se guarda en mayúsculas y sin espacios.', maxLength: 20 },
    { nombre: 'nombre', etiqueta: 'Nombre del almacén', icono: 'boxes', requerido: true, placeholder: 'Ej. Almacén principal', maxLength: 100 },
    {
      nombre: 'sucursal',
      etiqueta: 'Sucursal',
      icono: 'store',
      tipo: 'remoto',
      requerido: true,
      vacio: 'Elija la sucursal',
      vacioSinFuente: 'Primero elija la empresa',
      etiquetaDe: 'sucursal_nombre',
      fuente: deLaEmpresa('/organizacion/sucursales/'),
      etiquetaOpcion: (s) => `${s.codigo} · ${s.nombre}`,
    },
    { nombre: 'tipo', etiqueta: 'Tipo de almacén', icono: 'settings', tipo: 'select', opciones: TIPOS_ALMACEN },
    { nombre: 'permite_venta', etiqueta: 'Se vende desde aquí', icono: 'cart', tipo: 'booleano', ayuda: 'Elige «No» para mermas, averiados o depósitos sin atención al cliente.' },
    {
      nombre: 'responsable',
      etiqueta: 'Responsable',
      icono: 'user',
      tipo: 'remoto',
      vacio: 'Sin responsable',
      etiquetaDe: 'responsable_nombre',
      fuente: deLaEmpresa('/mantenimiento/personal/'),
      etiquetaOpcion: (p) => p.nombre_completo,
    },
    { nombre: 'direccion', etiqueta: 'Dirección', icono: 'building', placeholder: 'Ej. Jr. Jorge Chávez N° 12', completo: true, maxLength: 250 },
    ubigeo('Opcional: la guía de remisión lo propone como ubigeo del punto de partida.'),
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.codigo ?? '').trim()) errores.codigo = 'Ingrese el código.'
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre del almacén.'
    if (!f.sucursal) errores.sucursal = 'Elija la sucursal.'
    return errores
  },
}

export const UBICACIONES = {
  femenino: true, // «Nueva ubicación», «registrada», «eliminada»
  clave: 'ubicaciones',
  ruta: '/mantenimiento/ubicaciones',
  endpoint: '/mantenimiento/ubicaciones/',
  permiso: 'MANTENIMIENTO.UBICACIONES',
  deOrganizacion: false,
  porEmpresa: true,
  icono: 'ubicacion',
  titulo: 'Ubicaciones',
  singular: 'ubicación',
  descripcion: 'Vitrinas, estantes y cajas de cada almacén, para encontrar rápido un producto. Luego se asignan desde la ficha del producto.',
  buscar: 'Buscar ubicación…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `${r.codigo} · ${r.almacen_nombre}`,
  inicial: { codigo: '', nombre: '', almacen: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [
    { titulo: 'Código', celda: (r) => <strong>{r.codigo}</strong> },
    { titulo: 'Ubicación', celda: (r) => r.nombre },
    { titulo: 'Almacén', celda: (r) => <span className="pildora" data-tono="azul">{r.almacen_nombre}</span> },
    { titulo: 'Productos', celda: (r) => (r.n_productos > 0 ? r.n_productos : '—'), suave: true },
    { titulo: 'Empresa', celda: (r, ctx) => ctx.nombreEmpresa(r.empresa) },
  ],
  campos: [
    EMPRESA,
    {
      nombre: 'almacen',
      etiqueta: 'Almacén',
      icono: 'boxes',
      tipo: 'remoto',
      soloAlta: true, // una ubicación no se pasa a otro almacén
      requerido: true,
      vacio: 'Elija el almacén',
      vacioSinFuente: 'Primero elija la empresa',
      vacioSinOpciones: 'La empresa aún no tiene almacenes: crea primero uno',
      etiquetaDe: 'almacen_nombre',
      fuente: deLaEmpresa('/mantenimiento/almacenes/'),
      etiquetaOpcion: (a) => `${a.codigo} · ${a.nombre}`,
    },
    { nombre: 'codigo', etiqueta: 'Código', icono: 'tags', requerido: true, placeholder: 'Ej. V1 o A-03', ayuda: 'Corto, para leerlo de un vistazo. Se guarda en mayúsculas y sin espacios.', maxLength: 20 },
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'ubicacion', requerido: true, placeholder: 'Ej. Vitrina 1 (mouse y teclados)', maxLength: 100 },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    // La empresa y el almacén solo se eligen al crear: el servidor avisa si faltan.
    if (!String(f.codigo ?? '').trim()) errores.codigo = 'Ingrese el código.'
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre.'
    return errores
  },
}

const siNo = (valor) => (valor ? 'Sí' : 'No')

export const TIPOS_COMPROBANTE = {
  clave: 'tipos-comprobante',
  ruta: '/mantenimiento/comprobantes',
  endpoint: '/mantenimiento/tipos-comprobante/',
  permiso: 'MANTENIMIENTO.COMPROBANTES',
  deOrganizacion: true,
  icono: 'file',
  titulo: 'Tipos de comprobante',
  singular: 'tipo de comprobante',
  descripcion: 'Factura, boleta, notas y demás documentos (Tabla 10 de SUNAT). Aquí defines cuáles usa tu organización y cómo se escribe su serie.',
  buscar: 'Buscar tipo de comprobante…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `Código SUNAT ${r.codigo} · ${r.abreviatura}`,
  inicial: { codigo: '', nombre: '', abreviatura: '', es_electronico: 'false', aplica_compras: 'true', aplica_ventas: 'false', lleva_igv: 'true', ejemplo_serie: '', patron_serie: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [
    { titulo: 'Código', celda: (r) => <strong>{r.codigo}</strong> },
    { titulo: 'Comprobante', celda: (r) => <>{r.nombre}<br /><small className="celda-suave">{r.abreviatura}</small></> },
    { titulo: 'Electrónico', celda: (r) => siNo(r.es_electronico), suave: true },
    { titulo: 'Compras', celda: (r) => siNo(r.aplica_compras), suave: true },
    { titulo: 'Ventas', celda: (r) => siNo(r.aplica_ventas), suave: true },
    { titulo: 'Ejemplo de serie', celda: (r) => (r.ejemplo_serie ? `Ej. ${r.ejemplo_serie}` : r.patron_serie ? 'Con formato' : 'Libre'), suave: true },
  ],
  campos: [
    { nombre: 'codigo', etiqueta: 'Código SUNAT', icono: 'tags', soloAlta: true, requerido: true, placeholder: 'Ej. 01', ayuda: 'Son 2 números de la Tabla 10 de SUNAT. No se puede cambiar después.', maxLength: 2 },
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'file', requerido: true, placeholder: 'Ej. Factura', maxLength: 80 },
    { nombre: 'abreviatura', etiqueta: 'Abreviatura', icono: 'tags', requerido: true, placeholder: 'Ej. FAC', ayuda: 'Se guarda en mayúsculas.', maxLength: 10 },
    { nombre: 'es_electronico', etiqueta: 'Es electrónico', icono: 'settings', tipo: 'booleano', ayuda: 'Los electrónicos exigen un número de hasta 8 dígitos.' },
    { nombre: 'aplica_compras', etiqueta: 'Se usa en compras', icono: 'truck', tipo: 'booleano' },
    { nombre: 'aplica_ventas', etiqueta: 'Se usa en ventas', icono: 'cart', tipo: 'booleano' },
    { nombre: 'lleva_igv', etiqueta: 'Detalla el IGV', icono: 'calculator', tipo: 'booleano', ayuda: 'No para guías de remisión ni recibos por honorarios.' },
    { nombre: 'ejemplo_serie', etiqueta: 'Ejemplo de serie', icono: 'scan', placeholder: 'Ej. F001', ayuda: 'Cómo se ve una serie de este comprobante. Es solo una guía para quien la escribe.', maxLength: 10 },
    { nombre: 'patron_serie', etiqueta: 'Regla técnica de la serie (avanzado)', icono: 'settings', completo: true, placeholder: 'Ej. F[A-Z0-9]{3}', ayuda: 'Opcional y para quien sepa de expresiones: con ella el sistema rechaza series mal escritas. Déjala como está si no la entiendes. Vacío = cualquier serie.', maxLength: 60 },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    // El código solo se escribe al crear; en la ficha no viene en el formulario.
    if (f.codigo !== undefined && !/^\d{2}$/.test(String(f.codigo ?? '').trim())) errores.codigo = 'Son 2 números (por ejemplo, 01).'
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre.'
    if (!String(f.abreviatura ?? '').trim()) errores.abreviatura = 'Ingrese la abreviatura.'
    if (f.patron_serie) {
      try {
        new RegExp(`^(?:${f.patron_serie})$`)
      } catch {
        errores.patron_serie = 'No es una expresión válida.'
      }
    }
    return errores
  },
}

export const SERIES_COMPROBANTE = {
  femenino: true, // «Nueva serie», «registrada», «eliminada»
  clave: 'series-comprobante',
  ruta: '/mantenimiento/series-comprobante',
  endpoint: '/mantenimiento/series-comprobante/',
  permiso: 'MANTENIMIENTO.SERIES',
  deOrganizacion: false,
  porEmpresa: true,
  icono: 'scan',
  titulo: 'Series de comprobantes',
  singular: 'serie',
  descripcion: 'Las series con las que la empresa seleccionada emite sus comprobantes y su numeración. Cada empresa numera por separado y puede tener varias series del mismo tipo, por ejemplo una por punto de venta.',
  buscar: 'Buscar serie…',
  tituloFila: (r) => r.serie,
  subtituloFila: (r) => `${r.tipo_nombre}${r.nombre ? ` · ${r.nombre}` : ''}`,
  inicial: { tipo_comprobante: '', serie: '', nombre: '', sucursal: '', es_electronica: 'true', ultimo_numero: '0', estado: 'ACTIVO' },
  filtros: [{ nombre: 'es_electronica', todos: 'Electrónicas y físicas', opciones: [['1', 'Electrónicas'], ['0', 'Físicas']] }],
  columnas: [
    { titulo: 'Comprobante', celda: (r) => r.tipo_nombre },
    { titulo: 'Serie', celda: (r) => <strong>{r.serie}</strong> },
    { titulo: 'Punto de venta', celda: (r) => r.nombre || r.sucursal_nombre || 'Toda la empresa', suave: true },
    { titulo: 'Tipo', celda: (r) => <span className="pildora" data-tono={r.es_electronica ? 'azul' : 'gris'}>{r.es_electronica ? 'Electrónica' : 'Física'}</span> },
    { titulo: 'Último número', celda: (r) => r.ultimo_numero, suave: true },
    { titulo: 'Próximo', celda: (r) => <code>{r.proximo}</code> },
    { titulo: 'Empresa', celda: (r, ctx) => ctx.nombreEmpresa(r.empresa) },
  ],
  campos: [
    EMPRESA,
    {
      nombre: 'tipo_comprobante',
      etiqueta: 'Tipo de comprobante',
      icono: 'file',
      tipo: 'remoto',
      requerido: true,
      vacio: 'Elija el comprobante',
      etiquetaDe: 'tipo_nombre',
      fuente: () => ({ url: '/mantenimiento/tipos-comprobante/', params: { aplica_ventas: '1', estado: 'ACTIVO', page_size: 100 } }),
      etiquetaOpcion: (t) => `${t.codigo} · ${t.nombre}`,
      ayuda: 'Una vez que la serie emite comprobantes ya no se cambia.',
    },
    { nombre: 'serie', etiqueta: 'Serie', icono: 'scan', requerido: true, placeholder: 'Ej. F001', ayuda: 'Hasta 4 letras o números. Las facturas empiezan con F y las boletas con B (F001, B001).', maxLength: 4 },
    { nombre: 'nombre', etiqueta: 'Nombre o punto de venta', icono: 'store', placeholder: 'Ej. Tienda principal', ayuda: 'Opcional. Sirve para distinguir las series cuando la empresa tiene varios puntos de venta.', maxLength: 80 },
    {
      nombre: 'sucursal',
      etiqueta: 'Sucursal',
      icono: 'building',
      tipo: 'remoto',
      vacio: 'Toda la empresa',
      vacioSinFuente: 'Primero elija la empresa',
      etiquetaDe: 'sucursal_nombre',
      fuente: deLaEmpresa('/organizacion/sucursales/'),
      etiquetaOpcion: (s) => `${s.codigo} · ${s.nombre}`,
      ayuda: 'Opcional. Déjala vacía si la serie sirve a toda la empresa.',
    },
    { nombre: 'es_electronica', etiqueta: 'Es electrónica', icono: 'settings', tipo: 'booleano', ayuda: 'Las series electrónicas se envían a SUNAT. Elige «No» para comprobantes físicos de talonario.' },
    { nombre: 'ultimo_numero', etiqueta: 'Último número emitido', icono: 'tags', inputMode: 'numeric', maxLength: 8, placeholder: 'Ej. 0', ayuda: 'El siguiente comprobante saldrá con el número que sigue. Empieza en 0. Puedes cambiarlo mientras la serie no haya emitido nada (por ejemplo, si vienes de otro sistema y ya vas en el 245); después solo puede subir.' },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (f.tipo_comprobante !== undefined && !f.tipo_comprobante) errores.tipo_comprobante = 'Elija el tipo de comprobante.'
    if (!/^[A-Za-z0-9]{1,4}$/.test(String(f.serie ?? '').trim())) errores.serie = 'Hasta 4 letras o números (por ejemplo, F001).'
    if (f.ultimo_numero !== undefined && !/^\d{1,8}$/.test(String(f.ultimo_numero).trim())) errores.ultimo_numero = 'Un número entre 0 y 99999999.'
    return errores
  },
}

export const MEDIOS_PAGO = {
  clave: 'medios-pago',
  ruta: '/mantenimiento/medios-pago',
  endpoint: '/mantenimiento/medios-pago/',
  permiso: 'MANTENIMIENTO.MEDIOS_PAGO',
  deOrganizacion: true,
  icono: 'wallet',
  titulo: 'Métodos de pago',
  singular: 'método de pago',
  descripcion: 'Las formas en que pagas y cobras: efectivo, tarjeta, Yape… Agrega los que use tu negocio (por ejemplo, Izipay o la cuenta de un banco).',
  buscar: 'Buscar método de pago…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => etiqueta(TIPOS_MEDIO_PAGO, r.tipo),
  inicial: { nombre: '', tipo: 'OTRO', requiere_referencia: 'false', estado: 'ACTIVO' },
  filtros: [{ nombre: 'tipo', todos: 'Todos los tipos', opciones: TIPOS_MEDIO_PAGO }],
  columnas: [
    { titulo: 'Método de pago', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'Tipo', celda: (r) => <span className="pildora" data-tono="azul">{etiqueta(TIPOS_MEDIO_PAGO, r.tipo)}</span> },
    { titulo: 'Pide número de operación', celda: (r) => siNo(r.requiere_referencia), suave: true },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'wallet', requerido: true, placeholder: 'Ej. Izipay', maxLength: 60 },
    { nombre: 'tipo', etiqueta: 'Tipo', icono: 'tags', tipo: 'select', opciones: TIPOS_MEDIO_PAGO, ayuda: 'Agrupa los métodos parecidos en los reportes.' },
    { nombre: 'requiere_referencia', etiqueta: 'Pide número de operación', icono: 'documento', tipo: 'booleano', ayuda: 'Actívalo si al usarlo hay que anotar el número de operación o de voucher (tarjeta, transferencia, Yape…).' },
    ESTADO,
  ],
  validar: (f) => validarBase(f, [['nombre', 'Ingrese el nombre.']]),
}

export const PERIODICIDADES = {
  femenino: true, // «Nueva periodicidad», «registrada», «eliminada»
  clave: 'periodicidades',
  ruta: '/mantenimiento/periodicidades',
  endpoint: '/mantenimiento/periodicidades/',
  permiso: 'MANTENIMIENTO.PERIODICIDADES',
  deOrganizacion: true,
  icono: 'calendario',
  titulo: 'Periodicidades de cuotas',
  singular: 'periodicidad',
  descripcion: 'Cada cuánto vence una cuota cuando una compra o venta se paga a crédito. Con ellas el sistema arma el cronograma de pagos.',
  buscar: 'Buscar periodicidad…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => r.descripcion,
  inicial: { nombre: '', unidad: 'DIAS', cantidad: '', estado: 'ACTIVO' },
  filtros: [{ nombre: 'unidad', todos: 'Días y meses', opciones: UNIDADES_PERIODO }],
  columnas: [
    { titulo: 'Periodicidad', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'Vence', celda: (r) => r.descripcion },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'calendario', requerido: true, placeholder: 'Ej. Cada 10 días', maxLength: 60 },
    { nombre: 'unidad', etiqueta: 'Se cuenta en', icono: 'settings', tipo: 'select', opciones: UNIDADES_PERIODO, ayuda: 'Los meses respetan el día (el 15 de cada mes) y ajustan los meses cortos.' },
    { nombre: 'cantidad', etiqueta: 'Cada cuántos', icono: 'tags', requerido: true, placeholder: 'Ej. 7', ayuda: 'Un número: cada 7 días, cada 1 mes…', maxLength: 3 },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre.'
    const cantidad = Number(f.cantidad)
    const tope = f.unidad === 'MESES' ? 12 : 365
    if (!/^\d{1,3}$/.test(String(f.cantidad ?? '').trim()) || cantidad < 1 || cantidad > tope) {
      errores.cantidad = `Un número de 1 a ${tope} ${f.unidad === 'MESES' ? 'meses' : 'días'}.`
    }
    return errores
  },
}

const dinero = (valor, moneda) => `${moneda === 'USD' ? 'US$' : 'S/'} ${Number(valor).toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
// El tipo no viene en el formulario de la ficha (no se cambia): se toma del registro.
const tipoDe = (valores, registro) => valores.tipo ?? registro?.tipo

export const CUENTAS_FINANCIERAS = {
  femenino: true, // «Nueva caja o cuenta», «registrada», «eliminada»
  clave: 'cuentas-financieras',
  ruta: '/caja/cuentas',
  endpoint: '/mantenimiento/cuentas/',
  permiso: 'CAJA.CUENTAS',
  deOrganizacion: false,
  porEmpresa: true,
  icono: 'wallet',
  titulo: 'Cajas y cuentas',
  singular: 'caja o cuenta',
  descripcion: 'Dónde está el dinero de la empresa seleccionada: cajas de efectivo, cuentas de banco y billeteras digitales. Cada pago y cobro sale de una o entra a una de ellas. Puedes tener una caja por tienda.',
  buscar: 'Buscar caja o cuenta…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `${r.tipo_nombre} · ${r.moneda_nombre}`,
  inicial: { nombre: '', tipo: 'CAJA', moneda: 'PEN', sucursal: '', banco: '', numero_cuenta: '', cci: '', saldo_inicial: '0', fecha_saldo_inicial: '', rol_caja: 'MOSTRADOR', fondo_inicial: '0', exige_sesion: 'true', permite_saldo_negativo: 'false', cuenta_contable: '', codigo_entidad: '', saldo_minimo: '', estado: 'ACTIVO' },
  filtros: [
    { nombre: 'tipo', todos: 'Todos los tipos', opciones: TIPOS_CUENTA },
    { nombre: 'moneda', todos: 'Soles y dólares', opciones: MONEDAS_CUENTA },
  ],
  columnas: [
    { titulo: 'Caja o cuenta', celda: (r) => <>{r.nombre}<br /><small className="celda-suave">{r.sucursal_nombre ? `Sucursal ${r.sucursal_nombre}` : 'Toda la empresa'}</small></> },
    { titulo: 'Tipo', celda: (r) => <span className="pildora" data-tono={r.tipo === 'CAJA' ? 'verde' : r.tipo === 'BANCO' ? 'azul' : 'morado'}>{r.tipo_nombre}</span> },
    { titulo: 'Moneda', celda: (r) => r.moneda_nombre, suave: true },
    { titulo: 'Banco o número', celda: (r) => [r.banco, r.numero_cuenta].filter(Boolean).join(' · ') || '—', suave: true },
    { titulo: 'Saldo inicial', celda: (r) => dinero(r.saldo_inicial, r.moneda), suave: true },
    { titulo: 'Empresa', celda: (r, ctx) => ctx.nombreEmpresa(r.empresa) },
  ],
  campos: [
    EMPRESA,
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'wallet', requerido: true, placeholder: 'Ej. Caja efectivo, BCP soles, Yape', maxLength: 80 },
    { nombre: 'tipo', etiqueta: 'Tipo', icono: 'tags', tipo: 'select', opciones: TIPOS_CUENTA, requerido: true, ayuda: 'Puedes cambiarlo después. Una caja que ya tuvo sesiones no puede pasar a banco o billetera.' },
    { nombre: 'moneda', etiqueta: 'Moneda', icono: 'coins', tipo: 'select', opciones: MONEDAS_CUENTA, soloAlta: true, requerido: true, ayuda: 'No se puede cambiar después.' },
    {
      nombre: 'sucursal',
      etiqueta: 'Sucursal',
      icono: 'building',
      tipo: 'remoto',
      vacio: 'Toda la empresa',
      vacioSinFuente: 'Primero elija la empresa',
      etiquetaDe: 'sucursal_nombre',
      fuente: deLaEmpresa('/organizacion/sucursales/'),
      etiquetaOpcion: (s) => `${s.codigo} · ${s.nombre}`,
      ayuda: 'Una caja por tienda: elige la sucursal a la que pertenece. Déjala vacía si sirve a toda la empresa (por ejemplo, una cuenta de banco).',
    },
    { nombre: 'banco', etiqueta: 'Banco o entidad', icono: 'building', visibleSi: (v, r) => tipoDe(v, r) !== 'CAJA', placeholder: 'Ej. BCP, BBVA, Yape', maxLength: 60 },
    { nombre: 'numero_cuenta', etiqueta: 'Número de cuenta o celular', icono: 'documento', visibleSi: (v, r) => tipoDe(v, r) !== 'CAJA', placeholder: 'Ej. 193-12345678-0-12', ayuda: 'Solo lo ven quienes pueden editar cajas y cuentas; los demás ven los últimos 4 dígitos.', maxLength: 30 },
    { nombre: 'cci', etiqueta: 'Código interbancario (CCI)', icono: 'documento', visibleSi: (v, r) => tipoDe(v, r) === 'BANCO', placeholder: '20 números', maxLength: 20 },
    { nombre: 'saldo_inicial', etiqueta: 'Saldo inicial', icono: 'coins', placeholder: 'Ej. 0', ayuda: 'Con cuánto dinero empieza esta caja o cuenta en el sistema. Déjalo en 0 si empieza vacía.', maxLength: 16 },
    { nombre: 'fecha_saldo_inicial', etiqueta: 'Fecha del saldo inicial', icono: 'calendario', tipo: 'date', max: 'hoy', ayuda: 'Obligatoria si el saldo inicial es mayor que 0.' },
    {
      nombre: 'rol_caja',
      etiqueta: 'Qué caja es',
      icono: 'store',
      tipo: 'select',
      opciones: [
        ['MOSTRADOR', 'Mostrador (atiende al cliente)'],
        ['PRINCIPAL', 'Caja principal (caja fuerte de la tienda)'],
        ['CAJA_CHICA', 'Caja chica (fondo fijo para gastos menores)'],
      ],
      vacio: 'Sin definir',
      visibleSi: (v, r) => tipoDe(v, r) === 'CAJA',
      ayuda: 'Cada tienda tiene una sola caja principal; las demás son mostradores. La principal reparte el fondo y recibe lo que se recoge.',
    },
    { nombre: 'fondo_inicial', etiqueta: 'Fondo inicial sugerido', icono: 'coins', visibleSi: (v, r) => tipoDe(v, r) === 'CAJA', placeholder: 'Ej. 200', ayuda: 'Efectivo con el que suele abrir esta caja; se propone al abrir cada sesión.', maxLength: 16 },
    { nombre: 'exige_sesion', etiqueta: 'Exige abrir sesión', icono: 'reloj', tipo: 'booleano', visibleSi: (v, r) => tipoDe(v, r) === 'CAJA', ayuda: 'Con «Sí», no se mueve efectivo de esta caja si nadie la abrió; al cerrar se cuenta el dinero.' },
    { nombre: 'permite_saldo_negativo', etiqueta: 'Permite sobregiro', icono: 'coins', tipo: 'booleano', visibleSi: (v, r) => tipoDe(v, r) !== 'CAJA', ayuda: 'Con «Sí», se puede pagar aunque la cuenta no tenga saldo (sobregiro bancario). Con «No», el pago se bloquea hasta registrar el ingreso que falta. Las cajas de efectivo nunca quedan en negativo.' },
    { nombre: 'saldo_minimo', nulable: true, etiqueta: 'Avisar si baja de', icono: 'bell', placeholder: 'Ej. 500', ayuda: 'Opcional. Si el saldo baja de este monto, Saldos te avisa que hay que reponer o depositar.', maxLength: 16 },
    { nombre: 'cuenta_contable', etiqueta: 'Cuenta contable', icono: 'calculator', placeholder: 'Ej. 1041', ayuda: 'Para el Libro Caja y Bancos electrónico. Pregunta a tu contador qué cuenta del plan contable usa (101 caja, 104 cuentas corrientes…). Opcional.', maxLength: 20 },
    { nombre: 'codigo_entidad', etiqueta: 'Código SUNAT del banco', icono: 'building', visibleSi: (v, r) => tipoDe(v, r) !== 'CAJA', placeholder: 'Ej. 02', ayuda: 'Dos números de la tabla de entidades financieras de SUNAT. Lo confirma tu contador. Opcional.', maxLength: 2 },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre.'
    if (String(f.saldo_minimo ?? '').trim() && !/^\d{1,14}([.,]\d{1,2})?$/.test(String(f.saldo_minimo).trim())) errores.saldo_minimo = 'Un número desde 0, con hasta 2 decimales.'
    if (String(f.cuenta_contable ?? '').trim() && !/^\d{2,20}$/.test(String(f.cuenta_contable).trim())) errores.cuenta_contable = 'Use de 2 a 20 números, por ejemplo 1041.'
    if (String(f.codigo_entidad ?? '').trim() && !/^\d{2}$/.test(String(f.codigo_entidad).trim())) errores.codigo_entidad = 'Son 2 números.'
    if (f.tipo === 'CAJA' && !/^\d{1,14}(\.\d{1,2})?$/.test(String(f.fondo_inicial ?? '0').trim().replace(',', '.'))) errores.fondo_inicial = 'Un número desde 0, con hasta 2 decimales.'
    if (f.tipo === 'BANCO' && !String(f.banco ?? '').trim()) errores.banco = 'Indique el banco.'
    const saldo = String(f.saldo_inicial ?? '').trim().replace(',', '.')
    if (!/^\d{1,14}(\.\d{1,2})?$/.test(saldo)) errores.saldo_inicial = 'Un número desde 0, con hasta 2 decimales.'
    else if (Number(saldo) > 0 && !f.fecha_saldo_inicial) errores.fecha_saldo_inicial = 'Indique desde qué fecha es ese saldo.'
    if (f.cci && !/^\d{20}$/.test(String(f.cci).replace(/\s/g, ''))) errores.cci = 'Son 20 números.'
    return errores
  },
}

export const CONCEPTOS_CAJA = {
  clave: 'conceptos-caja',
  ruta: '/caja/conceptos',
  endpoint: '/mantenimiento/conceptos-caja/',
  permiso: 'MANTENIMIENTO.CONCEPTOS_CAJA',
  deOrganizacion: true,
  icono: 'tags',
  titulo: 'Conceptos de caja',
  singular: 'concepto de caja',
  descripcion: 'Para qué entra o sale dinero de una caja o cuenta: pago a proveedor, comisión, aporte… Agrega los que use tu negocio. Los marcados «del sistema» los usa el sistema por su cuenta y no se borran.',
  buscar: 'Buscar concepto…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => r.tipo_nombre,
  inicial: { nombre: '', tipo: 'EGRESO', estado: 'ACTIVO' },
  filtros: [{ nombre: 'tipo', todos: 'Ingresos y egresos', opciones: TIPOS_CONCEPTO_CAJA }],
  columnas: [
    {
      titulo: 'Concepto',
      celda: (r) => (
        <>
          <strong>{r.nombre}</strong>
          {r.automatico && <small className="celda-suave"> · del sistema</small>}
        </>
      ),
    },
    { titulo: 'Tipo', celda: (r) => <span className="pildora" data-tono={r.tipo === 'INGRESO' ? 'verde' : 'ambar'}>{r.tipo_nombre}</span> },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'tags', requerido: true, placeholder: 'Ej. Propinas', maxLength: 80 },
    { nombre: 'tipo', etiqueta: 'Tipo', icono: 'swap', tipo: 'select', opciones: TIPOS_CONCEPTO_CAJA, soloAlta: true, ayuda: 'No se cambia después: si te equivocas, crea otro.' },
    ESTADO,
  ],
  validar: (f) => validarBase(f, [['nombre', 'Ingrese el nombre.']]),
}

export const CATEGORIAS_GASTO = {
  clave: 'categorias-gasto',
  ruta: '/gastos/categorias',
  endpoint: '/mantenimiento/categorias-gasto/',
  permiso: 'MANTENIMIENTO.CATEGORIAS_GASTO',
  deOrganizacion: true,
  femenino: true,
  icono: 'tags',
  titulo: 'Categorías de gasto',
  singular: 'categoría de gasto',
  descripcion: 'En qué gasta la empresa: servicios, alquiler, movilidad… Sirven para ordenar los gastos y ver cuánto se va en cada cosa. Agrega las que use tu negocio.',
  buscar: 'Buscar categoría…',
  tituloFila: (r) => r.nombre,
  subtituloFila: () => 'Categoría de gasto',
  inicial: { nombre: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [{ titulo: 'Categoría', celda: (r) => <strong>{r.nombre}</strong> }],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'tags', requerido: true, placeholder: 'Ej. Seguridad y vigilancia', maxLength: 80 },
    ESTADO,
  ],
  validar: (f) => validarBase(f, [['nombre', 'Ingrese el nombre.']]),
}

export const CENTROS_COSTO = {
  clave: 'centros-costo',
  ruta: '/mantenimiento/centros-costo',
  endpoint: '/mantenimiento/centros-costo/',
  permiso: 'MANTENIMIENTO.CENTROS_COSTO',
  deOrganizacion: true,
  icono: 'coins',
  titulo: 'Centros de costo',
  singular: 'centro de costo',
  descripcion: 'Áreas del negocio a las que se cargan los gastos. Las comparten todas tus empresas.',
  buscar: 'Buscar centro de costo…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => r.codigo,
  inicial: { codigo: '', nombre: '', padre: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [
    { titulo: 'Código', celda: (r) => <strong>{r.codigo}</strong> },
    { titulo: 'Centro de costo', celda: (r) => r.nombre },
    { titulo: 'Grupo', celda: (r) => r.padre_nombre || '—', suave: true },
    { titulo: 'Centros dentro', celda: (r) => (r.n_hijos > 0 ? r.n_hijos : '—'), suave: true },
  ],
  campos: [
    { nombre: 'codigo', etiqueta: 'Código', icono: 'tags', requerido: true, placeholder: 'Ej. CC-01', ayuda: 'Se guarda en mayúsculas y sin espacios.', maxLength: 20 },
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'coins', requerido: true, placeholder: 'Ej. Servicio técnico', maxLength: 100 },
    {
      nombre: 'padre',
      etiqueta: 'Grupo',
      icono: 'layers',
      tipo: 'remoto',
      completo: true,
      vacio: 'Ninguno (es un grupo o va solo)',
      vacioSinOpciones: 'Aún no hay grupos: crea primero uno',
      etiquetaDe: 'padre_nombre',
      ayuda: 'Opcional: elige el grupo al que pertenece, por ejemplo «Operaciones».',
      fuente: () => ({ url: '/mantenimiento/centros-costo/', params: { padre: 'ninguno', estado: 'ACTIVO', page_size: 100 } }),
      etiquetaOpcion: (c) => `${c.codigo} · ${c.nombre}`,
      excluir: (registro) => registro?.id, // no puede ser su propio grupo
    },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.codigo ?? '').trim()) errores.codigo = 'Ingrese el código.'
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre.'
    return errores
  },
}

export const MARCAS = {
  femenino: true, // «Nueva marca», «registrada», «eliminada»
  clave: 'marcas',
  ruta: '/mantenimiento/marcas',
  endpoint: '/mantenimiento/marcas/',
  permiso: 'MANTENIMIENTO.MARCAS',
  deOrganizacion: true,
  icono: 'tags',
  titulo: 'Marcas',
  singular: 'marca',
  descripcion: 'Marcas de los productos: las comparten todas tus empresas.',
  buscar: 'Buscar marca…',
  tituloFila: (r) => r.nombre,
  subtituloFila: () => 'Marca de productos',
  inicial: { nombre: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [{ titulo: 'Marca', celda: (r) => <strong>{r.nombre}</strong> }],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre de la marca', icono: 'tags', requerido: true, placeholder: 'Ej. Logitech', completo: true, maxLength: 100 },
    ESTADO,
  ],
  validar: (f) => (String(f.nombre ?? '').trim() ? {} : { nombre: 'Ingrese el nombre de la marca.' }),
}

export const UNIDADES = {
  femenino: true, // «Nueva unidad», «registrada», «eliminada»
  clave: 'unidades',
  ruta: '/mantenimiento/unidades',
  endpoint: '/mantenimiento/unidades/',
  permiso: 'MANTENIMIENTO.UNIDADES',
  deOrganizacion: true,
  icono: 'calculator',
  titulo: 'Unidades de medida',
  singular: 'unidad de medida',
  descripcion: 'Cómo se cuenta y se vende cada producto: unidad, kilo, metro, caja…',
  buscar: 'Buscar unidad…',
  sembrar: { texto: 'Cargar las más comunes', exito: (n) => (n ? `Se cargaron ${n} unidades.` : 'Ya tienes todas las unidades comunes.') },
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `Abreviatura ${r.abreviatura}`,
  inicial: { nombre: '', abreviatura: '', codigo_sunat: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [
    { titulo: 'Unidad', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'Abreviatura', celda: (r) => r.abreviatura },
    { titulo: 'Código SUNAT', suave: true, celda: (r) => r.codigo_sunat || '—' },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre', icono: 'calculator', requerido: true, placeholder: 'Ej. Kilogramo', maxLength: 100 },
    { nombre: 'abreviatura', etiqueta: 'Abreviatura', icono: 'tags', requerido: true, placeholder: 'Ej. KG', maxLength: 10, ayuda: 'Es lo que se imprime junto a la cantidad.' },
    { nombre: 'codigo_sunat', etiqueta: 'Código SUNAT', icono: 'documento', placeholder: 'Ej. KGM', maxLength: 5, ayuda: 'Opcional. Lo piden las facturas electrónicas.' },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese el nombre de la unidad.'
    if (!String(f.abreviatura ?? '').trim()) errores.abreviatura = 'Ingrese la abreviatura.'
    return errores
  },
}

export const LISTAS_PRECIO = {
  femenino: true, // «Nueva lista de precios», «registrada»
  clave: 'listas-precio',
  ruta: '/mantenimiento/listas-precio',
  endpoint: '/mantenimiento/listas-precio/',
  permiso: 'MANTENIMIENTO.LISTAS_PRECIO',
  deOrganizacion: true,
  icono: 'coins',
  titulo: 'Listas de precios',
  singular: 'lista de precios',
  descripcion: 'Los niveles de precio de venta de tus productos. Ponles el nombre que use tu negocio.',
  buscar: 'Buscar lista…',
  sembrar: { texto: 'Cargar las 4 estándar', exito: (n) => (n ? `Se cargaron ${n} listas.` : 'Ya tienes las listas estándar.') },
  protegido: (r) => r.es_principal, // la principal no se desactiva ni se elimina
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => (r.es_principal ? 'Lista principal de venta' : 'Lista de precios'),
  inicial: { nombre: '', uso: 'OTRA', estado: 'ACTIVO' },
  filtros: [],
  columnas: [
    { titulo: 'Lista', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'Tipo', suave: true, celda: (r) => (r.es_principal ? 'Principal (precio normal)' : 'Adicional') },
    { titulo: 'Se usa como', suave: true, celda: (r) => etiqueta(USOS_LISTA, r.uso) },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Nombre de la lista', icono: 'coins', requerido: true, placeholder: 'Ej. Mayorista', completo: true, maxLength: 100 },
    { nombre: 'uso', etiqueta: 'Para qué se usa', icono: 'coins', tipo: 'select', opciones: USOS_LISTA, completo: true, ayuda: 'Ventas se guía por esto, no por el nombre: de aquí salen el precio normal, el piso al descontar y el precio a crédito.' },
    ESTADO,
  ],
  validar: (f) => (String(f.nombre ?? '').trim() ? {} : { nombre: 'Ingrese el nombre de la lista.' }),
}

/** Terminación de los participios según el género del maestro: «registrado» / «registrada». */
export const generoDe = (config) => (config.femenino ? { nuevo: 'Nueva', o: 'a' } : { nuevo: 'Nuevo', o: 'o' })

export { etiqueta }

// --- Transporte de la mercadería: las listas que elige la guía de remisión -----------------------------

/** La placa sin espacios ni guiones y en mayúsculas: «abc-123» se guarda como ABC123. */
export const limpiarPlaca = (valor) => valor.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8)
const soloDigitos = (largo) => (valor) => valor.replace(/\D/g, '').slice(0, largo)
const enMayusculas = (valor) => valor.toUpperCase()

export const EMPRESAS_TRANSPORTE = {
  femenino: true, // «Nueva empresa de transporte», «registrada», «eliminada»
  clave: 'empresas-transporte',
  ruta: '/mantenimiento/transporte/empresas',
  endpoint: '/mantenimiento/empresas-transporte/',
  permiso: 'MANTENIMIENTO.TRANSPORTE',
  deOrganizacion: true,
  icono: 'truck',
  titulo: 'Empresas de transporte',
  singular: 'empresa de transporte',
  descripcion: 'Las empresas que llevan tu mercadería (transporte público). La guía de remisión las elige de esta lista, con su RUC y sus registros del MTC.',
  buscar: 'Buscar por nombre, RUC o registro…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `RUC ${r.ruc}`,
  inicial: { nombre: '', ruc: '', registro_mtc: '', certificado_inspeccion: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [
    { titulo: 'Empresa', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'RUC', celda: (r) => r.ruc },
    { titulo: 'N° de registro MTC', celda: (r) => r.registro_mtc || '—', suave: true },
    { titulo: 'Cert. de inspección', celda: (r) => r.certificado_inspeccion || '—', suave: true },
  ],
  campos: [
    { nombre: 'nombre', etiqueta: 'Razón social', icono: 'building', requerido: true, placeholder: 'Ej. Transportes El Rápido S.A.C.', completo: true, maxLength: 250 },
    { nombre: 'ruc', etiqueta: 'RUC', icono: 'documento', requerido: true, placeholder: 'Ej. 20123456789', maxLength: 11, transformar: soloDigitos(11) },
    { nombre: 'registro_mtc', etiqueta: 'N° de registro MTC', icono: 'tags', placeholder: 'Opcional', maxLength: 30, transformar: enMayusculas },
    { nombre: 'certificado_inspeccion', etiqueta: 'Certificado de inspección', icono: 'tags', placeholder: 'Opcional', maxLength: 30, transformar: enMayusculas },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!String(f.nombre ?? '').trim()) errores.nombre = 'Ingrese la razón social.'
    if (!/^\d{11}$/.test(String(f.ruc ?? '').trim())) errores.ruc = 'El RUC debe tener 11 dígitos.'
    return errores
  },
}

export const CONDUCTORES = {
  clave: 'conductores',
  ruta: '/mantenimiento/transporte/conductores',
  endpoint: '/mantenimiento/conductores/',
  permiso: 'MANTENIMIENTO.TRANSPORTE',
  deOrganizacion: true,
  icono: 'user',
  titulo: 'Conductores',
  singular: 'conductor',
  descripcion: 'Quienes manejan los vehículos que llevan tu mercadería. La guía de remisión los elige de esta lista, con su documento y su licencia.',
  buscar: 'Buscar por nombre, documento o licencia…',
  tituloFila: (r) => r.nombre,
  subtituloFila: (r) => `${etiqueta(TIPOS_DOCUMENTO, r.tipo_documento)} ${r.numero_documento}`,
  inicial: { tipo_documento: 'DNI', numero_documento: '', nombre: '', licencia: '', estado: 'ACTIVO' },
  filtros: [],
  // Con el DNI se completa el nombre desde RENIEC (quien tiene el permiso de consultas).
  consulta: { DNI: (d) => ({ nombre: [d.nombres, d.apellidos].filter(Boolean).join(' ') }) },
  columnas: [
    { titulo: 'Conductor', celda: (r) => <strong>{r.nombre}</strong> },
    { titulo: 'Documento', celda: celdaDocumento },
    { titulo: 'Licencia de conducir', celda: (r) => r.licencia || '—', suave: true },
  ],
  campos: [
    { nombre: 'tipo_documento', etiqueta: 'Tipo de documento', icono: 'documento', tipo: 'select', opciones: TIPOS_DOCUMENTO.filter(([v]) => v !== 'RUC') },
    { nombre: 'numero_documento', etiqueta: 'Número de documento', icono: 'documento', requerido: true, documento: true },
    { nombre: 'nombre', etiqueta: 'Nombres y apellidos', icono: 'user', requerido: true, placeholder: 'Ej. Henry Ramírez Bartra', completo: true, maxLength: 150 },
    { nombre: 'licencia', etiqueta: 'Licencia de conducir', icono: 'tags', placeholder: 'Ej. Q43512345', ayuda: 'Opcional. Sale en la guía de remisión.', maxLength: 20, transformar: enMayusculas },
    ESTADO,
  ],
  validar: (f) => validarBase(f, [['nombre', 'Ingrese el nombre del conductor.']]),
}

export const VEHICULOS = {
  clave: 'vehiculos',
  ruta: '/mantenimiento/transporte/vehiculos',
  endpoint: '/mantenimiento/vehiculos/',
  permiso: 'MANTENIMIENTO.TRANSPORTE',
  deOrganizacion: true,
  icono: 'truck',
  titulo: 'Vehículos',
  singular: 'vehículo',
  descripcion: 'Los vehículos que llevan tu mercadería. La guía de remisión elige el principal y los secundarios de esta lista, con su placa, marca y modelo.',
  buscar: 'Buscar por placa, marca o modelo…',
  tituloFila: (r) => r.placa,
  subtituloFila: (r) => [r.marca, r.modelo].filter(Boolean).join(' ') || 'Vehículo',
  inicial: { placa: '', marca: '', modelo: '', estado: 'ACTIVO' },
  filtros: [],
  columnas: [
    { titulo: 'Placa', celda: (r) => <strong>{r.placa}</strong> },
    { titulo: 'Marca', celda: (r) => r.marca || '—', suave: true },
    { titulo: 'Modelo', celda: (r) => r.modelo || '—', suave: true },
  ],
  campos: [
    { nombre: 'placa', etiqueta: 'Placa', icono: 'tags', requerido: true, placeholder: 'Ej. ABC123', ayuda: 'Sin espacios ni guiones: «abc-123» se guarda como ABC123.', maxLength: 8, transformar: limpiarPlaca },
    { nombre: 'marca', etiqueta: 'Marca', icono: 'tags', placeholder: 'Ej. Yamaha', maxLength: 60 },
    { nombre: 'modelo', etiqueta: 'Modelo', icono: 'tags', placeholder: 'Ej. XTZ150', maxLength: 60 },
    ESTADO,
  ],
  validar: (f) => {
    const errores = {}
    if (!/^[A-Z0-9]{5,8}$/.test(limpiarPlaca(String(f.placa ?? '')))) errores.placa = 'La placa debe tener de 5 a 8 letras o números.'
    return errores
  },
}
