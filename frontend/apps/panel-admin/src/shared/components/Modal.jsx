import { useEffect, useRef } from 'react'
import { MARCA } from '../../core/marca'
import { Icono } from './IconosPanel'
import { LogoMarca } from './LogoMarca'
import './modal.css'

/**
 * Cuadro de diálogo premium sobre el elemento nativo <dialog> (foco, Escape y fondo los maneja
 * el navegador). Marco rojo brillante con esquinas cortadas y cabecera con la marca, el título
 * y un subtítulo opcional. El contenido se monta solo mientras está abierto: los formularios
 * nacen limpios.
 */
export default function Modal({ titulo, subtitulo, onCerrar, children, ancho = 560 }) {
  const dialogo = useRef(null)

  useEffect(() => {
    const el = dialogo.current
    if (el && !el.open) el.showModal()
    return () => el?.close()
  }, [])

  return (
    <dialog
      ref={dialogo}
      className="modal"
      style={{ maxWidth: ancho }}
      onCancel={(e) => {
        e.preventDefault()
        onCerrar()
      }}
      aria-labelledby="modal-titulo"
    >
      <div className="modal-brillo">
        <div className="modal-borde">
          <div className="modal-cuerpo">
            <header className="modal-cabecera">
              <span className="modal-marca" aria-hidden="true">
                <LogoMarca tam={34} />
                <b>
                  {MARCA.nombrePrincipal}
                  <i>{MARCA.nombreAcento}</i>
                </b>
              </span>
              <div className="modal-titulos">
                <h2 id="modal-titulo">{titulo}</h2>
                {subtitulo && <p>{subtitulo}</p>}
              </div>
              <button type="button" className="modal-cerrar" aria-label="Cerrar" onClick={onCerrar}>
                <Icono nombre="cerrar" tam={20} />
              </button>
            </header>
            {children}
          </div>
        </div>
      </div>
    </dialog>
  )
}
