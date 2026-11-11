import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, estadoVencimiento } from '../compras'

/** Un importe por moneda, uno debajo del otro: soles y dólares nunca se suman. */
export const Montos = ({ montos, campo, vacio = '—' }) =>
  montos.some((m) => Number(m[campo]) > 0)
    ? montos.filter((m) => Number(m[campo]) > 0).map((m) => <div key={m.moneda}>{dinero(m[campo], m.moneda)}</div>)
    : vacio

/** Lo que se debe a cada proveedor: una fila por proveedor, el más atrasado primero. */
export default function PorProveedor({ parametros, pagina, tamano, onPagina, onTamano, hayFiltros, onAbrir }) {
  const consulta = useListado(['compras', 'por-pagar-proveedores'], '/compras/por-pagar/proveedores/', { ...parametros, page: pagina, page_size: tamano }, { enabled: Boolean(parametros.empresa) })
  const filas = consulta.data?.results ?? []

  return (
    <>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Proveedor</th>
                <th className="centrado">Facturas</th>
                <th>Próximo vencimiento</th>
                <th className="num">Vencido</th>
                <th className="num">Total adeudado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={6} icono="wallet" titulo={hayFiltros || parametros.q ? 'Ningún proveedor coincide' : 'No hay deudas pendientes'} descripcion="Los proveedores aparecen aquí mientras tengan compras a crédito sin pagar." />}
              {filas.map((f) => {
                const v = f.dias_atraso > 0 ? { texto: `Vencida hace ${f.dias_atraso} ${f.dias_atraso === 1 ? 'día' : 'días'}`, tono: 'rojo' } : estadoVencimiento(f.proximo_vencimiento)
                return (
                  <tr key={f.proveedor}>
                    <td className="col-texto">
                      <strong>{f.proveedor_nombre}</strong>
                      <span className="sub-texto">
                        {f.tipo_documento} {f.numero_documento}
                        {f.ciudad ? ` · ${f.ciudad}` : ''}
                      </span>
                    </td>
                    <td className="centrado">{f.facturas}</td>
                    <td className="cxp-vence">
                      {fechaCorta(f.proximo_vencimiento)}
                      <span className="pildora" data-tono={v.tono}>{v.texto}</span>
                    </td>
                    <td className="num cxp-vencido">
                      <Montos montos={f.montos} campo="vencido" />
                    </td>
                    <td className="num">
                      <strong>
                        <Montos montos={f.montos} campo="saldo" />
                      </strong>
                    </td>
                    <td className="centrado">
                      <button type="button" className="boton-cabecera" onClick={() => onAbrir(f)}>
                        <Icono nombre="ojo" tam={18} /> Ver deudas
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>
      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={onPagina} onTamano={onTamano} />
    </>
  )
}
