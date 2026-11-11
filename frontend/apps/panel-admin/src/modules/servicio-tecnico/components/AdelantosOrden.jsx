import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta, paraServidor } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { useImpresionDocumento } from '../../ventas/hooks/useImpresionDocumento'
import { useConfiguracionServicio } from '../hooks/useConfiguracionServicio'
import { ReciboAdelantoA4, ReciboAdelantoTicket } from './ReciboAdelanto'

const VACIO = []
const ESTADOS_DE_DEVOLUCION = ['NO_APROBADO', 'SIN_SOLUCION', 'ABANDONADO']

/** Recibe un adelanto: da el recibo interno y el dinero entra a la caja. */
function RecibirModal({ orden, onCerrar }) {
  const medios = useConfiguracionServicio(orden.empresa).data?.medios_pago ?? VACIO
  const [f, setF] = useState({ monto: '', medio: '', referencia: '' })
  const [error, setError] = useState('')
  const medio = medios.find((m) => String(m.id) === String(f.medio)) ?? medios.find((m) => m.tipo === 'EFECTIVO') ?? medios[0]
  const tope = orden.adelantos.tope
  const libre = tope === null ? null : Math.max(Number(tope) - Number(orden.adelantos.resumen.disponible), 0)

  const recibir = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/adelantos/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio'], ['caja']],
    exito: 'Adelanto recibido.',
    alExito: onCerrar,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (recibir.isPending) return
    const monto = Number(paraServidor(f.monto))
    if (!Number.isFinite(monto) || monto <= 0) return setError('Escribe el monto del adelanto.')
    if (libre !== null && monto > libre) return setError(`Solo se pueden recibir hasta ${dinero(libre)} más (el total que cobra esta empresa).`)
    if (!medio) return setError('Elige el método de pago.')
    if (medio.requiere_referencia && !f.referencia.trim()) return setError(`Indica el número de operación del pago con ${medio.nombre}.`)
    setError('')
    recibir.mutate({ monto: monto.toFixed(2), medio_pago: medio.id, ...(f.referencia.trim() ? { referencia: f.referencia.trim() } : {}) }, { onError: (e) => setError(erroresDeCampo(e).monto || mensajeDeError(e)) })
  }
  return (
    <Modal titulo="Recibir un adelanto" subtitulo={`Orden ${orden.codigo} · ${orden.cliente_nombre}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p className="celda-suave">Se le da un recibo interno y el dinero entra a la caja. Al entregar el equipo se descuenta de lo que pague.{libre !== null ? ` Puedes recibir hasta ${dinero(libre)} más.` : ''}</p>
        <Campo etiqueta="Monto (S/)" requerido error={error}>
          {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.monto} disabled={recibir.isPending} onChange={(e) => setF({ ...f, monto: e.target.value })} />}
        </Campo>
        <Campo etiqueta="Método de pago" tipo="select">
          {(p) => (
            <select {...p} value={medio?.id ?? ''} disabled={recibir.isPending} onChange={(e) => setF({ ...f, medio: e.target.value, referencia: '' })}>
              {medios.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nombre}
                </option>
              ))}
            </select>
          )}
        </Campo>
        {medio?.requiere_referencia && (
          <Campo etiqueta="N° de operación" requerido>
            {(p) => <input {...p} maxLength={60} value={f.referencia} disabled={recibir.isPending} onChange={(e) => setF({ ...f, referencia: e.target.value })} />}
          </Campo>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={recibir.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={recibir.isPending}>
            {recibir.isPending ? 'Guardando…' : 'Recibir adelanto'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Devolver el adelanto al cliente, o anular el recibo si se emitió por error. */
function AccionModal({ orden, recibo, accion, onCerrar }) {
  const devolver = accion === 'devolver'
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const ejecutar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/adelantos/${accion}/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio'], ['caja']],
    exito: devolver ? 'Adelanto devuelto al cliente.' : 'Recibo anulado.',
    alExito: onCerrar,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (ejecutar.isPending) return
    if (motivo.trim().length < 5) return setError('Explica el motivo con unas palabras.')
    setError('')
    ejecutar.mutate({ adelanto: recibo.id, motivo: motivo.trim() }, { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }
  return (
    <Modal titulo={devolver ? `Devolver ${recibo.codigo}` : `Anular ${recibo.codigo}`} subtitulo={`${dinero(recibo.monto)} · ${recibo.medio_nombre}`} onCerrar={onCerrar} ancho={500}>
      <form onSubmit={enviar} noValidate>
        <p>{devolver ? 'El dinero sale de la caja por donde entró y se le devuelve al cliente. No lleva nota de crédito: nunca se facturó.' : 'Úsalo solo si el recibo se emitió por error: el ingreso a la caja se deshace y no sale dinero.'}</p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={2} maxLength={250} value={motivo} disabled={ejecutar.isPending} onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={ejecutar.isPending}>
            Cancelar
          </button>
          <button type="submit" className={devolver ? 'primario' : 'peligro'} disabled={ejecutar.isPending}>
            {ejecutar.isPending ? 'Guardando…' : devolver ? 'Devolver el dinero' : 'Anular recibo'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Los adelantos del cliente: recibos internos, lo que falta devolver y lo que se descontó al facturar. */
export default function AdelantosOrden({ orden: o }) {
  const [recibiendo, setRecibiendo] = useState(false)
  const [accion, setAccion] = useState(null) // { recibo, accion }
  const [impreso, setImpreso] = useState(null)
  const { imprimir, portal } = useImpresionDocumento(
    impreso
      ? { tipo: 'recibo-adelanto', titulo: `Recibo de adelanto ${impreso.codigo}`, subtitulo: o.cliente_nombre, formatos: { A4: <ReciboAdelantoA4 orden={o} recibo={impreso} />, TICKET: <ReciboAdelantoTicket orden={o} recibo={impreso} /> } }
      : null,
  )
  const a = o.adelantos
  const r = a.resumen
  if (!o.permite.adelantos && a.recibos.length === 0) return null
  const porDevolver = Number(r.disponible)
  const cerradaSinCobro = ESTADOS_DE_DEVOLUCION.includes(o.estado) || (o.estado === 'LISTO_ENTREGA' && o.entrega && !o.entrega.cobra)

  const imprimirRecibo = (recibo) => {
    setImpreso(recibo)
    setTimeout(imprimir, 0)
  }

  return (
    <PanelTarjeta
      icono="wallet"
      titulo="Adelantos"
      descripcion="Lo que el cliente deja por adelantado. Se descuenta al facturar el servicio."
      acciones={
        o.permite.adelantos ? (
          <button type="button" className="boton-cabecera" onClick={() => setRecibiendo(true)}>
            Recibir adelanto
          </button>
        ) : undefined
      }
    >
      {porDevolver > 0 && cerradaSinCobro && (
        <p role="alert" className="campo-error">
          El cliente tiene {dinero(porDevolver)} de adelanto por devolver: el servicio no se va a cobrar. Devuélvelo antes de entregar el equipo.
        </p>
      )}
      {a.recibos.length === 0 ? (
        <p className="estado-vacio">El cliente no dejó adelanto.</p>
      ) : (
        <>
          <dl className="servicio-cabecera-ficha">
            <div className="gasto-dato">
              <dt>Por descontar</dt>
              <dd>{dinero(r.disponible)}</dd>
            </div>
            <div className="gasto-dato">
              <dt>Ya descontado</dt>
              <dd>{dinero(r.aplicado)}</dd>
            </div>
            <div className="gasto-dato">
              <dt>Devuelto</dt>
              <dd>{dinero(r.devuelto)}</dd>
            </div>
          </dl>
          <ul className="voucher-lista">
            {a.recibos.map((x) => (
              <li key={x.id} className="servicio-aviso-item">
                <strong>
                  {x.codigo} · {dinero(x.monto)} · {x.medio_nombre}
                </strong>
                <span>
                  <span className="pildora" data-tono={x.aplicado ? 'verde' : x.disponible ? 'ambar' : 'gris'}>
                    {x.estado_nombre}
                  </span>
                  {x.comprobante && ` ${x.comprobante}`}
                </span>
                <span className="sub-texto">
                  {fechaCorta(x.fecha)}
                  {x.referencia ? ` · Operación ${x.referencia}` : ''}
                  {x.devolucion_motivo ? ` · ${x.devolucion_motivo}` : ''}
                  {x.anulacion_motivo ? ` · ${x.anulacion_motivo}` : ''}
                </span>
                <span className="servicio-pasos">
                  {x.estado !== 'ANULADO' && (
                    <button type="button" className="boton-cabecera" onClick={() => imprimirRecibo(x)}>
                      <Icono nombre="documento" tam={17} /> Imprimir recibo
                    </button>
                  )}
                  {o.permite.adelantos && x.disponible && (
                    <>
                      <button type="button" className="boton-cabecera" onClick={() => setAccion({ recibo: x, accion: 'devolver' })}>
                        Devolver
                      </button>
                      <button type="button" className="boton-cabecera" onClick={() => setAccion({ recibo: x, accion: 'anular' })}>
                        Anular
                      </button>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {recibiendo && <RecibirModal orden={o} onCerrar={() => setRecibiendo(false)} />}
      {accion && <AccionModal orden={o} recibo={accion.recibo} accion={accion.accion} onCerrar={() => setAccion(null)} />}
      {portal}
    </PanelTarjeta>
  )
}
