import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'

const POR_PAGINA = 100 // el máximo que permite el servidor
const MAX_PAGINAS = 30 // tope de seguridad: 3 000 categorías

/**
 * TODAS las categorías activas (con su familia y su número de campos de especificación),
 * recorriendo las páginas del servidor. La clave empieza con «categorias»: al guardar una plantilla
 * se invalida y el contador de campos se refresca solo.
 */
export function useTodasLasCategorias() {
  return useQuery({
    queryKey: ['categorias', 'todas'],
    queryFn: async ({ signal }) => {
      const todas = []
      let total = Infinity
      for (let pagina = 1; todas.length < total && pagina <= MAX_PAGINAS; pagina += 1) {
        const { data } = await api.get('/mantenimiento/categorias/', {
          params: { estado: 'ACTIVO', page: pagina, page_size: POR_PAGINA, orden: 'familia' },
          signal,
        })
        total = data.count
        todas.push(...data.results)
        if (data.results.length === 0) break
      }
      return todas
    },
    staleTime: 30_000,
  })
}
