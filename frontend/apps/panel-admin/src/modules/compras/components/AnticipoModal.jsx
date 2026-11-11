import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
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
import { dinero, MONEDAS } from '../compras'

/** Órdenes del proveedor que todavía esperan mercadería (emitidas o recibidas en parte), en esa moneda. */
function useOrdenesDelProveedor(empresa, proveedor, moneda) {
  return useQuery({
    queryKey: ['compras', 'ordenes', 'para-anticipo', empresa, proveedor?.id, moneda],
    queryFn: ({ signal }) =>
      api.get('/compras/ordenes/', { params: { empresa, proveedor: proveedor.id, pendientes: 1, page_size: 100 }, signal }).then((r) => r.data.results.filter((o) => o.moneda === moneda)),
    enabled: Boolean(empresa && proveedor),
    staleTime: 0,
  })
}

/** Lo ya anticipado de una orden frente a su total, para no pasarse. */
function ResumenOrden({ ordenId }) {
  const consulta = useQuery({
    queryKey: ['compras', 'orden', ordenId],
    queryFn: ({ signal }) => api.get(`/compras/ordenes/${ordenId}/`, { signal }).then((r) => r.data),
    enabled: Boolean(ordenId),
    staleTime: 0,
  })
  const o = consulta.data
  if (!o) return null
  const ya = (o.anticipos ?? []).filter((a) => a.estado === 'EMITIDO').reduce((s, a) => s + Math.round(aNumero(a.monto) * 100), 0) / 100
  const falta = Math.max(0, Math.round((aNumero(o.total) - ya) * 100) / 100)
  return (
    <p className="celda-suave" aria-live="polite">
      Total de la orden {dinero(o.total, o.moneda)} · ya anticipado {dinero(ya, o.moneda)} · se puede anticipar hasta {dinero(falta, o.moneda)}.
    </p>
  )
}

/**
 * Registrar un anticipo: dinero que se adelanta a un proveedor. Sale de la caja o cuenta elegida y
 * deja un saldo a favor con ese proveedor (se usa en «Saldos a favor»). Puede ligarse a una orden.
 * `inicial` precarga proveedor, moneda y orden cuando se abre desde la ficha de una orden.
 */
export default function AnticipoModal({ inicial = {}, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeVerCajas = tiene('CAJA.CUENTAS.VER')
  const [proveedor, setProveedor] = useState(inicial.proveedor ?? null)
  const [moneda, setMoneda] = useState(inicial.moneda ?? 'PEN')
  const [monto, setMonto] = useState('')
  const [cuenta, setCuenta] = useState('')
  const [medio, setMedio] = useState('')
  const [fecha, setFecha] = useState(hoyIso())
  const [referencia, setReferencia] = useState('')
  const [glosa, setGlosa] = useState('')
  const [orden, setOrden] = useState(inicial.orden ? String(inicial.orden) : '')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const medios = useOpciones('/mantenimiento/medios-pago/').data ?? []
  const todasLasCuentas = useOpciones('/mantenimiento/cuentas/', { empresa: empresaActivaId }, { enabled: puedeVerCajas && Boolean(empresaActivaId) }).data ?? []
  const cuentas = todasLasCuentas.filter((c) => c.moneda === moneda)
  const ordenes = useOrdenesDelProveedor(empresaActivaId, proveedor, moneda)
  // Si la orden viene precargada y aún no cargó la lista, se ofrece igual para no perderla.
  const opcionesOrden = ordenes.data ?? []

  const cuerpo = {
    empresa: empresaActivaId,
    proveedor: proveedor?.id,
    moneda,
    monto: paraServidor(monto),
    cuenta: cuenta ? Number(cuenta) : null,
    fecha,
    ...(medio ? { medio_pago: Number(medio) } : {}),
    ...(referencia.trim() ? { referencia: referencia.trim() } : {}),
    ...(glosa.trim() ? { glosa: glosa.trim() } : {}),
    ...(orden ? { orden: Number(orden) } : {}),
  }
  const clave = useClaveIdempotente(cuerpo)

  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/compras/anticipos/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras'], ['caja'], ['movimientos']],
    exito: 'Anticipo registrado. El saldo a favor ya está disponible.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (registrar.isPending) return
    const e = validarDinero({ monto, cuenta, fecha })
    if (!proveedor) e.proveedor = 'Elija el proveedor.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    registrar.mutate(
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
    <Modal titulo="Registrar anticipo" subtitulo="Dinero que adelantas a un proveedor" onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <p className="celda-suave">
          El dinero sale de la caja o cuenta que elijas y queda como saldo a favor con el proveedor. Luego lo usas en «Saldos a favor» para pagar cuotas de sus compras a crédito.
        </p>
        <fieldset disabled={registrar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="campo">
            <span className="compra-etiqueta">
              Proveedor <span className="requerido" aria-hidden="true">*</span>
            </span>
            {proveedor ? (
              <div className="compra-proveedor-elegido">
                <div className="compra-proveedor-datos">
                  <strong>{proveedor.nombre}</strong>
                  {proveedor.numero_documento && (
                    <span className="sub-texto">
                      {proveedor.tipo_documento} {proveedor.numero_documento}
                    </span>
                  )}
                </div>
                {!inicial.proveedor && (
                  <button
                    type="button"
                    onClick={() => {
                      setProveedor(null)
                      setOrden('')
                    }}
                  >
                    Cambiar
                  </button>
                )}
              </div>
            ) : (
              <BuscadorAsincrono
                clave="proveedores-anticipo"
                url="/mantenimiento/proveedores/"
                parametros={{ estado: 'ACTIVO' }}
                etiqueta="Buscar proveedor"
                placeholder="Busca por razón social o RUC…"
                icono="handshake"
                autoFocus
                onElegir={setProveedor}
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
            {errores.proveedor && (
              <small role="alert" className="campo-error">
                {errores.proveedor}
              </small>
            )}
          </div>

          <div className="fila-campos">
            <Campo etiqueta="Moneda" tipo="select" requerido>
              {(p) => (
                <select
                  {...p}
                  value={moneda}
                  disabled={Boolean(inicial.moneda)}
                  onChange={(ev) => {
                    setMoneda(ev.target.value)
                    setCuenta('')
                    setOrden('')
                  }}
                >
                  {Object.entries(MONEDAS).map(([valor, m]) => (
                    <option key={valor} value={valor}>
                      {m.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta={`Monto (${MONEDAS[moneda].simbolo})`} requerido error={errores.monto}>
              {(p) => <input {...p} inputMode="decimal" autoComplete="off" value={monto} onChange={(ev) => setMonto(ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Fecha" icono="calendario" requerido error={errores.fecha}>
              {(p) => <input {...p} type="date" max={hoyIso()} value={fecha} onChange={(ev) => setFecha(ev.target.value)} />}
            </Campo>
          </div>

          {!puedeVerCajas ? (
            <p role="alert" className="compra-aviso">
              No tienes acceso a las cajas y cuentas de esta empresa. Pide el permiso «Ver cajas y cuentas» para registrar el anticipo.
            </p>
          ) : (
            <div className="fila-campos">
              <Campo etiqueta="Sale de" tipo="select" requerido error={errores.cuenta} ayuda={cuentas.length === 0 ? `No hay cajas o cuentas en ${MONEDAS[moneda].nombre.toLowerCase()}.` : undefined}>
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
              <Campo etiqueta="Método de pago (opcional)" tipo="select">
                {(p) => (
                  <select {...p} value={medio} onChange={(ev) => setMedio(ev.target.value)}>
                    <option value="">Sin indicar</option>
                    {medios.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.nombre}
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

          <Campo etiqueta="Orden de compra (opcional)" tipo="select" ayuda={proveedor ? 'Solo órdenes emitidas o recibidas en parte de este proveedor y moneda.' : 'Elige primero el proveedor.'}>
            {(p) => (
              <select {...p} value={orden} disabled={!proveedor || Boolean(inicial.orden)} onChange={(ev) => setOrden(ev.target.value)}>
                <option value="">Sin orden</option>
                {inicial.orden && !opcionesOrden.some((o) => String(o.id) === String(inicial.orden)) && <option value={inicial.orden}>{inicial.ordenCodigo ?? `Orden ${inicial.orden}`}</option>}
                {opcionesOrden.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.codigo} · {dinero(o.total, o.moneda)}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          {orden && <ResumenOrden ordenId={orden} />}

          <Campo etiqueta="Nota (opcional)" contador={{ actual: glosa.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} value={glosa} onChange={(ev) => setGlosa(ev.target.value)} />}
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
          <button type="submit" className="primario" disabled={registrar.isPending || !puedeVerCajas}>
            {registrar.isPending ? 'Registrando…' : 'Registrar anticipo'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
