import { mensajeDeError } from '../../core/api/client'

/**
 * Cubre los tres estados que nunca deben quedar en blanco: cargando, error y vacío.
 * Si hay datos, muestra a sus hijos.
 */
export default function EstadoConsulta({ consulta, vacio = 'No hay registros para mostrar.', hayDatos, children }) {
  if (consulta.isLoading) return <p aria-busy="true">Cargando…</p>
  if (consulta.isError) {
    return (
      <div role="alert" className="estado-error">
        <p>{mensajeDeError(consulta.error)}</p>
        <button type="button" onClick={() => consulta.refetch()}>
          Reintentar
        </button>
      </div>
    )
  }
  if (!hayDatos) return <p className="estado-vacio">{vacio}</p>
  return children
}
