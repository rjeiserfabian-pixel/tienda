import { api } from '../../core/api/client'
import { aCsv, descargarTexto } from '../../shared/utils/csv'
import { sinVacios } from '../../shared/hooks/useListado'

const MAXIMO_FILAS = 5000 // tope de seguridad: una exportación no debe cargar la base entera
const POR_PAGINA = 100 // el máximo que acepta la API

const ENCABEZADOS = ['Usuario', 'Nombres', 'Apellidos', 'Correo', 'Empresas', 'Roles', 'Estado', 'Último acceso']

/**
 * Descarga un CSV con los usuarios que coinciden con los filtros actuales (no solo la página
 * visible). Recorre la API paginada. Devuelve cuántas filas exportó y si se cortó por el tope.
 */
export async function exportarUsuarios(filtros) {
  const filas = []
  let pagina = 1
  let cortado = false
  for (;;) {
    const { data } = await api.get('/seguridad/usuarios/', {
      params: sinVacios({ ...filtros, page: pagina, page_size: POR_PAGINA }),
    })
    filas.push(...data.results)
    if (!data.next) break
    if (filas.length >= MAXIMO_FILAS) {
      cortado = true
      break
    }
    pagina += 1
  }
  const csv = aCsv(
    ENCABEZADOS,
    filas.map((u) => [
      u.username,
      u.nombres,
      u.apellidos,
      u.email,
      u.empresas.map((e) => e.nombre).join('; '),
      u.roles.join('; '),
      u.activo ? 'Activo' : 'Inactivo',
      u.ultimo_acceso ?? '',
    ]),
  )
  const fecha = new Date().toISOString().slice(0, 10)
  descargarTexto(csv, `usuarios-${fecha}.csv`)
  return { total: filas.length, cortado }
}
