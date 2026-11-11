import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { cantidad, fechaCorta } from '../inventario'
import { soles } from '../utilidades'

const FORMATOS = {
  num: (v) => (v === '' ? '' : cantidad(v)),
  soles: (v) => (v === '' ? '' : soles(v)),
  entero: (v) => v,
}
const tal = (v) => v

const celda = (columna, fila) => {
  const valor = fila[columna.clave] ?? ''
  if (columna.clave === 'fecha') return fechaCorta(valor)
  return (FORMATOS[columna.tipo] ?? tal)(valor)
}

/** Reporte en pantalla: resumen, tabla de las primeras filas y aviso si hay más. */
export default function VistaReporte({ consulta }) {
  const datos = consulta.data
  return (
    <section className="vista-reporte" aria-label="Vista previa del reporte" aria-live="polite">
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && (
          <>
            <header className="vista-reporte-cabecera">
              <div>
                <h3>{datos.titulo}</h3>
                {datos.encabezado && <p className="celda-suave">{datos.encabezado}</p>}
              </div>
              <dl className="resumen-reporte">
                {(datos.resumen ?? []).map((r) => (
                  <div key={r.titulo}>
                    <dt>{r.titulo}</dt>
                    <dd>{(FORMATOS[r.tipo] ?? tal)(r.valor)}</dd>
                  </div>
                ))}
              </dl>
            </header>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    {datos.columnas.map((c) => (
                      <th key={c.clave} className={c.tipo === 'texto' ? undefined : 'num'}>{c.titulo}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {datos.filas.length === 0 && (
                    <FilaVacia columnas={datos.columnas.length} icono="documento" titulo="Sin datos en este periodo" descripcion="No hay movimientos ni saldos con esos filtros. Prueba con otro periodo o almacén." />
                  )}
                  {datos.filas.map((fila, i) => (
                    <tr key={i} data-antiguo={fila.antiguo ? 'si' : undefined}>
                      {datos.columnas.map((c) => (
                        <td key={c.clave} className={c.tipo === 'texto' ? undefined : 'num'}>{celda(c, fila)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {datos.recortado && (
              <p className="celda-suave">
                Se muestran las primeras {datos.filas.length} de {datos.total_filas} filas. El archivo trae todas.
              </p>
            )}
          </>
        )}
      </EstadoConsulta>
    </section>
  )
}
