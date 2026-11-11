import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { hoyIso, paraServidor } from '../../almacen/inventario'
import { superaUmbral, TIPOS, validarMovimiento } from '../caja'

const CAMPO_DEL_SERVIDOR = { cuenta: 'cuenta', concepto: 'concepto', monto: 'monto', fecha: 'fecha' }

/**
 * Registrar a mano un ingreso o un egreso de una caja o cuenta (un aporte, un gasto, una comisión…).
 * Los pagos de compras y los cobros de ventas no se registran aquí: se generan solos.
 */
export default function MovimientoModal({ tipoInicial, cuentas, cuentaInicial, umbral, onCerrar }) {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [f, setF] = useState({ tipo: tipoInicial, cuenta: cuentaInicial ? String(cuentaInicial) : '', concepto: '', monto: '', fecha: hoyIso(), referencia: '', glosa: '', medio: '' })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const conceptos = useOpciones('/mantenimiento/conceptos-caja/', { manual: '1', tipo: f.tipo }).data ?? []
  const metodos = useOpciones('/mantenimiento/medios-pago/', { estado: 'ACTIVO' }).data ?? []
  const cuentasActivas = cuentas.filter((c) => c.estado === 'ACTIVO')
  const cuenta = cuentasActivas.some((c) => String(c.cuenta) === f.cuenta) ? f.cuenta : cuentasActivas.length === 1 ? String(cuentasActivas[0].cuenta) : ''
  const elegida = cuentasActivas.find((c) => String(c.cuenta) === cuenta)
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))

  const cuerpo = {
    empresa: empresaActivaId,
    cuenta: Number(cuenta) || null,
    tipo: f.tipo,
    concepto: Number(f.concepto) || null,
    monto: paraServidor(f.monto),
    fecha: f.fecha,
    ...(f.medio ? { medio_pago: Number(f.medio) } : {}),
    ...(f.referencia.trim() ? { referencia: f.referencia.trim() } : {}),
    ...(f.glosa.trim() ? { glosa: f.glosa.trim() } : {}),
  }
  const clave = useClaveIdempotente(cuerpo)

  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/caja/movimientos/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: (m) => `${TIPOS[m.tipo]} N° ${String(m.numero).padStart(6, '0')} registrado.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (registrar.isPending) return
    const locales = validarMovimiento({ ...f, cuenta }, hoyIso())
    setErrores(locales)
    setGeneral('')
    if (Object.keys(locales).length) return
    registrar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const delServidor = Object.fromEntries(Object.entries(erroresDeCampo(error)).flatMap(([k, v]) => (CAMPO_DEL_SERVIDOR[k] ? [[CAMPO_DEL_SERVIDOR[k], v]] : [])))
          setErrores(delServidor)
          setGeneral(Object.keys(delServidor).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo={f.tipo === 'INGRESO' ? 'Registrar ingreso' : 'Registrar egreso'} subtitulo={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. El saldo de la caja o cuenta se actualiza al instante.`} onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={registrar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="segmentos" role="radiogroup" aria-label="Tipo de movimiento">
            {Object.entries(TIPOS).map(([valor, texto]) => (
              <button key={valor} type="button" role="radio" aria-checked={f.tipo === valor} className={f.tipo === valor ? 'activo' : undefined} onClick={() => setF((previo) => ({ ...previo, tipo: valor, concepto: '' }))}>
                {texto}
              </button>
            ))}
          </div>
          <div className="fila-campos">
            <Campo etiqueta="Caja o cuenta" tipo="select" requerido error={errores.cuenta}>
              {(p) => (
                <select {...p} value={cuenta} onChange={(ev) => poner('cuenta', ev.target.value)}>
                  <option value="">Elija la caja o cuenta</option>
                  {cuentasActivas.map((c) => (
                    <option key={c.cuenta} value={c.cuenta}>
                      {c.nombre} ({c.moneda === 'USD' ? 'US$' : 'S/'})
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Método de pago" tipo="select" ayuda="Con qué se pagó o cobró. Si no eliges, se toma según la cuenta: una caja es efectivo; un banco, banco.">
              {(p) => (
                <select {...p} value={f.medio} onChange={(ev) => poner('medio', ev.target.value)}>
                  <option value="">Según la cuenta</option>
                  {metodos.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Concepto" tipo="select" requerido error={errores.concepto}>
              {(p) => (
                <select {...p} value={f.concepto} onChange={(ev) => poner('concepto', ev.target.value)}>
                  <option value="">Elija el concepto</option>
                  {conceptos.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
          </div>
          {elegida?.tipo === 'CAJA' && superaUmbral(f.monto, elegida.moneda, umbral) && (
            <p className="compra-aviso" role="status">
              Este importe llega al límite de bancarización ({elegida.moneda === 'USD' ? 'US$' : 'S/'} {Number(umbral[elegida.moneda]).toLocaleString('es-PE')}). Pagarlo o cobrarlo en efectivo puede hacer perder el gasto o el crédito fiscal: si puedes, usa una transferencia o un depósito.
            </p>
          )}
          <div className="fila-campos">
            <Campo etiqueta={`Monto (${elegida?.moneda === 'USD' ? 'US$' : 'S/'})`} requerido error={errores.monto}>
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.monto} onChange={(ev) => poner('monto', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Fecha" icono="calendario" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" max={hoyIso()} min={elegida?.fecha_saldo_inicial ?? undefined} value={f.fecha} onChange={(ev) => poner('fecha', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="N° de operación">
              {(p) => <input {...p} maxLength={60} placeholder="Opcional" value={f.referencia} onChange={(ev) => poner('referencia', ev.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Detalle (glosa)" contador={{ actual: f.glosa.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} placeholder="Ej. Aporte inicial de caja" value={f.glosa} onChange={(ev) => poner('glosa', ev.target.value)} />}
          </Campo>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={registrar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={registrar.isPending}>
            {registrar.isPending ? 'Registrando…' : f.tipo === 'INGRESO' ? 'Registrar ingreso' : 'Registrar egreso'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
