import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { soles } from '../pedidos'
import '../tienda.css'
import '../metricas.css'

const PERIODOS = [
  { valor: 7, texto: '7 días' },
  { valor: 30, texto: '30 días' },
  { valor: 90, texto: '90 días' },
]

const Cifra = ({ etiqueta, valor, ayuda }) => (
  <div className="metrica-cifra">
    <dt>{etiqueta}</dt>
    <dd>{valor}</dd>
    {ayuda && <small>{ayuda}</small>}
  </div>
)

/** Barras por día (sin librerías: el alto es proporcional al importe). */
function Barras({ serie }) {
  const maximo = Math.max(...serie.map((d) => Number(d.total)), 1)
  return (
    <div className="metrica-barras" role="img" aria-label="Ventas por día">
      {serie.map((d) => (
        <span
          key={d.fecha}
          className="metrica-barra"
          style={{ height: `${Math.max((Number(d.total) / maximo) * 100, d.pedidos ? 4 : 0)}%` }}
          title={`${d.fecha}: ${d.pedidos} pedidos · ${soles(d.total)}`}
        />
      ))}
    </div>
  )
}

const Atencion = ({ n, texto, a, tono = 'ambar' }) =>
  n > 0 ? (
    <li>
      <span className="pildora" data-tono={tono}>
        {n}
      </span>{' '}
      <Link to={a}>{texto}</Link>
    </li>
  ) : null

/** Cómo va la tienda: ventas, embudo, productos que más salen y lo que requiere atención. */
export default function MetricasTiendaPage() {
  const [dias, setDias] = useState(30)
  const consulta = useQuery({
    queryKey: ['tienda', 'metricas', dias],
    queryFn: ({ signal }) => api.get('/tienda/admin/metricas/', { params: { dias }, signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
    refetchInterval: 120_000,
  })
  const d = consulta.data
  const a = d?.atencion
  const hayAtencion = a && (a.por_verificar || a.con_problema || a.por_atender || a.reclamos_pendientes)

  return (
    <main className="listado tienda-pagina">
      <CabeceraListado icono="chart" titulo="Métricas de la tienda" descripcion="Cómo van las ventas web. Los importes incluyen IGV, tal como paga el cliente." />
      <div className="tienda-segmentos" role="group" aria-label="Periodo">
        {PERIODOS.map((p) => (
          <button key={p.valor} type="button" aria-pressed={dias === p.valor} onClick={() => setDias(p.valor)}>
            {p.texto}
          </button>
        ))}
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(d)}>
        {d && (
          <>
            {hayAtencion && (
              <PanelTarjeta id="metricas-atencion" icono="bell" titulo="Requiere tu atención">
                <ul className="metrica-atencion">
                  <Atencion n={a.por_verificar} texto="transferencias por verificar" a="/tienda/pedidos" />
                  <Atencion n={a.con_problema} texto="pedidos con problema (comprobante o reembolso)" a="/tienda/pedidos" tono="rojo" />
                  <Atencion n={a.por_atender} texto="pedidos pagados por atender" a="/tienda/pedidos" />
                  <Atencion n={a.reclamos_vencidos} texto="reclamos con el plazo vencido" a="/tienda/reclamos" tono="rojo" />
                  <Atencion n={a.reclamos_pendientes - a.reclamos_vencidos} texto="reclamos por responder" a="/tienda/reclamos" />
                </ul>
              </PanelTarjeta>
            )}

            <PanelTarjeta id="metricas-ventas" icono="coins" titulo={`Ventas de los últimos ${d.dias} días`}>
              <dl className="metrica-cifras">
                <Cifra etiqueta="Vendido" valor={soles(d.ventas.total)} />
                <Cifra etiqueta="Pedidos cobrados" valor={d.ventas.pedidos} />
                <Cifra etiqueta="Ticket promedio" valor={soles(d.ventas.ticket_promedio)} />
                <Cifra etiqueta="Descontado con cupones" valor={soles(d.ventas.descuentos)} />
              </dl>
              <Barras serie={d.ventas.serie} />
              <p className="sub-texto">
                {d.ventas.serie[0].fecha} → {d.ventas.serie.at(-1).fecha}
              </p>
            </PanelTarjeta>

            <div className="metrica-rejilla">
              <PanelTarjeta id="metricas-embudo" icono="cart" titulo="De pedido a pago">
                <dl className="metrica-cifras">
                  <Cifra etiqueta="Pedidos creados" valor={d.embudo.creados} />
                  <Cifra etiqueta="Cobrados" valor={d.embudo.cobrados} ayuda={d.embudo.tasa_pago !== null ? `${d.embudo.tasa_pago} % de los creados` : undefined} />
                  <Cifra etiqueta="Sin pagar (vencidos o cancelados)" valor={d.embudo.sin_pagar} />
                </dl>
                <p className="sub-texto">
                  Pagan con: tarjeta {d.pago.tarjeta} · Yape {d.pago.yape} · transferencia {d.pago.transferencia}. Entrega: envío {d.entrega.envio} · recojo {d.entrega.recojo}.
                </p>
              </PanelTarjeta>

              <PanelTarjeta id="metricas-clientes" icono="users" titulo="Clientes">
                <dl className="metrica-cifras">
                  <Cifra etiqueta="Cuentas nuevas" valor={d.clientes.nuevos} />
                  <Cifra etiqueta="Compraron" valor={d.clientes.compradores} />
                  <Cifra etiqueta="Cuentas en total" valor={d.clientes.total} />
                </dl>
              </PanelTarjeta>
            </div>

            <PanelTarjeta id="metricas-top" icono="box" titulo="Lo que más se vende">
              {d.top_productos.length === 0 ? (
                <p className="celda-suave">Todavía no hay ventas en este periodo.</p>
              ) : (
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th>Producto</th>
                        <th className="num">Unidades</th>
                        <th className="num">Importe</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.top_productos.map((p) => (
                        <tr key={p.id}>
                          <td data-etiqueta="Producto" className="col-texto">
                            {p.nombre}
                          </td>
                          <td data-etiqueta="Unidades" className="num">
                            {p.unidades}
                          </td>
                          <td data-etiqueta="Importe" className="num">
                            {soles(p.total)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </PanelTarjeta>

            <div className="metrica-rejilla">
              <PanelTarjeta id="metricas-marketing" icono="megaphone" titulo="Marketing">
                <dl className="metrica-cifras">
                  <Cifra etiqueta="Cupones usados" valor={d.cupones.usos} ayuda={`${soles(d.cupones.descontado)} descontados`} />
                  <Cifra etiqueta="Recordatorios de carrito" valor={d.carrito_abandonado.recordatorios} ayuda={`${d.carrito_abandonado.recuperados} compraron · ${soles(d.carrito_abandonado.vendido)}`} />
                </dl>
              </PanelTarjeta>
              <PanelTarjeta id="metricas-interes" icono="chat" titulo="Interés de los clientes">
                <dl className="metrica-cifras">
                  <Cifra etiqueta="Opiniones nuevas" valor={d.opiniones.nuevas} ayuda={`${d.opiniones.sin_respuesta} sin respuesta`} />
                  <Cifra etiqueta="Favoritos guardados" valor={d.interes.favoritos} />
                  <Cifra etiqueta="Piden aviso de stock" valor={d.interes.avisos_pendientes} />
                </dl>
                {d.interes.mas_pedidos.length > 0 && (
                  <>
                    <p className="sub-texto">Agotados que más esperan (conviene reponerlos):</p>
                    <ul className="pedido-lista-simple">
                      {d.interes.mas_pedidos.map((p) => (
                        <li key={p.id}>
                          {p.nombre} · {p.personas} {p.personas === 1 ? 'persona' : 'personas'}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </PanelTarjeta>
            </div>
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
