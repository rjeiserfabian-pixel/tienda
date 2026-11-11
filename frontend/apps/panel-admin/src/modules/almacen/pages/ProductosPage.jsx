import { useState } from 'react'
import { Link } from 'react-router-dom'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { MODO_LECTURA } from '../../../shared/hooks/useModoLectura'
import { ESTADOS } from '../../mantenimiento/maestros'
import ImagenProtegida from '../components/ImagenProtegida'
import { useOpciones } from '../hooks/useOpciones'
import { soles, TIPOS_PRODUCTO } from '../utilidades'
import '../productos.css'

const RUTA = '/almacen/productos'

/** Lista de productos: búsqueda, filtros, miniatura, precio de la lista principal y paginación. */
export default function ProductosPage() {
  const { tiene } = usePermisos()
  const puedeEditar = tiene('MANTENIMIENTO.PRODUCTOS.EDITAR', { organizacion: true })
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState({ estado: '', tipo: '', familia: '', publicado: '' })
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda, 400)

  const familias = useOpciones('/mantenimiento/familias/')
  const listas = useOpciones('/mantenimiento/listas-precio/')
  const principal = (listas.data ?? []).find((l) => l.es_principal)

  const consulta = useListado(['productos'], '/mantenimiento/productos/', { q, ...filtros, page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []
  const desde = (pagina - 1) * tamano + 1

  const filtrar = (campo, valor) => {
    setFiltros((previo) => ({ ...previo, [campo]: valor }))
    setPagina(1)
  }

  const precioPrincipal = (producto) => {
    const fila = producto.precios.find((x) => x.lista === principal?.id)
    return fila ? soles(fila.precio) : '—'
  }

  return (
    <main className="listado">
      <CabeceraListado icono="package" titulo="Productos" descripcion="Todo lo que compras y vendes. El catálogo es uno solo para todas tus empresas.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar productos"
          placeholder="Buscar producto…"
        />
        <select className="boton-cabecera" aria-label="Familia" value={filtros.familia} onChange={(e) => filtrar('familia', e.target.value)}>
          <option value="">Todas las familias</option>
          {(familias.data ?? []).map((f) => (
            <option key={f.id} value={f.id}>{f.nombre}</option>
          ))}
        </select>
        <select className="boton-cabecera" aria-label="Tipo" value={filtros.tipo} onChange={(e) => filtrar('tipo', e.target.value)}>
          <option value="">Bienes y servicios</option>
          {TIPOS_PRODUCTO.map(([v, t]) => (
            <option key={v} value={v}>{t.split(' (')[0]}s</option>
          ))}
        </select>
        <select className="boton-cabecera" aria-label="Estado" value={filtros.estado} onChange={(e) => filtrar('estado', e.target.value)}>
          <option value="">Todos los estados</option>
          {ESTADOS.map(([v, t]) => (
            <option key={v} value={v}>{t}s</option>
          ))}
        </select>
        <select className="boton-cabecera" aria-label="Publicación en la tienda" value={filtros.publicado} onChange={(e) => filtrar('publicado', e.target.value)}>
          <option value="">Con y sin tienda</option>
          <option value="1">En tienda</option>
          <option value="0">Sin publicar</option>
        </select>
        <Can permiso="MANTENIMIENTO.PRODUCTOS.CREAR" organizacion>
          <Link to={`${RUTA}/nuevo`} className="primario boton-cabecera">
            <Icono nombre="agregar" tam={20} /> Nuevo producto
          </Link>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Foto</th>
                <th>Código</th>
                <th>Producto</th>
                <th>Familia › Categoría</th>
                <th>Unidad</th>
                <th>{principal ? `Precio ${principal.nombre}` : 'Precio'}</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={9} icono="package" titulo="No hay productos con esos filtros" descripcion="Cambia la búsqueda o registra uno con el botón «Nuevo producto»." />
              )}
              {filas.map((p, i) => (
                <tr key={p.id}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td>
                    {p.foto_principal ? (
                      <ImagenProtegida url={`/mantenimiento/productos/${p.id}/fotos/${p.foto_principal}/imagen/?tam=mini`} alt={p.nombre} className="producto-miniatura" />
                    ) : (
                      <span className="producto-miniatura imagen-vacia" aria-hidden="true"><Icono nombre="camara" tam={20} /></span>
                    )}
                  </td>
                  <td className="celda-suave">{p.codigo}</td>
                  <td>
                    <strong>{p.nombre}</strong>
                    <small className="celda-suave producto-sub">
                      {[p.marca_nombre, p.tipo === 'SERVICIO' ? 'Servicio' : null].filter(Boolean).join(' · ')}
                    </small>
                    {(p.publicado_web || p.destacado || p.es_nuevo) && (
                      <span className="producto-etiquetas">
                        {p.publicado_web && <span className="etiqueta etiqueta-ok" title="Se muestra en la tienda virtual">En tienda</span>}
                        {p.destacado && <span className="etiqueta etiqueta-aviso">Destacado</span>}
                        {p.es_nuevo && <span className="etiqueta">Novedad</span>}
                      </span>
                    )}
                  </td>
                  <td className="celda-suave">{p.familia_nombre} › {p.categoria_nombre}</td>
                  <td>{p.unidad_abreviatura}</td>
                  <td>{precioPrincipal(p)}</td>
                  <td>
                    <span className={`estado-pildora ${p.estado === 'ACTIVO' ? 'activo' : 'inactivo'}`}>{p.estado === 'ACTIVO' ? 'Activo' : 'Inactivo'}</span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <Link to={`${RUTA}/${p.id}${MODO_LECTURA}`} className="accion-icono ver" aria-label={`Ver ${p.nombre}`} title="Ver (solo consulta)">
                        <Icono nombre="ojo" tam={19} />
                      </Link>
                      {puedeEditar && (
                        <Link to={`${RUTA}/${p.id}#datos`} className="accion-icono editar" aria-label={`Editar ${p.nombre}`} title="Editar">
                          <Icono nombre="lapiz" tam={19} />
                        </Link>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
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
