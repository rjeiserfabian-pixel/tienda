import { useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { paraServidor } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import CobroVenta from '../../ventas/components/CobroVenta'
import { useConfiguracionVenta } from '../../ventas/hooks/useConfiguracionVenta'
import { useImpresionTicket } from '../../ventas/hooks/useImpresionTicket'
import { cobroNuevo, faltaCobrar, medioPorDefecto } from '../../ventas/ventas'

const VACIO = []
const centimos = (valor) => Math.round(Number(valor) * 100)

/** Lo que se ve al entregar: los comprobantes emitidos (uno por empresa), listos para imprimir. */
function EntregaHecha({ orden, venta, onCerrar }) {
  const { imprimir, portal } = useImpresionTicket(venta)
  const vuelto = venta.comprobantes.flatMap((c) => c.cobros).reduce((suma, k) => suma + Number(k.vuelto), 0)
  return (
    <Modal titulo="Equipo entregado" subtitulo={`Orden ${orden.codigo} · ${orden.cliente_nombre}`} onCerrar={onCerrar} ancho={560}>
      <ul className="pos-emitidos">
        {venta.comprobantes.map((c) => (
          <li key={c.id}>
            <div>
              <strong>
                {c.tipo_nombre} {c.numero_completo}
              </strong>
              <span className="sub-texto">
                {c.empresa_nombre} · {dinero(c.total, venta.moneda)}
              </span>
            </div>
            <button type="button" className="boton-cabecera" onClick={() => imprimir(c)}>
              <Icono nombre="documento" tam={18} /> Imprimir
            </button>
          </li>
        ))}
      </ul>
      <p className="pos-total-hecho">
        Total cobrado <strong>{dinero(venta.total, venta.moneda)}</strong>
      </p>
      {vuelto > 0 && (
        <p className="pos-vuelto" role="status">
          Entrega de vuelto: <strong>{dinero(vuelto, venta.moneda)}</strong>
        </p>
      )}
      <div className="modal-pie">
        <button type="button" className="primario" autoFocus onClick={onCerrar}>
          Listo
        </button>
      </div>
      {portal}
    </Modal>
  )
}

/** Cobra lo presupuestado (un comprobante por empresa que participó) y entrega el equipo. */
export default function EntregarEquipoModal({ orden, onCerrar }) {
  const info = orden.entrega
  const cobra = info.cobra
  const adelantos = info.adelantos
  const porCobrar = cobra ? (adelantos.por_cobrar ?? info.total) : '0'
  const totalCts = centimos(porCobrar)
  const cubierto = cobra && totalCts === 0 // el adelanto ya cubre todo
  const exceso = Number(adelantos.exceso)
  const empresasDelCobro = info.por_empresa.map((e) => e.empresa)
  const consulta = useConfiguracionVenta(orden.empresa, orden.sucursal)
  const config = consulta.data
  const medios = config?.medios_pago ?? VACIO
  const tipos = useMemo(() => (config?.tipos_comprobante ?? VACIO).filter((t) => empresasDelCobro.every((id) => config.empresas.find((e) => e.id === id)?.tipos.includes(t.codigo))), [config, empresasDelCobro])

  const [tipoElegido, setTipoElegido] = useState('')
  const [cobros, setCobros] = useState(null)
  const [sinCobro, setSinCobro] = useState(false)
  // Sin cobrar el servicio, lo que dejó el cliente tiene que devolverse antes de entregar.
  const pendienteDeDevolver = Number(adelantos.total) > 0 && (!cobra || sinCobro) ? Number(adelantos.total) : 0
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const [hecha, setHecha] = useState(null)
  const [recoge, setRecoge] = useState({ titular: true, nombre: '', documento: '' })

  const tipo = tipoElegido || (['03', 'NV'].find((c) => tipos.some((t) => t.codigo === c)) ?? tipos[0]?.codigo ?? '')
  const inicial = useMemo(() => {
    const medio = config && cobra ? medioPorDefecto(medios, config, 'PEN', empresasDelCobro) : null
    return medio && totalCts > 0 ? [cobroNuevo(medio.id, totalCts, true)] : []
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, cobra, totalCts])
  const lista = cobros ?? inicial

  const entregar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/entregar/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio'], ['ventas'], ['caja'], ['almacen']],
    exito: 'Equipo entregado.',
    alExito: (datos) => (datos.venta ? setHecha(datos.venta) : onCerrar()),
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (entregar.isPending) return
    if (pendienteDeDevolver > 0) return setError(`El cliente tiene ${dinero(pendienteDeDevolver)} de adelanto por devolver: devuélvelo antes de entregar.`)
    if (cobra && !sinCobro && exceso > 0) return setError(`Los adelantos pasan del comprobante de esta empresa en ${dinero(exceso)}: devuelve esa diferencia al cliente primero.`)
    if (!recoge.titular && recoge.nombre.trim().length < 3) return setError('Indica el nombre de quien recoge el equipo.')
    if (!recoge.titular && recoge.documento.trim().length < 6) return setError('Indica el documento de quien recoge (no es el titular).')
    let cuerpo = {}
    if (cobra && sinCobro) {
      if (motivo.trim().length < 5) return setError('Explica por qué se entrega sin cobrar (garantía, cortesía…).')
      cuerpo = { sin_cobro: true, motivo: motivo.trim() }
    } else if (cobra) {
      if (!tipo) return setError('No hay un tipo de comprobante con serie en todas las empresas de este cobro.')
      if (tipo === '01' && !orden.cliente_documento.startsWith('RUC')) return setError('Para una factura el cliente debe tener RUC.')
      if (!cubierto && (lista.length === 0 || faltaCobrar(totalCts, lista) !== 0)) return setError(faltaCobrar(totalCts, lista) > 0 ? 'Falta cobrar una parte del total.' : 'Los cobros pasan del total.')
      for (const c of lista) {
        const medio = medios.find((m) => m.id === c.medio)
        if (medio?.requiere_referencia && !c.referencia.trim()) return setError(`Indica el número de operación del cobro con ${medio.nombre}.`)
      }
      cuerpo = {
        tipo_comprobante: tipo,
        cobros: (cubierto ? [] : lista).map((c) => ({
          medio_pago: c.medio,
          monto: paraServidor(c.monto),
          ...(c.referencia.trim() ? { referencia: c.referencia.trim() } : {}),
          ...(c.recibido !== '' ? { recibido: paraServidor(c.recibido) } : {}),
        })),
      }
    }
    setError('')
    cuerpo = { ...cuerpo, recoge_es_titular: recoge.titular, ...(recoge.titular ? {} : { recoge_nombre: recoge.nombre.trim(), recoge_documento: recoge.documento.trim() }) }
    entregar.mutate(cuerpo, { onError: (e) => setError(erroresDeCampo(e).cobros || erroresDeCampo(e).tipo_comprobante || mensajeDeError(e)) })
  }

  if (hecha) return <EntregaHecha orden={orden} venta={hecha} onCerrar={onCerrar} />
  const cargando = cobra && !sinCobro && consulta.isLoading
  return (
    <Modal titulo="Entregar el equipo" subtitulo={`Orden ${orden.codigo} · ${orden.cliente_nombre}`} onCerrar={onCerrar} ancho={640}>
      <form onSubmit={enviar} noValidate>
        {!cobra && <p>No hay nada que cobrar en esta entrega. Al confirmar, la orden queda «Entregado / Cerrado».</p>}
        {cobra && (
          <>
            <p>
              Se cobra el presupuesto aprobado: <strong>{dinero(info.total, info.moneda)}</strong>.
              {Number(adelantos.aplicables) > 0 && (
                <>
                  {' '}
                  Se descuenta el adelanto de <strong>{dinero(adelantos.aplicables)}</strong>: el cliente paga <strong>{dinero(porCobrar)}</strong>.
                </>
              )}
              {info.por_empresa.length > 1 ? ' Saldrá un comprobante por cada empresa:' : ''}
            </p>
            {info.por_empresa.length > 1 && (
              <ul className="celda-suave">
                {info.por_empresa.map((e) => (
                  <li key={e.empresa}>
                    {e.nombre}: {dinero(e.total, info.moneda)}
                  </li>
                ))}
              </ul>
            )}
            {!sinCobro && (info.deuda_interna ?? []).length > 0 && (
              <p className="celda-suave" role="note">
                El comprobante y el dinero son de {info.por_empresa[0]?.nombre}.{' '}
                {info.deuda_interna.map((d) => `Por los repuestos que surtió ${d.nombre} se le deberán ${dinero(d.monto, info.moneda)} (se liquida al cerrar la caja).`).join(' ')}
              </p>
            )}
            {!sinCobro && (
              <>
                {consulta.isError && (
                  <p role="alert" className="campo-error">
                    {mensajeDeError(consulta.error)} Para cobrar hace falta poder vender en la empresa.
                  </p>
                )}
                <Campo etiqueta="Comprobante" tipo="select">
                  {(p) => (
                    <select {...p} value={tipo} disabled={entregar.isPending || cargando} onChange={(e) => setTipoElegido(e.target.value)}>
                      {tipos.length === 0 && <option value="">Sin tipos con serie en todas las empresas</option>}
                      {tipos.map((t) => (
                        <option key={t.codigo} value={t.codigo}>
                          {t.nombre}
                        </option>
                      ))}
                    </select>
                  )}
                </Campo>
                {cubierto && <p role="status">El adelanto cubre todo el servicio: no hay nada más que cobrar. El comprobante sale por el total.</p>}
                {config && !cubierto && <CobroVenta config={config} medios={medios} cobros={lista} totalCts={totalCts} moneda="PEN" empresasDelCarrito={empresasDelCobro} disabled={entregar.isPending} onCobros={setCobros} />}
              </>
            )}
            {info.sin_cobro_permitido && (
              <label>
                <input type="checkbox" checked={sinCobro} disabled={entregar.isPending} onChange={(e) => setSinCobro(e.target.checked)} /> Entregar sin cobrar (garantía, cortesía)
              </label>
            )}
            {sinCobro && (
              <Campo etiqueta="Por qué se entrega sin cobrar" requerido contador={{ actual: motivo.length, max: 500 }}>
                {(p) => <textarea {...p} rows={2} maxLength={500} value={motivo} disabled={entregar.isPending} onChange={(e) => setMotivo(e.target.value)} />}
              </Campo>
            )}
          </>
        )}
        <div className="servicio-recoge" role="radiogroup" aria-label="Quién recoge el equipo">
          <span className="compra-etiqueta">Quién recoge el equipo</span>
          <div className="segmentos">
            <button type="button" role="radio" aria-checked={recoge.titular} className={recoge.titular ? 'activo' : undefined} disabled={entregar.isPending} onClick={() => setRecoge({ ...recoge, titular: true })}>
              El titular ({orden.cliente_nombre})
            </button>
            <button type="button" role="radio" aria-checked={!recoge.titular} className={!recoge.titular ? 'activo' : undefined} disabled={entregar.isPending} onClick={() => setRecoge({ ...recoge, titular: false })}>
              Otra persona
            </button>
          </div>
          {!recoge.titular && (
            <div className="fila-campos">
              <Campo etiqueta="Nombre de quien recoge" requerido>
                {(p) => <input {...p} maxLength={120} value={recoge.nombre} disabled={entregar.isPending} onChange={(e) => setRecoge({ ...recoge, nombre: e.target.value })} />}
              </Campo>
              <Campo etiqueta="Documento (DNI)" requerido>
                {(p) => <input {...p} maxLength={20} value={recoge.documento} disabled={entregar.isPending} onChange={(e) => setRecoge({ ...recoge, documento: e.target.value })} />}
              </Campo>
            </div>
          )}
        </div>
        {pendienteDeDevolver > 0 && (
          <p role="alert" className="campo-error">
            El cliente tiene {dinero(pendienteDeDevolver)} de adelanto por devolver. Devuélvelo en la ficha de la orden antes de entregar.
          </p>
        )}
        {exceso > 0 && cobra && !sinCobro && (
          <p role="alert" className="campo-error">
            Los adelantos pasan del comprobante de esta empresa en {dinero(exceso)}: devuelve esa diferencia al cliente en la ficha de la orden.
          </p>
        )}
        {info.garantia_dias > 0 && <p className="celda-suave">El servicio tiene {info.garantia_dias} días de garantía desde hoy.</p>}
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={entregar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={entregar.isPending || cargando || pendienteDeDevolver > 0 || (cobra && !sinCobro && exceso > 0)}>
            {entregar.isPending ? 'Entregando…' : cobra && !sinCobro ? 'Cobrar y entregar' : 'Entregar equipo'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
