import { useState } from 'react'
import { fechaCorta } from '../../almacen/inventario'
import Paginacion from '../../../shared/components/Paginacion'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useListado } from '../../../shared/hooks/useListado'
import { dinero } from '../../compras/compras'

/** Cuánto dejó cada servicio cobrado: lo cobrado sin IGV, lo que costaron los repuestos y la comisión. */
export default function ReporteUtilidad({ empresa, rango, utilidad }) {
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(10)
  const lista = useListado(['servicio', 'reporte-utilidad'], '/servicio-tecnico/reportes/utilidad/', { empresa, ...rango, page: pagina, page_size: tamano })
  const t = utilidad.totales
  const filas = lista.data?.results ?? []

  return (
    <section aria-label="Utilidad por servicio">
      <h3>Utilidad por servicio</h3>
      <p className="celda-suave">Solo cuentan los servicios cobrados cuyo comprobante sigue vigente. La utilidad es lo cobrado sin IGV menos el costo real de los repuestos y la comisión del técnico.</p>
      <dl className="cxp-tarjetas" aria-label="Totales">
        <div>
          <dt>Servicios cobrados</dt>
          <dd>{t.servicios}</dd>
        </div>
        <div>
          <dt>Cobrado (sin IGV)</dt>
          <dd>{dinero(t.ingreso)}</dd>
        </div>
        <div>
          <dt>Costo de repuestos</dt>
          <dd>{dinero(t.costo)}</dd>
        </div>
        <div>
          <dt>Comisiones</dt>
          <dd>{dinero(t.comision)}</dd>
        </div>
        <div data-tono={Number(t.utilidad) < 0 ? 'rojo' : undefined}>
          <dt>Utilidad</dt>
          <dd>{dinero(t.utilidad)}</dd>
        </div>
      </dl>
      {utilidad.por_tipo_servicio.length > 0 && (
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Tipo de servicio</th>
                <th className="num">Servicios</th>
                <th className="num">Cobrado</th>
                <th className="num">Costo repuestos</th>
                <th className="num">Utilidad</th>
              </tr>
            </thead>
            <tbody>
              {utilidad.por_tipo_servicio.map((f) => (
                <tr key={f.nombre}>
                  <td>{f.nombre}</td>
                  <td className="num">{f.servicios}</td>
                  <td className="num">{dinero(f.ingreso)}</td>
                  <td className="num">{dinero(f.costo)}</td>
                  <td className="num">{dinero(f.utilidad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h4>Orden por orden</h4>
      <EstadoConsulta consulta={lista} hayDatos={Boolean(lista.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Entrega</th>
                <th>Orden</th>
                <th>Cliente y equipo</th>
                <th>Técnico</th>
                <th className="num">Cobrado</th>
                <th className="num">Repuestos</th>
                <th className="num">Comisión</th>
                <th className="num">Utilidad</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <tr>
                  <td colSpan={8} className="estado-vacio">
                    No hubo servicios cobrados en ese periodo.
                  </td>
                </tr>
              )}
              {filas.map((f) => (
                <tr key={f.orden}>
                  <td>{fechaCorta(f.fecha_entrega)}</td>
                  <td>
                    <strong>{f.codigo}</strong>
                    <span className="sub-texto">{f.tipo_servicio}</span>
                  </td>
                  <td className="col-texto">
                    {f.cliente}
                    <span className="sub-texto">{f.equipo}</span>
                  </td>
                  <td>{f.tecnico || <span className="celda-suave">—</span>}</td>
                  <td className="num">{dinero(f.ingreso)}</td>
                  <td className="num">{dinero(f.costo_repuestos)}</td>
                  <td className="num">{dinero(f.comision)}</td>
                  <td className="num">{dinero(f.utilidad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>
      <Paginacion
        pagina={pagina}
        tamano={tamano}
        total={lista.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(n) => {
          setTamano(n)
          setPagina(1)
        }}
      />
    </section>
  )
}
