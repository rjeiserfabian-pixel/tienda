import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora, MEDIOS_AVISO } from '../servicio'

function AvisoModal({ orden, onCerrar }) {
  const [medio, setMedio] = useState('WHATSAPP')
  const [mensaje, setMensaje] = useState('')
  const [error, setError] = useState('')
  const registrar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/avisos/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio']],
    exito: 'Aviso registrado.',
    alExito: onCerrar,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (registrar.isPending) return
    if (mensaje.trim().length < 3) return setError('Escribe qué se le dijo al cliente.')
    setError('')
    registrar.mutate({ medio, mensaje: mensaje.trim() }, { onError: (e) => setError(erroresDeCampo(e).mensaje || mensajeDeError(e)) })
  }
  // Abre WhatsApp con el mensaje escrito (no se envía solo: lo revisa y lo manda quien atiende).
  const abrirWhatsapp = () => {
    const texto = mensaje.trim() || orden.whatsapp.mensaje
    setMedio('WHATSAPP')
    setMensaje(texto)
    window.open(`https://wa.me/${orden.whatsapp.numero}?text=${encodeURIComponent(texto)}`, '_blank', 'noopener,noreferrer')
  }
  const subtitulo = `Orden ${orden.codigo} · ${orden.cliente_nombre}${orden.cliente_telefono ? ` · Tel. ${orden.cliente_telefono}` : ''}`
  return (
    <Modal titulo="Avisar al cliente" subtitulo={subtitulo} onCerrar={onCerrar} ancho={540}>
      <form onSubmit={enviar} noValidate>
        <p className="celda-suave">Avisa al cliente por el medio que prefieras y deja aquí la constancia.</p>
        <Campo etiqueta="Medio" tipo="select">
          {(p) => (
            <select {...p} value={medio} disabled={registrar.isPending} onChange={(e) => setMedio(e.target.value)}>
              {MEDIOS_AVISO.map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
                </option>
              ))}
            </select>
          )}
        </Campo>
        {orden.whatsapp.numero ? (
          <button type="button" className="boton-cabecera" disabled={registrar.isPending} onClick={abrirWhatsapp}>
            <Icono nombre="chat" tam={18} /> Abrir WhatsApp con el mensaje
          </button>
        ) : (
          <p className="celda-suave">El cliente no tiene un teléfono válido para WhatsApp: llámalo o agrégalo en su ficha.</p>
        )}
        <Campo etiqueta="Qué se le dijo" requerido error={error} contador={{ actual: mensaje.length, max: 500 }}>
          {(p) => <textarea {...p} rows={3} maxLength={500} placeholder="Ej. Se le avisó que el equipo ya está listo para recoger." value={mensaje} disabled={registrar.isPending} onChange={(e) => setMensaje(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={registrar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={registrar.isPending}>
            {registrar.isPending ? 'Guardando…' : 'Registrar aviso'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Constancia de los avisos al cliente: por qué medio, qué se le dijo, quién y cuándo. */
export default function AvisosOrden({ orden: o }) {
  const [abierto, setAbierto] = useState(false)
  return (
    <PanelTarjeta
      icono="chat"
      titulo="Avisos al cliente"
      descripcion="Cada vez que se le avisa algo al cliente queda anotado aquí."
      acciones={
        o.permite.avisar ? (
          <button type="button" className="boton-cabecera" onClick={() => setAbierto(true)}>
            Registrar aviso
          </button>
        ) : undefined
      }
    >
      <div className="aviso-enlace">
        <span className="celda-suave">Enlace para que el cliente vea el estado</span>
        <div className="aviso-enlace-acciones">
          <a className="aviso-enlace-boton" href={o.url_publica} target="_blank" rel="noopener noreferrer">
            Abrir
          </a>
          <button
            type="button"
            className="aviso-enlace-boton"
            onClick={() => navigator.clipboard?.writeText(o.url_publica)}
          >
            Copiar enlace
          </button>
        </div>
        {o.acepta_whatsapp && <span className="celda-suave">El cliente aceptó avisos por WhatsApp.</span>}
      </div>
      {o.notificaciones.length > 0 && (
        <ul className="voucher-lista" aria-label="Avisos automáticos">
          {o.notificaciones.map((n) => (
            <li key={n.id} className="servicio-aviso-item">
              <strong>WhatsApp automático: {n.evento_nombre}</strong>
              <span className="pildora" data-tono={n.estado === 'ENVIADO' ? 'verde' : n.estado === 'FALLIDO' ? 'rojo' : n.estado === 'OMITIDO' ? 'gris' : 'ambar'}>
                {n.estado_nombre}
              </span>
              {n.detalle && <span className="sub-texto">{n.detalle}</span>}
              <span className="sub-texto">{fechaHora(n.fecha)}</span>
            </li>
          ))}
        </ul>
      )}
      {o.avisos.length === 0 ? (
        <p className="estado-vacio">Todavía no se le avisó nada al cliente.</p>
      ) : (
        <ul className="voucher-lista">
          {o.avisos.map((a) => (
            <li key={a.id} className="servicio-aviso-item">
              <strong>{a.medio_nombre}</strong>
              <span>{a.mensaje}</span>
              <span className="sub-texto">
                {fechaHora(a.creado_en)} · {a.usuario_nombre || 'Sistema'}
              </span>
            </li>
          ))}
        </ul>
      )}
      {abierto && <AvisoModal orden={o} onCerrar={() => setAbierto(false)} />}
    </PanelTarjeta>
  )
}
