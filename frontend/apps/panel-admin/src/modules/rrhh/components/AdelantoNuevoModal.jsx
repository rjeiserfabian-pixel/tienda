import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useEntregarAdelanto, useOpcionesAdelanto } from '../hooks/useAdelantos'
import { decimal, decimalValido, entero, soles } from '../rrhh'
import '../rrhh.css'

const hoy = () => new Date().toLocaleDateString('en-CA') // AAAA-MM-DD en la hora local

const TIPOS = [
  ['ADELANTO', 'Adelanto de sueldo'],
  ['PRESTAMO', 'Préstamo'],
]

/** Reparte el monto en cuotas iguales; la última lleva los centavos (igual que el servidor). */
function cuotasDe(monto, n) {
  const centimos = Math.round(Number(monto) * 100)
  const base = Math.floor(centimos / n)
  return Array.from({ length: n }, (_, i) => (i === n - 1 ? centimos - base * (n - 1) : base) / 100)
}

/** Entrega un adelanto de sueldo o un préstamo: sale dinero de una caja y se programan los descuentos. */
export default function AdelantoNuevoModal({ onCerrar, onCreado }) {
  const { empresaActivaId } = useEmpresas()
  const opciones = useOpcionesAdelanto(empresaActivaId)
  const [f, setF] = useState({ personal: '', tipo: 'ADELANTO', fecha: hoy(), monto: '', cuotas: '3', cuenta: '', medio: '', referencia: '', motivo: '' })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const prestamo = f.tipo === 'PRESTAMO'
  const cuentas = opciones.data?.cuentas ?? []
  const cuenta = f.cuenta || (cuentas.length === 1 ? String(cuentas[0].id) : '')
  const nCuotas = prestamo ? Number(f.cuotas) || 0 : 1

  const cuerpo = {
    empresa: empresaActivaId,
    personal: Number(f.personal) || null,
    tipo: f.tipo,
    fecha: f.fecha,
    monto: f.monto,
    num_cuotas: nCuotas,
    cuenta: Number(cuenta) || null,
    ...(f.medio ? { medio_pago: Number(f.medio) } : {}),
    referencia: f.referencia.trim(),
    motivo: f.motivo.trim(),
  }
  const llave = useClaveIdempotente(cuerpo)
  const entregar = useEntregarAdelanto({ exito: 'Entrega registrada: el dinero salió de la caja.', alExito: (a) => (onCreado ? onCreado(a) : onCerrar()) })

  const enviar = (evento) => {
    evento.preventDefault()
    if (entregar.isPending) return
    const e = {}
    if (!f.personal) e.personal = 'Elija al trabajador.'
    if (!f.fecha) e.fecha = 'Indique la fecha de entrega.'
    else if (f.fecha > hoy()) e.fecha = 'No puede ser futura.'
    if (!decimalValido(f.monto, 9_999_999.99) || Number(f.monto) <= 0 || !/^\d+(\.\d{1,2})?$/.test(f.monto)) e.monto = 'Un monto en soles, mayor que cero, con hasta 2 decimales.'
    if (prestamo && !(nCuotas >= 1 && nCuotas <= 36)) e.cuotas = 'De 1 a 36 cuotas.'
    if (!cuenta) e.cuenta = 'Elija de qué caja o cuenta sale el dinero.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    entregar.mutate(
      { datos: cuerpo, llave },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores({ ...delServidor, cuotas: delServidor.num_cuotas })
          setGeneral(Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion' ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  const vistaCuotas = prestamo && decimalValido(f.monto) && Number(f.monto) > 0 && nCuotas >= 1 && nCuotas <= 36 ? cuotasDe(f.monto, nCuotas) : null

  return (
    <Modal titulo="Nuevo adelanto o préstamo" subtitulo="El dinero sale de una caja o cuenta y se descuenta en la planilla." onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={entregar.isPending} className="rh-opciones">
          <div className="segmentos" role="radiogroup" aria-label="Tipo">
            {TIPOS.map(([valor, texto]) => (
              <button key={valor} type="button" role="radio" aria-checked={f.tipo === valor} className={f.tipo === valor ? 'activo' : undefined} onClick={() => poner('tipo', valor)}>
                {texto}
              </button>
            ))}
          </div>
          <p className="celda-suave">{prestamo ? 'Se devuelve en cuotas mensuales iguales, desde el mes siguiente a la entrega.' : 'Se descuenta de una vez, en la planilla del mes de la entrega.'}</p>

          <Campo etiqueta="Trabajador" tipo="select" requerido error={errores.personal}>
            {(p) => (
              <select {...p} value={f.personal} onChange={(e) => poner('personal', e.target.value)}>
                <option value="">Elegir trabajador</option>
                {(opciones.data?.trabajadores ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nombre_completo}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <div className="rh-fila-campos">
            <Campo etiqueta="Fecha de entrega" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" max={hoy()} value={f.fecha} onChange={(e) => poner('fecha', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Monto (S/)" requerido error={errores.monto}>
              {(p) => <input {...p} inputMode="decimal" autoComplete="off" value={f.monto} onChange={(e) => poner('monto', decimal(e.target.value))} />}
            </Campo>
            {prestamo && (
              <Campo etiqueta="Número de cuotas" requerido error={errores.cuotas}>
                {(p) => <input {...p} inputMode="numeric" maxLength={2} value={f.cuotas} onChange={(e) => poner('cuotas', entero(e.target.value))} />}
              </Campo>
            )}
          </div>
          {vistaCuotas && (
            <p className="rh-aviso" role="status">
              {nCuotas} cuota(s): {vistaCuotas[0] === vistaCuotas.at(-1) ? `${soles(vistaCuotas[0])} cada una` : `${soles(vistaCuotas[0])} y la última de ${soles(vistaCuotas.at(-1))}`}.
            </p>
          )}
          <div className="rh-fila-campos">
            <Campo etiqueta="Sale de" tipo="select" requerido error={errores.cuenta} ayuda={opciones.isSuccess && cuentas.length === 0 ? 'No hay cajas o cuentas en soles activas.' : undefined}>
              {(p) => (
                <select {...p} value={cuenta} onChange={(e) => poner('cuenta', e.target.value)}>
                  <option value="">Elegir caja o cuenta</option>
                  {cuentas.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Método de pago" tipo="select" error={errores.medio_pago}>
              {(p) => (
                <select {...p} value={f.medio} onChange={(e) => poner('medio', e.target.value)}>
                  <option value="">Sin indicar</option>
                  {(opciones.data?.medios_pago ?? []).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
          </div>
          <div className="rh-fila-campos">
            <Campo etiqueta="N° de operación" error={errores.referencia} contador={{ actual: f.referencia.length, max: 60 }}>
              {(p) => <input {...p} maxLength={60} placeholder="Opcional" value={f.referencia} onChange={(e) => poner('referencia', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Motivo" error={errores.motivo} contador={{ actual: f.motivo.length, max: 150 }}>
              {(p) => <input {...p} maxLength={150} placeholder="Opcional" value={f.motivo} onChange={(e) => poner('motivo', e.target.value)} />}
            </Campo>
          </div>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={entregar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={entregar.isPending || opciones.isLoading}>
            {entregar.isPending ? 'Entregando…' : 'Entregar el dinero'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
