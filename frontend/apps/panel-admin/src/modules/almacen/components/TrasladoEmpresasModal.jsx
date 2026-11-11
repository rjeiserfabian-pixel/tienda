import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../hooks/useClaveIdempotente'
import { useOpciones } from '../hooks/useOpciones'
import { hoyIso, nuevaLinea, numerosDe, paraServidor, serieValida } from '../inventario'
import { aNumero } from '../utilidades'
import '../inventario.css'
import LineasMovimiento from './LineasMovimiento'

const nombreDe = (e) => e?.nombre_comercial || e?.razon_social || ''

function cuerpoDe(f, lineas) {
  return {
    empresa: Number(f.entrega) || null,
    almacen_origen: Number(f.origen) || null,
    almacen_destino: Number(f.destino) || null,
    fecha: f.fecha,
    observacion: f.observacion.trim(),
    lineas: lineas.map((l) => {
      const series = l.producto?.lleva_serie ? numerosDe(l.series) : []
      return {
        producto: l.producto?.id ?? null,
        cantidad: l.producto?.lleva_serie ? String(series.length) : paraServidor(l.cantidad),
        ...(l.producto?.lleva_serie ? { series } : {}),
      }
    }),
  }
}

function revisar(f, lineas) {
  const campos = {}
  const porLinea = {}
  if (!f.entrega || !f.recibe) campos.recibe = 'Elija las dos empresas.'
  if (!f.origen) campos.origen = 'Elija el almacén de salida.'
  if (!f.destino) campos.destino = 'Elija el almacén de llegada.'
  if (!f.fecha) campos.fecha = 'Indique la fecha.'
  else if (f.fecha > hoyIso()) campos.fecha = 'La fecha no puede ser futura.'
  for (const l of lineas) {
    const e = {}
    if (!l.producto) e.producto = 'Elija el producto.'
    if (l.producto?.lleva_serie) {
      const series = numerosDe(l.series)
      const mala = series.find((s) => !serieValida(s))
      if (!series.length) e.series = 'Escriba las series o IMEI que se trasladan.'
      else if (mala) e.series = `«${mala}» no es válida.`
      else if (new Set(series).size !== series.length) e.series = 'Hay series repetidas.'
    } else {
      const cantidad = aNumero(l.cantidad)
      if (cantidad === null || cantidad <= 0) e.cantidad = 'Mayor que cero.'
      else if (!/^\d+([.,]\d{1,3})?$/.test(String(l.cantidad).trim())) e.cantidad = 'Hasta 3 decimales.'
    }
    if (Object.keys(e).length) porLinea[l.id] = e
  }
  return { campos, porLinea, valido: !Object.keys(campos).length && !Object.keys(porLinea).length }
}

/** Lo que se ve al terminar: la mercadería ya está en la otra empresa y, si va a viajar, se ofrece la guía. */
function TrasladoHecho({ hecho, onCerrar }) {
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const puedeGuia = tiene('VENTAS.GUIA_REMISION') && hecho.movimiento
  return (
    <Modal titulo="Traslado registrado" subtitulo={`N° ${String(hecho.numero).padStart(6, '0')} · de ${hecho.entrega} a ${hecho.recibe}`} onCerrar={onCerrar} ancho={560}>
      <p role="status" className="modal-aviso">
        La mercadería ya está en «{hecho.almacen_destino}» de {hecho.recibe}. {hecho.recibe} le debe a {hecho.entrega} el costo (S/ {hecho.total_costo}); se liquida junto con las ventas internas.
        {puedeGuia ? ' Si la mercadería va a viajar a otro local, crea ahora su guía de remisión; en el mismo local no hace falta.' : ''}
      </p>
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          Listo
        </button>
        {puedeGuia && (
          <button type="button" className="primario" onClick={() => navegar(`/ventas/guias-remision/nueva?traspaso=${hecho.movimiento}`)}>
            <Icono nombre="truck" tam={18} /> Crear guía de remisión
          </button>
        )}
      </div>
    </Modal>
  )
}

/** Pasa mercadería de una empresa a la otra sin vender: sale al costo promedio y la que recibe queda debiéndolo. */
export default function TrasladoEmpresasModal({ onCerrar }) {
  const { empresas, empresaActivaId } = useEmpresas()
  const [hecho, setHecho] = useState(null)
  const otra = empresas.find((e) => e.id !== empresaActivaId)
  const [f, setF] = useState({
    entrega: String(empresaActivaId ?? ''),
    recibe: String(otra?.id ?? ''),
    origen: '',
    destino: '',
    fecha: hoyIso(),
    observacion: '',
  })
  const [lineas, setLineas] = useState(() => [nuevaLinea()])
  const [errores, setErrores] = useState({ campos: {}, porLinea: {} })
  const [general, setGeneral] = useState('')

  const almacenesEntrega = useOpciones('/mantenimiento/almacenes/', { empresa: f.entrega }, { enabled: Boolean(f.entrega) })
  const almacenesRecibe = useOpciones('/mantenimiento/almacenes/', { empresa: f.recibe }, { enabled: Boolean(f.recibe) })
  const deEntrega = almacenesEntrega.data ?? []
  const deRecibe = almacenesRecibe.data ?? []
  const origen = f.origen || String(deEntrega[0]?.id ?? '')
  const destino = f.destino || String(deRecibe[0]?.id ?? '')
  const formulario = useMemo(() => ({ ...f, origen, destino }), [f, origen, destino])
  const cuerpo = useMemo(() => cuerpoDe(formulario, lineas), [formulario, lineas])
  const clave = useClaveIdempotente(cuerpo)

  const trasladar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/ventas/traslados-empresas/', datos, { params: { empresa: datos.empresa }, headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['almacen'], ['movimientos'], ['stock'], ['kardex'], ['series'], ['ventas']],
    exito: 'Traslado registrado.',
    alExito: setHecho,
    avisarError: false,
  })

  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  // Al cambiar una empresa se borra el almacén elegido (era de la otra) y, si coincide, se cambia la otra.
  const elegirEmpresa = (campo, valor) =>
    setF((previo) => {
      const siguiente = { ...previo, [campo]: valor, [campo === 'entrega' ? 'origen' : 'destino']: '' }
      const contraria = campo === 'entrega' ? 'recibe' : 'entrega'
      if (siguiente[contraria] === valor) {
        siguiente[contraria] = String(empresas.find((e) => String(e.id) !== valor)?.id ?? '')
        siguiente[campo === 'entrega' ? 'destino' : 'origen'] = ''
      }
      return siguiente
    })

  const enviar = (evento) => {
    evento.preventDefault()
    if (trasladar.isPending) return
    const revision = revisar(formulario, lineas)
    setErrores(revision)
    setGeneral('')
    if (!revision.valido) return
    trasladar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores({ campos: delServidor, porLinea: {} })
          setGeneral(Object.keys(delServidor).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  if (hecho) return <TrasladoHecho hecho={hecho} onCerrar={onCerrar} />

  const e = errores.campos
  const nombreEntrega = nombreDe(empresas.find((x) => String(x.id) === f.entrega))
  const nombreRecibe = nombreDe(empresas.find((x) => String(x.id) === f.recibe))
  return (
    <Modal titulo="Traslado entre empresas" subtitulo="Pasa mercadería de una empresa a la otra sin vender. Sale al costo y la que recibe queda debiéndolo." onCerrar={onCerrar} ancho={940}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={trasladar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="fila-campos">
            <Campo etiqueta="Entrega la mercadería" tipo="select" requerido error={e.empresa}>
              {(p) => (
                <select {...p} value={f.entrega} onChange={(ev) => elegirEmpresa('entrega', ev.target.value)}>
                  {empresas.map((x) => (
                    <option key={x.id} value={x.id}>{nombreDe(x)}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Sale del almacén" tipo="select" requerido error={e.almacen_origen || e.origen}>
              {(p) => (
                <select {...p} value={origen} onChange={(ev) => poner('origen', ev.target.value)}>
                  {deEntrega.map((a) => (
                    <option key={a.id} value={a.id}>{a.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
          </div>
          <div className="fila-campos">
            <Campo etiqueta="Recibe la mercadería" tipo="select" requerido error={e.recibe}>
              {(p) => (
                <select {...p} value={f.recibe} onChange={(ev) => elegirEmpresa('recibe', ev.target.value)}>
                  {empresas.map((x) => (
                    <option key={x.id} value={x.id}>{nombreDe(x)}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Llega al almacén" tipo="select" requerido error={e.almacen_destino || e.destino}>
              {(p) => (
                <select {...p} value={destino} onChange={(ev) => poner('destino', ev.target.value)}>
                  {deRecibe.map((a) => (
                    <option key={a.id} value={a.id}>{a.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Fecha" icono="calendario" requerido error={e.fecha}>
              {(p) => <input {...p} type="date" max={hoyIso()} value={f.fecha} onChange={(ev) => poner('fecha', ev.target.value)} />}
            </Campo>
          </div>

          <LineasMovimiento lineas={lineas} onCambiar={setLineas} tipo="SALIDA" conPrecio={false} errores={errores.porLinea} disabled={trasladar.isPending} />
          {e.lineas && <p role="alert" className="campo-error">{e.lineas}</p>}

          <Campo etiqueta="Observación" error={e.observacion}>
            {(p) => <input {...p} maxLength={200} placeholder="Opcional. Ej. Reposición de la tienda" value={f.observacion} onChange={(ev) => poner('observacion', ev.target.value)} />}
          </Campo>
          {f.entrega && f.recibe && <p className="campo-ayuda">{nombreRecibe} le deberá a {nombreEntrega} lo que cueste la mercadería. Se liquida al cerrar la caja, junto con las ventas internas.</p>}
        </fieldset>

        {general && <p role="alert" className="campo-error">{general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={trasladar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={trasladar.isPending || empresas.length < 2}>
            {trasladar.isPending ? 'Trasladando…' : 'Registrar traslado'}
          </button>
        </div>
        {empresas.length < 2 && <p className="campo-ayuda">Necesitas acceso a las dos empresas para trasladar mercadería entre ellas.</p>}
      </form>
    </Modal>
  )
}
