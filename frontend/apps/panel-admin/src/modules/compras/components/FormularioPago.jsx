import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { hoyIso, paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero, nuevoPago, repartirPago, resolverPagos, totalPagado } from '../compras'
import PagosContado from './PagosContado'

const centimos = (n) => Math.round(n * 100)

/**
 * Pagar una deuda: una o varias filas de pago (efectivo y Yape, por ejemplo), cada una con su caja
 * o cuenta. Por defecto paga todo; se puede escribir menos y el resto queda pendiente. Dice a qué
 * cuotas se aplicará antes de confirmar.
 */
export default function FormularioPago({ compra, cuotasIniciales = [], onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeVerCajas = tiene('CAJA.CUENTAS.VER')
  const moneda = compra.moneda
  const pendientes = compra.cuotas.filter((c) => aNumero(c.saldo) > 0)
  const deuda = pendientes.reduce((s, c) => s + centimos(aNumero(c.saldo)), 0) / 100

  const medios = useOpciones('/mantenimiento/medios-pago/').data ?? []
  const cuentas = useOpciones('/mantenimiento/cuentas/', { empresa: empresaActivaId }, { enabled: puedeVerCajas && Boolean(empresaActivaId) }).data ?? []

  // '' = las cuotas en orden; 'elegidas' = las que se marcaron en la ficha; un número = solo esa cuota
  const [cuota, setCuota] = useState(cuotasIniciales.length ? 'elegidas' : '')
  const [pagos, setPagos] = useState(() => [nuevoPago()])
  const [fecha, setFecha] = useState(hoyIso())
  const [errores, setErrores] = useState({ campos: {}, pagos: {} })
  const [general, setGeneral] = useState('')

  const ids = cuota === 'elegidas' ? cuotasIniciales : cuota ? [Number(cuota)] : []
  const elegidas = pendientes.filter((c) => ids.includes(c.id))
  const tope = ids.length ? elegidas.reduce((s, c) => s + centimos(aNumero(c.saldo)), 0) / 100 : deuda
  const resueltos = resolverPagos(pagos, tope.toFixed(2), { medios, cuentas, moneda, tipoCambio: moneda === 'USD' ? compra.tipo_cambio : '' })
  const suma = totalPagado(resueltos)
  const aplicacion = repartirPago(compra.cuotas, suma, ids)

  const cuerpo = {
    fecha,
    ...(ids.length ? { cuotas: ids } : {}),
    pagos: resueltos.map((p) => ({
      medio_pago: Number(p.medio),
      cuenta: Number(p.cuenta),
      monto: paraServidor(p.monto),
      ...(p.pideReferencia || p.referencia.trim() ? { referencia: p.referencia.trim() } : {}),
      ...(p.otraMoneda ? { tipo_cambio: paraServidor(p.tipoCambio) } : {}),
      ...(p.aporte ? { aporte_socio: true } : {}),
    })),
  }
  const clave = useClaveIdempotente(cuerpo)

  const pagar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`/compras/${compra.id}/pagar/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras'], ['caja']],
    exito: 'Pago registrado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const validar = () => {
    const campos = {}
    const porPago = {}
    resueltos.forEach((p) => {
      const e = {}
      const monto = aNumero(p.monto)
      if (!p.medio) e.medio = 'Elija el método.'
      if (!p.cuenta) e.cuenta = 'Elija la caja o cuenta.'
      if (monto === null || monto <= 0) e.monto = 'Mayor que cero.'
      else if (!/^\d+([.,]\d{1,2})?$/.test(String(p.monto).trim())) e.monto = 'Hasta 2 decimales.'
      if (p.pideReferencia && !p.referencia.trim()) e.referencia = 'Indique el N° de operación.'
      if (p.otraMoneda && !(aNumero(p.tipoCambio) > 0)) e.tipoCambio = 'Indique el tipo de cambio.'
      if (Object.keys(e).length) porPago[p.id] = e
    })
    if (!Object.keys(porPago).length && centimos(suma) > centimos(tope)) campos.general = `Los pagos suman más de lo que se debe (${dinero(tope, moneda)}).`
    if (!fecha) campos.fecha = 'Indique la fecha.'
    else if (fecha > hoyIso()) campos.fecha = 'No puede ser futura.'
    else if (fecha < compra.fecha_emision) campos.fecha = 'No puede ser anterior a la compra.'
    return { campos, pagos: porPago, valido: !Object.keys(campos).length && !Object.keys(porPago).length }
  }

  const enviar = (evento) => {
    evento.preventDefault()
    if (pagar.isPending) return
    const revision = validar()
    setErrores(revision)
    setGeneral(revision.campos.general ?? '')
    if (!revision.valido) return
    pagar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores({ campos: {}, pagos: {} })
          setGeneral(Object.keys(delServidor).length ? Object.values(delServidor).join(' ') : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <form onSubmit={enviar} noValidate>
      <fieldset disabled={pagar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
        <div className="fila-campos">
          <Campo etiqueta="Pagar" tipo="select">
            {(p) => (
              <select
                {...p}
                value={cuota}
                onChange={(ev) => {
                  setCuota(ev.target.value)
                  setPagos([nuevoPago()]) // el primer pago vuelve a tomar todo lo que corresponde
                }}
              >
                <option value="">Las cuotas en orden (la más antigua primero)</option>
                {cuotasIniciales.length > 0 && (
                  <option value="elegidas">
                    Las cuotas que marqué ({pendientes.filter((c) => cuotasIniciales.includes(c.id)).map((c) => c.numero).join(', ')})
                  </option>
                )}
                {pendientes.map((c) => (
                  <option key={c.id} value={c.id}>
                    Solo la cuota {c.numero} ({dinero(c.saldo, moneda)})
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Fecha del pago" icono="calendario" error={errores.campos.fecha}>
            {(p) => <input {...p} type="date" min={compra.fecha_emision} max={hoyIso()} value={fecha} onChange={(ev) => setFecha(ev.target.value)} />}
          </Campo>
        </div>
        <PagosContado
          resueltos={resueltos}
          cuentas={cuentas}
          medios={medios}
          moneda={moneda}
          total={tope}
          errores={errores.pagos}
          sinPermisoCajas={!puedeVerCajas}
          onPagos={setPagos}
          disabled={pagar.isPending}
          amortizar
        />
      </fieldset>
      {aplicacion.length > 0 && (
        <p className="celda-suave" aria-live="polite">
          Se aplicará a: {aplicacion.map((a) => `cuota ${a.numero} (${dinero(a.monto, moneda)})`).join(', ')}.
        </p>
      )}
      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={pagar.isPending}>
          Cancelar
        </button>
        <button type="submit" className="primario" disabled={pagar.isPending || !puedeVerCajas}>
          {pagar.isPending ? 'Pagando…' : 'Registrar pago'}
        </button>
      </div>
    </form>
  )
}
