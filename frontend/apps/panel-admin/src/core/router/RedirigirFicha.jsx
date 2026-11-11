import { Navigate, useLocation, useParams } from 'react-router-dom'

/** Lleva una dirección antigua de una ficha (`/viejo/:id`) a la nueva, conservando `?modo=` y `#`. */
export default function RedirigirFicha({ base }) {
  const { id } = useParams()
  const { search, hash } = useLocation()
  return <Navigate to={`${base}/${id}${search}${hash}`} replace />
}
