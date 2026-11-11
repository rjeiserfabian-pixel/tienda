import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta, hoyIso, paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import AccionConNotaModal from '../../caja/components/AccionConNotaModal'
import { dinero } from '../../compras/compras'
import '../../almacen/inventario.css'
import '../ventas.css'

const VACIO = []
const centimos = (valor) => Math.round((aNumero(valor) ?? 0) * 100)

/** Pasa lo vendido con tarjeta del POS al banco: lo que depositó el procesador y su comisión. */
function LiquidarModal({ pos, empresaId, onCerrar }) {
  const bancos = (useOpciones('/mantenimiento/cuentas/', { empresa: empresaId }).data ?? VACIO).filter((c) => c.tipo !== 'CAJA' && c.id !== pos.cuenta && c.moneda === pos.moneda)
  const hoy = hoyIso()
  const [bruto, setBruto] = useState(Number(pos.saldo).toFixed(2))
  const [comision, setComision] = useState('')
  const [destino, setDestino] = useState('')
  const [fecha, setFecha] = useState(hoy)
  const [referencia, setReferencia] = useState('')
  const [observacion, setObservacion] = useState('')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const netoCts = centimos(bruto) - centimos(comision)
  const cuerpo = { empresa: empresaId, cuenta_pos: pos.cuenta, cuenta_destino: Number(destino) || 0, bruto: paraServidor(bruto), ...(comision.trim() ? { comision: paraServidor(comision) } : {}), fecha, ...(referencia.trim() ? { referencia: referencia.trim() } : {}), ...(observacion.trim() ? { observacion: observacion.trim() } : {}) }
  const clave = useClaveIdempotente(cuerpo)
  const liquidar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/ventas/liquidaciones/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas'], ['caja']],
    exito: (l) => `Liquidación N° ${String(l.numero).padStart(6, '0')} registrada.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (liquidar.isPending) return
    const e = {}
    if (centimos(bruto) <= 0) e.bruto = 'Indica cuánto se vendió con tarjeta.'
    if (centimos(bruto) > centimos(pos.saldo)) e.bruto = `En el POS solo hay ${dinero(pos.saldo, pos.moneda)} por liquidar.`
    if (comision.trim() && (centimos(comision) < 0 || centimos(comision) >= centimos(bruto))) e.comision = 'La comisión debe ser menor que lo vendido.'
    if (!destino) e.destino = 'Elige el banco donde se depositó.'
    if (fecha > hoy) e.fecha = 'La fecha no puede ser futura.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    liquidar.mutate({ datos: cuerpo, llave: clave }, {
      onError: (error) => {
        const campos = erroresDeCampo(error)
        setErrores({ bruto: campos.bruto, comision: campos.comision, destino: campos.cuenta_destino })
        setGeneral(Object.keys(campos).length ? 'Revisa los datos marcados.' : mensajeDeError(error))
      },
    })
  }

  return (
    <Modal titulo="Liquidar tarjetas" subtitulo={`${pos.nombre} · por liquidar ${dinero(pos.saldo, pos.moneda)}`} onCerrar={onCerrar} ancho={620}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={liquidar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <p className="celda-suave">Cuando el procesador deposita lo vendido con tarjeta, descuenta su comisión. Aquí se pasa del POS al banco lo que depositó, y la comisión queda como gasto.</p>
          <div className="fila-campos">
            <Campo etiqueta={`Vendido con tarjeta (${pos.moneda === 'USD' ? 'US$' : 'S/'})`} requerido error={errores.bruto} ayuda="Lo que se vendió y ahora se liquida (antes de la comisión).">
              {(p) => <input {...p} inputMode="decimal" value={bruto} onChange={(e) => setBruto(e.target.value.replace(',', '.'))} />}
            </Campo>
            <Campo etiqueta="Comisión retenida" error={errores.comision} ayuda="Opcional. Lo que el procesador descontó (con su IGV).">
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={comision} onChange={(e) => setComision(e.target.value.replace(',', '.'))} />}
            </Campo>
          </div>
          <p className="pos-vuelto" role="status">
            Debe llegar al banco: <strong>{dinero(Math.max(netoCts, 0) / 100, pos.moneda)}</strong>
          </p>
          <Campo etiqueta="Se depositó en" tipo="select" requerido error={errores.destino}>
            {(p) => (
              <select {...p} value={destino} onChange={(e) => setDestino(e.target.value)}>
                <option value="">Elige el banco</option>
                {bancos.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <div className="fila-campos">
            <Campo etiqueta="Fecha del depósito" icono="calendario" error={errores.fecha}>
              {(p) => <input {...p} type="date" max={hoy} value={fecha} onChange={(e) => setFecha(e.target.value)} />}
            </Campo>
            <Campo etiqueta="Lote u operación" ayuda="Opcional: para encontrarlo en el estado de cuenta.">
              {(p) => <input {...p} maxLength={60} value={referencia} onChange={(e) => setReferencia(e.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Observación" contador={{ actual: observacion.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={observacion} onChange={(e) => setObservacion(e.target.value)} />}
          </Campo>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={liquidar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={liquidar.isPending}>
            {liquidar.isPending ? 'Liquidando…' : 'Liquidar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Liquidación de tarjetas: lo que falta recibir del procesador, y el historial de lo ya liquidado. */
export default function LiquidacionTarjetasPage() {
  const { empresaActivaId } = useEmpresas()
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'liquidar', pos } o { tipo: 'anular', fila }

  const pendientes = useQuery({
    queryKey: ['ventas', 'liquidaciones-pendientes', empresaActivaId],
    queryFn: ({ signal }) => api.get('/ventas/liquidaciones/pendientes/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const historial = useListado(['ventas', 'liquidaciones'], '/ventas/liquidaciones/', { empresa: empresaActivaId, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = historial.data?.results ?? VACIO
  const cuentas = pendientes.data ?? VACIO

  return (
    <main className="listado">
      <CabeceraListado icono="wallet" titulo="Liquidar tarjetas" descripcion="Las ventas con tarjeta llegan al banco días después, menos la comisión del procesador. Mientras tanto están en la cuenta del POS." />

      <EstadoConsulta consulta={pendientes} hayDatos={Boolean(pendientes.data)}>
        {cuentas.length === 0 ? (
          <p className="estado-vacio">Ninguna cuenta recibe cobros con tarjeta. Configúrala en «Cuentas de cobro» (método Tarjeta → la cuenta del POS).</p>
        ) : (
          <div className="cxp-resumen">
            {cuentas.map((c) => (
              <dl className="cxp-tarjetas" key={c.cuenta} aria-label={c.nombre}>
                <div data-tono={Number(c.saldo) > 0 ? 'ambar' : undefined}>
                  <dt>{c.nombre}</dt>
                  <dd>{dinero(c.saldo, c.moneda)}</dd>
                  <small>Por liquidar</small>
                </div>
                <div className="liquidar-accion">
                  <button type="button" className="primario boton-cabecera" disabled={Number(c.saldo) <= 0} onClick={() => setDialogo({ tipo: 'liquidar', pos: c })}>
                    <Icono nombre="wallet" tam={18} /> Liquidar
                  </button>
                </div>
              </dl>
            ))}
          </div>
        )}
      </EstadoConsulta>

      <h3>Liquidaciones hechas</h3>
      <EstadoConsulta consulta={historial} hayDatos={Boolean(historial.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>N°</th>
                <th>Fecha</th>
                <th>Del POS</th>
                <th>Al banco</th>
                <th className="num">Vendido</th>
                <th className="num">Comisión</th>
                <th className="num">Depositado</th>
                <th>Lote</th>
                <th>Estado</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="wallet" titulo="Todavía no hay liquidaciones" descripcion="Cuando el procesador deposite, regístralo desde el botón «Liquidar»." />}
              {filas.map((l) => (
                <tr key={l.id} className={l.estado === 'ANULADO' ? 'anulado' : undefined}>
                  <td className="celda-suave">{String(l.numero).padStart(6, '0')}</td>
                  <td>{fechaCorta(l.fecha)}</td>
                  <td>{l.cuenta_pos_nombre}</td>
                  <td>{l.cuenta_destino_nombre}</td>
                  <td className="num">{dinero(l.bruto, l.moneda)}</td>
                  <td className="num">{dinero(l.comision, l.moneda)}</td>
                  <td className="num">{dinero(l.neto, l.moneda)}</td>
                  <td className="celda-suave">{l.referencia || '—'}</td>
                  <td>
                    <span className="pildora" data-tono={l.estado === 'ANULADO' ? 'rojo' : 'verde'}>
                      {l.estado === 'ANULADO' ? 'Anulada' : 'Vigente'}
                    </span>
                  </td>
                  <td className="centrado">
                    {l.estado !== 'ANULADO' && (
                      <button type="button" className="accion-icono peligro-suave" aria-label={`Anular la liquidación ${l.numero}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', fila: l })}>
                        <Icono nombre="papelera" tam={18} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>
      <Paginacion
        pagina={pagina}
        tamano={tamano}
        total={historial.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

      {dialogo?.tipo === 'liquidar' && <LiquidarModal pos={dialogo.pos} empresaId={empresaActivaId} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'anular' && (
        <AccionConNotaModal
          url={`/ventas/liquidaciones/${dialogo.fila.id}/anular/`}
          invalidar={[['ventas'], ['caja']]}
          titulo="Anular la liquidación"
          subtitulo={`N° ${String(dialogo.fila.numero).padStart(6, '0')} · ${dinero(dialogo.fila.neto, dialogo.fila.moneda)}`}
          descripcion="El dinero sale del banco y vuelve, con la comisión, a la cuenta del POS."
          campo="motivo"
          etiqueta="Motivo"
          requerido
          placeholder="Ej. Se registró el lote equivocado"
          boton="Anular liquidación"
          exito="Liquidación anulada."
          peligro
          onCerrar={() => setDialogo(null)}
        />
      )}
    </main>
  )
}
