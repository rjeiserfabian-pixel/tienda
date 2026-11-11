import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import PagosContado from '../../compras/components/PagosContado'
import { resolverPagos, totalPagado } from '../../compras/compras'
import { useCatalogosCompra } from '../../compras/hooks/useCatalogosCompra'
import { dinero, erroresDePagos, nuevoPago } from '../gastos'

/**
 * Pagar lo que falta de un gasto por pagar: todo o una parte, con uno o varios métodos. Lo que no se
 * paga ahora sigue pendiente. El dinero sale de la caja o cuenta elegida y queda en el libro.
 */
export default function PagarGastoModal({ gasto, onCerrar }) {
  const catalogos = useCatalogosCompra(gasto.empresa)
  const saldo = Number(gasto.saldo)
  const [pagos, setPagos] = useState([nuevoPago()])
  const [intento, setIntento] = useState(false)
  const [error, setError] = useState('')

  const medios = catalogos.medios.data ?? []
  const cuentas = catalogos.cuentas.data ?? []
  const resueltos = resolverPagos(pagos, saldo.toFixed(2), { medios, cuentas, moneda: gasto.moneda, tipoCambio: gasto.moneda === 'USD' ? gasto.tipo_cambio : '' })
  const errores = erroresDePagos(resueltos)
  const pagado = totalPagado(resueltos)
  const valido = pagado > 0 && pagado <= saldo + 0.001 && Object.keys(errores).length === 0

  const cuerpo = {
    pagos: resueltos.map((p) => ({
      medio_pago: Number(p.medio),
      cuenta: Number(p.cuenta),
      monto: paraServidor(p.monto),
      ...(p.pideReferencia || (p.referencia ?? '').trim() ? { referencia: p.referencia.trim() } : {}),
      ...(p.otraMoneda && aNumero(p.tipoCambio) > 0 ? { tipo_cambio: paraServidor(p.tipoCambio) } : {}),
      ...(p.aporte ? { aporte_socio: true } : {}),
    })),
  }
  const clave = useClaveIdempotente(cuerpo)

  const pagar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`/gastos/${gasto.id}/pagar/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['gastos'], ['caja']],
    exito: 'Pago registrado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (pagar.isPending) return
    setIntento(true)
    setError('')
    if (!valido) {
      setError(pagado > saldo + 0.001 ? `Los pagos pasan de lo que falta (${dinero(saldo, gasto.moneda)}).` : 'Complete los datos del pago.')
      return
    }
    pagar.mutate({ datos: cuerpo, llave: clave }, { onError: (e) => setError(mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Pagar el gasto" subtitulo={`N° ${String(gasto.numero).padStart(6, '0')} · ${gasto.descripcion} · falta ${dinero(saldo, gasto.moneda)}`} onCerrar={onCerrar} ancho={860}>
      <form onSubmit={enviar} noValidate>
        <p className="celda-suave">Puedes pagar todo o una parte. Lo que no pagues ahora sigue por pagar.</p>
        <PagosContado resueltos={resueltos} cuentas={cuentas} medios={medios} moneda={gasto.moneda} total={saldo.toFixed(2)} errores={intento ? errores : {}} sinPermisoCajas={!catalogos.puedeVerCajas} onPagos={setPagos} disabled={pagar.isPending} amortizar />
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={pagar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={pagar.isPending}>
            {pagar.isPending ? 'Pagando…' : `Pagar ${dinero(pagado, gasto.moneda)}`}
          </button>
        </div>
      </form>
    </Modal>
  )
}
