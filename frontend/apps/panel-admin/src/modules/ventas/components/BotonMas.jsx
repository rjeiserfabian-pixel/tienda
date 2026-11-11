import Can from '../../../shared/components/Can'
import { Icono } from '../../../shared/components/IconosPanel'

/** Botón «+» al lado de una lista de transporte: registra uno nuevo al vuelo (solo con el permiso de crear). */
export default function BotonMas({ etiqueta, disabled, onClick }) {
  return (
    <Can permiso="MANTENIMIENTO.TRANSPORTE.CREAR" organizacion>
      <button type="button" className="accion-icono guia-mas" aria-label={etiqueta} title={etiqueta} disabled={disabled} onClick={onClick}>
        <Icono nombre="agregar" tam={20} />
      </button>
    </Can>
  )
}
