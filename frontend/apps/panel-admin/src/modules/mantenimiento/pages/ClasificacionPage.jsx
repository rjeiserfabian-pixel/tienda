import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import EspecificacionesModal from '../components/EspecificacionesModal'
import '../components/clasificacion.css'
import '../components/especificaciones.css'

const INVALIDAR = [['familias'], ['categorias'], ['opciones']]
const URL_FAMILIAS = '/mantenimiento/familias/'
const URL_CATEGORIAS = '/mantenimiento/categorias/'

function CampoEstado({ valor, onCambio, deshabilitado }) {
  return (
    <Campo etiqueta="Estado" icono="settings" tipo="select">
      {(p) => (
        <select {...p} name="estado" value={valor} disabled={deshabilitado} onChange={(e) => onCambio(e.target.value)}>
          <option value="ACTIVO">Activo</option>
          <option value="INACTIVO">Inactivo</option>
        </select>
      )}
    </Campo>
  )
}

/** Alta o edición de una familia (solo nombre y estado). */
function FamiliaModal({ familia, onCerrar }) {
  const editando = Boolean(familia)
  const [f, setF] = useState({ nombre: familia?.nombre ?? '', estado: familia?.estado ?? 'ACTIVO' })
  const [errores, setErrores] = useState({})

  const guardar = useMutacion({
    mutationFn: (datos) =>
      (editando ? api.patch(`${URL_FAMILIAS}${familia.id}/`, datos) : api.post(URL_FAMILIAS, datos)).then((r) => r.data),
    invalidar: INVALIDAR,
    exito: editando ? 'Familia actualizada.' : 'Familia registrada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    if (!f.nombre.trim()) return setErrores({ nombre: 'Ingrese el nombre de la familia.' })
    setErrores({})
    guardar.mutate(editando ? f : { nombre: f.nombre }, {
      onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }),
    })
  }

  return (
    <Modal titulo={editando ? 'Editar familia' : 'Nueva familia'} subtitulo="Grupo general de productos, p. ej. Accesorios de computadora." onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Nombre de la familia" icono="layers" requerido error={errores.nombre}>
          {(p) => <input {...p} name="nombre" placeholder="Ej. Accesorios de computadora" maxLength={100} value={f.nombre} disabled={guardar.isPending} onChange={(e) => setF({ ...f, nombre: e.target.value })} />}
        </Campo>
        {editando && <CampoEstado valor={f.estado} deshabilitado={guardar.isPending} onCambio={(estado) => setF({ ...f, estado })} />}
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending}>{guardar.isPending ? 'Guardando…' : editando ? 'Guardar' : 'Registrar familia'}</button>
        </div>
      </form>
    </Modal>
  )
}

/** Alta o edición de una categoría. Al editar se puede mover a otra familia. */
function CategoriaModal({ categoria, familiaInicial, familias, onCerrar }) {
  const editando = Boolean(categoria)
  const [f, setF] = useState({
    familia: String(categoria?.familia ?? familiaInicial?.id ?? ''),
    nombre: categoria?.nombre ?? '',
    estado: categoria?.estado ?? 'ACTIVO',
  })
  const [errores, setErrores] = useState({})
  // Solo familias activas, más la actual de la categoría aunque esté inactiva.
  const opciones = familias.filter((x) => x.estado === 'ACTIVO' || x.id === categoria?.familia)

  const guardar = useMutacion({
    mutationFn: (datos) =>
      (editando ? api.patch(`${URL_CATEGORIAS}${categoria.id}/`, datos) : api.post(URL_CATEGORIAS, datos)).then((r) => r.data),
    invalidar: INVALIDAR,
    exito: editando ? 'Categoría actualizada.' : 'Categoría registrada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const locales = {}
    if (!f.familia) locales.familia = 'Elija la familia.'
    if (!f.nombre.trim()) locales.nombre = 'Ingrese el nombre de la categoría.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    const datos = { familia: Number(f.familia), nombre: f.nombre }
    guardar.mutate(editando ? { ...datos, estado: f.estado } : datos, {
      onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }),
    })
  }

  return (
    <Modal titulo={editando ? 'Editar categoría' : 'Nueva categoría'} subtitulo="Tipo específico de producto dentro de una familia." onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Familia" icono="layers" tipo="select" requerido error={errores.familia} ayuda={editando ? 'Cámbiala para mover la categoría a otra familia.' : undefined}>
          {(p) => (
            <select {...p} name="familia" value={f.familia} disabled={guardar.isPending} onChange={(e) => setF({ ...f, familia: e.target.value })}>
              <option value="">Elija la familia</option>
              {opciones.map((x) => (
                <option key={x.id} value={x.id}>{x.nombre}</option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Nombre de la categoría" icono="tags" requerido error={errores.nombre}>
          {(p) => <input {...p} name="nombre" placeholder="Ej. Teclados" maxLength={100} value={f.nombre} disabled={guardar.isPending} onChange={(e) => setF({ ...f, nombre: e.target.value })} />}
        </Campo>
        {editando && <CampoEstado valor={f.estado} deshabilitado={guardar.isPending} onCambio={(estado) => setF({ ...f, estado })} />}
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending}>{guardar.isPending ? 'Guardando…' : editando ? 'Guardar' : 'Registrar categoría'}</button>
        </div>
      </form>
    </Modal>
  )
}

/**
 * Familias y categorías de productos en una sola pantalla: a la izquierda las familias y a la
 * derecha las categorías de la familia elegida. Son de la organización: las comparten todas
 * sus empresas.
 */
export default function ClasificacionPage() {
  const { tiene } = usePermisos()
  const puede = (accion) => tiene(`MANTENIMIENTO.CLASIFICACION.${accion}`, { organizacion: true })
  const [busquedaFamilia, setBusquedaFamilia] = useState('')
  const [elegida, setElegida] = useState(null)
  const [busquedaCategoria, setBusquedaCategoria] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [modal, setModal] = useState(null) // { tipo: 'familia'|'categoria', registro?: ... }
  const [aEliminar, setAEliminar] = useState(null) // { tipo, registro }
  const qFamilia = useDebounce(busquedaFamilia, 400)
  const qCategoria = useDebounce(busquedaCategoria, 400)

  const familias = useListado(['familias'], URL_FAMILIAS, { q: qFamilia, page_size: 100 })
  const listaFamilias = familias.data?.results ?? []
  const activa = listaFamilias.find((f) => f.id === elegida) ?? listaFamilias[0] ?? null

  const categorias = useListado(
    ['categorias'],
    URL_CATEGORIAS,
    { familia: activa?.id, q: qCategoria, page: pagina, page_size: tamano },
    { enabled: Boolean(activa) },
  )
  const filas = activa ? (categorias.data?.results ?? []) : []
  const desde = (pagina - 1) * tamano + 1

  const cambiarEstado = useMutacion({
    mutationFn: ({ tipo, registro }) =>
      api
        .patch(`${tipo === 'familia' ? URL_FAMILIAS : URL_CATEGORIAS}${registro.id}/`, {
          estado: registro.estado === 'ACTIVO' ? 'INACTIVO' : 'ACTIVO',
        })
        .then((r) => r.data),
    invalidar: INVALIDAR,
    exito: 'Estado actualizado.',
  })
  const eliminar = useMutacion({
    mutationFn: ({ tipo, registro }) => api.delete(`${tipo === 'familia' ? URL_FAMILIAS : URL_CATEGORIAS}${registro.id}/`),
    invalidar: INVALIDAR,
    exito: 'Eliminado.',
    alExito: () => setAEliminar(null),
  })

  const elegirFamilia = (id) => {
    setElegida(id)
    setPagina(1)
    setBusquedaCategoria('')
  }
  const pendiente = cambiarEstado.isPending ? cambiarEstado.variables?.registro?.id : null

  return (
    <main className="listado">
      <CabeceraListado
        icono="layers"
        titulo="Familias y categorías"
        descripcion="Clasifica los productos de todas tus empresas: la familia es el grupo general y la categoría el tipo específico."
      >
        {puede('CREAR') && (
          <button type="button" className="primario boton-cabecera" onClick={() => setModal({ tipo: 'familia' })}>
            <Icono nombre="agregar" tam={20} /> Nueva familia
          </button>
        )}
      </CabeceraListado>

      <div className="clasif">
        <aside className="clasif-familias" aria-label="Familias">
          <Buscador valor={busquedaFamilia} onCambio={setBusquedaFamilia} etiqueta="Buscar familias" placeholder="Buscar familia…" />
          <EstadoConsulta consulta={familias} hayDatos={Boolean(familias.data)}>
            <ul className="clasif-lista">
              {listaFamilias.length === 0 && <li className="clasif-vacio">{qFamilia ? 'Ninguna familia coincide.' : 'Aún no hay familias. Crea la primera.'}</li>}
              {listaFamilias.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    className={`clasif-item${f.id === activa?.id ? ' activo' : ''}${f.estado === 'INACTIVO' ? ' inactivo' : ''}`}
                    aria-current={f.id === activa?.id ? 'true' : undefined}
                    onClick={() => elegirFamilia(f.id)}
                  >
                    <Icono nombre="layers" tam={20} />
                    <span className="clasif-nombre">{f.nombre}</span>
                    <span className="clasif-conteo" title="Categorías">{f.n_categorias}</span>
                  </button>
                </li>
              ))}
            </ul>
            {familias.data && familias.data.count > listaFamilias.length && (
              <p className="campo-ayuda">Mostrando {listaFamilias.length} de {familias.data.count}. Usa el buscador para encontrar las demás.</p>
            )}
          </EstadoConsulta>
        </aside>

        <section className="clasif-detalle" aria-label="Categorías">
          {!activa ? (
            <p className="clasif-vacio">Elige o crea una familia para ver sus categorías.</p>
          ) : (
            <>
              <header className="clasif-cab">
                <span className="panel-tarjeta-icono" aria-hidden="true"><Icono nombre="layers" tam={22} /></span>
                <div className="clasif-cab-texto">
                  <h3>{activa.nombre}</h3>
                  <p>
                    {activa.n_categorias} categoría(s) ·{' '}
                    <span className={`estado-pildora ${activa.estado === 'ACTIVO' ? 'activo' : 'inactivo'}`}>{activa.estado === 'ACTIVO' ? 'Activa' : 'Inactiva'}</span>
                  </p>
                </div>
                <div className="acciones-fila">
                  {puede('EDITAR') && (
                    <>
                      <button type="button" className="accion-icono editar" title="Editar la familia" aria-label={`Editar la familia ${activa.nombre}`} onClick={() => setModal({ tipo: 'familia', registro: activa })}>
                        <Icono nombre="lapiz" tam={19} />
                      </button>
                      <button
                        type="button"
                        className={`accion-icono ${activa.estado === 'ACTIVO' ? 'peligro-suave' : 'reactivar'}`}
                        title={activa.estado === 'ACTIVO' ? 'Desactivar la familia' : 'Activar la familia'}
                        aria-label={activa.estado === 'ACTIVO' ? `Desactivar la familia ${activa.nombre}` : `Activar la familia ${activa.nombre}`}
                        disabled={pendiente === activa.id}
                        onClick={() => cambiarEstado.mutate({ tipo: 'familia', registro: activa })}
                      >
                        <Icono nombre={activa.estado === 'ACTIVO' ? 'apagar' : 'reactivar'} tam={19} />
                      </button>
                    </>
                  )}
                  {puede('ELIMINAR') && (
                    <button
                      type="button"
                      className="accion-icono peligro-suave"
                      title={activa.n_categorias > 0 ? 'Elimina o mueve primero sus categorías' : 'Eliminar la familia'}
                      aria-label={`Eliminar la familia ${activa.nombre}`}
                      disabled={activa.n_categorias > 0}
                      onClick={() => setAEliminar({ tipo: 'familia', registro: activa })}
                    >
                      <Icono nombre="papelera" tam={19} />
                    </button>
                  )}
                </div>
              </header>

              <div className="clasif-barra">
                <Buscador
                  valor={busquedaCategoria}
                  onCambio={(v) => {
                    setBusquedaCategoria(v)
                    setPagina(1)
                  }}
                  etiqueta="Buscar categorías"
                  placeholder="Buscar categoría…"
                />
                {puede('CREAR') && activa.estado === 'ACTIVO' && (
                  <button type="button" className="primario boton-cabecera" onClick={() => setModal({ tipo: 'categoria' })}>
                    <Icono nombre="agregar" tam={20} /> Nueva categoría
                  </button>
                )}
              </div>

              <EstadoConsulta consulta={categorias} hayDatos={Boolean(categorias.data)}>
                <div className="marco-tabla">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th className="centrado">#</th>
                        <th>Categoría</th>
                        <th>Estado</th>
                        <th>Especificaciones</th>
                        <th className="centrado">Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filas.length === 0 && (
                        <FilaVacia columnas={5} icono="layers" titulo={qCategoria ? 'Ninguna categoría coincide' : 'Esta familia aún no tiene categorías'} descripcion={qCategoria ? 'Prueba con otro nombre.' : 'Crea la primera con el botón «Nueva categoría».'} />
                      )}
                      {filas.map((c, i) => (
                        <tr key={c.id}>
                          <td className="centrado celda-suave">{desde + i}</td>
                          <td><strong>{c.nombre}</strong></td>
                          <td>
                            <span className={`estado-pildora ${c.estado === 'ACTIVO' ? 'activo' : 'inactivo'}`}>{c.estado === 'ACTIVO' ? 'Activa' : 'Inactiva'}</span>
                          </td>
                          <td>
                            {puede('VER') && (
                              <button
                                type="button"
                                className={`esp-boton${c.n_campos ? '' : ' sin-datos'}`}
                                title={puede('EDITAR') ? 'Definir los datos técnicos de esta categoría' : 'Ver los datos técnicos de esta categoría'}
                                aria-label={`Especificaciones de ${c.nombre}: ${c.n_campos ?? 0} datos`}
                                onClick={() => setModal({ tipo: 'especificaciones', registro: c })}
                              >
                                <Icono nombre="checklist" tam={16} />
                                <span>{c.n_campos ? 'Especificaciones' : puede('EDITAR') ? 'Definir' : 'Ver'}</span>
                                <span className="esp-cuenta">{c.n_campos ?? 0}</span>
                              </button>
                            )}
                          </td>
                          <td className="centrado">
                            <span className="acciones-fila">
                              {puede('EDITAR') && (
                                <>
                                  <button type="button" className="accion-icono editar" title="Editar o mover de familia" aria-label={`Editar la categoría ${c.nombre}`} onClick={() => setModal({ tipo: 'categoria', registro: c })}>
                                    <Icono nombre="lapiz" tam={19} />
                                  </button>
                                  <button
                                    type="button"
                                    className={`accion-icono ${c.estado === 'ACTIVO' ? 'peligro-suave' : 'reactivar'}`}
                                    title={c.estado === 'ACTIVO' ? 'Desactivar' : 'Activar'}
                                    aria-label={c.estado === 'ACTIVO' ? `Desactivar la categoría ${c.nombre}` : `Activar la categoría ${c.nombre}`}
                                    disabled={pendiente === c.id}
                                    onClick={() => cambiarEstado.mutate({ tipo: 'categoria', registro: c })}
                                  >
                                    <Icono nombre={c.estado === 'ACTIVO' ? 'apagar' : 'reactivar'} tam={19} />
                                  </button>
                                </>
                              )}
                              {puede('ELIMINAR') && (
                                <button type="button" className="accion-icono peligro-suave" title="Eliminar" aria-label={`Eliminar la categoría ${c.nombre}`} onClick={() => setAEliminar({ tipo: 'categoria', registro: c })}>
                                  <Icono nombre="papelera" tam={19} />
                                </button>
                              )}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Paginacion
                  pagina={pagina}
                  tamano={tamano}
                  total={categorias.data?.count ?? 0}
                  onPagina={setPagina}
                  onTamano={(t) => {
                    setTamano(t)
                    setPagina(1)
                  }}
                />
              </EstadoConsulta>
            </>
          )}
        </section>
      </div>

      {modal?.tipo === 'familia' && <FamiliaModal familia={modal.registro} onCerrar={() => setModal(null)} />}
      {modal?.tipo === 'categoria' && (
        <CategoriaModal categoria={modal.registro} familiaInicial={activa} familias={listaFamilias} onCerrar={() => setModal(null)} />
      )}
      {modal?.tipo === 'especificaciones' && (
        <EspecificacionesModal categoria={modal.registro} puedeEditar={puede('EDITAR')} onCerrar={() => setModal(null)} />
      )}
      {aEliminar && (
        <ConfirmarModal
          titulo={`Eliminar ${aEliminar.tipo === 'familia' ? 'familia' : 'categoría'}`}
          mensaje={`¿Eliminar «${aEliminar.registro.nombre}»? Dejará de aparecer y su nombre quedará libre. Si solo quieres que no se use, mejor desactívala.`}
          textoConfirmar="Eliminar"
          enviando={eliminar.isPending}
          onConfirmar={() => eliminar.mutate(aEliminar)}
          onCerrar={() => setAEliminar(null)}
        />
      )}
    </main>
  )
}
