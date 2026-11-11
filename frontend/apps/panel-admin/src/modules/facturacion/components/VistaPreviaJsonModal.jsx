import { useState } from 'react'
import { mensajeDeError } from '../../../core/api/client'
import Modal from '../../../shared/components/Modal'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useVistaPreviaFe } from '../hooks/useFacturacion'
import '../facturacion.css'

/**
 * Muestra el JSON que se enviaría a la API de facturación, tal cual. Las claves SOL salen ocultas, así que se
 * puede revisar (o copiar para probarlo aparte) sin exponerlas. No envía nada.
 */
export default function VistaPreviaJsonModal({ documento, onCerrar }) {
  const notificar = useNotificar()
  const vista = useVistaPreviaFe(documento.origen, documento.id)
  const [copiando, setCopiando] = useState(false)
  const texto = vista.data ? JSON.stringify(vista.data.payload, null, 2) : ''

  const copiar = async () => {
    setCopiando(true)
    try {
      await navigator.clipboard.writeText(texto)
      notificar('exito', 'JSON copiado (con las claves ocultas).')
    } catch {
      notificar('error', 'No se pudo copiar. Selecciona el texto y cópialo a mano.')
    } finally {
      setCopiando(false)
    }
  }

  return (
    <Modal titulo="Vista previa del envío" subtitulo={`${documento.tipo_nombre} ${documento.numero}. Esto es lo que se enviaría a la API; no se envía nada.`} onCerrar={onCerrar} ancho={860}>
      {vista.isLoading && <p aria-busy="true">Armando el documento…</p>}
      {vista.isError && (
        <p role="alert" className="campo-error">
          {mensajeDeError(vista.error)}
        </p>
      )}
      {vista.data && (
        <>
          <p className="celda-suave">
            Modo: <strong>{vista.data.modo === 'PRODUCCION' ? 'Producción' : 'Beta (pruebas)'}</strong> · Facturación electrónica {vista.data.activo ? 'activa' : 'apagada'}
          </p>
          {vista.data.faltantes.length > 0 && (
            <div role="status" className="modal-aviso">
              Antes de enviar falta configurar: {vista.data.faltantes.join('; ')}.
            </div>
          )}
          <pre className="fe-json" tabIndex={0} aria-label="JSON del documento">
            {texto}
          </pre>
        </>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          Cerrar
        </button>
        <button type="button" className="primario" onClick={copiar} disabled={!vista.data || copiando}>
          {copiando ? 'Copiando…' : 'Copiar JSON'}
        </button>
      </div>
    </Modal>
  )
}
