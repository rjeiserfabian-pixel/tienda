import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

const NotificacionesContext = createContext(null)
const DURACION_MS = 5000

/** Avisos breves (éxito/error) para que ninguna operación falle ni termine en silencio. */
export function NotificacionesProvider({ children }) {
  const [avisos, setAvisos] = useState([])
  const contador = useRef(0)

  const descartar = useCallback((id) => setAvisos((previos) => previos.filter((a) => a.id !== id)), [])

  const notificar = useCallback(
    (tipo, mensaje) => {
      const id = ++contador.current
      setAvisos((previos) => [...previos.slice(-3), { id, tipo, mensaje }])
      setTimeout(() => descartar(id), DURACION_MS)
    },
    [descartar],
  )

  const valor = useMemo(() => ({ notificar }), [notificar])

  return (
    <NotificacionesContext.Provider value={valor}>
      {children}
      <div className="avisos" role="status" aria-live="polite">
        {avisos.map((aviso) => (
          <div key={aviso.id} className={`aviso aviso-${aviso.tipo}`}>
            <span>{aviso.mensaje}</span>
            <button type="button" aria-label="Cerrar aviso" onClick={() => descartar(aviso.id)}>
              ×
            </button>
          </div>
        ))}
      </div>
    </NotificacionesContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNotificar() {
  const contexto = useContext(NotificacionesContext)
  if (!contexto) throw new Error('useNotificar debe usarse dentro de <NotificacionesProvider>')
  return contexto.notificar
}
