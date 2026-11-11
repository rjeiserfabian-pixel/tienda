import ImpresionDesdeLista from '../../ventas/components/ImpresionDesdeLista'
import { especificacionIngreso } from '../especificaciones'

/** Vista previa de la hoja de ingreso de una orden del listado, sin abrir su ficha. */
export default function ImpresionOrden({ id }) {
  // La misma clave de la ficha (el id de la ruta es texto): si ya se vio, no se pide otra vez.
  return <ImpresionDesdeLista clave={['servicio', 'orden', String(id)]} url={`/servicio-tecnico/ordenes/${id}/`} especificacion={especificacionIngreso} />
}
