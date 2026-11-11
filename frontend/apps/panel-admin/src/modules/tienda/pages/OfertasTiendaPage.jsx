import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import BannerModal from '../components/BannerModal'
import OfertaModal from '../components/OfertaModal'
import { ESTADOS_BANNER, ESTADOS_OFERTA, FILTROS_ESTADO, fechaHora, soles } from '../ofertas'
import '../tienda.css'
import '../ofertas.css'

const CLAVE_OFERTAS = ['tienda', 'ofertas']
const CLAVE_BANNERS = ['tienda', 'banners']
const TAMANO = 25

/** Miniatura de un banner (la imagen se pide con sesión: funciona aunque la tienda esté cerrada). */
function Miniatura({ banner }) {
  const [direccion, setDireccion] = useState(null)
  useEffect(() => {
    if (!banner.tiene_escritorio) {
      setDireccion(null)
      return undefined
    }
    const control = new AbortController()
    let url = null
    api
      .get(`/tienda/admin/banners/${banner.id}/imagen/escritorio/`, { responseType: 'blob', signal: control.signal })
      .then((r) => {
        url = URL.createObjectURL(r.data)
        setDireccion(url)
      })
      .catch(() => !control.signal.aborted && setDireccion(null))
    return () => {
      control.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [banner.id, banner.tiene_escritorio, banner.version])
  return <div className="banner-miniatura">{direccion ? <img src={direccion} alt={banner.alt} loading="lazy" /> : <span className="celda-suave">Sin imagen</span>}</div>
}

function PestanaOfertas() {
  const [estado, setEstado] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [abierta, setAbierta] = useState(null) // {} = nueva
  const [aEliminar, setAEliminar] = useState(null)
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(CLAVE_OFERTAS, '/tienda/admin/ofertas/', { estado, q, page: pagina }, { refetchInterval: 60_000 })
  const filas = consulta.data?.results ?? []
  const verMargen = Boolean(consulta.data?.ver_margen)

  const eliminar = useMutacion({
    mutationFn: (o) => api.delete(`/tienda/admin/ofertas/${o.id}/`),
    invalidar: [CLAVE_OFERTAS],
    exito: 'Oferta eliminada.',
    alExito: () => setAEliminar(null),
  })
  const alternar = useMutacion({
    mutationFn: (o) => api.patch(`/tienda/admin/ofertas/${o.id}/`, { activa: !o.activa }).then((r) => r.data),
    invalidar: [CLAVE_OFERTAS],
  })

  return (
    <>
      <div className="ofertas-barra">
        <div className="tienda-segmentos" role="group" aria-label="Estado de las ofertas">
          {FILTROS_ESTADO.map((f) => (
            <button
              key={f.valor || 'todas'}
              type="button"
              aria-pressed={estado === f.valor}
              onClick={() => {
                setEstado(f.valor)
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
          etiqueta="Buscar ofertas"
          placeholder="Producto o código…"
        />
        <button type="button" className="boton-cabecera primario" onClick={() => setAbierta({})}>
          <Icono nombre="agregar" tam={18} /> Nueva oferta
        </button>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos tabla-ofertas">
            <thead>
              <tr>
                <th>Producto</th>
                <th className="num">Precio normal</th>
                <th className="num">Oferta</th>
                <th>Vigencia</th>
                {verMargen && <th className="num">Margen</th>}
                <th>Estado</th>
                <th>
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia
                  columnas={verMargen ? 7 : 6}
                  icono="megaphone"
                  titulo="Todavía no hay ofertas"
                  descripcion="Crea una oferta para que un producto salga con precio especial y cuenta regresiva en la tienda."
                />
              )}
              {filas.map((o) => {
                const e = ESTADOS_OFERTA[o.estado] ?? { texto: o.estado, tono: 'gris' }
                return (
                  <tr key={o.id}>
                    <td data-etiqueta="Producto" className="col-texto">
                      {o.producto.nombre}
                      <span className="sub-texto">
                        Código {o.producto.codigo}
                        {o.etiqueta ? ` · ${o.etiqueta}` : ''}
                      </span>
                    </td>
                    <td data-etiqueta="Precio normal" className="num">
                      {soles(o.precio_normal)}
                      <span className="sub-texto">sin IGV</span>
                    </td>
                    <td data-etiqueta="Oferta" className="num">
                      <b>{soles(o.precio_oferta)}</b>
                      {o.ahorro_pct ? <span className="sub-texto">-{o.ahorro_pct} %</span> : null}
                    </td>
                    <td data-etiqueta="Vigencia">
                      {fechaHora(o.desde)}
                      <span className="sub-texto">hasta {fechaHora(o.hasta)}</span>
                    </td>
                    {verMargen && (
                      <td data-etiqueta="Margen" className="num">
                        {o.margen_pct != null ? `${o.margen_pct} %` : '—'}
                      </td>
                    )}
                    <td data-etiqueta="Estado">
                      <span className="pildora" data-tono={e.tono}>
                        {e.texto}
                      </span>
                    </td>
                    <td data-etiqueta="Acciones" className="celda-acciones">
                      <div className="envios-acciones">
                        <button type="button" className="icono-boton" aria-label={`${o.activa ? 'Pausar' : 'Reanudar'} la oferta de ${o.producto.nombre}`} disabled={alternar.isPending} onClick={() => alternar.mutate(o)}>
                          <Icono nombre={o.activa ? 'apagar' : 'reactivar'} tam={18} />
                        </button>
                        <button type="button" className="icono-boton" aria-label={`Editar la oferta de ${o.producto.nombre}`} onClick={() => setAbierta(o)}>
                          <Icono nombre="lapiz" tam={18} />
                        </button>
                        <button type="button" className="icono-boton" aria-label={`Eliminar la oferta de ${o.producto.nombre}`} onClick={() => setAEliminar(o)}>
                          <Icono nombre="papelera" tam={18} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Paginacion pagina={pagina} tamano={TAMANO} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={() => {}} />
      </EstadoConsulta>

      {abierta && <OfertaModal oferta={abierta.id ? abierta : null} onCerrar={() => setAbierta(null)} />}
      {aEliminar && (
        <ConfirmarModal
          titulo="¿Eliminar la oferta?"
          mensaje={`Se borra la oferta de «${aEliminar.producto.nombre}». Los pedidos ya creados no cambian de precio.`}
          textoConfirmar="Eliminar"
          enviando={eliminar.isPending}
          onConfirmar={() => eliminar.mutate(aEliminar)}
          onCerrar={() => setAEliminar(null)}
        />
      )}
    </>
  )
}

function PestanaBanners() {
  const [abierto, setAbierto] = useState(null)
  const [aEliminar, setAEliminar] = useState(null)
  const consulta = useQuery({
    queryKey: CLAVE_BANNERS,
    queryFn: ({ signal }) => api.get('/tienda/admin/banners/', { signal }).then((r) => r.data),
    refetchInterval: 60_000,
  })
  const banners = consulta.data ?? []

  const eliminar = useMutacion({
    mutationFn: (b) => api.delete(`/tienda/admin/banners/${b.id}/`),
    invalidar: [CLAVE_BANNERS],
    exito: 'Banner eliminado.',
    alExito: () => setAEliminar(null),
  })
  const alternar = useMutacion({
    mutationFn: (b) => api.patch(`/tienda/admin/banners/${b.id}/`, { activo: !b.activo }).then((r) => r.data),
    invalidar: [CLAVE_BANNERS],
  })

  return (
    <>
      <div className="ofertas-barra">
        <p className="celda-suave ofertas-nota">Las imágenes grandes del inicio de la tienda. Se muestran hasta 8 a la vez, en el orden que indiques.</p>
        <button type="button" className="boton-cabecera primario" onClick={() => setAbierto({})}>
          <Icono nombre="agregar" tam={18} /> Nuevo banner
        </button>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {banners.length === 0 ? (
          <div className="ofertas-vacio">
            <Icono nombre="camara" tam={34} />
            <h3>Todavía no hay banners</h3>
            <p>Sin banners, el inicio de la tienda muestra su portada normal. Sube uno para anunciar una campaña.</p>
          </div>
        ) : (
          <ul className="banners-lista">
            {banners.map((b) => {
              const e = ESTADOS_BANNER[b.estado] ?? { texto: b.estado, tono: 'gris' }
              return (
                <li key={b.id} className="banner-tarjeta" data-apagado={!b.activo || undefined}>
                  <Miniatura banner={b} />
                  <div className="banner-cuerpo">
                    <div className="banner-titulo">
                      <h4>{b.titulo}</h4>
                      <span className="pildora" data-tono={e.tono}>
                        {e.texto}
                      </span>
                    </div>
                    {b.subtitulo && <p className="celda-suave">{b.subtitulo}</p>}
                    <p className="celda-suave">
                      Orden {b.orden}
                      {b.enlace ? ` · ${b.enlace}` : ''}
                    </p>
                    {(b.desde || b.hasta) && (
                      <p className="celda-suave">
                        {b.desde ? `Desde ${fechaHora(b.desde)}` : ''} {b.hasta ? `hasta ${fechaHora(b.hasta)}` : ''}
                      </p>
                    )}
                    <div className="envios-acciones">
                      <button type="button" className="icono-boton" aria-label={`${b.activo ? 'Pausar' : 'Reanudar'} el banner ${b.titulo}`} disabled={alternar.isPending} onClick={() => alternar.mutate(b)}>
                        <Icono nombre={b.activo ? 'apagar' : 'reactivar'} tam={18} />
                      </button>
                      <button type="button" className="icono-boton" aria-label={`Editar el banner ${b.titulo}`} onClick={() => setAbierto(b)}>
                        <Icono nombre="lapiz" tam={18} />
                      </button>
                      <button type="button" className="icono-boton" aria-label={`Eliminar el banner ${b.titulo}`} onClick={() => setAEliminar(b)}>
                        <Icono nombre="papelera" tam={18} />
                      </button>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </EstadoConsulta>

      {abierto && <BannerModal banner={abierto.id ? abierto : null} onCerrar={() => setAbierto(null)} />}
      {aEliminar && (
        <ConfirmarModal
          titulo="¿Eliminar el banner?"
          mensaje={`Se quita «${aEliminar.titulo}» del inicio de la tienda.`}
          textoConfirmar="Eliminar"
          enviando={eliminar.isPending}
          onConfirmar={() => eliminar.mutate(aEliminar)}
          onCerrar={() => setAEliminar(null)}
        />
      )}
    </>
  )
}

/** Ofertas con fecha de fin (cuenta regresiva) y banners del inicio de la tienda. */
export default function OfertasTiendaPage() {
  const [pestana, setPestana] = useState('ofertas')
  return (
    <main className="listado tienda-pagina ofertas-pagina">
      <CabeceraListado icono="megaphone" titulo="Ofertas y banners" descripcion="Precios especiales con cuenta regresiva y las imágenes promocionales del inicio de la tienda." />
      <div className="tienda-segmentos ofertas-pestanas" role="group" aria-label="Sección">
        <button type="button" aria-pressed={pestana === 'ofertas'} onClick={() => setPestana('ofertas')}>
          Ofertas
        </button>
        <button type="button" aria-pressed={pestana === 'banners'} onClick={() => setPestana('banners')}>
          Banners
        </button>
      </div>
      {pestana === 'ofertas' ? <PestanaOfertas /> : <PestanaBanners />}
    </main>
  )
}
