import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { useImpresionDocumento } from '../../ventas/hooks/useImpresionDocumento'
import { especificacionActa } from '../especificaciones'
import { fechaHora } from '../servicio'

/** Recibe de nuevo el equipo entregado, dentro de su garantía: nace una orden ligada, sin cobro. */
function ReingresoModal({ orden, onCerrar }) {
  const navegar = useNavigate()
  const [f, setF] = useState({ falla: '', estado: '' })
  const [error, setError] = useState('')
  const reingresar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/reingreso/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio']],
    exito: (nueva) => `Reingreso por garantía registrado: ${nueva.codigo}.`,
    alExito: (nueva) => navegar(`/servicio-tecnico/ordenes/${nueva.id}`),
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (reingresar.isPending) return
    if (f.falla.trim().length < 5) return setError('Describe la falla que reporta el cliente.')
    setError('')
    reingresar.mutate(
      { falla_reportada: f.falla.trim(), ...(f.estado.trim() ? { estado_fisico: f.estado.trim() } : {}) },
      { onError: (e) => setError(erroresDeCampo(e).falla_reportada || mensajeDeError(e)) },
    )
  }
  return (
    <Modal titulo="Reingreso por garantía" subtitulo={`${orden.codigo} · ${orden.equipo_descripcion}`} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <p>
          La garantía vence el {fechaCorta(orden.garantia.hasta)}. Se crea una orden nueva ligada a esta: el equipo pasa otra vez por diagnóstico y reparación, <strong>sin cobro</strong> al cliente.
        </p>
        <Campo etiqueta="Falla que reporta el cliente" requerido error={error} contador={{ actual: f.falla.length, max: 1000 }}>
          {(p) => <textarea {...p} rows={3} maxLength={1000} placeholder="Ej. Volvió a fallar el video." value={f.falla} disabled={reingresar.isPending} onChange={(e) => setF({ ...f, falla: e.target.value })} />}
        </Campo>
        <Campo etiqueta="Estado físico al recibirlo" contador={{ actual: f.estado.length, max: 1000 }} ayuda="Opcional: rayones, golpes, sellos rotos…">
          {(p) => <textarea {...p} rows={2} maxLength={1000} value={f.estado} disabled={reingresar.isPending} onChange={(e) => setF({ ...f, estado: e.target.value })} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={reingresar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={reingresar.isPending}>
            {reingresar.isPending ? 'Registrando…' : 'Registrar reingreso'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Cómo salió el equipo: quién lo recogió, la garantía que corre y el reingreso si falla de nuevo. */
export default function EntregaGarantiaOrden({ orden: o }) {
  const [reingresando, setReingresando] = useState(false)
  const { imprimir, portal } = useImpresionDocumento(especificacionActa(o))
  const g = o.garantia
  const entregada = o.estado === 'ENTREGADO'
  if (!entregada && !o.es_garantia && o.reingresos.length === 0) return null

  return (
    <PanelTarjeta
      icono="shield"
      titulo="Entrega y garantía"
      descripcion={entregada ? 'Cómo salió el equipo y qué garantía tiene.' : 'Esta orden está ligada a una garantía.'}
      acciones={
        <>
          {entregada && (
            <button type="button" className="boton-cabecera" onClick={imprimir}>
              <Icono nombre="documento" tam={18} /> Imprimir acta
            </button>
          )}
          {o.permite.reingreso && (
            <button type="button" className="primario boton-cabecera" onClick={() => setReingresando(true)}>
              Reingreso por garantía
            </button>
          )}
        </>
      }
    >
      {o.es_garantia && (
        <p role="status" className="compra-aviso">
          Reingreso por garantía de <Link to={`/servicio-tecnico/ordenes/${o.reingreso_de}`}>{o.reingreso_de_codigo}</Link>: no se cobra.
        </p>
      )}
      {entregada && (
        <dl className="servicio-cabecera-ficha">
          <div className="gasto-dato">
            <dt>Entregado</dt>
            <dd>{fechaHora(o.fecha_entrega)}</dd>
          </div>
          <div className="gasto-dato">
            <dt>Recogió</dt>
            <dd>
              {o.recogio_nombre}
              <span className="sub-texto">{o.recogio_es_titular ? 'El titular' : `Otra persona · DNI ${o.recogio_documento}`}</span>
            </dd>
          </div>
          <div className="gasto-dato">
            <dt>Garantía</dt>
            <dd>
              {g.dias === 0 ? (
                'Sin garantía'
              ) : (
                <>
                  <span className="pildora" data-tono={g.vigente ? 'verde' : 'gris'}>
                    {g.vigente ? 'Vigente' : 'Vencida'}
                  </span>{' '}
                  {g.dias} días, hasta el {fechaCorta(g.hasta)}
                  {g.vigente && <span className="sub-texto">Quedan {g.dias_restantes} días</span>}
                </>
              )}
            </dd>
          </div>
        </dl>
      )}
      {o.reingresos.length > 0 && (
        <ul className="voucher-lista">
          {o.reingresos.map((r) => (
            <li key={r.id}>
              <span>Reingreso</span>
              <Link to={`/servicio-tecnico/ordenes/${r.id}`}>{r.codigo}</Link>
              <span className="celda-suave">{r.estado_nombre}</span>
            </li>
          ))}
        </ul>
      )}
      {reingresando && <ReingresoModal orden={o} onCerrar={() => setReingresando(false)} />}
      {portal}
    </PanelTarjeta>
  )
}
