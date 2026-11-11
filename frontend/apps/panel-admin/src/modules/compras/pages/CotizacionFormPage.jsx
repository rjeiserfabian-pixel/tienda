import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { hoyIso } from '../../almacen/inventario'
import LineasCotizacion from '../components/LineasCotizacion'
import ProveedoresElegidos from '../components/ProveedoresElegidos'
import { armarCuerpoCotizacion, borradorCotizacion, sePuedeEditar, validarCotizacion } from '../cotizaciones'
import { useCotizacionParaEditar } from '../hooks/useCotizaciones'
import '../../almacen/inventario.css'
import '../compras.css'
import '../cotizaciones.css'

const RUTA = '/compras/cotizaciones'
const SIN_ERRORES = {}
/** Qué dice el servidor → en qué campo del formulario se muestra. */
const CAMPO_DEL_SERVIDOR = { almacen: 'almacen', fecha: 'fecha', fecha_limite: 'fechaLimite', proveedores: 'proveedores' }

function Formulario({ inicial, cotizacion }) {
  const navegar = useNavigate()
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [b, setB] = useState(inicial)
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const [delServidor, setDelServidor] = useState(SIN_ERRORES)
  const [saliendo, setSaliendo] = useState(false)
  const editando = Boolean(cotizacion)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const almacen = b.almacen || String(almacenes.data?.[0]?.id ?? '')

  const poner = useCallback((campo, valor) => setB((previo) => ({ ...previo, [campo]: valor })), [])
  // Las listas reciben la función del valor anterior para no pisar lo que se escribe en otra línea.
  const cambiarLineas = useCallback((f) => setB((previo) => ({ ...previo, lineas: typeof f === 'function' ? f(previo.lineas) : f })), [])
  const cambiarProveedores = useCallback((f) => setB((previo) => ({ ...previo, proveedores: typeof f === 'function' ? f(previo.proveedores) : f })), [])

  const validacion = validarCotizacion(b, almacen)
  const cuerpo = armarCuerpoCotizacion(b, { empresa: editando ? null : empresaActivaId, almacen })
  const clave = useClaveIdempotente(cuerpo)
  const e = { ...(intento ? validacion.campos : SIN_ERRORES), ...delServidor }

  const guardar = useMutacion({
    mutationFn: ({ datos, llave }) =>
      editando
        ? api.post(`/compras/cotizaciones/${cotizacion.id}/editar/`, datos, { timeout: 30_000 }).then((r) => r.data)
        : api.post('/compras/cotizaciones/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras']],
    exito: (c) => (editando ? `Cotización ${c.codigo} actualizada.` : `Cotización ${c.codigo} guardada como borrador.`),
    alExito: (c) => navegar(`${RUTA}/${c.id}`, { replace: true }),
    avisarError: false,
  })
  const enviando = guardar.isPending
  const sinGuardar = b.proveedores.length > 0 || b.lineas.length > 0

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
  const cancelar = () => (sinGuardar && !editando ? setSaliendo(true) : navegar(editando ? `${RUTA}/${cotizacion.id}` : RUTA))
  const unidades = b.lineas.reduce((s, l) => s + (Number(String(l.cantidad).replace(',', '.')) || 0), 0)

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={editando ? `${RUTA}/${cotizacion.id}` : RUTA} texto={editando ? 'Volver a la cotización' : 'Volver a Cotizaciones'} />
      <CabeceraListado icono="cotizacion" titulo={editando ? `Editar ${cotizacion.codigo}` : 'Nueva cotización'} descripcion={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. Se guarda como borrador: después registras lo que respondió cada proveedor.`} />
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="documento" titulo="Datos de la cotización" descripcion="Todos los proveedores cotizan en la misma moneda y con la misma base de IGV, para que la comparación sea justa.">
            <div className="fila-campos">
              <Campo etiqueta="Almacén de destino" tipo="select" requerido error={e.almacen}>
                {(p) => (
                  <select {...p} value={almacen} disabled={enviando} onChange={(ev) => poner('almacen', ev.target.value)}>
                    {almacenes.isLoading && <option value="">Cargando…</option>}
                    {(almacenes.data ?? []).map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Fecha" icono="calendario" requerido error={e.fecha}>
                {(p) => <input {...p} type="date" max={hoyIso()} value={b.fecha} disabled={enviando} onChange={(ev) => poner('fecha', ev.target.value)} />}
              </Campo>
              <Campo etiqueta="Responder hasta" icono="calendario" error={e.fechaLimite} ayuda="Opcional. Hasta cuándo esperas respuestas.">
                {(p) => <input {...p} type="date" min={b.fecha} value={b.fechaLimite} disabled={enviando} onChange={(ev) => poner('fechaLimite', ev.target.value)} />}
              </Campo>
            </div>
            <div className="fila-campos">
              <Campo etiqueta="Moneda" tipo="select">
                {(p) => (
                  <select {...p} value={b.moneda} disabled={enviando} onChange={(ev) => poner('moneda', ev.target.value)}>
                    <option value="PEN">Soles</option>
                    <option value="USD">Dólares</option>
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Los precios" tipo="select">
                {(p) => (
                  <select {...p} value={b.incluyeIgv ? 'CON' : 'SIN'} disabled={enviando} onChange={(ev) => poner('incluyeIgv', ev.target.value === 'CON')}>
                    <option value="SIN">No incluyen IGV</option>
                    <option value="CON">Incluyen IGV</option>
                  </select>
                )}
              </Campo>
            </div>
            <ProveedoresElegidos proveedores={b.proveedores} onProveedores={cambiarProveedores} error={e.proveedores} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Productos a cotizar" descripcion="Lo que necesitas comprar y en qué cantidad. Los precios los darán los proveedores.">
            <LineasCotizacion lineas={b.lineas} onLineas={cambiarLineas} errores={intento ? validacion.porLinea : SIN_ERRORES} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Observación">
            <Campo etiqueta="Nota para los proveedores o interna" error={e.observacion} contador={{ actual: b.observacion.length, max: 250 }}>
              {(p) => <textarea {...p} rows={2} maxLength={250} placeholder="Opcional" value={b.observacion} disabled={enviando} onChange={(ev) => poner('observacion', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>
        </div>

        <aside className="compra-resumen" aria-label="Resumen de la cotización">
          <h3>Resumen</h3>
          <p className="celda-suave">
            {b.lineas.length} {b.lineas.length === 1 ? 'producto' : 'productos'} · {unidades} {unidades === 1 ? 'unidad' : 'unidades'}
          </p>
          <p className="celda-suave">
            {b.proveedores.length} {b.proveedores.length === 1 ? 'proveedor' : 'proveedores'} a cotizar
          </p>
          {intento && validacion.faltan.length > 0 && (
            <div className="compra-faltan">
              <strong>Para guardar falta:</strong>
              <ul>
                {validacion.faltan.map((texto) => (
                  <li key={texto}>{texto}</li>
                ))}
              </ul>
            </div>
          )}
          {general && (
            <p role="alert" className="campo-error">
              {general}
            </p>
          )}
          <button type="button" className="primario compra-registrar" disabled={enviando} onClick={enviar}>
            <Icono nombre="cotizacion" tam={20} /> {enviando ? 'Guardando…' : editando ? 'Guardar cambios' : 'Guardar cotización'}
          </button>
          <button type="button" disabled={enviando} onClick={cancelar}>
            Cancelar
          </button>
        </aside>
      </div>
      {saliendo && <ConfirmarModal titulo="Salir sin guardar" mensaje="Se perderá lo que escribiste en esta cotización. ¿Quieres salir?" textoConfirmar="Salir" onConfirmar={() => navegar(RUTA)} onCerrar={() => setSaliendo(false)} />}
    </main>
  )
}

/** Nueva cotización, o edición de una en borrador (si la dirección trae el número). */
export default function CotizacionFormPage() {
  const { id } = useParams()
  const { empresaActivaId } = useEmpresas()
  const carga = useCotizacionParaEditar(id)
  if (!empresaActivaId) return <p style={{ padding: 24 }}>Elige una empresa para trabajar con cotizaciones.</p>
  if (!id) return <Formulario key={empresaActivaId} inicial={borradorCotizacion()} cotizacion={null} />
  return (
    <EstadoConsulta consulta={carga.consulta} hayDatos={Boolean(carga.borrador)} vacio="La cotización no existe.">
      {carga.borrador && !sePuedeEditar(carga.cotizacion) && (
        <main className="listado">
          <BotonVolver ruta={`${RUTA}/${id}`} texto="Volver a la cotización" />
          <p className="estado-vacio">Esta cotización ya no se puede editar (ya tiene respuestas con precios o salió de borrador). Anúlala y crea otra si necesitas cambiarla.</p>
        </main>
      )}
      {carga.borrador && sePuedeEditar(carga.cotizacion) && <Formulario key={carga.cotizacion.id} inicial={carga.borrador} cotizacion={carga.cotizacion} />}
    </EstadoConsulta>
  )
}
