import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import ImagenProtegida from '../../almacen/components/ImagenProtegida'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { avanceDeFicha, faltantesDeFicha } from '../tienda'
import { useTodasLasCategorias } from '../hooks/useTodasLasCategorias'
import '../../almacen/productos.css'
import '../tienda.css'

const URL_PRODUCTOS = '/mantenimiento/productos/'
const RUTA_FICHA = '/almacen/productos'

/** Cantidad de productos activos con cada estado de publicación (solo el total, no la lista). */
function useConteo(publicado) {
  return useQuery({
    queryKey: ['tienda', 'conteo', publicado],
    queryFn: ({ signal }) =>
      api.get(URL_PRODUCTOS, { params: { publicado, estado: 'ACTIVO', page_size: 10 }, signal }).then((r) => r.data.count),
    staleTime: 30_000,
  })
}

function Resumen({ icono, valor, texto, ayuda, tono }) {
  return (
    <article className="tienda-resumen-tarjeta" data-tono={tono}>
      <span className="tienda-resumen-icono" aria-hidden="true">
        <Icono nombre={icono} tam={22} />
      </span>
      <div>
        <strong>{valor ?? '—'}</strong>
        <span>{texto}</span>
        {ayuda && <small>{ayuda}</small>}
      </div>
    </article>
  )
}

/** Interruptor pequeño para la fila: se lee y se opera con teclado y lector de pantalla. */
function Conmutador({ activo, onCambio, etiqueta, deshabilitado, ocupado, titulo }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={activo}
      aria-label={etiqueta}
      title={titulo}
      className="tienda-conmutador"
      disabled={deshabilitado || ocupado}
      data-ocupado={ocupado || undefined}
      onClick={() => onCambio(!activo)}
    >
      <span className="tienda-conmutador-pista" aria-hidden="true" />
    </button>
  )
}

const PUBLICACION = [
  ['', 'Todos'],
  ['1', 'En tienda'],
  ['0', 'Sin publicar'],
]

/** Productos en tienda: qué se muestra, qué se destaca y qué le falta a cada ficha. */
export default function ProductosTiendaPage() {
  const { tiene } = usePermisos()
  const puedeEditar = tiene('MANTENIMIENTO.PRODUCTOS.EDITAR', { organizacion: true })
  const veEspecificaciones = tiene('MANTENIMIENTO.CLASIFICACION.VER', { organizacion: true })
  const queryClient = useQueryClient()

  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState({ categoria: '', marca: '', publicado: '' })
  const [soloIncompletas, setSoloIncompletas] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [errores, setErrores] = useState({}) // id del producto → mensaje del servidor
  const q = useDebounce(busqueda, 400)

  const categorias = useTodasLasCategorias()
  const marcas = useOpciones('/mantenimiento/marcas/')
  const enTienda = useConteo('1')
  const sinPublicar = useConteo('0')

  const consulta = useListado(['tienda', 'productos'], URL_PRODUCTOS, { q, ...filtros, page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []
  const visibles = useMemo(() => (soloIncompletas ? filas.filter((p) => faltantesDeFicha(p).length > 0) : filas), [filas, soloIncompletas])
  const incompletasEnPagina = useMemo(() => filas.filter((p) => faltantesDeFicha(p).length > 0).length, [filas])
  const destacadosEnPagina = useMemo(() => filas.filter((p) => p.destacado).length, [filas])

  const filtrar = (campo, valor) => {
    setFiltros((previo) => ({ ...previo, [campo]: valor }))
    setPagina(1)
  }

  const cambiar = useMutation({
    mutationFn: ({ producto, campo, valor }) => api.patch(`${URL_PRODUCTOS}${producto.id}/`, { [campo]: valor }).then((r) => r.data),
    onSuccess: (_, { producto }) => {
      setErrores((previo) => {
        const resto = { ...previo }
        delete resto[producto.id]
        return resto
      })
      queryClient.invalidateQueries({ queryKey: ['tienda'] })
      queryClient.invalidateQueries({ queryKey: ['productos'] })
    },
    onError: (error, { producto }) => {
      const detalle = erroresDeCampo(error)
      const mensaje = detalle.publicado_web || detalle.destacado || detalle.es_nuevo || mensajeDeError(error)
      setErrores((previo) => ({ ...previo, [producto.id]: mensaje }))
    },
  })
  const ocupadoEn = (producto, campo) =>
    cambiar.isPending && cambiar.variables?.producto.id === producto.id && cambiar.variables?.campo === campo

  const opcionesCategoria = categorias.data ?? []

  return (
    <main className="listado tienda-pagina">
      <CabeceraListado
        icono="store"
        titulo="Productos en tienda"
        descripcion="Decide qué productos se muestran en la tienda virtual, cuáles se destacan y qué le falta a cada ficha."
      >
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar productos"
          placeholder="Buscar producto…"
        />
        <select className="boton-cabecera" aria-label="Categoría" value={filtros.categoria} onChange={(e) => filtrar('categoria', e.target.value)}>
          <option value="">Todas las categorías</option>
          {opcionesCategoria.map((c) => (
            <option key={c.id} value={c.id}>{c.familia_nombre} › {c.nombre}</option>
          ))}
        </select>
        <select className="boton-cabecera" aria-label="Marca" value={filtros.marca} onChange={(e) => filtrar('marca', e.target.value)}>
          <option value="">Todas las marcas</option>
          {(marcas.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>{m.nombre}</option>
          ))}
        </select>
        {veEspecificaciones && (
          <Link to="/tienda/especificaciones" className="boton-cabecera">
            <Icono nombre="checklist" tam={19} /> Especificaciones
          </Link>
        )}
      </CabeceraListado>

      <section className="tienda-resumen" aria-label="Resumen de la tienda">
        <Resumen icono="store" tono="ok" valor={enTienda.data} texto="En tienda" ayuda="Productos activos publicados" />
        <Resumen icono="package" valor={sinPublicar.data} texto="Sin publicar" ayuda="Productos activos que aún no se muestran" />
        <Resumen icono="tendencia" valor={consulta.data ? destacadosEnPagina : undefined} texto="Destacados" ayuda="En esta página" />
        <Resumen icono="checklist" tono={incompletasEnPagina ? 'aviso' : 'ok'} valor={consulta.data ? incompletasEnPagina : undefined} texto="Fichas incompletas" ayuda="En esta página" />
      </section>

      <div className="tienda-barra">
        <div className="tienda-segmentos" role="group" aria-label="Publicación en la tienda">
          {PUBLICACION.map(([valor, texto]) => (
            <button key={valor || 'todos'} type="button" aria-pressed={filtros.publicado === valor} onClick={() => filtrar('publicado', valor)}>
              {texto}
            </button>
          ))}
        </div>
        <label className="tienda-casilla">
          <input type="checkbox" checked={soloIncompletas} onChange={(e) => setSoloIncompletas(e.target.checked)} />
          <span>Solo fichas incompletas <small>(de esta página)</small></span>
        </label>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos tabla-tienda">
            <thead>
              <tr>
                <th scope="col"><span className="sr-only">Foto</span></th>
                <th scope="col">Producto</th>
                <th scope="col" className="centrado">En tienda</th>
                <th scope="col" className="centrado">Destacado</th>
                <th scope="col" className="centrado">Novedad</th>
                <th scope="col">Ficha</th>
                <th scope="col" className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {visibles.length === 0 && (
                <FilaVacia
                  columnas={7}
                  icono="store"
                  titulo={soloIncompletas ? 'No hay fichas incompletas en esta página' : 'No hay productos con esos filtros'}
                  descripcion={soloIncompletas ? 'Desmarca el filtro o cambia de página para ver más.' : 'Cambia la búsqueda o los filtros.'}
                />
              )}
              {visibles.map((p) => {
                const faltan = faltantesDeFicha(p)
                const avance = avanceDeFicha(p)
                const sinPermiso = puedeEditar ? undefined : 'No tienes permiso para editar productos'
                return (
                  <tr key={p.id}>
                    <td className="tienda-celda-foto">
                      {p.foto_principal ? (
                        <ImagenProtegida url={`/mantenimiento/productos/${p.id}/fotos/${p.foto_principal}/imagen/?tam=mini`} alt={p.nombre} className="producto-miniatura" />
                      ) : (
                        <span className="producto-miniatura imagen-vacia" role="img" aria-label="Sin foto">
                          <Icono nombre="camara" tam={20} />
                        </span>
                      )}
                    </td>
                    <td className="tienda-celda-producto">
                      <Link to={`${RUTA_FICHA}/${p.id}`} className="tienda-nombre">{p.nombre}</Link>
                      <small className="celda-suave producto-sub">
                        {p.codigo} · {[p.marca_nombre, `${p.familia_nombre} › ${p.categoria_nombre}`].filter(Boolean).join(' · ')}
                      </small>
                      {errores[p.id] && <small role="alert" className="campo-error tienda-error">{errores[p.id]}</small>}
                    </td>
                    <td className="centrado" data-label="En tienda">
                      <Conmutador
                        activo={p.publicado_web}
                        etiqueta={`${p.publicado_web ? 'Quitar de' : 'Mostrar en'} la tienda: ${p.nombre}`}
                        titulo={sinPermiso}
                        deshabilitado={!puedeEditar}
                        ocupado={ocupadoEn(p, 'publicado_web')}
                        onCambio={(valor) => cambiar.mutate({ producto: p, campo: 'publicado_web', valor })}
                      />
                    </td>
                    <td className="centrado" data-label="Destacado">
                      <Conmutador
                        activo={p.destacado}
                        etiqueta={`Destacado: ${p.nombre}`}
                        titulo={sinPermiso}
                        deshabilitado={!puedeEditar}
                        ocupado={ocupadoEn(p, 'destacado')}
                        onCambio={(valor) => cambiar.mutate({ producto: p, campo: 'destacado', valor })}
                      />
                    </td>
                    <td className="centrado" data-label="Novedad">
                      <Conmutador
                        activo={p.es_nuevo}
                        etiqueta={`Novedad: ${p.nombre}`}
                        titulo={sinPermiso}
                        deshabilitado={!puedeEditar}
                        ocupado={ocupadoEn(p, 'es_nuevo')}
                        onCambio={(valor) => cambiar.mutate({ producto: p, campo: 'es_nuevo', valor })}
                      />
                    </td>
                    <td className="tienda-celda-ficha" data-label="Ficha">
                      <div className="tienda-medidor" role="img" aria-label={`Ficha al ${avance} %`}>
                        <span style={{ width: `${avance}%` }} data-completa={faltan.length === 0 || undefined} />
                      </div>
                      {faltan.length === 0 ? (
                        <small className="tienda-ficha-ok">Completa</small>
                      ) : (
                        <small className="celda-suave">Falta: {faltan.join(', ')}</small>
                      )}
                    </td>
                    <td className="centrado tienda-celda-acciones">
                      <Link to={`${RUTA_FICHA}/${p.id}`} className="boton-cabecera tienda-editar" aria-label={`Editar la ficha de ${p.nombre}`}>
                        <Icono nombre="lapiz" tam={17} /> Editar ficha
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion
        pagina={pagina}
        tamano={tamano}
        total={consulta.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />
    </main>
  )
}
