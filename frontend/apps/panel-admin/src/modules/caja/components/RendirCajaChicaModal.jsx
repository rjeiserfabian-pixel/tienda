import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, totalDeGastos } from '../caja'

/**
 * Rendir la caja chica: se marcan los gastos que se presentan y otra caja repone exactamente ese
 * total, para que el fondo vuelva a su monto fijo.
 */
export default function RendirCajaChicaModal({ caja, cuentas, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const origenes = cuentas.filter((c) => c.cuenta !== caja.cuenta && c.moneda === caja.moneda && c.estado === 'ACTIVO')
  const principal = origenes.find((c) => c.rol_caja === 'PRINCIPAL')
  const [origen, setOrigen] = useState(principal ? String(principal.cuenta) : '')
  const [glosa, setGlosa] = useState('')
  const [desmarcados, setDesmarcados] = useState(() => new Set())
  const [error, setError] = useState('')

  const consulta = useQuery({
    queryKey: ['caja', 'gastos-por-rendir', caja.cuenta],
    queryFn: ({ signal }) => api.get('/caja/caja-chica/gastos/', { params: { empresa: empresaActivaId, cuenta: caja.cuenta }, signal }).then((r) => r.data),
    staleTime: 0,
  })
  const gastos = consulta.data ?? []
  const marcados = new Set(gastos.filter((g) => !desmarcados.has(g.id)).map((g) => g.id))
  const total = totalDeGastos(gastos, marcados)
  const elegido = origenes.find((c) => String(c.cuenta) === origen)

  const rendir = useMutacion({
    mutationFn: (cuerpo) => api.post('/caja/rendiciones/', cuerpo, { timeout: 30_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: (r) => `Rendición ${String(r.numero).padStart(6, '0')} hecha: se repusieron ${dinero(r.total, caja.moneda)}.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const alternar = (id) =>
    setDesmarcados((previo) => {
      const siguiente = new Set(previo)
      if (siguiente.has(id)) siguiente.delete(id)
      else siguiente.add(id)
      return siguiente
    })

  const enviar = (evento) => {
    evento.preventDefault()
    if (rendir.isPending) return
    if (marcados.size === 0) return setError('Marque al menos un gasto.')
    if (!origen) return setError('Elija la caja que repone el fondo.')
    setError('')
    rendir.mutate(
      { empresa: empresaActivaId, cuenta: caja.cuenta, cuenta_origen: Number(origen), movimientos: [...marcados], ...(glosa.trim() ? { glosa: glosa.trim() } : {}) },
      { onError: (e) => setError(Object.values(erroresDeCampo(e))[0] || mensajeDeError(e)) },
    )
  }

  return (
    <Modal titulo="Rendir la caja chica" subtitulo={`${caja.nombre} · fondo fijo ${dinero(caja.fondo, caja.moneda)}`} onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <p className="celda-suave">Marca los gastos que presentas con sus comprobantes. Otra caja repone exactamente ese total y el fondo vuelve a su monto.</p>
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
          {gastos.length === 0 ? (
            <p className="estado-vacio">No hay gastos por rendir.</p>
          ) : (
            <div role="group" aria-label="Gastos por rendir">
              {gastos.map((g) => (
                <label key={g.id} className="gasto-fila">
                  <input type="checkbox" checked={marcados.has(g.id)} disabled={rendir.isPending} onChange={() => alternar(g.id)} />
                  <span>{fechaCorta(g.fecha)}</span>
                  <span className="col-texto">
                    {g.concepto_nombre}
                    {(g.glosa || g.adjuntos_cantidad > 0) && (
                      <span className="sub-texto">
                        {g.glosa}
                        {g.adjuntos_cantidad > 0 ? ` · ${g.adjuntos_cantidad} voucher` : ' · sin voucher'}
                      </span>
                    )}
                  </span>
                  <span className="caja-egreso">{dinero(g.monto, caja.moneda)}</span>
                </label>
              ))}
            </div>
          )}
        </EstadoConsulta>
        <dl className="conteo-resumen" aria-live="polite">
          <div>
            <dt>Gastos marcados</dt>
            <dd>{marcados.size}</dd>
          </div>
          <div>
            <dt>Se repone</dt>
            <dd>{dinero(total, caja.moneda)}</dd>
          </div>
        </dl>
        <fieldset disabled={rendir.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="fila-campos">
            <Campo etiqueta="Repone desde" tipo="select" requerido>
              {(p) => (
                <select {...p} value={origen} onChange={(e) => setOrigen(e.target.value)}>
                  <option value="">Elija la caja o cuenta</option>
                  {origenes.map((c) => (
                    <option key={c.cuenta} value={c.cuenta}>
                      {c.nombre} · {dinero(c.saldo, c.moneda)}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Nota" contador={{ actual: glosa.length, max: 250 }}>
              {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={glosa} onChange={(e) => setGlosa(e.target.value)} />}
            </Campo>
          </div>
          {elegido && total > Number(elegido.saldo) && <p className="compra-aviso">«{elegido.nombre}» tiene {dinero(elegido.saldo, elegido.moneda)}: la reposición la dejaría en negativo.</p>}
        </fieldset>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={rendir.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={rendir.isPending || gastos.length === 0}>
            {rendir.isPending ? 'Rindiendo…' : 'Rendir y reponer'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
