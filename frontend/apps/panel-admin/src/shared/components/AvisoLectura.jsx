import { Link, useLocation } from 'react-router-dom'
import { Icono } from './IconosPanel'
import './listados.css'

/** Franja de "modo consulta" de las fichas; si el usuario puede editar, ofrece pasar a editar. */
export default function AvisoLectura({ puedeEditar }) {
  const { pathname } = useLocation()
  return (
    <div className="aviso-lectura" role="status">
      <Icono nombre="ojo" tam={20} />
      <span>Modo consulta: solo puedes ver la información, no modificarla.</span>
      {puedeEditar && (
        <Link to={`${pathname}#datos`} className="boton-cabecera primario" replace>
          <Icono nombre="lapiz" tam={18} /> Editar
        </Link>
      )}
    </div>
  )
}
