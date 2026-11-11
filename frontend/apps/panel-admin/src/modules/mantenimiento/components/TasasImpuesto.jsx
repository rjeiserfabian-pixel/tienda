import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'

const IMPUESTOS = [
  ['IGV', 'IGV (incluye el IPM)'],
  ['IVAP', 'IVAP'],
]
const SITUACION = {
  VIGENTE: { texto: 'Vigente', tono: 'verde' },
  FUTURA: { texto: 'Futura', tono: 'azul' },
  ANTERIOR: { texto: 'Anterior', tono: 'gris' },
}
const VACIO = { impuesto: 'IGV', porcentaje: '', vigente_desde: '' }

function NuevaTasa({ onListo }) {
  const [f, setF] = useState(VACIO)
  const [errores, setErrores] = useState({})
  const crear = useMutacion({
    mutationFn: (datos) => api.post('/mantenimiento/tasas-impuesto/', datos).then((r) => r.data),
    invalidar: [['tasas-impuesto']],
    exito: 'Tasa registrada.',
    alExito: () => {
      setF(VACIO)
      onListo()
    },
    avisarError: false,
  })
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const locales = {}
    const porcentaje = Number(String(f.porcentaje).replace(',', '.'))
    if (f.porcentaje === '' || !Number.isFinite(porcentaje) || porcentaje < 0 || porcentaje > 100) locales.porcentaje = 'Un número entre 0 y 100.'
    if (!f.vigente_desde) locales.vigente_desde = 'Indique desde qué fecha rige.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    crear.mutate(
      { impuesto: f.impuesto, porcentaje: String(porcentaje), vigente_desde: f.vigente_desde },
      { onError: (e) => setErrores({ general: 'No se pudo registrar.', ...erroresDeCampo(e) }) },
    )
  }

  return (
    <form className="igv-nueva-tasa" onSubmit={enviar} noValidate>
      <fieldset disabled={crear.isPending} className="sin-borde igv-fila-campos">
        <Campo etiqueta="Impuesto" tipo="select">
          {(p) => (
            <select {...p} value={f.impuesto} onChange={(e) => poner('impuesto', e.target.value)}>
              {IMPUESTOS.map(([v, t]) => (
                <option key={v} value={v}>{t}</option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Porcentaje" error={errores.porcentaje}>
          {(p) => <input {...p} inputMode="decimal" placeholder="Ej. 18" value={f.porcentaje} onChange={(e) => poner('porcentaje', e.target.value)} />}
        </Campo>
        <Campo etiqueta="Rige desde" icono="calendario" error={errores.vigente_desde || errores.general}>
          {(p) => <input {...p} type="date" min="2000-01-01" value={f.vigente_desde} onChange={(e) => poner('vigente_desde', e.target.value)} />}
        </Campo>
        <button type="submit" className="primario" disabled={crear.isPending}>
          <Icono nombre="agregar" tam={19} /> {crear.isPending ? 'Guardando…' : 'Agregar tasa'}
        </button>
      </fieldset>
    </form>
  )
}

const PORCENTAJE_VALIDO = (valor) => {
  const n = Number(String(valor).replace(',', '.'))
  return Number.isFinite(n) && n >= 0 && n <= 100 && String(valor).trim() !== '' ? n : null
}

/** Corrige el porcentaje o la fecha de una tasa; el servidor lo rechaza si un documento ya la usó. */
function EditarTasa({ tasa, onCerrar }) {
  const [f, setF] = useState({ porcentaje: String(Number(tasa.porcentaje)), vigente_desde: tasa.vigente_desde })
  const [errores, setErrores] = useState({})
  const guardar = useMutacion({
    mutationFn: (datos) => api.patch(`/mantenimiento/tasas-impuesto/${tasa.id}/`, datos).then((r) => r.data),
    invalidar: [['tasas-impuesto']],
    exito: 'Tasa actualizada.',
    alExito: onCerrar,
    avisarError: false,
  })
  const sinCambios = PORCENTAJE_VALIDO(f.porcentaje) === Number(tasa.porcentaje) && f.vigente_desde === tasa.vigente_desde
  const yaEmpezo = tasa.situacion !== 'FUTURA'

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || sinCambios) return
    const porcentaje = PORCENTAJE_VALIDO(f.porcentaje)
    const locales = {}
    if (porcentaje === null) locales.porcentaje = 'Un número entre 0 y 100.'
    if (!f.vigente_desde) locales.vigente_desde = 'Indique desde qué fecha rige.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    guardar.mutate(
      { porcentaje: String(porcentaje), vigente_desde: f.vigente_desde },
      { onError: (e) => setErrores({ general: mensajeDeError(e), ...erroresDeCampo(e) }) },
    )
  }

  return (
    <Modal titulo={`Editar la tasa de ${tasa.impuesto}`} subtitulo={`Hoy: ${Number(tasa.porcentaje)} % desde ${fechaCorta(tasa.vigente_desde)}`} onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={guardar.isPending} className="sin-borde">
          {yaEmpezo && (
            <p className="igv-aviso" role="note">
              Esta tasa ya está en uso. Edítala <strong>solo para corregir un error</strong>. Si la ley cambió el porcentaje, cierra esto y agrega una tasa nueva desde la fecha del cambio.
              Si ya hay documentos registrados con ella, el sistema no te dejará modificarla.
            </p>
          )}
          <Campo etiqueta="Porcentaje" error={errores.porcentaje}>
            {(p) => <input {...p} inputMode="decimal" value={f.porcentaje} onChange={(e) => setF((previo) => ({ ...previo, porcentaje: e.target.value }))} />}
          </Campo>
          <Campo etiqueta="Rige desde" icono="calendario" error={errores.vigente_desde}>
            {(p) => <input {...p} type="date" min="2000-01-01" value={f.vigente_desde} onChange={(e) => setF((previo) => ({ ...previo, vigente_desde: e.target.value }))} />}
          </Campo>
        </fieldset>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending || sinCambios}>
            {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Historial de tasas con su vigencia: un cambio de ley se agrega desde su fecha, sin tocar lo anterior. */
export default function TasasImpuesto() {
  const { tiene } = usePermisos()
  const puedeCrear = tiene('MANTENIMIENTO.IGV.CREAR', { organizacion: true })
  const puedeEditar = tiene('MANTENIMIENTO.IGV.EDITAR', { organizacion: true })
  const puedeEliminar = tiene('MANTENIMIENTO.IGV.ELIMINAR', { organizacion: true })
  const conAcciones = puedeEditar || puedeEliminar
  const [quitando, setQuitando] = useState(null)
  const [editando, setEditando] = useState(null)
  const consulta = useListado(['tasas-impuesto'], '/mantenimiento/tasas-impuesto/', { page_size: 50 })
  const filas = consulta.data?.results ?? []

  const quitar = useMutacion({
    mutationFn: (id) => api.delete(`/mantenimiento/tasas-impuesto/${id}/`),
    invalidar: [['tasas-impuesto']],
    exito: 'Tasa eliminada.',
    alExito: () => setQuitando(null),
  })

  return (
    <PanelTarjeta id="tasas" icono="chart" titulo="Tasas de impuesto" descripcion="El porcentaje que rige en cada fecha. Las compras y ventas usan la tasa de su propia fecha.">
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Impuesto</th>
                <th className="num">Porcentaje</th>
                <th>Desde</th>
                <th>Hasta</th>
                <th>Situación</th>
                {conAcciones && <th className="centrado">Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <tr><td colSpan={conAcciones ? 6 : 5} className="estado-vacio">No hay tasas cargadas.</td></tr>}
              {filas.map((t) => (
                <tr key={t.id}>
                  <td><strong>{t.impuesto}</strong></td>
                  <td className="num">{Number(t.porcentaje).toLocaleString('es-PE', { minimumFractionDigits: 2 })} %</td>
                  <td>{fechaCorta(t.vigente_desde)}</td>
                  <td className="celda-suave">{t.vigente_hasta ? fechaCorta(t.vigente_hasta) : 'Sin fin'}</td>
                  <td><span className="pildora" data-tono={SITUACION[t.situacion].tono}>{SITUACION[t.situacion].texto}</span></td>
                  {conAcciones && (
                    <td className="centrado">
                      <span className="acciones-fila">
                        {puedeEditar && (
                          <button type="button" className="accion-icono editar" aria-label={`Editar la tasa de ${t.impuesto} desde ${fechaCorta(t.vigente_desde)}`} title="Editar" onClick={() => setEditando(t)}>
                            <Icono nombre="lapiz" tam={19} />
                          </button>
                        )}
                        {puedeEliminar && t.situacion === 'FUTURA' && (
                          <button type="button" className="accion-icono peligro-suave" aria-label={`Eliminar la tasa de ${t.impuesto} desde ${fechaCorta(t.vigente_desde)}`} title="Eliminar" onClick={() => setQuitando(t)}>
                            <Icono nombre="papelera" tam={19} />
                          </button>
                        )}
                      </span>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>
      {puedeCrear ? (
        <>
          <h4 className="igv-subtitulo">Agregar una tasa nueva</h4>
          <p className="celda-suave">Si la ley cambia el porcentaje, agrégalo con la fecha en que empieza: es una sola fila por cambio de ley, y la anterior queda como historia. Para corregir un error de digitación usa el lápiz de la tabla.</p>
          <NuevaTasa onListo={() => consulta.refetch()} />
          <p className="celda-suave">
            El <strong>IVAP</strong> no viene cargado: pide a tu contador el porcentaje vigente y regístralo aquí antes de usar esa afectación.
          </p>
        </>
      ) : null}
      {editando && <EditarTasa tasa={editando} onCerrar={() => setEditando(null)} />}
      {quitando && (
        <ConfirmarModal
          titulo="Eliminar tasa"
          mensaje={`¿Eliminar la tasa de ${quitando.impuesto} (${quitando.porcentaje} %) que empezaría el ${fechaCorta(quitando.vigente_desde)}?`}
          textoConfirmar="Eliminar"
          enviando={quitar.isPending}
          onConfirmar={() => quitar.mutate(quitando.id)}
          onCerrar={() => setQuitando(null)}
        />
      )}
    </PanelTarjeta>
  )
}
