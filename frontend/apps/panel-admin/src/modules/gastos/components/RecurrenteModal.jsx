import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { hoyIso, paraServidor } from '../../almacen/inventario'
import { validarRecurrente } from '../gastos'
import ProveedorGasto from './ProveedorGasto'

const CAMPOS = { nombre: 'nombre', categoria: 'categoria', descripcion: 'descripcion', tipo_comprobante: 'tipo', proveedor: 'proveedor', importe_estimado: 'importe', periodicidad: 'periodicidad', proxima_fecha: 'proxima', avisar_dias: 'avisar' }

const desdeRegistro = (r) => ({
  nombre: r?.nombre ?? '',
  categoria: r ? String(r.categoria) : '',
  descripcion: r?.descripcion ?? '',
  conComprobante: r?.con_comprobante ?? true,
  tipo: r?.tipo_comprobante ? String(r.tipo_comprobante) : '',
  proveedor: r?.proveedor ? { id: r.proveedor, nombre: r.proveedor_nombre, tipo_documento: r.proveedor_tipo_documento, numero_documento: r.proveedor_documento } : null,
  moneda: r?.moneda ?? 'PEN',
  importe: r?.importe_estimado ?? '',
  periodicidad: r ? String(r.periodicidad) : '',
  proxima: r?.proxima_fecha ?? hoyIso(),
  avisar: String(r?.avisar_dias ?? 5),
})

/**
 * Crear o editar un gasto recurrente: lo que se paga cada cierto tiempo (alquiler, luz, internet).
 * El sistema no lo registra solo: avisa cuándo toca y propone estos datos.
 */
export default function RecurrenteModal({ registro, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const [f, setF] = useState(() => desdeRegistro(registro))
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const categorias = useOpciones('/mantenimiento/categorias-gasto/').data ?? []
  const periodicidades = useOpciones('/mantenimiento/periodicidades/').data ?? []
  const comprobantes = useOpciones('/mantenimiento/tipos-comprobante/', { aplica_compras: '1' }).data ?? []

  const guardar = useMutacion({
    mutationFn: (cuerpo) => (registro ? api.patch(`/gastos/recurrentes/${registro.id}/`, cuerpo) : api.post('/gastos/recurrentes/', cuerpo)).then((r) => r.data),
    invalidar: [['gastos'], ['caja']],
    exito: registro ? 'Gasto recurrente guardado.' : 'Gasto recurrente creado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const locales = validarRecurrente(f)
    setErrores(locales)
    setGeneral('')
    if (Object.keys(locales).length) return
    const cuerpo = {
      ...(registro ? {} : { empresa: empresaActivaId }),
      nombre: f.nombre.trim(),
      categoria: Number(f.categoria),
      descripcion: f.descripcion.trim(),
      con_comprobante: f.conComprobante,
      tipo_comprobante: f.conComprobante && f.tipo ? Number(f.tipo) : null,
      proveedor: f.conComprobante && f.proveedor ? f.proveedor.id : null,
      moneda: f.moneda,
      importe_estimado: String(f.importe).trim() ? paraServidor(f.importe) : null,
      periodicidad: Number(f.periodicidad),
      proxima_fecha: f.proxima,
      avisar_dias: Number(f.avisar),
    }
    guardar.mutate(cuerpo, {
      onError: (error) => {
        const campos = erroresDeCampo(error)
        const mapeados = Object.fromEntries(Object.entries(campos).flatMap(([k, v]) => (CAMPOS[k] ? [[CAMPOS[k], v]] : [])))
        setErrores(mapeados)
        setGeneral(Object.keys(mapeados).length ? 'Revise los datos marcados.' : mensajeDeError(error))
      },
    })
  }

  const simbolo = f.moneda === 'USD' ? 'US$' : 'S/'
  return (
    <Modal titulo={registro ? 'Editar gasto recurrente' : 'Nuevo gasto recurrente'} subtitulo="Lo que pagas cada cierto tiempo. El sistema te avisa cuándo toca; tú confirmas el importe cada vez." onCerrar={onCerrar} ancho={780}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={guardar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="fila-campos">
            <Campo etiqueta="Nombre" requerido error={errores.nombre}>
              {(p) => <input {...p} maxLength={80} placeholder="Ej. Alquiler del local" value={f.nombre} onChange={(e) => poner('nombre', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Categoría" tipo="select" requerido error={errores.categoria}>
              {(p) => (
                <select {...p} value={f.categoria} onChange={(e) => poner('categoria', e.target.value)}>
                  <option value="">Elija la categoría</option>
                  {categorias.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
          </div>
          <Campo etiqueta="¿Qué es y para qué?" requerido error={errores.descripcion} contador={{ actual: f.descripcion.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} placeholder="Ej. Alquiler mensual del local de Tarapoto" value={f.descripcion} onChange={(e) => poner('descripcion', e.target.value)} />}
          </Campo>
          <div className="segmentos" role="radiogroup" aria-label="¿Tiene comprobante?">
            {[[true, 'Con comprobante'], [false, 'Sin comprobante']].map(([valor, texto]) => (
              <button key={texto} type="button" role="radio" aria-checked={f.conComprobante === valor} className={f.conComprobante === valor ? 'activo' : undefined} onClick={() => poner('conComprobante', valor)}>
                {texto}
              </button>
            ))}
          </div>
          {f.conComprobante && (
            <>
              <Campo etiqueta="Tipo de comprobante" tipo="select" error={errores.tipo} ayuda="Opcional: se propone al registrar el gasto.">
                {(p) => (
                  <select {...p} value={f.tipo} onChange={(e) => poner('tipo', e.target.value)}>
                    <option value="">Lo elijo al registrar</option>
                    {comprobantes.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <ProveedorGasto proveedor={f.proveedor} onElegir={(p) => poner('proveedor', p)} error={errores.proveedor} obligatorio={false} disabled={guardar.isPending} />
            </>
          )}
          <div className="fila-campos">
            <Campo etiqueta="Moneda" tipo="select">
              {(p) => (
                <select {...p} value={f.moneda} onChange={(e) => poner('moneda', e.target.value)}>
                  <option value="PEN">Soles (S/)</option>
                  <option value="USD">Dólares (US$)</option>
                </select>
              )}
            </Campo>
            <Campo etiqueta={`Importe habitual (${simbolo})`} error={errores.importe} ayuda="Opcional. Es solo una guía: lo confirmas cada vez.">
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.importe} onChange={(e) => poner('importe', e.target.value)} />}
            </Campo>
          </div>
          <div className="fila-campos">
            <Campo etiqueta="Se repite" tipo="select" requerido error={errores.periodicidad}>
              {(p) => (
                <select {...p} value={f.periodicidad} onChange={(e) => poner('periodicidad', e.target.value)}>
                  <option value="">Elija cada cuánto</option>
                  {periodicidades.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Le toca el" icono="calendario" requerido error={errores.proxima} ayuda="La próxima vez que hay que pagarlo.">
              {(p) => <input {...p} type="date" value={f.proxima} onChange={(e) => poner('proxima', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Avisar con" error={errores.avisar} ayuda="Días de anticipación.">
              {(p) => <input {...p} type="number" min={0} max={30} value={f.avisar} onChange={(e) => poner('avisar', e.target.value)} />}
            </Campo>
          </div>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
