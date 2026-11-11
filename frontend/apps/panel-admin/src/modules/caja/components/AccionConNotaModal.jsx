import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

/**
 * Ventana de confirmación para una acción del estado de cuenta (cerrar, reabrir, descartar) con una
 * nota o motivo opcional u obligatorio. `campo` es el nombre que espera el servidor.
 */
export default function AccionConNotaModal({ invalidar = [['caja']], url, titulo, subtitulo, descripcion, campo, etiqueta, requerido, placeholder, boton, ocupado, exito, peligro, onCerrar, alExito }) {
  const [texto, setTexto] = useState('')
  const [error, setError] = useState('')

  const ejecutar = useMutacion({
    mutationFn: (cuerpo) => api.post(url, cuerpo).then((r) => r.data),
    invalidar,
    exito,
    alExito: (r) => {
      alExito?.(r)
      onCerrar()
    },
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (ejecutar.isPending) return
    if (campo && requerido && !texto.trim()) return setError('Este dato es obligatorio.')
    setError('')
    ejecutar.mutate(campo ? { [campo]: texto.trim() } : {}, { onError: (e) => setError(erroresDeCampo(e)[campo] || mensajeDeError(e)) })
  }

  return (
    <Modal titulo={titulo} subtitulo={subtitulo} onCerrar={onCerrar} ancho={540}>
      <form onSubmit={enviar} noValidate>
        {descripcion && <p>{descripcion}</p>}
        {campo ? (
          <Campo etiqueta={etiqueta} requerido={requerido} error={error} contador={{ actual: texto.length, max: 250 }}>
            {(p) => <textarea {...p} rows={3} maxLength={250} value={texto} disabled={ejecutar.isPending} placeholder={placeholder} onChange={(e) => setTexto(e.target.value)} />}
          </Campo>
        ) : (
          error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={ejecutar.isPending}>
            Cancelar
          </button>
          <button type="submit" className={peligro ? 'peligro' : 'primario'} disabled={ejecutar.isPending}>
            {ejecutar.isPending ? ocupado : boton}
          </button>
        </div>
      </form>
    </Modal>
  )
}
