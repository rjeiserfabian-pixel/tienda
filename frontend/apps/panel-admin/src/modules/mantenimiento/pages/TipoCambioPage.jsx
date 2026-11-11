import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import '../components/tipo-cambio.css'

const URL = '/mantenimiento/tipo-cambio/'
const INVALIDAR = [['tipo-cambio']]
const HOY = new Date().toLocaleDateString('en-CA') // AAAA-MM-DD en la hora local
const FUENTES = [
  ['SUNAT', 'SUNAT', 'azul'],
  ['SBS', 'SBS (promedio)', 'morado'],
  ['SBS_CONTABLE', 'SBS (contable)', 'cian'],
  ['MANUAL', 'Manual', 'gris'],
]
const nombreDe = (fuente) => FUENTES.find(([v]) => v === fuente)?.[1] ?? fuente
const tonoDe = (fuente) => FUENTES.find(([v]) => v === fuente)?.[2] ?? 'gris'
const fecha = (iso) => (iso ? iso.split('-').reverse().join('/') : '—')
const decimal = (texto) => texto.replace(',', '.').replace(/[^\d.]/g, '').replace(/^(\d*\.\d*).*$/, '$1')

/** Alta o edición de una tasa manual. */
function ManualModal({ fila, onCerrar }) {
  const editando = Boolean(fila)
  const [f, setF] = useState({ fecha: fila?.fecha ?? HOY, compra: fila?.compra ?? '', venta: fila?.venta ?? '' })
  const [errores, setErrores] = useState({})
  const guardar = useMutacion({
    mutationFn: (datos) => (editando ? api.patch(`${URL}${fila.id}/`, datos) : api.post(URL, datos)).then((r) => r.data),
    invalidar: INVALIDAR,
    exito: editando ? 'Tipo de cambio actualizado.' : 'Tipo de cambio registrado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const locales = {}
    if (!f.fecha) locales.fecha = 'Elija la fecha.'
    else if (f.fecha > HOY) locales.fecha = 'La fecha no puede ser futura.'
    if (!(Number(f.compra) > 0)) locales.compra = 'Ingrese la compra.'
    if (!(Number(f.venta) > 0)) locales.venta = 'Ingrese la venta.'
    else if (Number(f.venta) < Number(f.compra)) locales.venta = 'La venta no puede ser menor que la compra.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    guardar.mutate(f, { onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }) })
  }

  return (
    <Modal titulo={editando ? 'Editar tipo de cambio' : 'Nuevo tipo de cambio'} subtitulo="Tasa manual en soles por dólar. Las de SUNAT y SBS se traen solas." onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Fecha" icono="calendario" requerido error={errores.fecha}>
          {(p) => <input {...p} name="fecha" type="date" max={HOY} min="2000-01-01" value={f.fecha} disabled={guardar.isPending} onChange={(e) => setF({ ...f, fecha: e.target.value })} />}
        </Campo>
        <div className="modal-fila">
          <Campo etiqueta="Compra" icono="swap" requerido error={errores.compra}>
            {(p) => <input {...p} name="compra" inputMode="decimal" placeholder="Ej. 3.446" maxLength={8} value={f.compra} disabled={guardar.isPending} onChange={(e) => setF({ ...f, compra: decimal(e.target.value) })} />}
          </Campo>
          <Campo etiqueta="Venta" icono="swap" requerido error={errores.venta}>
            {(p) => <input {...p} name="venta" inputMode="decimal" placeholder="Ej. 3.452" maxLength={8} value={f.venta} disabled={guardar.isPending} onChange={(e) => setF({ ...f, venta: decimal(e.target.value) })} />}
          </Campo>
        </div>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending}>{guardar.isPending ? 'Guardando…' : editando ? 'Guardar' : 'Registrar'}</button>
        </div>
      </form>
    </Modal>
  )
}

/** Tipo de cambio (soles por dólar): lo oficial de SUNAT y SBS se trae solo cada día, y también a pedido. */
export default function TipoCambioPage() {
  const { tiene } = usePermisos()
  const notificar = useNotificar()
  const puede = (accion) => tiene(`MANTENIMIENTO.TIPO_CAMBIO.${accion}`, { organizacion: true })
  const [fuente, setFuente] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [modal, setModal] = useState(null) // { fila? }
  const [aEliminar, setAEliminar] = useState(null)

  const resumen = useQuery({
    queryKey: ['tipo-cambio', 'resumen'],
    queryFn: ({ signal }) => api.get(`${URL}resumen/`, { signal }).then((r) => r.data),
  })
  const consulta = useListado(['tipo-cambio'], URL, { fuente, desde, hasta, page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []
  const desdeFila = (pagina - 1) * tamano + 1

  const actualizar = useMutacion({
    mutationFn: (fuentes) => api.post(`${URL}actualizar/`, { fuentes }).then((r) => r.data),
    invalidar: INVALIDAR,
    avisarError: false,
    alExito: ({ resultados }) => {
      const fallidas = resultados.filter((r) => r.estado === 'error')
      const buenas = resultados.filter((r) => r.estado !== 'error')
      if (buenas.length === 0) notificar('error', fallidas[0]?.mensaje ?? 'No se pudo actualizar el tipo de cambio.')
      else {
        const nuevas = buenas.filter((r) => r.estado === 'nuevo' || r.estado === 'actualizado').length
        const aviso = fallidas.length ? ` ${fallidas.length} no respondió.` : ''
        notificar('exito', nuevas ? `Tipo de cambio actualizado.${aviso}` : `Ya estaba al día: no se gastó ninguna consulta.${aviso}`)
      }
    },
  })
  const eliminar = useMutacion({
    mutationFn: (f) => api.delete(`${URL}${f.id}/`),
    invalidar: INVALIDAR,
    exito: 'Tipo de cambio eliminado.',
    alExito: () => setAEliminar(null),
  })
  const reiniciar = (cambio) => {
    cambio()
    setPagina(1)
  }
  const porFuente = Object.fromEntries((resumen.data?.fuentes ?? []).map((f) => [f.fuente, f]))
  const uso = resumen.data?.uso
  const tonoUso = !uso ? 'gris' : uso.usadas >= uso.limite * 0.9 ? 'rojo' : uso.usadas >= uso.limite * 0.6 ? 'ambar' : 'verde'

  return (
    <main className="listado">
      <CabeceraListado icono="swap" titulo="Tipo de cambio" descripcion="Soles por dólar. Trae el de SUNAT con un clic (gasta 1 consulta de tu plan de Decolecta) o carga uno manual.">
        {puede('CREAR') && (
          <>
            {uso && (
              <span className="pildora" data-tono={tonoUso} style={{ minWidth: 0 }} title="Consultas a Decolecta este mes (DNI, RUC y tipo de cambio). Es una cuenta propia; la oficial está en tu perfil de Decolecta.">
                Consultas del mes: {uso.usadas}/{uso.limite}
              </span>
            )}
            <button type="button" className="boton-cabecera" onClick={() => actualizar.mutate(['SUNAT'])} disabled={actualizar.isPending} title="Trae el tipo de cambio de SUNAT (1 consulta)">
              <Icono nombre="reactivar" tam={19} /> {actualizar.isPending ? 'Actualizando…' : 'Actualizar SUNAT'}
            </button>
            <button type="button" className="boton-cabecera" onClick={() => actualizar.mutate(['SBS', 'SBS_CONTABLE'])} disabled={actualizar.isPending} title="Trae el promedio y el contable de la SBS (2 consultas)">
              <Icono nombre="reactivar" tam={19} /> Traer SBS
            </button>
            <button type="button" className="primario boton-cabecera" onClick={() => setModal({})}>
              <Icono nombre="agregar" tam={20} /> Nuevo manual
            </button>
          </>
        )}
      </CabeceraListado>

      <section className="tc-tarjetas" aria-label="Tipo de cambio vigente">
        {FUENTES.filter(([v]) => v !== 'MANUAL').map(([valor, nombre, tono]) => {
          const f = porFuente[valor]
          return (
            <article key={valor} className="tc-tarjeta" data-tono={tono}>
              <h3>{nombre}</h3>
              {f ? (
                <>
                  <p className="tc-valores">
                    <span><small>Compra</small><strong>{Number(f.compra).toFixed(3)}</strong></span>
                    <span><small>Venta</small><strong>{Number(f.venta).toFixed(3)}</strong></span>
                  </p>
                  <small className="celda-suave">Publicado el {fecha(f.fecha)}</small>
                </>
              ) : (
                <p className="celda-suave">Sin datos todavía.{puede('CREAR') ? ' Usa los botones de arriba para traerlo.' : ''}</p>
              )}
            </article>
          )
        })}
      </section>

      <div className="tc-filtros">
        <label className="tc-filtro">
          Fuente
          <select value={fuente} onChange={(e) => reiniciar(() => setFuente(e.target.value))}>
            <option value="">Todas</option>
            {FUENTES.map(([v, n]) => (
              <option key={v} value={v}>{n}</option>
            ))}
          </select>
        </label>
        <label className="tc-filtro">
          Desde
          <input type="date" value={desde} max={hasta || HOY} onChange={(e) => reiniciar(() => setDesde(e.target.value))} />
        </label>
        <label className="tc-filtro">
          Hasta
          <input type="date" value={hasta} min={desde || undefined} max={HOY} onChange={(e) => reiniciar(() => setHasta(e.target.value))} />
        </label>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Fecha</th>
                <th>Fuente</th>
                <th>Compra</th>
                <th>Venta</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={6} icono="swap" titulo="No hay tipos de cambio con esos filtros" descripcion="Cambia las fechas o usa «Actualizar SUNAT» para traer el de hoy." />
              )}
              {filas.map((f, i) => (
                <tr key={f.id}>
                  <td className="centrado celda-suave">{desdeFila + i}</td>
                  <td><strong>{fecha(f.fecha)}</strong></td>
                  <td><span className="pildora" data-tono={tonoDe(f.fuente)} style={{ minWidth: 0 }}>{nombreDe(f.fuente)}</span></td>
                  <td>{Number(f.compra).toFixed(3)}</td>
                  <td>{Number(f.venta).toFixed(3)}</td>
                  <td className="centrado">
                    {f.es_manual ? (
                      <span className="acciones-fila">
                        {puede('EDITAR') && (
                          <button type="button" className="accion-icono editar" title="Editar" aria-label={`Editar el tipo de cambio del ${fecha(f.fecha)}`} onClick={() => setModal({ fila: f })}>
                            <Icono nombre="lapiz" tam={19} />
                          </button>
                        )}
                        {puede('ELIMINAR') && (
                          <button type="button" className="accion-icono peligro-suave" title="Eliminar" aria-label={`Eliminar el tipo de cambio del ${fecha(f.fecha)}`} onClick={() => setAEliminar(f)}>
                            <Icono nombre="papelera" tam={19} />
                          </button>
                        )}
                      </span>
                    ) : (
                      <span className="celda-suave" title="Dato oficial: no se modifica">Oficial</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
      </EstadoConsulta>

      {modal && <ManualModal fila={modal.fila} onCerrar={() => setModal(null)} />}
      {aEliminar && (
        <ConfirmarModal
          titulo="Eliminar tipo de cambio"
          mensaje={`¿Eliminar el tipo de cambio manual del ${fecha(aEliminar.fecha)}?`}
          textoConfirmar="Eliminar"
          enviando={eliminar.isPending}
          onConfirmar={() => eliminar.mutate(aEliminar)}
          onCerrar={() => setAEliminar(null)}
        />
      )}
    </main>
  )
}
