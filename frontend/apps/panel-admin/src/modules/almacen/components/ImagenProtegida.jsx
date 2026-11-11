import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'

const comoDataUrl = (blob) =>
  new Promise((resolver, rechazar) => {
    const lector = new FileReader()
    lector.onload = () => resolver(lector.result)
    lector.onerror = () => rechazar(lector.error)
    lector.readAsDataURL(blob)
  })

/**
 * Imagen que solo el servidor entrega con sesión: se pide con el token (un <img src> simple no
 * lo enviaría) y se guarda en la caché de consultas como data URL, que no hay que liberar.
 */
export default function ImagenProtegida({ url, alt, className }) {
  const consulta = useQuery({
    queryKey: ['imagen', url],
    queryFn: ({ signal }) => api.get(url, { responseType: 'blob', signal }).then((r) => comoDataUrl(r.data)),
    enabled: Boolean(url),
    staleTime: 30 * 60_000,
    gcTime: 30 * 60_000,
    retry: 1,
  })

  if (consulta.data) return <img className={className} src={consulta.data} alt={alt} loading="lazy" />
  return (
    <span className={`${className ?? ''} imagen-vacia`} role="img" aria-label={consulta.isError ? 'No se pudo cargar la foto' : alt}>
      <Icono nombre="camara" tam={22} />
    </span>
  )
}
