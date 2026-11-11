import { useQuery } from '@tanstack/react-query'
import { api, mensajeDeError } from '../../../core/api/client'
import { valorDeParametro } from '../rrhh'
import '../rrhh.css'

/**
 * Los valores legales que rigen HOY y cuáles todavía no se cargaron. Sin sueldo mínimo, UIT o tasas de pensión
 * no se puede calcular una planilla bien: este panel lo avisa antes.
 */
export default function ResumenParametros() {
  const consulta = useQuery({
    queryKey: ['rrhh-parametros', 'resumen'],
    queryFn: ({ signal }) => api.get('/rrhh/parametros/resumen/', { signal }).then((r) => r.data),
    staleTime: 30_000,
  })

  if (consulta.isLoading) return <p aria-busy="true">Revisando los valores vigentes…</p>
  if (consulta.isError) {
    return (
      <p role="alert" className="campo-error">
        {mensajeDeError(consulta.error)}
      </p>
    )
  }
  const { parametros, faltan } = consulta.data
  return (
    <section className="rh-resumen" aria-label="Valores vigentes hoy">
      <header>
        <h3>Valores que rigen hoy</h3>
        {faltan > 0 ? (
          <span className="pildora" data-tono="ambar">
            Faltan {faltan} por cargar
          </span>
        ) : (
          <span className="pildora" data-tono="verde">
            Todos cargados
          </span>
        )}
      </header>
      <ul>
        {parametros.map((p) => (
          <li key={p.codigo} data-falta={p.falta ? 'si' : undefined} title={p.para_que}>
            <span>{p.nombre}</span>
            <strong>{p.falta ? 'Falta cargar' : valorDeParametro(p.valor, p.unidad)}</strong>
          </li>
        ))}
      </ul>
      {faltan > 0 && <p className="campo-ayuda">Cárgalos con «Nuevo parámetro»: cada valor lleva la fecha desde la que rige. El contador puede mantenerlos.</p>}
    </section>
  )
}
