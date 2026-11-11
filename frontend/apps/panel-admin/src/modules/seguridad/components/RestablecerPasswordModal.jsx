import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

/**
 * Restablecer la contraseña de otro usuario (olvidó la suya y no puede usar su correo).
 * Paso 1: confirmar. Paso 2: la contraseña temporal se muestra UNA vez; vive solo en el estado
 * de este componente (no se guarda ni se vuelve a pedir al servidor).
 */
export default function RestablecerPasswordModal({ usuario, onCerrar }) {
  const [temporal, setTemporal] = useState(null)
  const [error, setError] = useState('')
  const [copiada, setCopiada] = useState(false)

  const restablecer = useMutacion({
    mutationFn: () => api.post(`/seguridad/usuarios/${usuario.id}/restablecer-password/`).then((r) => r.data),
    invalidar: [['usuarios']],
    avisarError: false,
  })

  const confirmar = () => {
    if (restablecer.isPending) return
    setError('')
    restablecer.mutate(undefined, {
      onSuccess: (datos) => setTemporal(datos.password_temporal),
      onError: (e) => setError(mensajeDeError(e)),
    })
  }

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(temporal)
      setCopiada(true)
    } catch {
      setCopiada(false) // sin permiso del portapapeles: la clave sigue visible para copiarla a mano
    }
  }

  if (temporal) {
    return (
      <Modal titulo="Contraseña temporal" subtitulo={`Entrégasela a ${usuario.username}.`} onCerrar={onCerrar} ancho={480}>
        <p className="campo-ayuda">
          Se muestra <strong>una sola vez</strong>: no se guarda ni se podrá consultar después. El usuario deberá cambiarla en su
          primer ingreso y sus sesiones abiertas se cerraron.
        </p>
        <div className="clave-temporal">
          <code aria-label="Contraseña temporal">{temporal}</code>
          <button type="button" onClick={copiar}>
            <Icono nombre="documento" tam={18} /> {copiada ? 'Copiada' : 'Copiar'}
          </button>
        </div>
        <div className="modal-pie">
          <button type="button" className="primario" onClick={onCerrar}>
            Ya la anoté
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal titulo="Restablecer contraseña" subtitulo={usuario.username} onCerrar={onCerrar} ancho={480}>
      <p>
        Se generará una contraseña temporal para <strong>{usuario.username}</strong>. Su contraseña actual dejará de funcionar y se
        cerrarán todas sus sesiones.
      </p>
      <p className="campo-ayuda">Antes de entregarla, confirma por otro medio que quien la pide es realmente esa persona.</p>
      {error && <p role="alert" className="campo-error">{error}</p>}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={restablecer.isPending}>
          Cancelar
        </button>
        <button type="button" className="peligro" onClick={confirmar} disabled={restablecer.isPending}>
          {restablecer.isPending ? 'Generando…' : 'Generar contraseña'}
        </button>
      </div>
    </Modal>
  )
}
