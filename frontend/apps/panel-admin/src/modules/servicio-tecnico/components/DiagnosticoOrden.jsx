import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useConfiguracionServicio } from '../hooks/useConfiguracionServicio'

const VACIO = []
const desdeOrden = (o) => ({
  diagnostico: o.diagnostico,
  trabajos: o.trabajos_a_realizar,
  horas: o.horas_estimadas ?? '',
  tipoServicio: '',
  notaInterna: o.nota_interna,
  notaCliente: o.nota_cliente,
})

function Lectura({ titulo, children }) {
  return (
    <div className="gasto-dato">
      <dt>{titulo}</dt>
      <dd>{children || <span className="celda-suave">Sin completar</span>}</dd>
    </div>
  )
}

/** Formulario del diagnóstico: lo que el técnico concluye, el tiempo que calcula y las notas. */
function Formulario({ orden: o, onCerrar }) {
  const [f, setF] = useState(() => desdeOrden(o))
  const [errores, setErrores] = useState({})
  const tipos = useConfiguracionServicio(o.empresa).data?.tipos_servicio ?? VACIO
  const poner = (campo) => (e) => setF((previo) => ({ ...previo, [campo]: e.target.value }))

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${o.id}/diagnostico/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio']],
    exito: 'Diagnóstico guardado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const horas = String(f.horas).trim().replace(',', '.')
    if (horas && !/^\d{1,3}(\.\d)?$/.test(horas)) return setErrores({ horas: 'Use horas con un decimal, por ejemplo 1.5.' })
    setErrores({})
    guardar.mutate(
      {
        diagnostico: f.diagnostico,
        trabajos_a_realizar: f.trabajos,
        horas_estimadas: horas === '' ? null : horas,
        nota_interna: f.notaInterna,
        nota_cliente: f.notaCliente,
        ...(f.tipoServicio ? { tipo_servicio: Number(f.tipoServicio) } : {}),
      },
      {
        onError: (e) => {
          const campos = erroresDeCampo(e)
          setErrores({ general: Object.keys(campos).length ? 'Revise los datos marcados.' : mensajeDeError(e), diagnostico: campos.diagnostico, trabajos: campos.trabajos_a_realizar, horas: campos.horas_estimadas, tipoServicio: campos.tipo_servicio })
        },
      },
    )
  }

  return (
    <form onSubmit={enviar} noValidate>
      <Campo etiqueta="Diagnóstico" error={errores.diagnostico} contador={{ actual: f.diagnostico.length, max: 2000 }} ayuda="Qué falla tiene el equipo y por qué.">
        {(p) => <textarea {...p} rows={4} maxLength={2000} value={f.diagnostico} disabled={guardar.isPending} onChange={poner('diagnostico')} />}
      </Campo>
      <Campo etiqueta="Trabajos a realizar" error={errores.trabajos} contador={{ actual: f.trabajos.length, max: 2000 }} ayuda="Lo que hay que hacer para solucionarlo.">
        {(p) => <textarea {...p} rows={3} maxLength={2000} value={f.trabajos} disabled={guardar.isPending} onChange={poner('trabajos')} />}
      </Campo>
      <div className="fila-campos">
        <Campo etiqueta="Tipo de servicio" tipo="select" error={errores.tipoServicio} ayuda="Define por qué estados pasa la orden.">
          {(p) => (
            <select {...p} value={f.tipoServicio} disabled={guardar.isPending} onChange={poner('tipoServicio')}>
              <option value="">{o.tipo_servicio ? 'Dejar el actual' : 'Aún no se sabe'}</option>
              {tipos.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.nombre}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Horas estimadas" error={errores.horas}>
          {(p) => <input {...p} inputMode="decimal" placeholder="Ej. 1.5" value={f.horas} disabled={guardar.isPending} onChange={poner('horas')} />}
        </Campo>
      </div>
      <Campo etiqueta="Nota para el cliente" contador={{ actual: f.notaCliente.length, max: 1000 }} ayuda="Lo que se le puede contar al cliente, sin tecnicismos.">
        {(p) => <textarea {...p} rows={2} maxLength={1000} value={f.notaCliente} disabled={guardar.isPending} onChange={poner('notaCliente')} />}
      </Campo>
      <Campo etiqueta="Nota interna" contador={{ actual: f.notaInterna.length, max: 1000 }} ayuda="Solo la ve el taller.">
        {(p) => <textarea {...p} rows={2} maxLength={1000} value={f.notaInterna} disabled={guardar.isPending} onChange={poner('notaInterna')} />}
      </Campo>
      {errores.general && (
        <p role="alert" className="campo-error">
          {errores.general}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
          Cancelar
        </button>
        <button type="submit" className="primario" disabled={guardar.isPending}>
          {guardar.isPending ? 'Guardando…' : 'Guardar diagnóstico'}
        </button>
      </div>
    </form>
  )
}

/** Diagnóstico y trabajos de la orden. Quien trabaja la orden puede editarlo; los demás lo leen. */
export default function DiagnosticoOrden({ orden: o }) {
  const [editando, setEditando] = useState(false)

  return (
    <PanelTarjeta
      icono="wrench"
      titulo="Diagnóstico y trabajos"
      descripcion="Lo que el técnico concluye al revisar el equipo."
      acciones={
        o.permite.diagnosticar && !editando ? (
          <button type="button" className="boton-cabecera" onClick={() => setEditando(true)}>
            {o.diagnostico ? 'Editar' : 'Escribir diagnóstico'}
          </button>
        ) : undefined
      }
    >
      {editando ? (
        <Formulario orden={o} onCerrar={() => setEditando(false)} />
      ) : (
        <dl className="servicio-cabecera-ficha">
          <Lectura titulo="Diagnóstico">{o.diagnostico && <p className="servicio-texto">{o.diagnostico}</p>}</Lectura>
          <Lectura titulo="Trabajos a realizar">{o.trabajos_a_realizar && <p className="servicio-texto">{o.trabajos_a_realizar}</p>}</Lectura>
          <Lectura titulo="Horas estimadas">{o.horas_estimadas !== null && o.horas_estimadas !== undefined ? `${o.horas_estimadas} h` : ''}</Lectura>
          <Lectura titulo="Nota para el cliente">{o.nota_cliente && <p className="servicio-texto">{o.nota_cliente}</p>}</Lectura>
          <Lectura titulo="Nota interna">{o.nota_interna && <p className="servicio-texto">{o.nota_interna}</p>}</Lectura>
        </dl>
      )}
    </PanelTarjeta>
  )
}
