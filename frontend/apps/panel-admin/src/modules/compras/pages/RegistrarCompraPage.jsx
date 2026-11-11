import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import ActualizarPreciosModal from '../components/ActualizarPreciosModal'
import DatosComprobante from '../components/DatosComprobante'
import FleteCompra from '../components/FleteCompra'
import FormaPagoCompra from '../components/FormaPagoCompra'
import ImportarXmlModal from '../components/ImportarXmlModal'
import LineasCompra from '../components/LineasCompra'
import ProveedorCompra from '../components/ProveedorCompra'
import ResumenCompra from '../components/ResumenCompra'
import { armarCuerpo, borradorInicial, cantidadDe, lineaCalculable, lineaDeProducto, numeroInterno, resolverPagos, validarCompra } from '../compras'
import { useCalculoCompra } from '../hooks/useCalculoCompra'
import { useCatalogosCompra } from '../hooks/useCatalogosCompra'
import { useRecepcionDeOrden } from '../hooks/useOrdenes'
import '../../almacen/inventario.css'
import '../compras.css'

const RUTA = '/compras/registro'
const VACIO = [] // referencia estable mientras un catálogo carga (no se rehacen los cálculos que dependen de él)
const CAMPOS_EN_VIVO = ['serie', 'ajuste', 'tipoCambio'] // se avisan al escribir; los obligatorios, al intentar registrar

/** Qué dice el servidor → en qué campo del formulario se muestra. */
const CAMPO_DEL_SERVIDOR = { proveedor: 'proveedor', almacen: 'almacen', tipo_comprobante: 'tipo', comprobante_serie: 'serie', comprobante_numero: 'numero', fecha_emision: 'fecha', ajuste_redondeo: 'ajuste', tipo_cambio: 'tipoCambio' }

function Formulario({ inicial = null, ordenInfo = null }) {
  const navegar = useNavigate()
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const { tiene } = usePermisos()
  const [b, setB] = useState(() => inicial ?? borradorInicial())
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const [delServidor, setDelServidor] = useState({})
  const [registrada, setRegistrada] = useState(null)
  const [saliendo, setSaliendo] = useState(false)
  const [importando, setImportando] = useState(false)
  const [totalXml, setTotalXml] = useState(null) // { total, moneda } de la factura XML cargada, para compararlo con el cálculo
  const catalogos = useCatalogosCompra(empresaActivaId)

  /** Cambia un campo del borrador; acepta un valor o una función del valor anterior. */
  const poner = useCallback((campo, valor) => setB((previo) => ({ ...previo, [campo]: typeof valor === 'function' ? valor(previo[campo]) : valor })), [])
  const ponerLineas = useCallback((f) => poner('lineas', f), [poner])

  // --- Lo que el usuario no eligió se completa con lo más probable (y se ve así en pantalla) ---
  const comprobantes = catalogos.comprobantes.data ?? VACIO
  const tipoCatalogo = comprobantes.find((t) => t.codigo === b.tipo) ?? comprobantes.find((t) => t.codigo === '01') ?? comprobantes[0]
  const almacen = b.almacen || String(catalogos.almacenes.data?.[0]?.id ?? '')
  const medios = catalogos.medios.data ?? VACIO
  const cuentas = catalogos.cuentas.data ?? VACIO
  const cuentasPen = useMemo(() => cuentas.filter((c) => c.moneda === 'PEN'), [cuentas])
  const periodicidades = catalogos.periodicidades.data ?? VACIO
  const periodicidadId = String(periodicidades.find((p) => String(p.id) === String(b.cuotas.periodicidad))?.id ?? periodicidades.find((p) => p.unidad === 'MESES' && p.cantidad === 1)?.id ?? periodicidades[0]?.id ?? '')
  const ubicacionesQ = useOpciones('/mantenimiento/ubicaciones/', { empresa: empresaActivaId, almacen }, { enabled: Boolean(almacen) && catalogos.puedeUbicar })
  const ubicaciones = useMemo(() => (catalogos.puedeUbicar ? (ubicacionesQ.data ?? []) : []), [catalogos.puedeUbicar, ubicacionesQ.data])
  const ubicacionesValidas = useMemo(() => new Set(ubicaciones.map((u) => u.id)), [ubicaciones])

  const medioBase = medios.find((m) => m.tipo === 'EFECTIVO') ?? medios[0]
  const medioFlete = medios.some((m) => String(m.id) === String(b.flete.medio)) ? String(b.flete.medio) : String(medioBase?.id ?? '')
  const cuentaFlete = cuentasPen.some((c) => String(c.id) === String(b.flete.cuenta)) ? String(b.flete.cuenta) : cuentasPen.length === 1 ? String(cuentasPen[0].id) : ''
  const fleteMedio = medios.find((m) => String(m.id) === medioFlete)

  // La primera cuota nunca vence antes de la emisión (si la emisión se movió, la cuota la sigue).
  const primeraCuota = b.cuotas.primera && b.cuotas.primera < b.fecha ? b.fecha : b.cuotas.primera
  const resuelto = useMemo(() => ({ ...b, cuotas: { ...b.cuotas, periodicidad: periodicidadId, primera: primeraCuota } }), [b, periodicidadId, primeraCuota])

  // --- Vista previa: el servidor calcula totales, IGV, costos y cuotas ---
  const contextoBase = { empresa: empresaActivaId, almacen, tipo: tipoCatalogo?.codigo ?? '', ubicacionesValidas }
  const cuerpoPrevio = armarCuerpo(resuelto, contextoBase, { previa: true })
  const previaActiva = Boolean(b.proveedor && almacen && cuerpoPrevio.lineas.length > 0)
  const calculo = useCalculoCompra(cuerpoPrevio, previaActiva)
  const total = calculo.datos?.total ?? null
  const resultados = useMemo(() => {
    const ids = b.lineas.filter(lineaCalculable).map((l) => l.id)
    const filas = calculo.datos?.lineas
    if (!filas || filas.length !== ids.length) return {}
    return Object.fromEntries(filas.map((fila, i) => [ids[i], fila]))
  }, [calculo.datos, b.lineas])

  // --- Validación y cuerpo final ---
  const pagos = resolverPagos(b.pagos, total ?? '0', { medios, cuentas, moneda: b.moneda, tipoCambio: b.moneda === 'USD' ? (b.tipoCambio || calculo.datos?.tipo_cambio || '') : '' })
  const contexto = { ...contextoBase, tipoCatalogo, pagos, medioFlete, cuentaFlete, medioFletePideReferencia: Boolean(fleteMedio?.requiere_referencia) }
  const validacion = validarCompra(resuelto, contexto, total)
  const cuerpo = armarCuerpo(resuelto, contexto)
  const clave = useClaveIdempotente(cuerpo)
  const erroresPantalla = intento ? validacion.campos : Object.fromEntries(Object.entries(validacion.campos).filter(([k]) => CAMPOS_EN_VIVO.includes(k)))
  const e = { ...erroresPantalla, ...delServidor }

  const puedeCambiarPrecios = tiene('MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO', { organizacion: true })
  /** Precios de venta preparados con «PV», por producto: se muestran al registrar para aplicarlos con el costo definitivo. */
  const propuestos = useMemo(() => Object.fromEntries(b.lineas.filter((l) => l.ventaPrecios).map((l) => [l.producto.id, l.ventaPrecios])), [b.lineas])
  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/compras/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras'], ['caja'], ['movimientos'], ['stock'], ['kardex'], ['periodos'], ['productos']],
    exito: (c) => `Compra N° ${numeroInterno(c)} registrada. El stock ya está al día.`,
    alExito: (compra) => (puedeCambiarPrecios ? setRegistrada(compra) : navegar(RUTA, { replace: true })),
    avisarError: false,
  })
  const enviando = registrar.isPending

  // Avisa si se intenta cerrar la pestaña con una compra a medias.
  const sinGuardar = !registrada && (Boolean(b.proveedor) || b.lineas.length > 0 || b.numero !== '')
  useEffect(() => {
    if (!sinGuardar) return undefined
    const avisar = (ev) => ev.preventDefault()
    window.addEventListener('beforeunload', avisar)
    return () => window.removeEventListener('beforeunload', avisar)
  }, [sinGuardar])

  const enviar = () => {
    if (enviando) return
    setIntento(true)
    setGeneral('')
    setDelServidor({})
    if (!validacion.valido) {
      setTimeout(() => {
        const primero = document.querySelector('.compra-principal [aria-invalid="true"]')
        primero?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        primero?.focus({ preventScroll: true })
      }, 0)
      return
    }
    registrar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const campos = Object.fromEntries(Object.entries(erroresDeCampo(error)).flatMap(([k, v]) => (CAMPO_DEL_SERVIDOR[k] ? [[CAMPO_DEL_SERVIDOR[k], v]] : [])))
          if (codigoDeError(error) === 'comprobante_duplicado') {
            campos.numero = 'Ya registraste un comprobante con esa serie y número de este proveedor.'
            setGeneral('Ese comprobante ya está registrado.')
          } else {
            setGeneral(Object.keys(campos).length ? 'Revise los datos marcados.' : mensajeDeError(error))
          }
          setDelServidor(campos)
        },
      },
    )
  }

  const cancelar = () => {
    if (sinGuardar) setSaliendo(true)
    else navegar(RUTA)
  }

  /** Pasa a la compra lo leído del XML (ya revisado y con cada línea enlazada a un producto). */
  const cargarXml = ({ lectura, proveedor, lineas }) => {
    const { comprobante } = lectura
    const codigosDeIgv = new Set((catalogos.afectaciones.data ?? []).map((a) => a.codigo))
    setB((previo) => ({
      ...previo,
      proveedor: proveedor ?? previo.proveedor,
      tipo: comprobante.tipo,
      serie: comprobante.serie,
      numero: comprobante.numero,
      fecha: comprobante.fecha_emision,
      moneda: comprobante.moneda,
      tipoCambio: '',
      incluyeIgv: false, // el XML trae el valor unitario sin IGV
      forma: comprobante.forma_pago,
      cuotas: comprobante.forma_pago === 'CREDITO' && comprobante.cuotas.length ? { ...previo.cuotas, cantidad: String(comprobante.cuotas.length), primera: comprobante.cuotas[0].fecha_vencimiento } : previo.cuotas,
      lineas: lineas.map((l) => ({ ...lineaDeProducto(l.producto), cantidad: l.cantidad, precio: l.precio_unitario, afectacion: codigosDeIgv.has(l.afectacion) ? l.afectacion : '' })),
    }))
    setTotalXml({ total: lectura.totales.total, moneda: comprobante.moneda })
    setImportando(false)
    setIntento(false)
    setGeneral('')
  }

  const unidades = b.lineas.reduce((s, l) => s + cantidadDe(l), 0)
  const afectaciones = catalogos.afectaciones.data ?? VACIO

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={RUTA} texto="Volver a Compras" />
      <CabeceraListado icono="truck" titulo="Registrar compra" descripcion={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. Al registrar, la mercadería entra al inventario con su costo.`} />
      {ordenInfo && (
        <p role="status" className="modal-aviso">
          <strong>Recibiendo la orden</strong> <Link to={`/compras/ordenes/${ordenInfo.orden}`}>{ordenInfo.codigo}</Link> de {ordenInfo.proveedor_nombre}. Solo se reciben productos de la orden y no más de lo que falta{Number(ordenInfo.tolerancia) > 0 ? ` (más ${ordenInfo.tolerancia} % de tolerancia)` : ''}. Manda el precio de tu factura: si cambia, verás la diferencia en el resumen.
        </p>
      )}
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta
            icono="handshake"
            titulo="Proveedor y comprobante"
            descripcion="Datos tal como figuran en la factura o boleta del proveedor."
            acciones={
              <button type="button" className="boton-cabecera" disabled={enviando} onClick={() => setImportando(true)} title="Lee el XML que te envió el proveedor y precarga la compra">
                <Icono nombre="importar" tam={19} /> Cargar XML
              </button>
            }
          >
            <ProveedorCompra proveedor={b.proveedor} onElegir={(p) => poner('proveedor', p)} error={e.proveedor} disabled={enviando || Boolean(b.orden)} />
            <DatosComprobante b={b} poner={poner} catalogos={catalogos} resuelto={{ tipo: tipoCatalogo?.codigo ?? '', tipoCatalogo, almacen }} e={e} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Productos" descripcion="Escribe o escanea para agregar. El IGV se propone solo según el producto y el proveedor.">
            <LineasCompra lineas={b.lineas} onLineas={ponerLineas} resultados={resultados} moneda={b.moneda} afectaciones={afectaciones} ubicaciones={ubicaciones} errores={intento ? validacion.porLinea : {}} disabled={enviando} puedePrecios={puedeCambiarPrecios} listas={catalogos.listas.data ?? VACIO} />
          </PanelTarjeta>

          <PanelTarjeta icono="wallet" titulo="Forma de pago" descripcion="Al contado se descuenta de una caja o cuenta; al crédito se programan las cuotas.">
            <FormaPagoCompra
              b={b}
              poner={poner}
              resueltos={pagos}
              cuentas={cuentas}
              medios={medios}
              total={total}
              erroresPagos={intento ? validacion.porPago : {}}
              errores={e}
              sinPermisoCajas={!catalogos.puedeVerCajas}
              periodicidades={periodicidades}
              periodicidadId={periodicidadId}
              cronograma={calculo.datos?.cuotas}
              disabled={enviando}
            />
          </PanelTarjeta>

          <PanelTarjeta icono="truck" titulo="Flete" descripcion="Opcional. El transporte se paga aparte y no cambia lo que se le debe al proveedor.">
            <FleteCompra
              flete={b.flete}
              onFlete={(f) => poner('flete', f)}
              comprobantes={comprobantes}
              medios={medios}
              cuentasPen={cuentasPen}
              resuelto={{ medio: medioFlete, cuenta: cuentaFlete, pideReferencia: Boolean(fleteMedio?.requiere_referencia) }}
              error={intento ? e.flete : undefined}
              disabled={enviando}
            />
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Observación">
            <Campo etiqueta="Nota interna" error={e.observacion} contador={{ actual: b.observacion.length, max: 250 }}>
              {(p) => <textarea {...p} rows={2} maxLength={250} placeholder="Opcional" value={b.observacion} disabled={enviando} onChange={(ev) => poner('observacion', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>
        </div>

        <ResumenCompra
          calculo={calculo.datos}
          calculando={calculo.calculando}
          errorCalculo={calculo.error}
          moneda={b.moneda}
          faltan={validacion.faltan}
          general={general}
          enviando={enviando}
          productos={b.lineas.length}
          unidades={unidades}
          totalXml={totalXml}
          avisosPrecio={calculo.datos?.avisos_precio}
          onRegistrar={enviar}
          onCancelar={cancelar}
        />
      </div>
      {importando && <ImportarXmlModal onCargar={cargarXml} onCerrar={() => setImportando(false)} />}
      {saliendo && (
        <ConfirmarModal titulo="Salir sin registrar" mensaje="Se perderá lo que escribiste en esta compra. ¿Quieres salir?" textoConfirmar="Salir" onConfirmar={() => navegar(RUTA)} onCerrar={() => setSaliendo(false)} />
      )}
      {registrada && <ActualizarPreciosModal compra={registrada} propuestos={propuestos} onCerrar={() => navegar(RUTA, { replace: true })} />}
    </main>
  )
}

/** Pantalla «Registrar compra». Se reinicia sola si se cambia de empresa (una compra es de una sola empresa). */
export default function RegistrarCompraPage() {
  const { empresaActivaId } = useEmpresas()
  const [params] = useSearchParams()
  const ordenId = params.get('orden')
  const recepcion = useRecepcionDeOrden(ordenId)
  if (!empresaActivaId) return <p style={{ padding: 24 }}>Elige una empresa para registrar la compra.</p>
  if (!ordenId) return <Formulario key={empresaActivaId} />
  // «Recibir mercadería» desde una orden: la compra arranca con lo que falta recibir.
  return (
    <EstadoConsulta consulta={recepcion.consulta} hayDatos={Boolean(recepcion.borrador)} vacio="La orden no existe.">
      {recepcion.borrador && !recepcion.orden.puede_recibir && (
        <main className="listado">
          <p className="estado-vacio">
            La orden {recepcion.orden.codigo} no admite recepciones en este momento ({recepcion.orden.estado === 'PENDIENTE' ? 'está por aprobar' : 'ya no espera mercadería'}). <Link to={`/compras/ordenes/${ordenId}`}>Volver a la orden</Link>
          </p>
        </main>
      )}
      {recepcion.borrador && recepcion.orden.puede_recibir && recepcion.borrador.lineas.length === 0 && (
        <main className="listado">
          <p className="estado-vacio">
            No falta recibir nada de la orden {recepcion.orden.codigo}. <Link to={`/compras/ordenes/${ordenId}`}>Volver a la orden</Link>
          </p>
        </main>
      )}
      {recepcion.borrador && recepcion.orden.puede_recibir && recepcion.borrador.lineas.length > 0 && <Formulario key={`${empresaActivaId}-${ordenId}`} inicial={recepcion.borrador} ordenInfo={recepcion.orden} />}
    </EstadoConsulta>
  )
}
