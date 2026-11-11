import Modal from './Modal'

/** Confirmación de acciones sensibles (desactivar, quitar acceso, eliminar). */
export default function ConfirmarModal({ titulo, mensaje, textoConfirmar = 'Confirmar', enviando, onConfirmar, onCerrar }) {
  return (
    <Modal titulo={titulo} onCerrar={onCerrar} ancho={420}>
      <p>{mensaje}</p>
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={enviando}>
          Cancelar
        </button>
        <button type="button" className="peligro" onClick={onConfirmar} disabled={enviando}>
          {enviando ? 'Procesando…' : textoConfirmar}
        </button>
      </div>
    </Modal>
  )
}
