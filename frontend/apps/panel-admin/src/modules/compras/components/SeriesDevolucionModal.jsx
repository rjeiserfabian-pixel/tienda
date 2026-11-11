import { useMemo, useState } from 'react'
import Modal from '../../../shared/components/Modal'

/**
 * Elige qué series o IMEI se devuelven: solo se ofrecen las de esa compra que siguen en el
 * almacén (las ya vendidas no se pueden devolver).
 */
export default function SeriesDevolucionModal({ producto, disponibles, elegidas, pendiente, onGuardar, onCerrar }) {
  const [marcadas, setMarcadas] = useState(() => new Set(elegidas))
  const [filtro, setFiltro] = useState('')
  const visibles = useMemo(() => {
    const texto = filtro.trim().toUpperCase()
    return texto ? disponibles.filter((s) => s.includes(texto)) : disponibles
  }, [disponibles, filtro])

  const alternar = (serie) =>
    setMarcadas((previas) => {
      const siguientes = new Set(previas)
      if (siguientes.has(serie)) siguientes.delete(serie)
      else siguientes.add(serie)
      return siguientes
    })
  const marcarVisibles = () => setMarcadas((previas) => new Set([...previas, ...visibles]))
  const limpiar = () => setMarcadas(new Set())
  const pasa = marcadas.size > pendiente

  return (
    <Modal titulo="Series a devolver" subtitulo={producto} onCerrar={onCerrar} ancho={560}>
      {disponibles.length === 0 ? (
        <p className="estado-vacio">Ya no queda ninguna serie de esta compra en el almacén.</p>
      ) : (
        <>
          <p className="celda-suave">
            Quedan {disponibles.length} en el almacén; todavía se pueden devolver {pendiente}.
          </p>
          <div className="fila-campos">
            <input type="search" aria-label="Buscar serie" placeholder="Buscar serie…" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
            <button type="button" onClick={marcarVisibles}>
              Marcar las visibles
            </button>
            <button type="button" onClick={limpiar} disabled={marcadas.size === 0}>
              Quitar todas
            </button>
          </div>
          <ul className="dev-series" aria-label="Series disponibles">
            {visibles.map((serie) => (
              <li key={serie}>
                <label>
                  <input type="checkbox" checked={marcadas.has(serie)} onChange={() => alternar(serie)} /> {serie}
                </label>
              </li>
            ))}
            {visibles.length === 0 && <li className="celda-suave">Ninguna serie coincide.</li>}
          </ul>
          {pasa && (
            <p role="alert" className="campo-error">
              Marcaste más de lo que se puede devolver ({pendiente}).
            </p>
          )}
        </>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          Cancelar
        </button>
        <button type="button" className="primario" disabled={pasa || disponibles.length === 0} onClick={() => onGuardar([...marcadas])}>
          Usar {marcadas.size} {marcadas.size === 1 ? 'serie' : 'series'}
        </button>
      </div>
    </Modal>
  )
}
