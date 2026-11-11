import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { useImpresionRecibo } from '../hooks/useImpresionRecibo'
import { aDinero, cuerpoAbonos, estadoDeCuota, totalCobrado, validarAbonos } from '../ventas'
import CobroVenta from './CobroVenta'

const VACIO = []
const SIN_EMPRESAS = []
const CONFIG_LIBRE = { cobros: {}, empresas: [] }

/** Cobra una parte (o todo) de un comprobante vendido a crédito, con uno o varios métodos. */
export default function AbonarModal({ comprobante, onCerrar }) {
  const moneda = comprobante.moneda
  const hoy = hoyIso()
  const medios = useOpciones('/mantenimiento/medios-pago/').data ?? VACIO
  const pendientes = comprobante.cuotas.filter((c) => Number(c.saldo) > 0)
  const saldoCts = Math.round(Number(comprobante.saldo) * 100)
  const [crudos, setCobros] = useState([])
  const [elegidas, setElegidas] = useState([])
  // Lo que se propone cobrar: las cuotas marcadas; si no hay ninguna, la más antigua.
  const objetivoCts = elegidas.length
    ? pendientes.filter((c) => elegidas.includes(c.id)).reduce((suma, c) => suma + Math.round(Number(c.saldo) * 100), 0)
    : Math.round(Number(pendientes[0]?.saldo ?? 0) * 100)
  const medioBaseId = (medios.find((m) => m.tipo === 'EFECTIVO') ?? medios[0])?.id
  // El primer cobro acompaña a ese monto mientras la persona no escriba otro; se guarda al tocarlo.
  let cobros = crudos
  if (crudos.length === 0) cobros = medioBaseId !== undefined && objetivoCts > 0 ? [{ id: 'inicial', medio: medioBaseId, monto: aDinero(objetivoCts), referencia: '', recibido: '', auto: true }] : []
  else if (crudos.length === 1 && crudos[0].auto) cobros = [{ ...crudos[0], monto: aDinero(objetivoCts) }]
  const [intento, setIntento] = useState(false)
  const [serieElegida, setSerieElegida] = useState('')
  const [hecho, setHecho] = useState(null) // el cobro ya registrado: { recibo }
  const { imprimir, portal } = useImpresionRecibo()
  const seriesRecibo = comprobante.series_recibo ?? VACIO
  const serieRecibo = seriesRecibo.some((x) => String(x.id) === serieElegida) ? serieElegida : String(seriesRecibo[0]?.id ?? '')
  const [error, setError] = useState('')

  const errores = validarAbonos({ cobros, medios: medios.map((m) => ({ id: m.id, nombre: m.nombre, tipo: m.tipo, requiere_referencia: m.requiere_referencia })), saldoCts })
  const cuerpo = errores.length === 0 ? cuerpoAbonos(cobros, elegidas, seriesRecibo.length > 1 ? serieRecibo : null) : null
  const clave = useClaveIdempotente(cuerpo)
  const cobrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`/ventas/comprobantes/${comprobante.id}/abonar/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas'], ['caja']],
    exito: 'Abono registrado.',
    alExito: (datos) => setHecho({ recibo: datos.recibo, numero: datos.abonos?.find((a) => a.recibo === datos.recibo)?.recibo_numero ?? '' }),
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (cobrar.isPending) return
    setIntento(true)
    setError('')
    if (!cuerpo) return
    cobrar.mutate({ datos: cuerpo, llave: clave }, { onError: (e) => setError(Object.keys(erroresDeCampo(e)).length ? 'Revise los datos del abono.' : mensajeDeError(e)) })
  }
  const alternar = (id) => setElegidas((previo) => (previo.includes(id) ? previo.filter((x) => x !== id) : [...previo, id]))

  if (hecho) {
    return (
      <Modal titulo="Cobro registrado" subtitulo={`${comprobante.numero_completo}${hecho.numero ? ` · Recibo ${hecho.numero}` : ''}`} onCerrar={onCerrar} ancho={520}>
        <p>El cobro quedó registrado y la caja ya lo muestra. Entrega el recibo al cliente.</p>
        <div className="acciones">
          <button type="button" onClick={onCerrar}>
            Cerrar
          </button>
          <button type="button" className="primario" autoFocus onClick={() => imprimir(hecho.recibo)}>
            <Icono nombre="documento" tam={18} /> Imprimir recibo
          </button>
        </div>
        {portal}
      </Modal>
    )
  }

  return (
    <Modal titulo="Cobrar a crédito" subtitulo={`${comprobante.numero_completo} · debe ${dinero(comprobante.saldo, moneda)}`} onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <fieldset className="pos-cuotas-elegir" disabled={cobrar.isPending}>
          <legend>¿A qué cuotas? <small className="celda-suave">Sin elegir, se cobran las más antiguas primero.</small></legend>
          {pendientes.map((c) => {
            const estado = estadoDeCuota(c, hoy)
            return (
              <label key={c.id}>
                <input type="checkbox" checked={elegidas.includes(c.id)} onChange={() => alternar(c.id)} />
                <span>
                  Cuota {c.numero} · vence {fechaCorta(c.fecha_vencimiento)} · debe {dinero(c.saldo, moneda)}
                </span>
                <span className="pildora" data-tono={estado.tono}>
                  {estado.texto}
                </span>
              </label>
            )
          })}
        </fieldset>

        {seriesRecibo.length > 1 && (
          <Campo etiqueta="Serie del recibo" tipo="select" requerido ayuda="Esta empresa tiene varias series de recibos: elige con cuál se entrega.">
            {(p) => (
              <select {...p} value={serieRecibo} disabled={cobrar.isPending} onChange={(e) => setSerieElegida(e.target.value)}>
                {seriesRecibo.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.proximo}
                    {x.nombre ? ` · ${x.nombre}` : ''}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        )}
        <CobroVenta config={CONFIG_LIBRE} medios={medios} cobros={cobros} totalCts={objetivoCts} moneda={moneda} empresasDelCarrito={SIN_EMPRESAS} disabled={cobrar.isPending} onCobros={setCobros} />
        <p className="celda-suave">Cobrado ahora: {dinero(aDinero(totalCobrado(cobros)), moneda)} de {dinero(comprobante.saldo, moneda)}.</p>

        {intento && errores.length > 0 && (
          <ul className="pos-avisos" role="alert">
            {[...new Set(errores)].map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="acciones">
          <button type="button" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={cobrar.isPending}>
            {cobrar.isPending ? 'Registrando…' : 'Registrar abono'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
