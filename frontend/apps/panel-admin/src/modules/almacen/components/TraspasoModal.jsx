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

function cuerpoDe(f, lineas, empresa) {
  return {
    empresa,
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
  if (!f.origen) campos.origen = 'Elija el almacén de origen.'
  if (!f.destino) campos.destino = 'Elija el almacén de destino.'
  if (f.origen && f.origen === f.destino) campos.destino = 'Debe ser distinto del origen.'
  if (!f.fecha) campos.fecha = 'Indique la fecha.'
  else if (f.fecha > hoyIso()) campos.fecha = 'La fecha no puede ser futura.'
  for (const l of lineas) {
    const e = {}
    if (!l.producto) e.producto = 'Elija el producto.'
    if (l.producto?.lleva_serie) {
      const series = numerosDe(l.series)
      const mala = series.find((s) => !serieValida(s))
      if (!series.length) e.series = 'Escriba las series o IMEI que se traspasan.'
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

/**
 * Lo que se ve al terminar un traspaso: avisa que la mercadería ya está en el almacén de destino y, a quien puede
 * emitir guías de remisión, le ofrece crear la del traspaso con sus datos (la guía no mueve stock).
 */
export function TraspasoHecho({ hecho: { salida, entrada }, onCerrar }) {
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const puedeGuia = tiene('VENTAS.GUIA_REMISION')
  return (
    <Modal titulo="Traspaso registrado" subtitulo={`N° ${String(salida.numero).padStart(6, '0')} · de ${salida.almacen_nombre} a ${entrada.almacen_nombre}`} onCerrar={onCerrar} ancho={560}>
      <p role="status" className="modal-aviso">
        La mercadería ya está en «{entrada.almacen_nombre}».{puedeGuia ? ' Si va a viajar, crea ahora su guía de remisión: se llena con los datos de este traspaso.' : ''}
      </p>
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          Listo
        </button>
        {puedeGuia && (
          <button type="button" className="primario" onClick={() => navegar(`/ventas/guias-remision/nueva?traspaso=${salida.id}`)}>
            <Icono nombre="truck" tam={18} /> Crear guía de remisión
          </button>
        )}
      </div>
    </Modal>
  )
}

/** Mueve mercadería entre dos almacenes de la misma empresa. El costo viaja con ella, sin precios. */
export default function TraspasoModal({ onCerrar }) {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [hecho, setHecho] = useState(null) // { salida, entrada } del traspaso recién registrado
  const [f, setF] = useState({ origen: '', destino: '', fecha: hoyIso(), observacion: '' })
  const [lineas, setLineas] = useState(() => [nuevaLinea()])
  const [errores, setErrores] = useState({ campos: {}, porLinea: {} })
  const [general, setGeneral] = useState('')

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId })
  const opciones = almacenes.data ?? []
  const origen = f.origen || String(opciones[0]?.id ?? '')
  const formulario = useMemo(() => ({ ...f, origen }), [f, origen])
  const cuerpo = useMemo(() => cuerpoDe(formulario, lineas, empresaActivaId), [formulario, lineas, empresaActivaId])
  const clave = useClaveIdempotente(cuerpo)

  const traspasar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/inventario/movimientos/traspaso/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['movimientos'], ['stock'], ['kardex'], ['series']],
    exito: 'Traspaso registrado.',
    alExito: setHecho,
    avisarError: false,
  })

  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (traspasar.isPending) return
    const revision = revisar(formulario, lineas)
    setErrores(revision)
    setGeneral('')
    if (!revision.valido) return
    traspasar.mutate(
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

  if (hecho) return <TraspasoHecho hecho={hecho} onCerrar={onCerrar} />

  const e = errores.campos
  return (
    <Modal titulo="Traspaso entre almacenes" subtitulo={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. El costo viaja con la mercadería; no se crea ni se pierde stock.`} onCerrar={onCerrar} ancho={940}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={traspasar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="fila-campos">
            <Campo etiqueta="Sale de" tipo="select" requerido error={e.almacen_origen || e.origen}>
              {(p) => (
                <select {...p} value={origen} onChange={(ev) => poner('origen', ev.target.value)}>
                  {opciones.map((a) => (
                    <option key={a.id} value={a.id}>{a.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Llega a" tipo="select" requerido error={e.almacen_destino || e.destino}>
              {(p) => (
                <select {...p} value={f.destino} onChange={(ev) => poner('destino', ev.target.value)}>
                  <option value="">Elegir almacén</option>
                  {opciones.filter((a) => String(a.id) !== origen).map((a) => (
                    <option key={a.id} value={a.id}>{a.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Fecha" icono="calendario" requerido error={e.fecha}>
              {(p) => <input {...p} type="date" max={hoyIso()} value={f.fecha} onChange={(ev) => poner('fecha', ev.target.value)} />}
            </Campo>
          </div>

          <LineasMovimiento lineas={lineas} onCambiar={setLineas} tipo="SALIDA" conPrecio={false} errores={errores.porLinea} disabled={traspasar.isPending} />
          {e.lineas && <p role="alert" className="campo-error">{e.lineas}</p>}

          <Campo etiqueta="Observación" error={e.observacion}>
            {(p) => <input {...p} maxLength={200} placeholder="Opcional. Ej. Reposición de la tienda" value={f.observacion} onChange={(ev) => poner('observacion', ev.target.value)} />}
          </Campo>
        </fieldset>

        {general && <p role="alert" className="campo-error">{general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={traspasar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={traspasar.isPending || opciones.length < 2}>
            {traspasar.isPending ? 'Traspasando…' : 'Registrar traspaso'}
          </button>
        </div>
        {opciones.length < 2 && !almacenes.isLoading && <p className="campo-ayuda">Necesitas al menos dos almacenes activos en la empresa para traspasar.</p>}
      </form>
    </Modal>
  )
}
