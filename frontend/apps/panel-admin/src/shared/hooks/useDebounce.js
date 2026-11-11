import { useEffect, useState } from 'react'

/** Valor retrasado: evita una petición por cada tecla en buscadores y filtros. */
export function useDebounce(valor, milisegundos = 400) {
  const [retrasado, setRetrasado] = useState(valor)

  useEffect(() => {
    const temporizador = setTimeout(() => setRetrasado(valor), milisegundos)
    return () => clearTimeout(temporizador)
  }, [valor, milisegundos])

  return retrasado
}
