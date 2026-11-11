import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import DatosOrden from '../components/DatosOrden'
import LineasOrden from '../components/LineasOrden'
import ProveedorCompra from '../components/ProveedorCompra'
import ResumenOrden from '../components/ResumenOrden'
import { armarCuerpoOrden, borradorOrden, lineaCalculable, validarOrden } from '../ordenes'
import { useCalculoOrden, useOrdenParaEditar } from '../hooks/useOrdenes'
import '../../almacen/inventario.css'
import '../compras.css'

const RUTA = '/compras/ordenes'
const SIN_ERRORES = {}
const VACIO = []
/** Qué dice el servidor → en qué campo del formulario se muestra. */
const CAMPO_DEL_SERVIDOR = { proveedor: 'proveedor', almacen: 'almacen', fecha_emision: 'fecha', fecha_entrega: 'entrega', tipo_cambio: 'tipoCambio', plazo_dias: 'plazo' }

function Formulario({ inicial, orden }) {
  const navegar = useNavigate()
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [b, setB] = useState(inicial)
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const [delServidor, setDelServidor] = useState(SIN_ERRORES)
  const [saliendo, setSaliendo] = useState(false)
  const editando = Boolean(orden)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const afectaciones = useOpciones('/mantenimiento/afectaciones-igv/', { aplica_compras: '1' }).data ?? VACIO
  const almacen = b.almacen || String(almacenes.data?.[0]?.id ?? '')

  const poner = useCallback((campo, valor) => setB((previo) => ({ ...previo, [campo]: valor })), [])
  // `poner` recibe un valor; para las líneas hace falta la función del valor anterior.
  const cambiarLineas = useCallback((f) => setB((previo) => ({ ...previo, lineas: typeof f === 'function' ? f(previo.lineas) : f })), [])

  const cuerpoPrevio = armarCuerpoOrden(b, { empresa: empresaActivaId, almacen }, { previa: true })
  const previaActiva = Boolean(b.proveedor && almacen && cuerpoPrevio.lineas.length > 0)
  const calculo = useCalculoOrden(cuerpoPrevio, previaActiva)
  const resultados = useMemo(() => {
    const ids = b.lineas.filter(lineaCalculable).map((l) => l.id)
    const filas = calculo.datos?.lineas
    if (!filas || filas.length !== ids.length) return {}
    return Object.fromEntries(filas.map((fila, i) => [ids[i], fila]))
  }, [calculo.datos, b.lineas])

  const validacion = validarOrden(b, almacen)
  const cuerpo = armarCuerpoOrden(b, { empresa: empresaActivaId, almacen })
  const clave = useClaveIdempotente(cuerpo)
  const e = { ...(intento ? validacion.campos : SIN_ERRORES), ...delServidor }

  const guardar = useMutacion({
    mutationFn: ({ datos, llave }) =>
      editando
        ? api.post(`/compras/ordenes/${orden.id}/editar/`, datos, { timeout: 30_000 }).then((r) => r.data)
        : api.post('/compras/ordenes/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras']],
    exito: (o) => (editando ? `Orden ${o.codigo} actualizada.` : `Orden ${o.codigo} guardada como borrador.`),
    alExito: (o) => navegar(`${RUTA}/${o.id}`, { replace: true }),
    avisarError: false,
  })
  const enviando = guardar.isPending
  const sinGuardar = Boolean(b.proveedor) || b.lineas.length > 0

  const enviar = () => {
    if (enviando) return
    setIntento(true)
    setGeneral('')
    setDelServidor(SIN_ERRORES)
    if (!validacion.valido) {
      setTimeout(() => {
        const primero = document.querySelector('.compra-principal [aria-invalid="true"]')
        primero?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        primero?.focus({ preventScroll: true })
      }, 0)
      return
    }
    guardar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const campos = erroresDeCampo(error)
          const mapeados = {}
          const otros = []
          for (const [campo, mensaje] of Object.entries(campos)) {
            if (CAMPO_DEL_SERVIDOR[campo]) mapeados[CAMPO_DEL_SERVIDOR[campo]] = mensaje
            else otros.push(mensaje)
          }
          setDelServidor(mapeados)
          setGeneral(otros.length ? otros.join(' ') : Object.keys(campos).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }
  const cancelar = () => (sinGuardar && !editando ? setSaliendo(true) : navegar(editando ? `${RUTA}/${orden.id}` : RUTA))
  const unidades = b.lineas.reduce((s, l) => s + (Number(String(l.cantidad).replace(',', '.')) || 0), 0)

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={editando ? `${RUTA}/${orden.id}` : RUTA} texto={editando ? 'Volver a la orden' : 'Volver a Órdenes de compra'} />
      <CabeceraListado icono="checklist" titulo={editando ? `Editar ${orden.codigo}` : 'Nueva orden de compra'} descripcion={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. Se guarda como borrador; la emites desde su ficha.`} />
      {editando && orden.motivo_rechazo && (
        <p role="status" className="modal-aviso">
          <strong>Fue rechazada:</strong> {orden.motivo_rechazo}
        </p>
      )}
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="handshake" titulo="Proveedor y condiciones" descripcion="A quién se le pide, a dónde llega y cómo se pactó.">
            <ProveedorCompra proveedor={b.proveedor} onElegir={(p) => poner('proveedor', p)} error={e.proveedor} disabled={enviando} />
            <DatosOrden b={b} poner={poner} almacenes={almacenes} almacen={almacen} e={e} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Productos" descripcion="Lo que se le pide al proveedor y a qué precio. El IGV se propone solo según el producto y el proveedor.">
            <LineasOrden lineas={b.lineas} onLineas={cambiarLineas} resultados={resultados} moneda={b.moneda} afectaciones={afectaciones} errores={intento ? validacion.porLinea : SIN_ERRORES} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Observación">
            <Campo etiqueta="Nota para el proveedor o interna" error={e.observacion} contador={{ actual: b.observacion.length, max: 250 }}>
              {(p) => <textarea {...p} rows={2} maxLength={250} placeholder="Opcional" value={b.observacion} disabled={enviando} onChange={(ev) => poner('observacion', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>
        </div>

        <ResumenOrden
          calculo={calculo.datos}
          calculando={calculo.calculando}
          errorCalculo={calculo.error}
          moneda={b.moneda}
          faltan={intento ? validacion.faltan : VACIO}
          general={general}
          enviando={enviando}
          productos={b.lineas.length}
          unidades={unidades}
          textoGuardar={editando ? 'Guardar cambios' : 'Guardar orden'}
          onGuardar={enviar}
          onCancelar={cancelar}
        />
      </div>
      {saliendo && <ConfirmarModal titulo="Salir sin guardar" mensaje="Se perderá lo que escribiste en esta orden. ¿Quieres salir?" textoConfirmar="Salir" onConfirmar={() => navegar(RUTA)} onCerrar={() => setSaliendo(false)} />}
    </main>
  )
}

/** Nueva orden, o edición de una en borrador (si la dirección trae el número de la orden). */
export default function OrdenCompraFormPage() {
  const { id } = useParams()
  const { empresaActivaId } = useEmpresas()
  const carga = useOrdenParaEditar(id)
  if (!empresaActivaId) return <p style={{ padding: 24 }}>Elige una empresa para trabajar con órdenes de compra.</p>
  if (!id) return <Formulario key={empresaActivaId} inicial={borradorOrden()} orden={null} />
  return (
    <EstadoConsulta consulta={carga.consulta} hayDatos={Boolean(carga.borrador)} vacio="La orden no existe.">
      {carga.borrador && carga.orden.estado !== 'BORRADOR' && (
        <main className="listado">
          <BotonVolver ruta={`${RUTA}/${id}`} texto="Volver a la orden" />
          <p className="estado-vacio">Esta orden ya no está en borrador: ábrela y usa «Reabrir» si necesitas cambiarla.</p>
        </main>
      )}
      {carga.borrador && carga.orden.estado === 'BORRADOR' && <Formulario key={carga.orden.id} inicial={carga.borrador} orden={carga.orden} />}
    </EstadoConsulta>
  )
}
