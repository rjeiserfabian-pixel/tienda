import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import { cantidad, fechaCorta } from '../../almacen/inventario'
import AccionConNotaModal from '../../caja/components/AccionConNotaModal'
import { dinero } from '../../compras/compras'
import ProformaImpresa from '../components/ProformaImpresa'
import ProformaTicket from '../components/ProformaTicket'
import { useImpresionDocumento } from '../hooks/useImpresionDocumento'
import { ESTADOS_PROFORMA } from '../ventas'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../ventas.css'

const RUTA = '/ventas/proformas'

/** Ficha de una proforma: lo cotizado, lo que cobraría cada empresa, imprimirla y venderla. */
export default function ProformaFichaPage() {
  const { id } = useParams()
  const navegar = useNavigate()
  const [anulando, setAnulando] = useState(false)
  const consulta = useQuery({
    queryKey: ['ventas', 'proforma', id],
    queryFn: ({ signal }) => api.get(`/ventas/proformas/${id}/`, { signal }).then((r) => r.data),
  })
  const p = consulta.data
  const { imprimir, portal } = useImpresionDocumento(p ? { tipo: 'proforma', titulo: `Proforma ${p.numero_completo}`, subtitulo: p.cliente_nombre, formatos: { A4: <ProformaImpresa proforma={p} />, TICKET: <ProformaTicket proforma={p} /> } } : null)
  const e = p && ESTADOS_PROFORMA[p.estado_proforma]
  const disponible = p && (p.estado_proforma === 'VIGENTE' || p.estado_proforma === 'VENCIDA')

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={RUTA} texto="Volver a Proformas" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(p)}>
        {p && (
          <>
            <CabeceraListado icono="cotizacion" titulo={`Proforma ${p.numero_completo}`} descripcion={`${fechaCorta(p.fecha)} · ${p.cliente_nombre} · Atendió ${p.vendedor_nombre}`}>
              <span className="pildora" data-tono={e.tono}>
                {e.texto}
              </span>
              <button type="button" className="boton-cabecera" onClick={imprimir}>
                <Icono nombre="documento" tam={18} /> Imprimir
              </button>
              {disponible && (
                <Can permiso="VENTAS.VENDER">
                  <button type="button" className="primario boton-cabecera" onClick={() => navegar(`/ventas/pos?proforma=${p.id}`)}>
                    <Icono nombre="cart" tam={18} /> Vender
                  </button>
                  <button type="button" className="boton-cabecera peligro-suave" onClick={() => setAnulando(true)}>
                    Anular
                  </button>
                </Can>
              )}
            </CabeceraListado>
            {p.estado_proforma === 'VENCIDA' && <p className="compra-aviso">Esta proforma venció el {fechaCorta(p.valida_hasta)}: al venderla los precios se recalculan con las listas de hoy, salvo los que se cambiaron a mano.</p>}
            {p.estado === 'ANULADO' && <p className="compra-aviso">Proforma anulada: {p.motivo_anulacion}</p>}
            <dl className="venta-datos">
              <div>
                <dt>Cliente</dt>
                <dd>
                  {p.cliente_nombre}
                  {p.cliente_documento ? ` · ${p.cliente_documento}` : ''}
                  {p.cliente_contacto ? ` · ${p.cliente_contacto}` : ''}
                </dd>
              </div>
              <div>
                <dt>Válida hasta</dt>
                <dd>{fechaCorta(p.valida_hasta)}</dd>
              </div>
              <div>
                <dt>Lista de precios</dt>
                <dd>{p.lista_nombre || '—'}</dd>
              </div>
              <div>
                <dt>Total</dt>
                <dd>
                  <strong>{dinero(p.total, p.moneda)}</strong>
                </dd>
              </div>
            </dl>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th>Surte</th>
                    <th className="num">Cant.</th>
                    <th className="num">P. unit. sin IGV</th>
                    <th className="num">IGV</th>
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {p.lineas.map((l) => (
                    <tr key={l.id}>
                      <td className="col-texto">
                        {l.descripcion}
                        <span className="sub-texto">
                          {l.codigo} · {l.afectacion_nombre}
                        </span>
                      </td>
                      <td className="celda-suave">{l.empresa_nombre}</td>
                      <td className="num">
                        {cantidad(l.cantidad)} {l.unidad}
                      </td>
                      <td className="num">{dinero(l.precio_unitario, p.moneda)}</td>
                      <td className="num">{dinero(l.igv, p.moneda)}</td>
                      <td className="num">{dinero(l.total, p.moneda)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {p.por_empresa.length > 1 && (
              <dl className="compra-totales compra-totales-ficha">
                {p.por_empresa.map((x) => (
                  <div key={x.empresa}>
                    <dt>{x.nombre}</dt>
                    <dd>{dinero(x.total, p.moneda)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p>Forma de pago cotizada: {p.forma_pago === 'CREDITO' ? 'A crédito (precio de crédito)' : 'Al contado'}</p>
            {p.cliente_direccion && <p>Dirección: {p.cliente_direccion}</p>}
            {p.atencion && <p>Con atención a: {p.atencion}</p>}
            {(p.fecha_entrega || p.lugar_entrega) && <p>Entrega: {[p.fecha_entrega && fechaCorta(p.fecha_entrega), p.lugar_entrega].filter(Boolean).join(' · ')}</p>}
            {p.condiciones && <p>Condiciones: {p.condiciones}</p>}
            {anulando && (
              <AccionConNotaModal
                url={`/ventas/proformas/${p.id}/anular/`}
                invalidar={[['ventas']]}
                titulo="Anular la proforma"
                subtitulo={`${p.numero_completo} · ${p.cliente_nombre}`}
                descripcion="La proforma queda anulada y ya no se puede vender."
                campo="motivo"
                etiqueta="Motivo"
                requerido
                placeholder="Ej. El cliente ya no la necesita"
                boton="Anular proforma"
                exito="Proforma anulada."
                peligro
                onCerrar={() => setAnulando(false)}
              />
            )}
            {portal}
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
