import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero } from '../caja'

/**
 * Abre el turno de una caja de efectivo. El fondo inicial, si lo hay, sale de otra caja (la principal
 * de la tienda, que se propone sola) y entra de inmediato a esta.
 */
export default function AbrirSesionModal({ cuenta, cuentas, onCerrar, alAbrir }) {
  const { empresaActivaId } = useEmpresas()
  const origenes = cuentas.filter((c) => c.tipo === 'CAJA' && c.moneda === cuenta.moneda && c.cuenta !== cuenta.cuenta && c.estado === 'ACTIVO')
  const sugerida = origenes.find((c) => c.rol_caja === 'PRINCIPAL' && c.sucursal_nombre === cuenta.sucursal_nombre) ?? origenes.find((c) => c.rol_caja === 'PRINCIPAL')
  const [fondo, setFondo] = useState(Number(cuenta.fondo_inicial) > 0 ? String(Number(cuenta.fondo_inicial)) : '')
  const [desde, setDesde] = useState(sugerida ? String(sugerida.cuenta) : '')
  const [observacion, setObservacion] = useState('')
  const [conHermanas, setConHermanas] = useState(true)
  const comparte = cuenta.comparte_con ?? []
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const abrir = useMutacion({
    mutationFn: (datos) => api.post('/caja/sesiones/', datos, { timeout: 30_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: (s) => `Sesión ${String(s.numero).padStart(6, '0')} abierta en ${cuenta.nombre}.`,
    alExito: (s) => {
      alAbrir?.(s)
      onCerrar()
    },
    avisarError: false,
  })

  const monto = aNumero(fondo)
  const origen = origenes.find((c) => String(c.cuenta) === desde)

  const enviar = (evento) => {
    evento.preventDefault()
    if (abrir.isPending) return
    const e = {}
    if (String(fondo).trim() && !/^\d{1,14}([.,]\d{1,2})?$/.test(String(fondo).trim())) e.fondo = 'Un número, con hasta 2 decimales.'
    if (monto > 0 && !desde) e.desde = 'Elija de qué caja sale el fondo.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    abrir.mutate(
      {
        empresa: empresaActivaId,
        cuenta: cuenta.cuenta,
        ...(monto > 0 ? { fondo: paraServidor(fondo), desde_cuenta: Number(desde) } : {}),
        ...(comparte.length > 0 && conHermanas ? { con_hermanas: true } : {}),
        ...(observacion.trim() ? { observacion: observacion.trim() } : {}),
      },
      {
        onError: (error) => {
          const campos = erroresDeCampo(error)
          setErrores({ fondo: campos.fondo, desde: campos.desde_cuenta })
          setGeneral(Object.keys(campos).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo={`Abrir ${cuenta.nombre}`} subtitulo={`Hay ${dinero(cuenta.saldo, cuenta.moneda)} en la caja según el sistema.`} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={abrir.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <p className="celda-suave">Al abrir la sesión empiezas tu turno: todo el efectivo que entre o salga de esta caja queda en ella hasta que la cierres y cuentes el dinero.</p>
          <div className="fila-campos">
            <Campo etiqueta={`Fondo inicial (${cuenta.moneda === 'USD' ? 'US$' : 'S/'})`} error={errores.fondo} ayuda="Opcional. Efectivo que se te entrega para empezar.">
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={fondo} onChange={(e) => setFondo(e.target.value)} />}
            </Campo>
            {monto > 0 && (
              <Campo etiqueta="Sale de" tipo="select" error={errores.desde}>
                {(p) => (
                  <select {...p} value={desde} onChange={(e) => setDesde(e.target.value)}>
                    <option value="">Elija la caja</option>
                    {origenes.map((c) => (
                      <option key={c.cuenta} value={c.cuenta}>
                        {c.nombre} · {dinero(c.saldo, c.moneda)}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
            )}
          </div>
          {monto > 0 && origenes.length === 0 && (
            <p className="compra-aviso" role="status">
              El fondo se pasa desde otra caja de efectivo de la empresa, y «{cuenta.nombre}» es la única. Abre sin fondo y registra el dinero en «Movimientos» como un Ingreso, o crea otra caja (la principal o la chica) en «Cajas y cuentas».
            </p>
          )}
          {comparte.length > 0 && (
            <label className="caja-compartida">
              <span>
                <input type="checkbox" checked={conHermanas} onChange={(e) => setConHermanas(e.target.checked)} />{' '}
                <strong>Este mostrador lo comparten {comparte.join(' y ')}.</strong> Abrir también sus cajas (sin fondo): al cerrar, se cuenta el cajón una sola vez.
              </span>
            </label>
          )}
          {origen && monto > Number(origen.saldo) && <p className="compra-aviso">«{origen.nombre}» tiene {dinero(origen.saldo, origen.moneda)}: el fondo la dejaría en negativo.</p>}
          <Campo etiqueta="Observación" contador={{ actual: observacion.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={observacion} onChange={(e) => setObservacion(e.target.value)} />}
          </Campo>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={abrir.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={abrir.isPending}>
            {abrir.isPending ? 'Abriendo…' : 'Abrir sesión'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
