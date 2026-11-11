import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import EstadoVacio from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import EspecificacionesModal from '../../mantenimiento/components/EspecificacionesModal'
import { useTodasLasCategorias } from '../hooks/useTodasLasCategorias'
import { datosTexto, plano } from '../tienda'
import '../tienda.css'

const ESTADOS = [
  ['todas', 'Todas'],
  ['con', 'Con plantilla'],
  ['sin', 'Sin plantilla'],
]

/** Agrupa categorías por familia conservando el orden en que llegan (ya vienen por familia). */
function agruparPorFamilia(categorias) {
  const grupos = []
  const porId = new Map()
  for (const c of categorias) {
    let grupo = porId.get(c.familia)
    if (!grupo) {
      grupo = { id: c.familia, nombre: c.familia_nombre, categorias: [] }
      porId.set(c.familia, grupo)
      grupos.push(grupo)
    }
    grupo.categorias.push(c)
  }
  return grupos
}

/** Especificaciones por categoría: qué datos técnicos se piden y cuáles filtran en la tienda. */
export default function EspecificacionesTiendaPage() {
  const { tiene } = usePermisos()
  const puedeEditar = tiene('MANTENIMIENTO.CLASIFICACION.EDITAR', { organizacion: true })
  const veProductos = tiene('MANTENIMIENTO.PRODUCTOS.VER', { organizacion: true })
  const queryClient = useQueryClient()

  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('todas')
  const [modal, setModal] = useState(null) // la categoría que se está configurando
  const q = useDebounce(busqueda, 300)

  const consulta = useTodasLasCategorias()
  const todas = useMemo(() => consulta.data ?? [], [consulta.data])
  const conPlantilla = useMemo(() => todas.filter((c) => c.n_campos > 0).length, [todas])
  const avance = todas.length ? Math.round((conPlantilla / todas.length) * 100) : 0

  const grupos = useMemo(() => {
    const buscado = plano(q)
    const filtradas = todas.filter((c) => {
      if (estado === 'con' && !(c.n_campos > 0)) return false
      if (estado === 'sin' && c.n_campos > 0) return false
      return !buscado || plano(`${c.nombre} ${c.familia_nombre}`).includes(buscado)
    })
    return agruparPorFamilia(filtradas)
  }, [todas, q, estado])

  const cerrar = () => {
    setModal(null)
    queryClient.invalidateQueries({ queryKey: ['categorias'] }) // refresca el número de datos
  }

  return (
    <main className="listado tienda-pagina">
      <CabeceraListado
        icono="checklist"
        titulo="Especificaciones por categoría"
        descripcion="Los datos técnicos que se piden a cada tipo de producto: arman la ficha y los filtros de la tienda."
      >
        <Buscador valor={busqueda} onCambio={setBusqueda} etiqueta="Buscar categoría" placeholder="Buscar categoría o familia…" />
        {veProductos && (
          <Link to="/tienda/productos" className="boton-cabecera">
            <Icono nombre="store" tam={19} /> Productos en tienda
          </Link>
        )}
      </CabeceraListado>

      <section className="tienda-ayuda" aria-label="Para qué sirve">
        <Icono nombre="ojo" tam={22} />
        <p>
          Cada categoría tiene su propia lista de datos: una laptop pide memoria RAM y procesador, un mouse pide DPI y tipo de conexión.
          Se definen <strong>una sola vez</strong> por categoría y luego cada producto solo llena los suyos. Los datos marcados como{' '}
          <strong>filtro</strong> permiten al cliente filtrar en la tienda (por ejemplo laptops con 16 GB), y los marcados para la{' '}
          <strong>tarjeta</strong> se ven sin abrir el producto. Para empezar rápido, carga una de las plantillas de ejemplo.
        </p>
      </section>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <section className="tienda-avance" aria-label="Avance de las plantillas">
          <div>
            <strong>{conPlantilla} de {todas.length}</strong> categorías con plantilla
          </div>
          <div className="tienda-medidor tienda-medidor-ancho" role="img" aria-label={`${avance} % de las categorías tiene plantilla`}>
            <span style={{ width: `${avance}%` }} data-completa={avance === 100 || undefined} />
          </div>
        </section>

        <div className="tienda-barra">
          <div className="tienda-segmentos" role="group" aria-label="Filtrar por plantilla">
            {ESTADOS.map(([valor, texto]) => (
              <button key={valor} type="button" aria-pressed={estado === valor} onClick={() => setEstado(valor)}>
                {texto}
              </button>
            ))}
          </div>
        </div>

        {grupos.length === 0 ? (
          <EstadoVacio
            icono="layers"
            titulo={todas.length === 0 ? 'Aún no hay categorías' : 'Ninguna categoría coincide'}
            descripcion={todas.length === 0 ? 'Crea familias y categorías en Mantenimiento › Familias y categorías.' : 'Cambia la búsqueda o el filtro.'}
          />
        ) : (
          <div className="tienda-familias">
            {grupos.map((g) => {
              const conEnGrupo = g.categorias.filter((c) => c.n_campos > 0).length
              return (
                <section key={g.id} className="tienda-familia" aria-labelledby={`familia-${g.id}`}>
                  <header>
                    <h3 id={`familia-${g.id}`}>{g.nombre}</h3>
                    <small>{conEnGrupo} de {g.categorias.length} con plantilla</small>
                  </header>
                  <ul className="tienda-categorias">
                    {g.categorias.map((c) => {
                      const tiene_ = c.n_campos > 0
                      return (
                        <li key={c.id}>
                          <span className="tienda-categoria-nombre">{c.nombre}</span>
                          <span className={`tienda-estado ${tiene_ ? 'con' : 'sin'}`}>
                            {tiene_ ? `Con plantilla · ${datosTexto(c.n_campos)}` : 'Sin plantilla'}
                          </span>
                          <button
                            type="button"
                            className={tiene_ || !puedeEditar ? 'boton-cabecera' : 'primario boton-cabecera'}
                            aria-label={`${puedeEditar ? 'Configurar' : 'Ver'} las especificaciones de ${c.nombre}`}
                            onClick={() => setModal(c)}
                          >
                            <Icono nombre={puedeEditar ? 'lapiz' : 'ojo'} tam={17} /> {puedeEditar ? (tiene_ ? 'Configurar' : 'Definir') : 'Ver'}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              )
            })}
          </div>
        )}
      </EstadoConsulta>

      {modal && <EspecificacionesModal categoria={modal} puedeEditar={puedeEditar} onCerrar={cerrar} />}
    </main>
  )
}
