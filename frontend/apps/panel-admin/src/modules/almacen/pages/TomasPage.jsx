import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import TomaNuevaModal from '../components/TomaNuevaModal'
import { useOpciones } from '../hooks/useOpciones'
import { ESTADOS_TOMA, fechaHora, numeroToma } from '../tomas'
import '../inventario.css'
import '../tomas.css'

/** Las tomas de inventario físico de la empresa: una por almacén y por conteo. */
export default function TomasPage() {
  const { empresaActivaId } = useEmpresas()
  const navegar = useNavigate()
  const [creando, setCreando] = useState(false)
  const [almacen, setAlmacen] = useState('')
  const [estado, setEstado] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const consulta = useListado(['tomas'], '/inventario/tomas/', { empresa: empresaActivaId, almacen, estado, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  const cambiar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="checklist" titulo="Toma de inventario" descripcion="Cuenta lo que hay en el almacén y compáralo con lo que dice el sistema. Cada toma congela el stock al abrirla; el ajuste solo se hace al aprobarla.">
        <select className="boton-cabecera" aria-label="Estado" value={estado} onChange={(e) => cambiar(setEstado)(e.target.value)}>
          <option value="">Todos los estados</option>
          {Object.entries(ESTADOS_TOMA).map(([valor, { texto }]) => (
            <option key={valor} value={valor}>
              {texto}
            </option>
          ))}
        </select>
        {(almacenes.data ?? []).length > 1 && (
          <select className="boton-cabecera" aria-label="Almacén" value={almacen} onChange={(e) => cambiar(setAlmacen)(e.target.value)}>
            <option value="">Todos los almacenes</option>
            {almacenes.data.map((a) => (
              <option key={a.id} value={a.id}>
                {a.nombre}
              </option>
            ))}
          </select>
        )}
        <Can permiso="INVENTARIO.TOMAS.GESTIONAR">
          <button type="button" className="boton-cabecera primario" onClick={() => setCreando(true)}>
            <Icono nombre="agregar" tam={19} /> Nueva toma
          </button>
        </Can>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Toma</th>
                <th>Almacén</th>
                <th>Estado</th>
                <th>Qué se cuenta</th>
                <th>Corte del stock</th>
                <th>Creada</th>
                <th className="centrado">Ver</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={7} icono="checklist" titulo="Todavía no hay tomas de inventario" descripcion="Crea una toma para contar un almacén y detectar faltantes y sobrantes." />
              )}
              {filas.map((t) => {
                const e = ESTADOS_TOMA[t.estado] ?? { texto: t.estado_nombre, tono: 'gris' }
                return (
                  <tr key={t.id} className="toma-fila-clicable" onClick={() => navegar(`/almacen/tomas/${t.id}`)}>
                    <td>
                      <strong>{numeroToma(t.numero)}</strong>
                      {t.observacion && <span className="sub-texto">{t.observacion}</span>}
                    </td>
                    <td>{t.almacen_nombre}</td>
                    <td>
                      <span className="pildora" data-tono={e.tono}>
                        {e.texto}
                      </span>
                    </td>
                    <td>
                      {t.alcance === 'TODO' ? 'Todo el almacén' : `${t.categorias.length} categoría(s)`}
                      {t.conteo_ciego && <span className="sub-texto">Conteo a ciegas</span>}
                    </td>
                    <td>{fechaHora(t.fecha_corte)}</td>
                    <td>{fechaHora(t.creado_en)}</td>
                    <td className="centrado">
                      <span className="acciones-fila">
                        <button
                          type="button"
                          className="accion-icono ver"
                          aria-label={`Abrir la toma ${numeroToma(t.numero)}`}
                          title="Ver la toma"
                          onClick={(evento) => {
                            evento.stopPropagation()
                            navegar(`/almacen/tomas/${t.id}`)
                          }}
                        >
                          <Icono nombre="ojo" tam={19} />
                        </button>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={cambiar(setTamano)} />
      {creando && <TomaNuevaModal onCerrar={() => setCreando(false)} onCreada={(toma) => navegar(`/almacen/tomas/${toma.id}`)} />}
    </main>
  )
}
