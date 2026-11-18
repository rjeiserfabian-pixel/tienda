import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import Avatar from '../../../shared/components/Avatar'
import Cambios from '../../../shared/components/Cambios'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaHora } from '../../../shared/utils/fechas'

const CATEGORIAS = [
  ['', 'Todos los eventos'],
  ['sesion.', 'Ingresos y sesiones'],
  ['password.', 'Contraseñas'],
  ['mfa.', 'Verificación en dos pasos'],
  ['usuario.', 'Usuarios'],
  ['rol.', 'Roles y permisos'],
  ['empresa.', 'Empresas'],
  ['sucursal.', 'Sucursales'],
  ['organizacion.', 'Organización'],
  ['ventas.', 'Ventas'],
  ['compras.', 'Compras'],
  ['caja.', 'Caja y bancos'],
  ['gastos.', 'Gastos'],
  ['inventario.', 'Inventario'],
  ['producto.', 'Productos'],
  ['servicio_tecnico.', 'Servicio técnico'],
  ['rrhh.', 'Recursos humanos'],
  ['tienda.', 'Tienda virtual'],
  ['garantias.', 'Garantías'],
  ['comisiones.', 'Comisiones'],
]

// Color de la píldora según el tipo de evento (lo que va antes del punto).
const TONOS = {
  sesion: 'azul',
  password: 'ambar',
  mfa: 'morado',
  usuario: 'cian',
  rol: 'rosa',
  empresa: 'verde',
  sucursal: 'naranja',
  organizacion: 'rojo',
  ventas: 'verde',
  compras: 'naranja',
  caja: 'cian',
  inventario: 'morado',
  producto: 'azul',
  rrhh: 'rosa',
  tienda: 'azul',
}

const tonoDe = (accion) => TONOS[accion.split('.')[0]] ?? 'gris'
const FILTROS_VACIOS = { accion: '', exito: '', desde: '', hasta: '', riesgo: '' }
const TAMANOS = [10, 20, 50, 100] // los que acepta el servidor para la auditoría

function DetalleEvento({ evento, onCerrar }) {
  return (
    <Modal titulo="Detalle del evento" subtitulo={evento.accion} onCerrar={onCerrar} ancho={640}>
      <dl className="datos-lista">
        <dt>Fecha</dt>
        <dd>{fechaHora(evento.creado_en)}</dd>
        <dt>Usuario</dt>
        <dd>{evento.usuario ?? 'Sin usuario (acción anónima)'}</dd>
        <dt>Resultado</dt>
        <dd>{evento.exito ? 'Correcto' : 'Fallido'}</dd>
        <dt>Resumen</dt>
        <dd>{evento.resumen || '—'}</dd>
        <dt>IP</dt>
        <dd>{evento.ip ?? '—'}</dd>
        <dt>Referencia</dt>
        <dd>{evento.request_id || '—'}</dd>
      </dl>
      <Cambios detalle={evento.detalle} />
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          <Icono nombre="cerrar" tam={18} /> Cerrar
        </button>
      </div>
    </Modal>
  )
}


const GRAVEDAD = { ALTA: 'rojo', MEDIA: 'ambar' }
const PERIODOS = [
  [7, 'Últimos 7 días'],
  [30, 'Últimos 30 días'],
  [90, 'Últimos 90 días'],
]

/** Lo que más conviene revisar: cada categoría de riesgo con cuántas veces pasó y si superó su umbral. */
function Riesgos({ onVer }) {
  const [dias, setDias] = useState(7)
  const consulta = useQuery({
    queryKey: ['auditoria', 'riesgos', dias],
    queryFn: ({ signal }) => api.get('/auditoria/riesgos/', { params: { dias }, signal }).then((r) => r.data),
  })
  const d = consulta.data
  return (
    <section aria-labelledby="titulo-riesgos">
      <h2 id="titulo-riesgos">Eventos de riesgo</h2>
      <label>
        Periodo
        <select value={dias} onChange={(e) => setDias(Number(e.target.value))}>
          {PERIODOS.map(([valor, texto]) => (
            <option key={valor} value={valor}>
              {texto}
            </option>
          ))}
        </select>
      </label>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(d)}>
        {d && (
          <>
            <p>{d.alertas === 0 ? 'No hay alertas en este periodo.' : `${d.alertas} ${d.alertas === 1 ? 'alerta encendida' : 'alertas encendidas'}.`}</p>
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Qué se vigila</th>
                    <th className="num">Veces</th>
                    <th>Estado</th>
                    <th>Quiénes más</th>
                    <th className="centrado">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {d.categorias.map((c) => (
                    <tr key={c.clave}>
                      <td className="col-texto">
                        <strong>{c.nombre}</strong>
                        <span className="sub-texto">{c.descripcion}</span>
                      </td>
                      <td className="num">{c.total}</td>
                      <td>
                        {c.alerta ? (
                          <span className="pildora" data-tono={GRAVEDAD[c.gravedad]}>
                            Revisar (desde {c.umbral})
                          </span>
                        ) : (
                          <span className="pildora" data-tono="verde">
                            Normal
                          </span>
                        )}
                      </td>
                      <td className="celda-suave">{c.top_usuarios.length ? c.top_usuarios.map((u) => `${u.nombre ?? 'Sistema'} (${u.n})`).join(', ') : '—'}</td>
                      <td className="centrado">
                        <button type="button" disabled={c.total === 0} onClick={() => onVer(c.clave, dias)}>
                          Ver eventos
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </EstadoConsulta>
    </section>
  )
}

/** Consulta de auditoría: cursor (la tabla crece sin fin) y filtros en el servidor. */
export default function AuditoriaPage() {
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(true)
  const [detalle, setDetalle] = useState(null)
  const [vista, setVista] = useState('eventos')

  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(20)
  const consulta = useListado(['auditoria'], '/auditoria/eventos/', { ...filtros, page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []
  const cambiar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const limpiar = () => {
    setFiltros(FILTROS_VACIOS)
    setPagina(1)
  }
  const hayFiltros = Object.values(filtros).some(Boolean)
  const verRiesgo = (clave, dias) => {
    const hoy = new Date()
    const desde = new Date(hoy.getTime() - dias * 86_400_000).toLocaleDateString('en-CA')
    setFiltros({ ...FILTROS_VACIOS, riesgo: clave, desde })
    setPagina(1)
    setVista('eventos')
  }
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta

  return (
    <main className="listado">
      <CabeceraListado icono="history" titulo="Auditoría" descripcion="Registro de las acciones realizadas en el sistema.">
        <button
          type="button"
          className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`}
          aria-expanded={filtrosAbiertos}
          onClick={() => setFiltrosAbiertos((v) => !v)}
        >
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
      </CabeceraListado>

      <div className="segmentos" role="radiogroup" aria-label="Qué quieres ver">
        {[
          ['eventos', 'Todos los eventos'],
          ['riesgos', 'Alertas de riesgo'],
        ].map(([valor, texto]) => (
          <button key={valor} type="button" role="radio" aria-checked={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => setVista(valor)}>
            {texto}
          </button>
        ))}
      </div>
      {vista === 'riesgos' && <Riesgos onVer={verRiesgo} />}
      {vista === 'eventos' && filtros.riesgo && (
        <p>
          Mostrando solo los eventos de riesgo «{filtros.riesgo}».{' '}
          <button type="button" onClick={limpiar}>
            Quitar este filtro
          </button>
        </p>
      )}
      {vista === 'eventos' && filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Tipo de evento
            <select value={filtros.accion} onChange={cambiar('accion')}>
              {CATEGORIAS.map(([valor, texto]) => (
                <option key={valor} value={valor}>{texto}</option>
              ))}
            </select>
          </label>
          <label>
            Resultado
            <select value={filtros.exito} onChange={cambiar('exito')}>
              <option value="">Todos</option>
              <option value="true">Correctos</option>
              <option value="false">Fallidos</option>
            </select>
          </label>
          <label>
            Desde
            <input type="date" value={filtros.desde} onChange={cambiar('desde')} />
          </label>
          <label>
            Hasta
            <input type="date" value={filtros.hasta} onChange={cambiar('hasta')} />
          </label>
          {hayFiltros && (
            <button type="button" onClick={limpiar}>
              Limpiar filtros
            </button>
          )}
        </div>
      )}
      {rangoInvalido && <p role="alert" className="campo-error">La fecha inicial no puede ser posterior a la final.</p>}

      {vista === 'eventos' && (
        <>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Usuario</th>
                <th>Evento</th>
                <th>Resumen</th>
                <th>Resultado</th>
                <th>IP</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia
                  columnas={7}
                  icono="history"
                  titulo="No hay eventos con esos filtros"
                  descripcion="Amplía el rango de fechas o cambia el tipo de evento."
                >
                  {hayFiltros && (
                    <button type="button" onClick={limpiar}>
                      Limpiar filtros
                    </button>
                  )}
                </FilaVacia>
              )}
              {filas.map((e) => (
                <tr key={e.id}>
                  <td className="celda-suave" style={{ whiteSpace: 'nowrap' }}>{fechaHora(e.creado_en)}</td>
                  <td>
                    {e.usuario ? (
                      <span className="texto-pildora-fila">
                        <Avatar nombre={e.usuario} tam={30} />
                        {e.usuario}
                      </span>
                    ) : (
                      <span className="celda-suave">—</span>
                    )}
                  </td>
                  <td>
                    <span className="pildora" data-tono={tonoDe(e.accion)} style={{ minWidth: 0 }}>
                      {e.accion}
                    </span>
                  </td>
                  <td className="celda-suave">{e.resumen || '—'}</td>
                  <td>
                    <span className={`estado-pildora ${e.exito ? 'activo' : 'inactivo'}`}>{e.exito ? 'Correcto' : 'Fallido'}</span>
                  </td>
                  <td className="celda-suave">{e.ip ?? '—'}</td>
                  <td className="centrado">
                    <button type="button" className="accion-icono ver" title="Ver detalle" aria-label={`Ver el detalle de ${e.accion}`} onClick={() => setDetalle(e)}>
                      <Icono nombre="ojo" tam={19} />
                    </button>
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
        tamanos={TAMANOS}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

        </>
      )}

      {detalle && <DetalleEvento evento={detalle} onCerrar={() => setDetalle(null)} />}
    </main>
  )
}
