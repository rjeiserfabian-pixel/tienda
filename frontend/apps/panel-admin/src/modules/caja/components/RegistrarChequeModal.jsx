import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { hoyIso } from '../../almacen/inventario'
import { borradorCheque, cuerpoCheque, MONEDAS_CHEQUE, TIPOS_CHEQUE, validarCheque } from '../cheques'

const CAMPOS_DEL_SERVIDOR = ['numero', 'banco', 'importe', 'moneda', 'fecha_emision', 'fecha_pago', 'tercero', 'cuenta', 'cuenta_cartera', 'cliente', 'proveedor', 'glosa']

/** Anota un cheque que se recibió de un cliente o que se giró a un proveedor. */
export default function RegistrarChequeModal({ cuentas, onCerrar }) {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [f, setF] = useState(borradorCheque)
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const recibido = f.tipo === 'RECIBIDO'
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))

  const deCheques = useQuery({
    queryKey: ['caja', 'cheques', 'cuentas', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/cheques/cuentas/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const sugeridas = (deCheques.data ?? []).filter((c) => c.moneda === f.moneda)
  const activas = (cuentas ?? []).filter((c) => c.estado === 'ACTIVO' && c.moneda === f.moneda)
  const bancos = activas.filter((c) => c.tipo === 'BANCO')
  // Si solo hay una cuenta de cheques configurada en Ventas, se propone sola.
  const cartera = f.cuenta_cartera || (sugeridas.length === 1 ? String(sugeridas[0].id) : '')

  const cuerpo = cuerpoCheque({ ...f, cuenta_cartera: cartera }, empresaActivaId)
  const clave = useClaveIdempotente(cuerpo)

  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/caja/cheques/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: (c) => `Cheque ${c.numero} registrado.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (registrar.isPending) return
    const locales = validarCheque(f, hoyIso())
    setErrores(locales)
    setGeneral('')
    if (Object.keys(locales).length) return
    registrar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const campos = erroresDeCampo(error)
          const delServidor = Object.fromEntries(CAMPOS_DEL_SERVIDOR.filter((k) => campos[k]).map((k) => [k, campos[k]]))
          setErrores(delServidor)
          setGeneral(Object.keys(delServidor).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  const tercero = recibido ? f.cliente : f.proveedor
  const elegirTercero = (item) => {
    setF((previo) => ({ ...previo, [recibido ? 'cliente' : 'proveedor']: item ? { id: item.id, nombre: item.nombre } : null, tercero: item ? '' : previo.tercero }))
  }

  return (
    <Modal titulo="Registrar cheque" subtitulo={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}.`} onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={registrar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="segmentos" role="radiogroup" aria-label="Tipo de cheque">
            {Object.entries(TIPOS_CHEQUE).map(([valor, t]) => (
              <button
                key={valor}
                type="button"
                role="radio"
                aria-checked={f.tipo === valor}
                className={f.tipo === valor ? 'activo' : undefined}
                onClick={() => setF((previo) => ({ ...previo, tipo: valor, cuenta: '', cuenta_cartera: '', cliente: null, proveedor: null }))}
              >
                {t.largo}
              </button>
            ))}
          </div>

          <div className="fila-campos">
            <Campo etiqueta="N° del cheque" requerido error={errores.numero}>
              {(p) => <input {...p} maxLength={30} value={f.numero} onChange={(ev) => poner('numero', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Banco del cheque" requerido error={errores.banco}>
              {(p) => <input {...p} maxLength={60} placeholder="Ej. BBVA" value={f.banco} onChange={(ev) => poner('banco', ev.target.value)} />}
            </Campo>
          </div>

          <div className="fila-campos">
            <Campo etiqueta="Moneda" tipo="select" error={errores.moneda}>
              {(p) => (
                <select {...p} value={f.moneda} onChange={(ev) => setF((previo) => ({ ...previo, moneda: ev.target.value, cuenta: '', cuenta_cartera: '' }))}>
                  {Object.entries(MONEDAS_CHEQUE).map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta={`Importe (${f.moneda === 'USD' ? 'US$' : 'S/'})`} requerido error={errores.importe}>
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.importe} onChange={(ev) => poner('importe', ev.target.value)} />}
            </Campo>
          </div>

          <div className="fila-campos">
            <Campo etiqueta="Fecha de emisión" icono="calendario" requerido error={errores.fecha_emision}>
              {(p) => <input {...p} type="date" max={hoyIso()} value={f.fecha_emision} onChange={(ev) => poner('fecha_emision', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Fecha de pago" icono="calendario" ayuda="Solo si es un cheque diferido." error={errores.fecha_pago}>
              {(p) => <input {...p} type="date" min={f.fecha_emision || undefined} value={f.fecha_pago} onChange={(ev) => poner('fecha_pago', ev.target.value)} />}
            </Campo>
          </div>

          <div className="campo">
            <span className="etiqueta-texto" id="cheque-tercero">
              {recibido ? 'Cliente que lo giró' : 'Proveedor a quien se giró'}
            </span>
            {tercero ? (
              <div className="cheque-tercero-elegido">
                <strong>{tercero.nombre}</strong>
                <button type="button" onClick={() => elegirTercero(null)}>
                  Cambiar
                </button>
              </div>
            ) : (
              <BuscadorAsincrono
                clave={recibido ? 'cheque-cliente' : 'cheque-proveedor'}
                url={recibido ? '/mantenimiento/clientes/' : '/mantenimiento/proveedores/'}
                parametros={{ estado: 'ACTIVO' }}
                etiqueta={recibido ? 'Buscar cliente' : 'Buscar proveedor'}
                placeholder="Busca por nombre o documento…"
                icono={recibido ? 'user' : 'handshake'}
                onElegir={elegirTercero}
                mostrar={(p) => (
                  <>
                    <strong>{p.nombre}</strong>
                    <span className="sub-texto">
                      {p.tipo_documento} {p.numero_documento}
                    </span>
                  </>
                )}
              />
            )}
          </div>
          {!tercero && (
            <Campo etiqueta="O escriba el nombre" requerido error={errores.tercero} ayuda="Si no está registrado, escríbalo tal como figura en el cheque.">
              {(p) => <input {...p} maxLength={150} value={f.tercero} onChange={(ev) => poner('tercero', ev.target.value)} />}
            </Campo>
          )}

          {recibido ? (
            <>
              <Campo etiqueta="Cuenta de cheques" tipo="select" error={errores.cuenta_cartera} ayuda="La cuenta donde se anotó el cobro de la venta: de ahí sale el dinero al cobrar el cheque.">
                {(p) => (
                  <select {...p} value={cartera} onChange={(ev) => poner('cuenta_cartera', ev.target.value)}>
                    <option value="">Elegir al cobrarlo</option>
                    {sugeridas.length > 0 && (
                      <optgroup label="Configuradas en Ventas">
                        {sugeridas.map((c) => (
                          <option key={`s${c.id}`} value={c.id}>
                            {c.nombre}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    <optgroup label="Otras cuentas de la empresa">
                      {activas
                        .filter((c) => !sugeridas.some((s) => s.id === c.cuenta))
                        .map((c) => (
                          <option key={c.cuenta} value={c.cuenta}>
                            {c.nombre}
                          </option>
                        ))}
                    </optgroup>
                  </select>
                )}
              </Campo>
              {!deCheques.isLoading && sugeridas.length === 0 && (
                <p className="compra-aviso" role="status">
                  Todavía no hay una cuenta de cobro para el método «Cheque». Se configura en Ventas, en «Cuentas de cobro». Sin ella, el cobro de la venta no queda anotado donde corresponde.
                </p>
              )}
            </>
          ) : (
            <>
              <Campo etiqueta="Cuenta de banco de giro" tipo="select" requerido error={errores.cuenta}>
                {(p) => (
                  <select {...p} value={f.cuenta} onChange={(ev) => poner('cuenta', ev.target.value)}>
                    <option value="">Elija la cuenta del banco</option>
                    {bancos.map((c) => (
                      <option key={c.cuenta} value={c.cuenta}>
                        {c.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <p className="compra-aviso" role="status">
                Registrar un cheque girado no mueve dinero: el pago al proveedor ya sale de la cuenta cuando se registra en Compras con el método «Cheque». Aquí solo se controla cuáles siguen sin cobrar.
              </p>
            </>
          )}

          <Campo etiqueta="Detalle (glosa)" contador={{ actual: f.glosa.length, max: 250 }} error={errores.glosa}>
            {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={f.glosa} onChange={(ev) => poner('glosa', ev.target.value)} />}
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
            {registrar.isPending ? 'Registrando…' : 'Registrar cheque'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
