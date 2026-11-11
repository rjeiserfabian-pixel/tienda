import { useState } from 'react'
import { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useNotaToma } from '../hooks/useToma'
import { puedeContarEn } from '../tomas'
import '../inventario.css'
import '../tomas.css'
import TomaFilaConteo from './TomaFilaConteo'

const VISTAS = [
  ['', 'Todos'],
  ['pendiente', 'Por contar'],
  ['contado', 'Contados'],
  ['reconteo', 'Por recontar'],
  ['sin_nota', 'Sin nota'],
]
// Solo quien ve lo que dice el sistema puede filtrar por resultado (en un conteo a ciegas revelaría la diferencia).
const VISTAS_DE_RESULTADO = [
  ['FALTANTE', 'Faltantes'],
  ['SOBRANTE', 'Sobrantes'],
  ['CONFORME', 'Conformes'],
]

/** La vista elegida → los parámetros de filtro que entiende el servidor. */
const filtroDeVista = (vista) => {
  if (vista === 'pendiente' || vista === 'contado') return { estado: vista }
  if (vista === 'reconteo') return { reconteo: 1 }
  if (vista === 'sin_nota') return { sin_nota: 1 }
  if (vista) return { resultado: vista }
  return {}
}

/**
 * La hoja de conteo: los productos de la toma, con buscador (también para el lector de códigos de
 * barras), filtros y paginación. Se cuenta escribiendo la cantidad en cada fila y pulsando Enter.
 */
export default function TomaHojaConteo({ toma, verResultado, categorias, categoria, onCategoria, puedeContar, turno, registro }) {
  const [busqueda, setBusqueda] = useState('')
  const [vista, setVista] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda, 400)
  const { guardarNota } = useNotaToma(toma.id)

  const consulta = useListado(['tomas', 'detalle', toma.id], `/inventario/tomas/${toma.id}/detalle/`, { q, categoria, ...filtroDeVista(vista), page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []
  const verSistema = filas.some((f) => f.stock_sistema !== undefined)
  const enReconteo = toma.estado === 'EN_RECONTEO'
  const contando = puedeContar && puedeContarEn(toma.estado)

  const cambiar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }
  const conAjuste = verSistema && toma.estado === 'APROBADA'
  const vistas = verResultado ? [...VISTAS, ...VISTAS_DE_RESULTADO] : VISTAS
  const columnas = 3 + (verSistema ? 2 : 0) + (conAjuste ? 1 : 0) + (contando ? 1 : 0) + 1

  return (
    <section className="toma-panel" aria-label="Hoja de conteo">
      <header className="toma-panel-cabecera">
        <h3>Hoja de conteo</h3>
      </header>

      <div className="toma-filtros">
        <Buscador valor={busqueda} onCambio={cambiar(setBusqueda)} etiqueta="Buscar en la hoja" placeholder="Nombre, código o código de barras…" />
        <select className="boton-cabecera" aria-label="Categoría" value={categoria} onChange={(e) => onCategoria(e.target.value)}>
          <option value="">Todas las categorías</option>
          {categorias.map((c) => (
            <option key={c.categoria_id} value={c.categoria_id}>
              {c.categoria}
            </option>
          ))}
        </select>
        <div className="segmentos" role="radiogroup" aria-label="Qué productos ver">
          {vistas.map(([valor, texto]) => (
            <button key={texto} type="button" role="radio" aria-checked={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => cambiar(setVista)(valor)}>
              {texto}
            </button>
          ))}
        </div>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos toma-tabla">
            <thead>
              <tr>
                <th>Producto</th>
                {verSistema && (
                  <>
                    <th className="num">Sistema</th>
                    <th className="num">Diferencia</th>
                  </>
                )}
                <th>Contado</th>
                {conAjuste && <th className="num">Ajuste</th>}
                <th>Estado físico</th>
                <th>Nota</th>
                {contando && <th className="centrado">Acción</th>}
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={columnas} icono="checklist" titulo="No hay productos con esos filtros" descripcion="Cambia la búsqueda, la categoría o el estado para ver otros productos de la toma." />}
              {filas.map((fila) => (
                <TomaFilaConteo
                  key={`${fila.id}-${fila.numero_conteos}-${fila.nota}-${fila.estado_fisico}`}
                  fila={fila}
                  verSistema={verSistema}
                  editable={contando && (!enReconteo || fila.requiere_reconteo)}
                  conAccion={contando}
                  conAjuste={conAjuste}
                  enReconteo={enReconteo}
                  turno={turno}
                  registrar={registro.registrar}
                  guardarNota={guardarNota}
                />
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={cambiar(setTamano)} />
    </section>
  )
}
