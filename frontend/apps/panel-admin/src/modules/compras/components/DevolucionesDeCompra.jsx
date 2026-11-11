import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../../core/api/client'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, numeroInterno } from '../compras'
import { destinoDelDinero, ESTADO_DEVOLUCION } from '../devoluciones'

/** Las devoluciones que ya se hicieron de esta compra (no se muestra nada si no hay ninguna). */
export default function DevolucionesDeCompra({ compra }) {
  const consulta = useQuery({
    queryKey: ['compras', 'devoluciones', 'de-la-compra', compra.id],
    queryFn: ({ signal }) => api.get('/compras/devoluciones/', { params: { empresa: compra.empresa, compra: compra.id, page_size: 50 }, signal }).then((r) => r.data.results),
  })
  const filas = consulta.data ?? []
  if (filas.length === 0) return null

  return (
    <PanelTarjeta icono="swap" titulo="Devoluciones al proveedor" descripcion="Mercadería que se devolvió de esta compra.">
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>N°</th>
              <th>Fecha</th>
              <th>Nota de crédito</th>
              <th className="num">Total</th>
              <th>Dinero</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((d) => (
              <tr key={d.id} className={d.estado === 'ANULADO' ? 'anulado' : undefined}>
                <td>
                  <Link to={`/compras/devoluciones/${d.id}`}>{numeroInterno(d)}</Link>
                </td>
                <td>{fechaCorta(d.fecha_emision)}</td>
                <td className="col-texto">{d.comprobante}</td>
                <td className="num">{dinero(d.total, d.moneda)}</td>
                <td className="celda-suave">{destinoDelDinero(d)}</td>
                <td>
                  <span className={`estado-pildora ${ESTADO_DEVOLUCION[d.estado].clase}`}>{ESTADO_DEVOLUCION[d.estado].texto}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelTarjeta>
  )
}
