import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { fechaCorta, hoyIso, paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero, numeroInterno } from '../compras'

const centimos = (n) => Math.round((n ?? 0) * 100)

/**
 * Usa un saldo a favor para pagar una compra a crédito del mismo proveedor y moneda. No mueve
 * dinero en las cajas: las cuotas quedan pagadas con el saldo, de la más antigua a la más nueva.
 */
export default function UsarSaldoModal({ credito, onCerrar }) {
  const disponible = aNumero(credito.disponible)
  const deudas = useQuery({
    queryKey: ['compras', 'por-pagar', 'de-saldo', credito.id],
    queryFn: ({ signal }) =>
      api
        .get('/compras/por-pagar/', { params: { empresa: credito.empresa, proveedor: credito.proveedor, page_size: 100 }, signal })
        .then((r) => r.data.results.filter((c) => c.moneda === credito.moneda)),
    staleTime: 0,
  })
  const [compraId, setCompraId] = useState('')
  const [monto, setMonto] = useState('')
  const [fecha, setFecha] = useState(hoyIso())
  const [error, setError] = useState({})
  const [general, setGeneral] = useState('')

  const compras = deudas.data ?? []
  const compra = compras.find((c) => String(c.id) === String(compraId)) ?? (compras.length === 1 ? compras[0] : null)
  const saldoCompra = aNumero(compra?.saldo) ?? 0
  const tope = Math.min(disponible, saldoCompra)
  const montoFinal = monto === '' ? (compra ? (tope).toFixed(2) : '') : monto

  const cuerpo = compra ? { compra: compra.id, monto: paraServidor(montoFinal), fecha } : null
  const clave = useClaveIdempotente(cuerpo)
  const aplicar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`/compras/creditos/${credito.id}/aplicar/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras']],
    exito: 'Saldo a favor aplicado a la compra.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (aplicar.isPending) return
    const campos = {}
    if (!compra) campos.compra = 'Elija la compra a pagar.'
    const n = aNumero(montoFinal)
    if (n === null || n <= 0) campos.monto = 'Mayor que cero.'
    else if (!/^\d+([.,]\d{1,2})?$/.test(String(montoFinal).trim())) campos.monto = 'Hasta 2 decimales.'
    else if (centimos(n) > centimos(tope)) campos.monto = `Como máximo ${dinero(tope, credito.moneda)}.`
    if (!fecha) campos.fecha = 'Indique la fecha.'
    else if (fecha > hoyIso()) campos.fecha = 'No puede ser futura.'
    else if (compra && fecha < compra.fecha_emision) campos.fecha = 'No puede ser anterior a la compra.'
    setError(campos)
    setGeneral('')
    if (Object.keys(campos).length) return
    aplicar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (e) => {
          const delServidor = erroresDeCampo(e)
          setGeneral(Object.keys(delServidor).length ? Object.values(delServidor).join(' ') : mensajeDeError(e))
        },
      },
    )
  }

  return (
    <Modal titulo="Usar saldo a favor" subtitulo={`${credito.proveedor_nombre} · disponible ${dinero(credito.disponible, credito.moneda)}`} onCerrar={onCerrar} ancho={620}>
      <EstadoConsulta consulta={deudas} hayDatos={Boolean(deudas.data)}>
        {compras.length === 0 ? (
          <>
            <p className="estado-vacio">Este proveedor no tiene compras a crédito con deuda en {credito.moneda === 'USD' ? 'dólares' : 'soles'}.</p>
            <div className="modal-pie">
              <button type="button" onClick={onCerrar}>
                Cerrar
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={enviar} noValidate>
            <fieldset disabled={aplicar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
              <Campo etiqueta="Compra a pagar" tipo="select" requerido error={error.compra}>
                {(p) => (
                  <select
                    {...p}
                    value={compra ? String(compra.id) : ''}
                    onChange={(e) => {
                      setCompraId(e.target.value)
                      setMonto('')
                    }}
                  >
                    <option value="">Elija la compra</option>
                    {compras.map((c) => (
                      <option key={c.id} value={c.id}>
                        N° {numeroInterno(c)} · {c.comprobante} del {fechaCorta(c.fecha_emision)} · debe {dinero(c.saldo, c.moneda)}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <div className="fila-campos">
                <Campo etiqueta="Monto a usar" requerido error={error.monto} ayuda={compra ? `Como máximo ${dinero(tope, credito.moneda)}` : undefined}>
                  {(p) => <input {...p} inputMode="decimal" value={montoFinal} onChange={(e) => setMonto(e.target.value)} />}
                </Campo>
                <Campo etiqueta="Fecha" icono="calendario" requerido error={error.fecha}>
                  {(p) => <input {...p} type="date" max={hoyIso()} value={fecha} onChange={(e) => setFecha(e.target.value)} />}
                </Campo>
              </div>
              <p className="celda-suave">Se aplica a las cuotas de la más antigua a la más nueva. No sale dinero de ninguna caja.</p>
            </fieldset>
            {general && (
              <p role="alert" className="campo-error">
                {general}
              </p>
            )}
            <div className="modal-pie">
              <button type="button" onClick={onCerrar} disabled={aplicar.isPending}>
                Cancelar
              </button>
              <button type="submit" className="primario" disabled={aplicar.isPending}>
                {aplicar.isPending ? 'Aplicando…' : 'Usar saldo'}
              </button>
            </div>
          </form>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
