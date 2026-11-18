import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import EstadoVacio from '../../../shared/components/EstadoVacio'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora } from '../ofertas'
import { soles } from '../pedidos'
import '../tienda.css'
import '../ofertas.css'
import '../resenas.css'

const CLAVE = ['tienda', 'reclamos']
const TAMANO = 25
const FILTROS = [
  { valor: 'PENDIENTE', texto: 'Por responder' },
  { valor: 'por_vencer', texto: 'Por vencer' },
  { valor: 'RESPONDIDO', texto: 'Respondidos' },
  { valor: '', texto: 'Todos' },
]

const Dato = ({ etiqueta, children }) =>
  children ? (
    <div className="pedido-dato">
      <dt>{etiqueta}</dt>
      <dd>{children}</dd>
    </div>
  ) : null

/** Cuánto falta para vencer el plazo de respuesta (15 días hábiles). */
function Plazo({ r }) {
  if (r.estado === 'RESPONDIDO') return <span className="pildora" data-tono="verde">Respondido</span>
  if (r.vencido) return <span className="pildora" data-tono="rojo">Plazo vencido</span>
  const tono = r.dias_restantes <= 3 ? 'ambar' : 'gris'
  return (
    <span className="pildora" data-tono={tono}>
      {r.dias_restantes <= 0 ? 'Vence hoy' : `Faltan ${r.dias_restantes} días`}
    </span>
  )
}

function DetalleModal({ id, onCerrar }) {
  const consulta = useQuery({
    queryKey: [...CLAVE, id],
    queryFn: ({ signal }) => api.get(`/tienda/admin/reclamos/${id}/`, { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const r = consulta.data
  const [texto, setTexto] = useState('')
  const [error, setError] = useState('')
  const responder = useMutacion({
    mutationFn: () => api.post(`/tienda/admin/reclamos/${id}/responder/`, { texto: texto.trim() }).then((x) => x.data),
    invalidar: [CLAVE],
    exito: 'Respuesta guardada.',
    avisarError: false,
    alExito: () => setError(''),
  })
  const reenviar = useMutacion({
    mutationFn: () => api.post(`/tienda/admin/reclamos/${id}/reenviar/`, {}).then((x) => x.data),
    invalidar: [CLAVE],
    exito: 'Se volvió a intentar el envío.',
    avisarError: false,
  })
  const alError = { onError: (e) => setError(mensajeDeError(e)) }

  return (
    <Modal titulo={r ? `${r.tipo_texto} N.º ${r.numero}` : 'Reclamo'} subtitulo={r ? `${fechaHora(r.fecha)} · contra ${r.empresa}` : 'Cargando…'} onCerrar={onCerrar} ancho={760}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(r)}>
        {r && (
          <div className="pedido-detalle">
            <div className="pedido-estado-fila">
              <Plazo r={r} />
              <span className="sub-texto">Plazo para responder: hasta el {fechaHora(r.vence_en).slice(0, 10)} (15 días hábiles)</span>
            </div>
            <section aria-label="Consumidor">
              <h3>Consumidor</h3>
              <dl className="pedido-datos">
                <Dato etiqueta="Nombre">{r.nombre}</Dato>
                <Dato etiqueta="Documento">{r.documento}</Dato>
                <Dato etiqueta="Domicilio">{r.domicilio}</Dato>
                <Dato etiqueta="Teléfono">{r.telefono}</Dato>
                <Dato etiqueta="Correo">{r.correo}</Dato>
                <Dato etiqueta="Menor de edad">{r.menor_de_edad ? `Sí · apoderado: ${r.apoderado}` : ''}</Dato>
              </dl>
            </section>
            <section aria-label="Bien contratado">
              <h3>Bien contratado</h3>
              <dl className="pedido-datos">
                <Dato etiqueta="Tipo">{r.bien_tipo === 'PRODUCTO' ? 'Producto' : 'Servicio'}</Dato>
                <Dato etiqueta="Descripción">{r.bien_descripcion}</Dato>
                <Dato etiqueta="Monto reclamado">{r.monto ? soles(r.monto) : ''}</Dato>
                <Dato etiqueta="Pedido">{r.pedido_numero}</Dato>
              </dl>
            </section>
            <section aria-label="Detalle">
              <h3>Detalle del {r.tipo_texto.toLowerCase()}</h3>
              <p className="resena-texto">{r.detalle}</p>
              <h3>Lo que pide el consumidor</h3>
              <p className="resena-texto">{r.pedido_consumidor}</p>
            </section>

            {r.estado === 'RESPONDIDO' ? (
              <section aria-label="Respuesta" className="resena-respuesta">
                <b>Respuesta</b> <span className="sub-texto">({r.respondido_por}, {fechaHora(r.respondido_en)})</span>
                <p className="resena-texto">{r.respuesta}</p>
                {r.respuesta_enviada ? (
                  <span className="sub-texto">Se envió al correo del consumidor.</span>
                ) : (
                  <div>
                    <p role="alert" className="campo-error">No se pudo enviar la respuesta por correo. Reintenta o contacta al consumidor.</p>
                    <button type="button" disabled={reenviar.isPending} onClick={() => reenviar.mutate(undefined, alError)}>
                      {reenviar.isPending ? 'Enviando…' : 'Reenviar la respuesta'}
                    </button>
                  </div>
                )}
              </section>
            ) : (
              <section aria-label="Responder">
                <Campo etiqueta="Tu respuesta al consumidor" error={error} ayuda="Se le envía a su correo y queda registrada. Responde con claridad lo que se hará.">
                  {(p) => <textarea {...p} name="respuesta" rows={5} maxLength={2000} value={texto} onChange={(e) => setTexto(e.target.value)} />}
                </Campo>
                <div className="pagos-pie">
                  <button type="button" className="primario" disabled={responder.isPending || texto.trim().length < 10} onClick={() => responder.mutate(undefined, alError)}>
                    {responder.isPending ? 'Enviando…' : 'Responder y avisar al consumidor'}
                  </button>
                </div>
              </section>
            )}
          </div>
        )}
      </EstadoConsulta>
    </Modal>
  )
}

/** Libro de Reclamaciones: reclamos y quejas de los clientes, con el plazo legal para responder. */
export default function ReclamosTiendaPage() {
  const [filtro, setFiltro] = useState('PENDIENTE')
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [abierto, setAbierto] = useState(null)
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(CLAVE, '/tienda/admin/reclamos/', { estado: filtro, q, page: pagina }, { refetchInterval: 60_000 })
  const filas = consulta.data?.results ?? []
  const r = consulta.data?.resumen

  return (
    <main className="listado tienda-pagina">
      <CabeceraListado
        icono="bell"
        titulo="Libro de Reclamaciones"
        descripcion="Los reclamos y quejas que presentan tus clientes desde la tienda. La ley te da 15 días hábiles para responder; el sistema te avisa cuánto falta."
      />

      {r && (
        <dl className="pedido-datos resenas-resumen" aria-label="Resumen de reclamos">
          <div className="pedido-dato">
            <dt>Por responder</dt>
            <dd>{r.pendientes}</dd>
          </div>
          <div className="pedido-dato">
            <dt>Por vencer (3 días)</dt>
            <dd>{r.por_vencer}</dd>
          </div>
          <div className="pedido-dato">
            <dt>Plazo vencido</dt>
            <dd>{r.vencidos}</dd>
          </div>
          <div className="pedido-dato">
            <dt>Respondidos</dt>
            <dd>{r.respondidos}</dd>
          </div>
        </dl>
      )}

      <div className="ofertas-barra">
        <div className="tienda-segmentos" role="group" aria-label="Filtrar reclamos">
          {FILTROS.map((f) => (
            <button
              key={f.valor || 'todos'}
              type="button"
              aria-pressed={filtro === f.valor}
              onClick={() => {
                setFiltro(f.valor)
                setPagina(1)
              }}
            >
              {f.texto}
            </button>
          ))}
        </div>
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar reclamos"
          placeholder="Número, nombre, documento o pedido…"
        />
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {filas.length === 0 ? (
          <EstadoVacio icono="bell" titulo="No hay reclamos aquí" descripcion="Cuando un cliente presente un reclamo o una queja desde la tienda, aparecerá en esta lista." />
        ) : (
          <ul className="resenas-lista">
            {filas.map((x) => (
              <li key={x.id}>
                <div className="resena-cabeza">
                  <strong>N.º {x.numero}</strong>
                  <span className="pildora" data-tono={x.tipo === 'QUEJA' ? 'morado' : 'azul'}>
                    {x.tipo_texto}
                  </span>
                  <Plazo r={x} />
                </div>
                <p className="resena-texto">{x.detalle.length > 200 ? `${x.detalle.slice(0, 200)}…` : x.detalle}</p>
                <p className="sub-texto">
                  {x.nombre} · {x.documento} · contra {x.empresa} · {fechaHora(x.fecha)}
                </p>
                <div className="envios-acciones">
                  <button type="button" onClick={() => setAbierto(x.id)}>
                    {x.estado === 'PENDIENTE' ? 'Ver y responder' : 'Ver'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <Paginacion pagina={pagina} tamano={TAMANO} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={() => {}} />
      </EstadoConsulta>

      {abierto && <DetalleModal id={abierto} onCerrar={() => setAbierto(null)} />}
    </main>
  )
}
