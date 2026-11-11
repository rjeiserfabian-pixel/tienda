import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

/**
 * El almacén tomó otra unidad: cambia la serie que se entrega en una línea del pedido.
 * El comprobante ya emitido NO cambia (sigue con la serie asignada al pagar); queda registrado
 * qué serie se entregó de verdad, quién la cambió y por qué.
 */
export default function CambiarSerieModal({ numero, linea, invalidar, onCerrar }) {
  const actuales = linea.series_panel?.entregadas ?? []
  const [anterior, setAnterior] = useState(actuales[0] ?? '')
  const [nueva, setNueva] = useState('')
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')

  const guardar = useMutacion({
    mutationFn: () =>
      api
        .post(`/tienda/admin/pedidos/${numero}/serie/`, {
          linea: linea.id,
          anterior,
          nueva: nueva.trim().toUpperCase(),
          motivo: motivo.trim(),
        })
        .then((r) => r.data),
    invalidar,
    exito: 'Serie cambiada.',
    avisarError: false,
    alExito: onCerrar,
  })

  const enviar = (e) => {
    e.preventDefault()
    setError('')
    guardar.mutate(undefined, { onError: (err) => setError(mensajeDeError(err)) })
  }
  const listo = anterior && nueva.trim().length >= 3 && motivo.trim().length >= 3

  return (
    <Modal titulo="Cambiar la serie" subtitulo={linea.descripcion} onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        <p className="celda-suave">
          Usa esto solo si la unidad que tomaste del almacén es otra. La serie del comprobante no cambia; el sistema
          anota cuál se entregó realmente.
        </p>
        {actuales.length > 1 && (
          <Campo etiqueta="Serie a reemplazar" tipo="select">
            {(p) => (
              <select {...p} value={anterior} onChange={(e) => setAnterior(e.target.value)}>
                {actuales.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        )}
        {actuales.length === 1 && (
          <p>
            Serie actual: <strong>{anterior}</strong>
          </p>
        )}
        <Campo etiqueta="Serie de la unidad que tomaste" requerido ayuda="Escanéala o escríbela tal como está en el equipo.">
          {(p) => <input {...p} autoFocus autoComplete="off" maxLength={40} value={nueva} onChange={(e) => setNueva(e.target.value.toUpperCase())} />}
        </Campo>
        <Campo etiqueta="Motivo del cambio" requerido contador={{ actual: motivo.length, max: 200 }}>
          {(p) => <input {...p} maxLength={200} value={motivo} placeholder="Ej.: la unidad estaba dañada" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="acciones">
          <button type="button" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={!listo || guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Cambiar serie'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
