import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import PagosContado from '../../compras/components/PagosContado'
import { resolverPagos } from '../../compras/compras'
import { useCatalogosCompra } from '../../compras/hooks/useCatalogosCompra'
import ProveedorGasto from '../components/ProveedorGasto'
import RepartoGasto from '../components/RepartoGasto'
import { armarCuerpo, borradorDeRecurrente, borradorInicial, dinero, erroresDePagos, FORMAS_PAGO, importesDe, repartoInicial, validarGasto } from '../gastos'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../gastos.css'

const RUTA = '/gastos/registro'
const VACIO = []
const CAMPO_DEL_SERVIDOR = { categoria: 'categoria', fecha: 'fecha', descripcion: 'descripcion', tipo_comprobante: 'tipo', comprobante_serie: 'serie', comprobante_numero: 'numero', proveedor: 'proveedor', gastado_por: 'gastadoPor', tipo_cambio: 'tipoCambio', fecha_vencimiento: 'vence', reparto: 'reparto', base_gravada: 'base', igv: 'igv', no_gravado: 'importe' }

function Formulario() {
  const navegar = useNavigate()
  const { empresaActivaId, empresaActiva, empresas } = useEmpresas()
  const hoy = hoyIso()
  const [b, setB] = useState(() => borradorInicial(hoy))
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const [delServidor, setDelServidor] = useState({})
  const [registrado, setRegistrado] = useState(false)
  const [saliendo, setSaliendo] = useState(false)
  const [params] = useSearchParams()
  const idRecurrente = /^\d+$/.test(params.get('recurrente') ?? '') ? params.get('recurrente') : ''
  const rellenado = useRef(false)
  const poner = (campo, valor) => setB((previo) => ({ ...previo, [campo]: typeof valor === 'function' ? valor(previo[campo]) : valor }))

  const catalogos = useCatalogosCompra(empresaActivaId)
  const categorias = useOpciones('/mantenimiento/categorias-gasto/').data ?? VACIO
  const sucursales = useOpciones('/organizacion/sucursales/', { empresa: empresaActivaId }).data ?? VACIO
  const configuracion = useQuery({
    queryKey: ['gastos', 'configuracion', empresaActivaId],
    queryFn: ({ signal }) => api.get('/gastos/configuracion/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
    staleTime: 60_000,
  })
  const tasa = Number(configuracion.data?.igv_porcentaje ?? 18)
  const plantilla = useQuery({
    queryKey: ['gastos', 'recurrente', idRecurrente],
    queryFn: ({ signal }) => api.get(`/gastos/recurrentes/${idRecurrente}/`, { signal }).then((r) => r.data),
    enabled: Boolean(idRecurrente),
    staleTime: 0,
    retry: false,
  })
  const tope = configuracion.data ? Number(configuracion.data.tope_sin_comprobante) : null
  const puedeExceder = Boolean(configuracion.data?.puede_exceder_tope)
  const puedeRepartir = Boolean(configuracion.data?.puede_repartir) && empresas.length > 1

  const comprobantes = catalogos.comprobantes.data ?? VACIO
  const tipoComprobante = comprobantes.find((t) => String(t.id) === String(b.tipo)) ?? null
  const detallaIgv = Boolean(tipoComprobante?.lleva_igv)
  const medios = catalogos.medios.data ?? VACIO
  const cuentas = catalogos.cuentas.data ?? VACIO

  // Con la plantilla cargada y los catálogos listos, se propone todo una sola vez.
  useEffect(() => {
    const r = plantilla.data
    if (!r || rellenado.current || !configuracion.data || comprobantes.length === 0) return
    rellenado.current = true
    const tipo = comprobantes.find((t) => t.id === r.tipo_comprobante)
    setB((previo) => borradorDeRecurrente(previo, r, { detallaIgv: Boolean(tipo?.lleva_igv), tasa }))
  }, [plantilla.data, configuracion.data, comprobantes, tasa])

  const importes = importesDe(b, detallaIgv, tasa)
  const total = importes.total
  const pagos = resolverPagos(b.pagos, total.toFixed(2), { medios, cuentas, moneda: b.moneda, tipoCambio: b.moneda === 'USD' ? b.tipoCambio : '' })
  const errPagos = erroresDePagos(pagos)
  const repartoActivo = puedeRepartir && b.repartir

  const validacion = validarGasto(b, { detallaIgv, tasa, total, tope, puedeExceder, hoy, pagos, errPagos, tipoComprobante, repartoActivo })
  const e = { ...(intento ? validacion.errores : {}), ...delServidor }

  const cuerpo = useMemo(
    () => (validacion.valido ? armarCuerpo(b, { empresa: empresaActivaId, importes, pagos, tipoComprobante, repartoActivo }) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(b), JSON.stringify(pagos), validacion.valido, empresaActivaId, repartoActivo],
  )
  const clave = useClaveIdempotente(cuerpo)

  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/gastos/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['gastos'], ['caja']],
    exito: (g) => `Gasto N° ${String(g.numero).padStart(6, '0')} registrado.`,
    alExito: (g) => {
      setRegistrado(true)
      navegar(`${RUTA}/${g.id}`, { replace: true })
    },
    avisarError: false,
  })
  const enviando = registrar.isPending

  const sinGuardar = !registrado && (b.descripcion.trim() !== '' || b.importe !== '' || b.base !== '' || Boolean(b.proveedor))
  useEffect(() => {
    if (!sinGuardar) return undefined
    const avisar = (ev) => ev.preventDefault()
    window.addEventListener('beforeunload', avisar)
    return () => window.removeEventListener('beforeunload', avisar)
  }, [sinGuardar])

  const enviar = () => {
    if (enviando) return
    setIntento(true)
    setGeneral('')
    setDelServidor({})
    if (!validacion.valido || !cuerpo) {
      setTimeout(() => {
        const primero = document.querySelector('.compra-principal [aria-invalid="true"]')
        primero?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        primero?.focus({ preventScroll: true })
      }, 0)
      return
    }
    registrar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const campos = erroresDeCampo(error)
          const mapeados = Object.fromEntries(Object.entries(campos).flatMap(([k, v]) => (CAMPO_DEL_SERVIDOR[k] ? [[CAMPO_DEL_SERVIDOR[k], v]] : [])))
          setDelServidor(mapeados)
          setGeneral(Object.keys(campos).length && Object.keys(mapeados).length === Object.keys(campos).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  const cancelar = () => (sinGuardar ? setSaliendo(true) : navegar(RUTA))
  const cambiarModo = (conComprobante) => {
    setB((previo) => ({ ...previo, conComprobante, importe: '', base: '', igv: '', igvManual: false, noGravado: '' }))
    setIntento(false)
  }
  const activarReparto = (valor) => {
    poner('repartir', valor)
    if (valor && b.reparto.length === 0) poner('reparto', repartoInicial(empresas, empresaActivaId))
  }
  const simbolo = b.moneda === 'USD' ? 'US$' : 'S/'

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={RUTA} texto="Volver a Gastos" />
      <CabeceraListado icono="coins" titulo="Registrar gasto" descripcion={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. Con comprobante (factura, recibo, boleta) o sin él (un taxi, una propina).`} />
      {plantilla.data && (
        <p className="compra-aviso" role="status">
          Registrando «{plantilla.data.nombre}», que tocaba el {fechaCorta(plantilla.data.proxima_fecha)}. Revisa el importe y el comprobante de esta vez: al registrar, pasa solo al siguiente ciclo.
        </p>
      )}
      {idRecurrente && plantilla.isError && <p className="compra-aviso">No se pudo cargar el gasto recurrente: puedes registrar el gasto a mano.</p>}
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="documento" titulo="¿Tiene comprobante?" descripcion="El comprobante es el documento que te dieron al pagar.">
            <div className="gasto-modos" role="radiogroup" aria-label="¿Tiene comprobante?">
              <button type="button" role="radio" aria-checked={b.conComprobante} className={b.conComprobante ? 'activo' : undefined} disabled={enviando} onClick={() => cambiarModo(true)}>
                <strong>Con comprobante</strong>
                <span>Factura, boleta, recibo de luz, agua o internet, recibo por honorarios.</span>
              </button>
              <button type="button" role="radio" aria-checked={!b.conComprobante} className={!b.conComprobante ? 'activo' : undefined} disabled={enviando} onClick={() => cambiarModo(false)}>
                <strong>Sin comprobante</strong>
                <span>Un taxi, una propina, un gasto menor sin documento.</span>
              </button>
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="coins" titulo="El gasto" descripcion="Qué fue, cuándo y en qué categoría.">
            <div className="fila-campos">
              <Campo etiqueta="Fecha" icono="calendario" requerido error={e.fecha}>
                {(p) => <input {...p} type="date" max={hoy} value={b.fecha} disabled={enviando} onChange={(ev) => poner('fecha', ev.target.value)} />}
              </Campo>
              <Campo etiqueta="Categoría" tipo="select" requerido error={e.categoria}>
                {(p) => (
                  <select {...p} value={b.categoria} disabled={enviando} onChange={(ev) => poner('categoria', ev.target.value)}>
                    <option value="">Elija la categoría</option>
                    {categorias.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              {sucursales.length > 1 && (
                <Campo etiqueta="Tienda" tipo="select" ayuda="Opcional: para ver los gastos por tienda.">
                  {(p) => (
                    <select {...p} value={b.sucursal} disabled={enviando} onChange={(ev) => poner('sucursal', ev.target.value)}>
                      <option value="">Toda la empresa</option>
                      {sucursales.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.nombre}
                        </option>
                      ))}
                    </select>
                  )}
                </Campo>
              )}
            </div>
            <Campo etiqueta="¿Qué fue y para qué?" requerido error={e.descripcion} contador={{ actual: b.descripcion.length, max: 250 }}>
              {(p) => <input {...p} maxLength={250} placeholder={b.conComprobante ? 'Ej. Luz de octubre del local' : 'Ej. Taxi a la oficina de SUNAT'} value={b.descripcion} disabled={enviando} onChange={(ev) => poner('descripcion', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>

          {b.conComprobante ? (
            <PanelTarjeta icono="documento" titulo="Comprobante" descripcion="Datos tal como figuran en el documento.">
              <div className="fila-campos">
                <Campo etiqueta="Tipo de comprobante" tipo="select" requerido error={e.tipo}>
                  {(p) => (
                    <select {...p} value={b.tipo} disabled={enviando} onChange={(ev) => setB((previo) => ({ ...previo, tipo: ev.target.value, base: '', igv: '', igvManual: false, noGravado: '', importe: '' }))}>
                      <option value="">Elija el tipo</option>
                      {comprobantes.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.nombre}
                        </option>
                      ))}
                    </select>
                  )}
                </Campo>
                <Campo etiqueta="Serie" error={e.serie} ayuda="Opcional si no la tiene.">
                  {(p) => <input {...p} maxLength={10} placeholder="Ej. F001" value={b.serie} disabled={enviando} onChange={(ev) => poner('serie', ev.target.value.toUpperCase())} />}
                </Campo>
                <Campo etiqueta="Número" requerido error={e.numero}>
                  {(p) => <input {...p} maxLength={20} placeholder="Ej. 000123" value={b.numero} disabled={enviando} onChange={(ev) => poner('numero', ev.target.value.toUpperCase())} />}
                </Campo>
              </div>
              <ProveedorGasto proveedor={b.proveedor} onElegir={(p) => poner('proveedor', p)} error={e.proveedor} obligatorio={tipoComprobante?.codigo === '01'} disabled={enviando} />
            </PanelTarjeta>
          ) : (
            <PanelTarjeta icono="user" titulo="Quién lo gastó" descripcion="Sin comprobante queda un registro de quién hizo el gasto.">
              <Campo etiqueta="Nombre de quien lo gastó" requerido error={e.gastadoPor}>
                {(p) => <input {...p} maxLength={120} placeholder="Ej. Rosa Quispe" value={b.gastadoPor} disabled={enviando} onChange={(ev) => poner('gastadoPor', ev.target.value)} />}
              </Campo>
              {tope !== null && !puedeExceder && <p className="celda-suave">Un gasto sin comprobante puede llegar hasta S/ {tope.toFixed(2)}. Para más, pide el comprobante o a quien pueda autorizarlo.</p>}
              {!b.conComprobante && <p className="compra-aviso">Sin comprobante, este gasto no sirve como crédito fiscal ni se suma a las compras de SUNAT. Queda marcado «sin sustento».</p>}
            </PanelTarjeta>
          )}

          <PanelTarjeta icono="coins" titulo="Importe" descripcion={b.conComprobante && detallaIgv ? 'Escribe lo que dice el comprobante. El IGV se calcula solo, y lo puedes corregir.' : 'Cuánto costó, en total.'}>
            <div className="fila-campos">
              <Campo etiqueta="Moneda" tipo="select">
                {(p) => (
                  <select {...p} value={b.moneda} disabled={enviando} onChange={(ev) => poner('moneda', ev.target.value)}>
                    <option value="PEN">Soles (S/)</option>
                    <option value="USD">Dólares (US$)</option>
                  </select>
                )}
              </Campo>
              {b.moneda === 'USD' && (
                <Campo etiqueta="Tipo de cambio" requerido error={e.tipoCambio}>
                  {(p) => <input {...p} inputMode="decimal" placeholder="3.75" value={b.tipoCambio} disabled={enviando} onChange={(ev) => poner('tipoCambio', ev.target.value)} />}
                </Campo>
              )}
            </div>
            {b.conComprobante && detallaIgv ? (
              <div className="fila-campos">
                <Campo etiqueta={`Base sin IGV (${simbolo})`} error={e.base}>
                  {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={b.base} disabled={enviando} onChange={(ev) => poner('base', ev.target.value)} />}
                </Campo>
                <Campo etiqueta={`IGV ${tasa}% (${simbolo})`} error={e.igv}>
                  {(p) => (
                    <input
                      {...p}
                      inputMode="decimal"
                      placeholder="0.00"
                      value={b.igvManual ? b.igv : importes.igv ? importes.igv.toFixed(2) : ''}
                      disabled={enviando}
                      onChange={(ev) => setB((previo) => ({ ...previo, igv: ev.target.value, igvManual: true }))}
                    />
                  )}
                </Campo>
                <Campo etiqueta={`Importe sin IGV (${simbolo})`} ayuda="Opcional: conceptos exonerados o inafectos.">
                  {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={b.noGravado} disabled={enviando} onChange={(ev) => poner('noGravado', ev.target.value)} />}
                </Campo>
              </div>
            ) : (
              <Campo etiqueta={`Importe total (${simbolo})`} requerido error={e.importe} ayuda={b.conComprobante && tipoComprobante && !detallaIgv ? 'Este comprobante no detalla el IGV: escribe el total.' : undefined}>
                {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={b.importe} disabled={enviando} onChange={(ev) => poner('importe', ev.target.value)} />}
              </Campo>
            )}
          </PanelTarjeta>

          <PanelTarjeta icono="wallet" titulo="Pago" descripcion="Si ya se pagó, de dónde salió el dinero. Si no, queda por pagar.">
            <div className="segmentos" role="radiogroup" aria-label="Forma de pago">
              {Object.entries(FORMAS_PAGO).map(([valor, texto]) => (
                <button key={valor} type="button" role="radio" aria-checked={b.forma === valor} className={b.forma === valor ? 'activo' : undefined} disabled={enviando} onClick={() => poner('forma', valor)}>
                  {texto}
                </button>
              ))}
            </div>
            {b.forma === 'CONTADO' ? (
              <PagosContado resueltos={pagos} cuentas={cuentas} medios={medios} moneda={b.moneda} total={total.toFixed(2)} errores={intento ? errPagos : {}} sinPermisoCajas={!catalogos.puedeVerCajas} onPagos={(f) => poner('pagos', f)} disabled={enviando} />
            ) : (
              <Campo etiqueta="Vence el" icono="calendario" requerido error={e.vence} ayuda="Por ejemplo, la fecha límite del recibo de luz. Lo pagas después, desde la ficha del gasto.">
                {(p) => <input {...p} type="date" min={b.fecha} value={b.vence} disabled={enviando} onChange={(ev) => poner('vence', ev.target.value)} />}
              </Campo>
            )}
          </PanelTarjeta>

          {puedeRepartir && (
            <PanelTarjeta icono="building" titulo="¿De qué empresa es?" descripcion="Va solo a esta empresa, o se reparte entre varias por porcentaje.">
              <RepartoGasto activo={b.repartir} onActivar={activarReparto} reparto={b.reparto} onReparto={(f) => poner('reparto', f)} empresas={empresas} total={total} moneda={b.moneda} error={e.reparto} disabled={enviando} nombreEmpresa={empresaActiva?.nombre_comercial || empresaActiva?.razon_social} />
            </PanelTarjeta>
          )}

          <PanelTarjeta icono="documento" titulo="Observación">
            <Campo etiqueta="Nota interna" contador={{ actual: b.observacion.length, max: 250 }}>
              {(p) => <textarea {...p} rows={2} maxLength={250} placeholder="Opcional. Después podrás adjuntar la foto del comprobante." value={b.observacion} disabled={enviando} onChange={(ev) => poner('observacion', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>
        </div>

        <aside className="compra-resumen" aria-label="Resumen del gasto">
          <h3>Resumen</h3>
          <p className="celda-suave">{b.conComprobante ? (tipoComprobante ? `${tipoComprobante.nombre}${b.numero ? ` ${b.serie ? `${b.serie}-` : ''}${b.numero}` : ''}` : 'Con comprobante') : 'Sin comprobante'}</p>
          <dl className="compra-totales">
            {b.conComprobante && detallaIgv && importes.base > 0 && (
              <div>
                <dt>Base gravada</dt>
                <dd>{dinero(importes.base, b.moneda)}</dd>
              </div>
            )}
            {b.conComprobante && detallaIgv && importes.igv > 0 && (
              <div>
                <dt>IGV</dt>
                <dd>{dinero(importes.igv, b.moneda)}</dd>
              </div>
            )}
            {b.conComprobante && detallaIgv && importes.noGravado > 0 && (
              <div>
                <dt>Sin IGV</dt>
                <dd>{dinero(importes.noGravado, b.moneda)}</dd>
              </div>
            )}
            <div className="compra-total">
              <dt>Total del gasto</dt>
              <dd>{dinero(total, b.moneda)}</dd>
            </div>
          </dl>
          {repartoActivo && <p className="celda-suave">Se reparte entre {b.reparto.length} empresas. El comprobante y el IGV quedan en {empresaActiva?.nombre_comercial || empresaActiva?.razon_social}.</p>}
          {b.forma === 'POR_PAGAR' && <p className="celda-suave">Queda por pagar: no sale dinero de ninguna caja todavía.</p>}
          {validacion.faltan.length > 0 && (
            <div className="compra-faltan">
              <strong>Para registrar falta:</strong>
              <ul>
                {validacion.faltan.map((texto) => (
                  <li key={texto}>{texto}</li>
                ))}
              </ul>
            </div>
          )}
          {general && (
            <p role="alert" className="campo-error">
              {general}
            </p>
          )}
          <button type="button" className="primario compra-registrar" disabled={enviando} onClick={enviar}>
            <Icono nombre="coins" tam={20} /> {enviando ? 'Registrando…' : 'Registrar gasto'}
          </button>
          <button type="button" disabled={enviando} onClick={cancelar}>
            Cancelar
          </button>
        </aside>
      </div>
      {saliendo && <ConfirmarModal titulo="Salir sin registrar" mensaje="Se perderá lo que escribiste en este gasto. ¿Quieres salir?" textoConfirmar="Salir" onConfirmar={() => navegar(RUTA)} onCerrar={() => setSaliendo(false)} />}
    </main>
  )
}

/** Pantalla «Registrar gasto». Se reinicia sola si se cambia de empresa (un gasto es de una sola empresa titular). */
export default function RegistrarGastoPage() {
  const { empresaActivaId } = useEmpresas()
  if (!empresaActivaId) return <p style={{ padding: 24 }}>Elige una empresa para registrar el gasto.</p>
  return <Formulario key={empresaActivaId} />
}
