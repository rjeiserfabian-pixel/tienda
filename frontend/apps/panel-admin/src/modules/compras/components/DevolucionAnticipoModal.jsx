import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { hoyIso, paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { validarDinero } from '../anticipos'
import { dinero } from '../compras'

/**
 * El proveedor devuelve (todo o parte de) el dinero de un anticipo: entra a una caja o cuenta y baja
 * el saldo a favor. No puede pasar de lo que aún está disponible (sin usar en compras).
 */
export default function DevolucionAnticipoModal({ anticipo, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeVerCajas = tiene('CAJA.CUENTAS.VER')
  const disponible = aNumero(anticipo.disponible) ?? 0
  const [monto, setMonto] = useState(disponible.toFixed(2))
  const [cuenta, setCuenta] = useState('')
  const [fecha, setFecha] = useState(hoyIso())
  const [referencia, setReferencia] = useState('')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const cuentas = (useOpciones('/mantenimiento/cuentas/', { empresa: empresaActivaId }, { enabled: puedeVerCajas && Boolean(empresaActivaId) }).data ?? []).filter((c) => c.moneda === anticipo.moneda)

  const cuerpo = {
    monto: paraServidor(monto),
    cuenta: cuenta ? Number(cuenta) : null,
    fecha,
    ...(referencia.trim() ? { referencia: referencia.trim() } : {}),
  }
  const clave = useClaveIdempotente(cuerpo)

  const devolver = useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`/compras/anticipos/${anticipo.id}/devolver/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras'], ['caja'], ['movimientos']],
    exito: 'Devolución registrada. El saldo a favor bajó.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (devolver.isPending) return
    const e = validarDinero({ monto, cuenta, fecha, minimo: anticipo.fecha, tope: disponible })
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    devolver.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setGeneral(Object.keys(delServidor).length ? Object.values(delServidor).join(' ') : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo="Devolución del proveedor" subtitulo={`${anticipo.codigo} · ${anticipo.proveedor_nombre}`} onCerrar={onCerrar} ancho={600}>
      <form onSubmit={enviar} noValidate>
        <p>
          Registra el dinero que el proveedor te devolvió de este anticipo. Entra a la caja o cuenta que elijas y el saldo a favor baja por el mismo monto. Disponible sin usar: <strong>{dinero(disponible, anticipo.moneda)}</strong>.
        </p>
        <fieldset disabled={devolver.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="fila-campos">
            <Campo etiqueta="Monto devuelto" requerido error={errores.monto}>
              {(p) => <input {...p} inputMode="decimal" autoComplete="off" value={monto} onChange={(ev) => setMonto(ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Fecha" icono="calendario" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" min={anticipo.fecha} max={hoyIso()} value={fecha} onChange={(ev) => setFecha(ev.target.value)} />}
            </Campo>
          </div>
          {!puedeVerCajas ? (
            <p role="alert" className="compra-aviso">
              No tienes acceso a las cajas y cuentas de esta empresa. Pide el permiso «Ver cajas y cuentas».
            </p>
          ) : (
            <div className="fila-campos">
              <Campo etiqueta="Entra a" tipo="select" requerido error={errores.cuenta} ayuda={cuentas.length === 0 ? 'No hay cajas o cuentas en esa moneda.' : undefined}>
                {(p) => (
                  <select {...p} value={cuenta} onChange={(ev) => setCuenta(ev.target.value)}>
                    <option value="">Elija la caja o cuenta</option>
                    {cuentas.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="N° de operación (opcional)">
                {(p) => <input {...p} maxLength={60} value={referencia} onChange={(ev) => setReferencia(ev.target.value)} />}
              </Campo>
            </div>
          )}
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={devolver.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={devolver.isPending || !puedeVerCajas}>
            {devolver.isPending ? 'Registrando…' : 'Registrar devolución'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
