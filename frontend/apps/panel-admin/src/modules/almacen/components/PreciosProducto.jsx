import { Link } from 'react-router-dom'
import Campo from '../../../shared/components/Campo'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useCalculoPrecios } from '../../../shared/hooks/useCalculoPrecios'
import { aNumero, soles } from '../utilidades'

/**
 * Costo y precios por lista, en soles. El precio manda: al escribir la utilidad (o el margen, según
 * cómo trabaje la organización) se calcula el precio y al escribir el precio se calcula el
 * porcentaje. Si cambia el costo, los precios se quedan y el porcentaje se recalcula.
 */
export default function PreciosProducto({ listas, costo, precios, errores, deshabilitado, onCosto, onPrecios }) {
  const calc = useCalculoPrecios()
  const hayCosto = (aNumero(costo) ?? 0) > 0

  // Cada fila guarda el precio; el porcentaje solo se guarda mientras se escribe (si no, se deriva).
  const cambiarCosto = (valor) => {
    onCosto(valor)
    // El precio no se mueve: lo que se ajusta es el porcentaje que ya no es verdad.
    onPrecios(Object.fromEntries(Object.entries(precios).map(([id, p]) => [id, { precio: p.precio }])))
  }
  const cambiarPrecio = (id, precio) => onPrecios({ ...precios, [id]: { precio } })
  const cambiarPorcentaje = (id, pct) => onPrecios({ ...precios, [id]: { pct, precio: calc.aPrecio(costo, pct) } })

  return (
    <PanelTarjeta id="precios" icono="coins" titulo="Costo y precios" descripcion={`Todo en soles. Escribe ${calc.articulo} y el precio se calcula, o escribe el precio y verás ${calc.articulo} (${calc.explicacion}).`}>
      <div className="precios-cuadro">
        <Campo etiqueta="Costo (S/)" icono="coins" error={errores.costo}>
          {(p) => (
            <input {...p} name="costo" inputMode="decimal" value={costo} disabled={deshabilitado} placeholder="0.00" onChange={(e) => cambiarCosto(e.target.value)} />
          )}
        </Campo>
      </div>
      {listas.length === 0 ? (
        <p className="celda-suave">
          Aún no hay listas de precios. <Link to="/mantenimiento/listas-precio">Créalas aquí</Link> para poder poner precios.
        </p>
      ) : (
        <div className="marco-tabla">
          <table className="tabla-datos tabla-precios">
            <thead>
              <tr>
                <th>Lista</th>
                <th>{calc.encabezado}</th>
                <th>Precio de venta (S/)</th>
              </tr>
            </thead>
            <tbody>
              {listas.map((lista) => {
                const fila = precios[lista.id] ?? { precio: '' }
                return (
                  <tr key={lista.id}>
                    <td>
                      <strong>{lista.nombre}</strong>
                      {lista.es_principal && <small className="celda-suave"> · principal</small>}
                    </td>
                    <td>
                      <input
                        name={`porcentaje_${lista.id}`}
                        aria-label={`${calc.nombre} de ${lista.nombre}`}
                        inputMode="decimal"
                        value={fila.pct ?? calc.aPorcentaje(costo, fila.precio)}
                        disabled={deshabilitado || !hayCosto}
                        title={hayCosto ? undefined : 'Escribe primero el costo'}
                        placeholder={hayCosto ? '0' : '—'}
                        onChange={(e) => cambiarPorcentaje(lista.id, e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        name={`precio_${lista.id}`}
                        aria-label={`Precio de ${lista.nombre}`}
                        inputMode="decimal"
                        value={fila.precio}
                        disabled={deshabilitado}
                        placeholder="0.00"
                        onChange={(e) => cambiarPrecio(lista.id, e.target.value)}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {errores.precios && <p role="alert" className="campo-error">{errores.precios}</p>}
      {hayCosto && precios && (
        <p className="celda-suave precios-nota">
          Costo {soles(costo)}. Si cambias el costo, los precios se mantienen y {calc.articulo} se ajusta.
        </p>
      )}
    </PanelTarjeta>
  )
}
