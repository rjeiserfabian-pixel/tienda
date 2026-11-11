import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { hoyIso, paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { CLASES, convertir, dinero, validarTransferencia } from '../caja'

const CAMPO_DEL_SERVIDOR = { cuenta_origen: 'origen', cuenta_destino: 'destino', monto: 'monto', fecha: 'fecha', tipo_cambio: 'tipoCambio', comision: 'comision', itf: 'itf' }

/** Qué cuentas se ofrecen según lo que se hace: depositar es de efectivo a banco, retirar es al revés. */
const sirveDeOrigen = (clase, c) => (clase === 'DEPOSITO' ? c.tipo === 'CAJA' : clase === 'RETIRO' ? c.tipo !== 'CAJA' : true)
const sirveDeDestino = (clase, c) => (clase === 'DEPOSITO' ? c.tipo !== 'CAJA' : clase === 'RETIRO' ? c.tipo === 'CAJA' : true)

/**
 * Pasar dinero de una caja o cuenta a otra: un depósito (efectivo al banco), un retiro (del banco a
 * la caja) o una transferencia cualquiera. Entre soles y dólares pide el tipo de cambio y calcula
 * lo que entra. A otra empresa solo con permiso. La comisión y el ITF, si los hay, salen del origen.
 */
export default function TransferenciaModal({ claseInicial = 'TRANSFERENCIA', cuentas, onCerrar }) {
  const { empresaActivaId, empresas } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeEntreEmpresas = tiene('CAJA.TRASLADAR_ENTRE_EMPRESAS') && empresas.length > 1
  const [f, setF] = useState({ clase: claseInicial, origen: '', destino: '', empresaDestino: '', monto: '', tipoCambio: '', fecha: hoyIso(), referencia: '', glosa: '', comision: '', itf: '' })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))

  const otraEmpresa = Boolean(f.empresaDestino) && Number(f.empresaDestino) !== empresaActivaId
  const cuentasOtraEmpresa = useQuery({
    queryKey: ['caja', 'saldos', Number(f.empresaDestino)],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: f.empresaDestino }, signal }).then((r) => r.data.cuentas),
    enabled: otraEmpresa,
  })
  const delOrigen = cuentas.filter((c) => c.estado === 'ACTIVO' && sirveDeOrigen(f.clase, c))
  const posiblesDestinos = (otraEmpresa ? (cuentasOtraEmpresa.data ?? []) : cuentas).filter((c) => c.estado === 'ACTIVO' && (otraEmpresa || String(c.cuenta) !== f.origen) && sirveDeDestino(f.clase, c))
  const origen = delOrigen.find((c) => String(c.cuenta) === f.origen)
  const destino = posiblesDestinos.find((c) => String(c.cuenta) === f.destino)
  const cambiaMoneda = Boolean(origen && destino && origen.moneda !== destino.moneda)
  const monto = aNumero(f.monto)
  const recibe = cambiaMoneda && monto > 0 && aNumero(f.tipoCambio) > 0 ? convertir(monto, origen.moneda, destino.moneda, aNumero(f.tipoCambio)) : null

  const cuerpo = {
    empresa: empresaActivaId,
    cuenta_origen: Number(f.origen) || null,
    cuenta_destino: Number(f.destino) || null,
    monto: paraServidor(f.monto),
    fecha: f.fecha,
    ...(cambiaMoneda ? { tipo_cambio: paraServidor(f.tipoCambio) } : {}),
    ...(aNumero(f.comision) > 0 ? { comision: paraServidor(f.comision) } : {}),
    ...(aNumero(f.itf) > 0 ? { itf: paraServidor(f.itf) } : {}),
    ...(f.referencia.trim() ? { referencia: f.referencia.trim() } : {}),
    ...(f.glosa.trim() ? { glosa: f.glosa.trim() } : {}),
  }
  const clave = useClaveIdempotente(cuerpo)

  const transferir = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/caja/transferencias/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: (t) => `${t.clase_nombre} N° ${String(t.numero).padStart(6, '0')} registrado.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (transferir.isPending) return
    const locales = validarTransferencia(f, { origen, destino, cambiaMoneda }, hoyIso())
    setErrores(locales)
    setGeneral('')
    if (Object.keys(locales).length) return
    transferir.mutate(
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

  const simbolo = origen?.moneda === 'USD' ? 'US$' : 'S/'
  return (
    <Modal titulo="Mover dinero" subtitulo="Depositar al banco, retirar a la caja o pasar dinero entre cuentas. Todo queda en el libro de movimientos." onCerrar={onCerrar} ancho={780}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={transferir.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="segmentos" role="radiogroup" aria-label="Qué vas a hacer">
            {Object.entries(CLASES).map(([valor, { titulo }]) => (
              <button key={valor} type="button" role="radio" aria-checked={f.clase === valor} className={f.clase === valor ? 'activo' : undefined} onClick={() => setF((previo) => ({ ...previo, clase: valor, origen: '', destino: '' }))}>
                {titulo}
              </button>
            ))}
          </div>
          <p className="celda-suave">{CLASES[f.clase].ayuda}</p>
          <div className="fila-campos">
            <Campo etiqueta="Sale de" tipo="select" requerido error={errores.origen}>
              {(p) => (
                <select {...p} value={f.origen} onChange={(ev) => setF((previo) => ({ ...previo, origen: ev.target.value, destino: previo.destino === ev.target.value ? '' : previo.destino }))}>
                  <option value="">Elija la caja o cuenta</option>
                  {delOrigen.map((c) => (
                    <option key={c.cuenta} value={c.cuenta}>
                      {c.nombre} ({c.moneda === 'USD' ? 'US$' : 'S/'}) · {dinero(c.saldo, c.moneda)}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            {puedeEntreEmpresas && (
              <Campo etiqueta="Empresa que recibe" tipo="select">
                {(p) => (
                  <select {...p} value={f.empresaDestino || String(empresaActivaId)} onChange={(ev) => setF((previo) => ({ ...previo, empresaDestino: ev.target.value, destino: '' }))}>
                    {empresas.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.nombre_comercial || e.razon_social}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
            )}
            <Campo etiqueta="Entra a" tipo="select" requerido error={errores.destino}>
              {(p) => (
                <select {...p} value={f.destino} onChange={(ev) => poner('destino', ev.target.value)}>
                  <option value="">{otraEmpresa && cuentasOtraEmpresa.isLoading ? 'Cargando…' : 'Elija la caja o cuenta'}</option>
                  {posiblesDestinos.map((c) => (
                    <option key={c.cuenta} value={c.cuenta}>
                      {c.nombre} ({c.moneda === 'USD' ? 'US$' : 'S/'})
                    </option>
                  ))}
                </select>
              )}
            </Campo>
          </div>
          {otraEmpresa && <p className="compra-aviso">Vas a pasar dinero a otra empresa. Queda registrado en las dos.</p>}
          <div className="fila-campos">
            <Campo etiqueta={`Monto que sale (${simbolo})`} requerido error={errores.monto}>
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.monto} onChange={(ev) => poner('monto', ev.target.value)} />}
            </Campo>
            {cambiaMoneda && (
              <Campo etiqueta="Tipo de cambio" requerido error={errores.tipoCambio}>
                {(p) => <input {...p} inputMode="decimal" placeholder="3.75" value={f.tipoCambio} onChange={(ev) => poner('tipoCambio', ev.target.value)} />}
              </Campo>
            )}
            <Campo etiqueta="Fecha" icono="calendario" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" max={hoyIso()} value={f.fecha} onChange={(ev) => poner('fecha', ev.target.value)} />}
            </Campo>
          </div>
          {cambiaMoneda && (
            <p className="celda-suave" aria-live="polite">
              {recibe === null ? 'Con el tipo de cambio se calcula lo que entra.' : <>Entra a «{destino.nombre}»: <strong>{dinero(recibe, destino.moneda)}</strong></>}
            </p>
          )}
          <div className="fila-campos">
            <Campo etiqueta={`Comisión del banco (${simbolo})`} error={errores.comision} ayuda="Opcional. Sale de la cuenta de origen.">
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.comision} onChange={(ev) => poner('comision', ev.target.value)} />}
            </Campo>
            <Campo etiqueta={`ITF (${simbolo})`} error={errores.itf} ayuda="Opcional. Impuesto a las transacciones financieras.">
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.itf} onChange={(ev) => poner('itf', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="N° de operación">
              {(p) => <input {...p} maxLength={60} placeholder="Opcional" value={f.referencia} onChange={(ev) => poner('referencia', ev.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Detalle (glosa)" contador={{ actual: f.glosa.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} placeholder="Ej. Depósito de las ventas del lunes" value={f.glosa} onChange={(ev) => poner('glosa', ev.target.value)} />}
          </Campo>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={transferir.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={transferir.isPending}>
            {transferir.isPending ? 'Registrando…' : CLASES[f.clase].boton}
          </button>
        </div>
      </form>
    </Modal>
  )
}
