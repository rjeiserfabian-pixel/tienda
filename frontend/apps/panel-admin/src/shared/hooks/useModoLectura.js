import { useSearchParams } from 'react-router-dom'

/** El ojo del listado abre la ficha con `?modo=lectura`; el lápiz, sin ese parámetro. */
export const MODO_LECTURA = '?modo=lectura'

export function useModoLectura() {
  const [params] = useSearchParams()
  return params.get('modo') === 'lectura'
}
