import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, estadoVencimiento, numeroInterno } from '../compras'

/** Tabla de facturas a crédito con deuda. Sirve para la vista «por factura» y para las deudas de un proveedor. */
export function TablaFacturas({ filas, onVer, onPagar, vacio }) {
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>Proveedor</th>
            <th>Comprobante</th>
            <th>Emisión</th>
            <th>Próximo vencimiento</th>
            <th className="num">Total</th>
            <th className="num">Pagado</th>
            <th className="num">Saldo</th>
            <th className="centrado">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {filas.length === 0 && <FilaVacia columnas={8} icono="wallet" titulo={vacio.titulo} descripcion={vacio.descripcion} />}
          {filas.map((c) => {
            const v = estadoVencimiento(c.proximo_vencimiento)
            return (
              <tr key={c.id}>
                <td className="col-texto">{c.proveedor_nombre}</td>
                <td>
                  {c.comprobante}
                  <span className="sub-texto">N° {numeroInterno(c)}</span>
                </td>
                <td className="celda-suave">{fechaCorta(c.fecha_emision)}</td>
                <td className="cxp-vence">
                  {fechaCorta(c.proximo_vencimiento)}
                  <span className="pildora" data-tono={v.tono}>{v.texto}</span>
                </td>
                <td className="num">{dinero(c.total, c.moneda)}</td>
                <td className="num">{dinero(c.pagado, c.moneda)}</td>
                <td className="num">
                  <strong>{dinero(c.saldo, c.moneda)}</strong>
                  {Number(c.saldo_vencido) > 0 && <span className="sub-texto cxp-vencido">Vencido {dinero(c.saldo_vencido, c.moneda)}</span>}
                </td>
                <td className="centrado">
                  <span className="acciones-fila">
                    <button type="button" className="accion-icono ver" aria-label={`Ver la compra ${c.comprobante}`} title="Ver detalle" onClick={() => onVer(c.id)}>
                      <Icono nombre="ojo" tam={19} />
                    </button>
                    <Can permiso="COMPRAS.PAGAR">
                      <button type="button" className="primario compra-pagar" onClick={() => onPagar(c.id)}>
                        Pagar
                      </button>
                    </Can>
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Vista «por factura»: todas las compras a crédito con deuda, la más urgente primero. */
export default function PorFactura({ parametros, pagina, tamano, onPagina, onTamano, hayFiltros, onVer, onPagar }) {
  const consulta = useListado(['compras', 'por-pagar'], '/compras/por-pagar/', { ...parametros, page: pagina, page_size: tamano }, { enabled: Boolean(parametros.empresa) })
  return (
    <>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <TablaFacturas
          filas={consulta.data?.results ?? []}
          onVer={onVer}
          onPagar={onPagar}
          vacio={{ titulo: hayFiltros || parametros.q ? 'No hay deudas con esos filtros' : 'No hay deudas pendientes', descripcion: 'Las compras a crédito aparecen aquí hasta que se pagan todas sus cuotas.' }}
        />
      </EstadoConsulta>
      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={onPagina} onTamano={onTamano} />
    </>
  )
}
