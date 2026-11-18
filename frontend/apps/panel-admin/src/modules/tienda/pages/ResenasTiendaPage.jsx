import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import EstadoVacio from '../../../shared/components/EstadoVacio'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora } from '../ofertas'
import '../tienda.css'
import '../ofertas.css'
import '../cupones.css'
import '../resenas.css'

const CLAVE = ['tienda', 'resenas']
const CLAVE_CONFIG = ['tienda', 'resenas-config']
const TAMANO = 25

const FILTROS = [
  { valor: '', texto: 'Todas' },
  { valor: 'PUBLICADA', texto: 'Publicadas' },
  { valor: 'sin_respuesta', texto: 'Sin respuesta' },
  { valor: 'OCULTA', texto: 'Ocultas' },
]

const Estrellas = ({ n }) => (
  <span className="resena-estrellas" role="img" aria-label={`${n} de 5 estrellas`}>
    {'★'.repeat(n)}
    <i>{'★'.repeat(5 - n)}</i>
  </span>
)

/** Pedir la reseña por correo unos días después de entregar. */
function PedirPorCorreo() {
  const consulta = useQuery({
    queryKey: CLAVE_CONFIG,
    queryFn: ({ signal }) => api.get('/tienda/admin/resenas/configuracion/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const d = consulta.data
  const [form, setForm] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (d) setForm({ pedir_activo: d.pedir_activo, pedir_dias: String(d.pedir_dias) })
  }, [d])
  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/tienda/admin/resenas/configuracion/', cuerpo).then((r) => r.data),
    invalidar: [CLAVE_CONFIG],
    exito: 'Configuración guardada.',
    avisarError: false,
  })
  if (!d || !form) return null
  const cambiado = form.pedir_activo !== d.pedir_activo || form.pedir_dias !== String(d.pedir_dias)
  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    const dias = Number(form.pedir_dias)
    if (!(Number.isInteger(dias) && dias >= 1 && dias <= 30)) return setError('Entre 1 y 30 días.')
    guardar.mutate({ pedir_activo: form.pedir_activo, pedir_dias: dias }, { onError: (e) => setError(mensajeDeError(e)) })
  }
  return (
    <PanelTarjeta
      id="resenas-correo"
      icono="correo"
      titulo="Pedir la reseña por correo"
      descripcion="Unos días después de entregar un pedido se le envía un correo con el enlace a cada producto. Solo a clientes que aceptaron recibir comunicaciones, y con enlace de baja."
    >
      <form onSubmit={enviar} noValidate className="envios-form">
        <Interruptor
          activo={form.pedir_activo}
          onCambio={(v) => setForm((f) => ({ ...f, pedir_activo: v }))}
          texto={form.pedir_activo ? 'Se pide la reseña' : 'No se pide la reseña'}
          descripcion="Las reseñas se publican solas; tú puedes ocultar las que no corresponda."
        />
        <Campo etiqueta="Días después de entregar" error={error} ayuda="Se envía una sola vez por pedido (de 1 a 30 días).">
          {(p) => <input {...p} name="pedir_dias" inputMode="numeric" value={form.pedir_dias} onChange={(e) => setForm((f) => ({ ...f, pedir_dias: e.target.value }))} />}
        </Campo>
        <div className="pagos-pie">
          <button type="submit" className="primario" disabled={!cambiado || guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </PanelTarjeta>
  )
}

/** Responder en público o explicar por qué se oculta: un texto corto. */
function TextoModal({ titulo, subtitulo, etiqueta, ayuda, inicial = '', obligatorio = false, textoBoton, enviando, onEnviar, onCerrar }) {
  const [texto, setTexto] = useState(inicial)
  const [error, setError] = useState('')
  const enviar = (evento) => {
    evento.preventDefault()
    if (obligatorio && texto.trim().length < 3) return setError('Escribe unas palabras.')
    onEnviar(texto.trim(), (e) => setError(mensajeDeError(e)))
  }
  return (
    <Modal titulo={titulo} subtitulo={subtitulo} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate className="envios-form">
        <Campo etiqueta={etiqueta} ayuda={ayuda} error={error}>
          {(p) => <textarea {...p} name="texto" rows={4} maxLength={600} value={texto} onChange={(e) => setTexto(e.target.value)} />}
        </Campo>
        <div className="pagos-pie">
          <button type="submit" className="primario" disabled={enviando}>
            {enviando ? 'Guardando…' : textoBoton}
          </button>
          <button type="button" onClick={onCerrar} disabled={enviando}>
            Cancelar
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Reseñas de los productos: ver, responder y ocultar. */
export default function ResenasTiendaPage() {
  const [filtro, setFiltro] = useState('')
  const [estrellas, setEstrellas] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [respondiendo, setRespondiendo] = useState(null)
  const [ocultando, setOcultando] = useState(null)
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(CLAVE, '/tienda/admin/resenas/', { estado: filtro, estrellas, q, page: pagina }, { refetchInterval: 60_000 })
  const filas = consulta.data?.results ?? []
  const r = consulta.data?.resumen

  const accion = (ruta, cuerpo, exito) => ({
    mutationFn: ({ id, ...datos }) => api.post(`/tienda/admin/resenas/${id}/${ruta}/`, { ...cuerpo, ...datos }).then((x) => x.data),
    invalidar: [CLAVE],
    exito,
    avisarError: false,
  })
  const responder = useMutacion({ ...accion('responder', {}, 'Respuesta guardada.'), alExito: () => setRespondiendo(null) })
  const ocultar = useMutacion({ ...accion('ocultar', {}, 'Reseña oculta: ya no se ve en la tienda.'), alExito: () => setOcultando(null) })
  const mostrar = useMutacion(accion('mostrar', {}, 'Reseña publicada de nuevo.'))

  return (
    <main className="listado tienda-pagina">
      <CabeceraListado
        icono="chat"
        titulo="Reseñas"
        descripcion="Opiniones de clientes que ya recibieron el producto. Se publican solas; si alguna no corresponde, la ocultas. Puedes responder en público."
      />

      <PedirPorCorreo />

      {r && (
        <dl className="pedido-datos resenas-resumen" aria-label="Resumen de reseñas">
          <div className="pedido-dato">
            <dt>Promedio</dt>
            <dd>{r.promedio ? `${r.promedio.toLocaleString('es-PE', { minimumFractionDigits: 1 })} ★` : '—'}</dd>
          </div>
          <div className="pedido-dato">
            <dt>Publicadas</dt>
            <dd>{r.publicadas}</dd>
          </div>
          <div className="pedido-dato">
            <dt>Sin respuesta</dt>
            <dd>{r.sin_respuesta}</dd>
          </div>
          <div className="pedido-dato">
            <dt>Ocultas</dt>
            <dd>{r.ocultas}</dd>
          </div>
        </dl>
      )}

      <div className="ofertas-barra">
        <div className="tienda-segmentos" role="group" aria-label="Filtrar reseñas">
          {FILTROS.map((f) => (
            <button
              key={f.valor || 'todas'}
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
        <select
          aria-label="Filtrar por estrellas"
          value={estrellas}
          onChange={(e) => {
            setEstrellas(e.target.value)
            setPagina(1)
          }}
        >
          <option value="">Todas las estrellas</option>
          {[5, 4, 3, 2, 1].map((n) => (
            <option key={n} value={n}>
              {n} {n === 1 ? 'estrella' : 'estrellas'}
            </option>
          ))}
        </select>
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar reseñas"
          placeholder="Producto, cliente o texto…"
        />
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {filas.length === 0 ? (
          <EstadoVacio icono="chat" titulo="Todavía no hay reseñas" descripcion="Aparecerán aquí cuando un cliente opine de un producto que recibió." />
        ) : (
          <ul className="resenas-lista">
            {filas.map((x) => (
              <li key={x.id} className={x.estado === 'OCULTA' ? 'oculta' : ''}>
                <div className="resena-cabeza">
                  <Estrellas n={x.estrellas} />
                  <strong>{x.producto}</strong>
                  <span className="pildora" data-tono={x.estado === 'OCULTA' ? 'gris' : 'verde'}>
                    {x.estado_texto}
                  </span>
                </div>
                {x.titulo && <p className="resena-titulo">{x.titulo}</p>}
                {x.comentario && <p className="resena-texto">{x.comentario}</p>}
                <p className="sub-texto">
                  {x.cliente} · Pedido {x.pedido} · {fechaHora(x.fecha)}
                  {x.editada_en ? ' · editada' : ''}
                </p>
                {x.oculta_motivo && <p className="sub-texto">Motivo para ocultarla: {x.oculta_motivo}</p>}
                {x.respuesta && (
                  <div className="resena-respuesta">
                    <b>Tu respuesta</b> <span className="sub-texto">({x.respuesta_por}, {fechaHora(x.respuesta_en)})</span>
                    <p>{x.respuesta}</p>
                  </div>
                )}
                <div className="envios-acciones">
                  <button type="button" onClick={() => setRespondiendo(x)}>
                    {x.respuesta ? 'Editar respuesta' : 'Responder'}
                  </button>
                  {x.estado === 'OCULTA' ? (
                    <button type="button" disabled={mostrar.isPending} onClick={() => mostrar.mutate({ id: x.id })}>
                      Volver a publicar
                    </button>
                  ) : (
                    <button type="button" onClick={() => setOcultando(x)}>
                      Ocultar
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <Paginacion pagina={pagina} tamano={TAMANO} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={() => {}} />
      </EstadoConsulta>

      {respondiendo && (
        <TextoModal
          titulo="Responder al cliente"
          subtitulo={`${respondiendo.producto} · ${respondiendo.cliente}`}
          etiqueta="Tu respuesta (se ve en la tienda)"
          ayuda="Sé amable y breve. No se permiten enlaces. Déjalo vacío para quitar la respuesta."
          inicial={respondiendo.respuesta}
          textoBoton="Guardar respuesta"
          enviando={responder.isPending}
          onEnviar={(texto, alError) => responder.mutate({ id: respondiendo.id, texto }, { onError: alError })}
          onCerrar={() => setRespondiendo(null)}
        />
      )}
      {ocultando && (
        <TextoModal
          titulo="Ocultar reseña"
          subtitulo={`${ocultando.producto} · ${ocultando.cliente}`}
          etiqueta="Motivo (solo lo ves tú, opcional)"
          ayuda="Úsalo cuando la reseña tenga insultos, datos personales o no trate del producto. No cuenta en el promedio."
          textoBoton="Ocultar reseña"
          enviando={ocultar.isPending}
          onEnviar={(motivo, alError) => ocultar.mutate({ id: ocultando.id, motivo }, { onError: alError })}
          onCerrar={() => setOcultando(null)}
        />
      )}
    </main>
  )
}
