import { useLocation, useNavigate } from 'react-router-dom'
import { Icono } from './IconosPanel'
import './listados.css'

/**
 * «Volver» de las fichas de detalle. Regresa a la pantalla de la que se vino; si la ficha se abrió
 * directamente (enlace o recarga) lleva a `ruta`, la lista, para no salir de la aplicación.
 */
export default function BotonVolver({ ruta, texto }) {
  const navegar = useNavigate()
  const { key } = useLocation()
  return (
    <button type="button" className="boton-volver" onClick={() => (key !== 'default' ? navegar(-1) : navegar(ruta))}>
      <Icono nombre="chevronIzq" tam={18} /> {texto}
    </button>
  )
}
