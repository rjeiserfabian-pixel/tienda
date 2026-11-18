import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { cambiosDePagos, desdeServidor, MAX_LLAVE, MODOS, revisarPagos, SI_NO_RECOGE } from '../pagos'
import '../tienda.css'
import '../pagos.css'
import '../cupones.css'

const CLAVE = ['tienda', 'pagos']

/** Pagos en línea: las llaves de Culqi, el modo y los medios de pago de la tienda. */
export default function PagosTiendaPage() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/tienda/admin/pagos/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const datos = consulta.data

  const [form, setForm] = useState(null)
  const [errores, setErrores] = useState({})
  const [cambiandoSecreta, setCambiandoSecreta] = useState(false)
  const [confirmarProduccion, setConfirmarProduccion] = useState(false)
  const [resultado, setResultado] = useState(null) // { ok, mensaje } de la prueba de conexión

  // El formulario se reinicia solo cuando cambian los datos guardados (la llave secreta nunca vuelve).
  const clave = useMemo(() => (datos ? JSON.stringify(desdeServidor(datos)) : null), [datos])
  useEffect(() => {
    if (clave) {
      setForm(JSON.parse(clave))
      setCambiandoSecreta(false)
    }
  }, [clave])

  const cambios = useMemo(() => (datos && form ? cambiosDePagos(datos, form) : {}), [datos, form])
  const hayCambios = Object.keys(cambios).length > 0

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/tienda/admin/pagos/', cuerpo).then((r) => r.data),
    invalidar: [CLAVE],
    exito: 'Configuración de pagos guardada.',
    avisarError: false,
    alExito: () => {
      // La llave secreta escrita se borra de la pantalla en cuanto se guarda.
      setForm((f) => (f ? { ...f, culqi_llave_secreta: '', quitar_llave_secreta: false } : f))
      setCambiandoSecreta(false)
      setResultado(null)
    },
  })

  const probar = useMutacion({
    mutationFn: () => api.post('/tienda/admin/pagos/probar/').then((r) => r.data),
    avisarError: false,
    alExito: (r) => setResultado(r),
  })

  const poner = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined, _general: undefined }))
    setResultado(null)
  }

  const enviar = () => {
    setConfirmarProduccion(false)
    guardar.mutate(cambios, {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }

  const alEnviar = (evento) => {
    evento.preventDefault()
    const locales = revisarPagos(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    // Activar en PRODUCCION cobra dinero real: se pide confirmación explícita.
    const activaProduccion = form.culqi_activo && form.culqi_modo === 'PRODUCCION' && (cambios.culqi_activo || cambios.culqi_modo)
    if (activaProduccion) setConfirmarProduccion(true)
    else enviar()
  }

  const probarConexion = () => {
    setResultado(null)
    probar.mutate(undefined, { onError: (error) => setResultado({ ok: false, mensaje: mensajeDeError(error) }) })
  }

  const empresas = datos?.opciones?.empresas ?? []
  const cuentasPosibles = datos?.opciones?.cuentas ?? []
  const quitandoSecreta = Boolean(form?.quitar_llave_secreta)
  const hayLlaveGuardada = Boolean(datos?.tiene_llave_secreta)
  const secretaPendiente = Boolean(form && (form.culqi_llave_secreta.trim() || quitandoSecreta))
  const faltan = datos?.faltan_para_activar ?? []
  const hayErrorDeCampo = Object.entries(errores).some(([k, v]) => k !== '_general' && v)

  return (
    <main className="listado tienda-pagina pagos-pagina">
      <CabeceraListado
        icono="wallet"
        titulo="Pagos en línea"
        descripcion="Cobra con tarjeta y Yape en tu tienda virtual a través de Culqi. Las llaves se guardan cifradas y nadie, ni tú, puede volver a verlas."
      />

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && form && (
          <>
            <ol className="pagos-pasos" aria-label="Cómo activar los pagos">
              <li>
                Crea tu cuenta en <strong>culqi.com</strong> y copia tus llaves desde <em>Desarrollo → API Keys</em>.
              </li>
              <li>
                Pégalas aquí. Empieza en <strong>modo Pruebas</strong>: no cobra dinero real.
              </li>
              <li>Prueba la conexión y activa los cobros. Cuando todo funcione, pasa a Producción.</li>
            </ol>

            <form onSubmit={alEnviar} noValidate className="pagos-form" aria-label="Configuración de pagos en línea">
              <PanelTarjeta id="pagos-estado" icono="wallet" titulo="Estado" descripcion="Mientras estén desactivados, la tienda no ofrece pago en línea.">
                <div className="pagos-estado">
                  <Interruptor
                    activo={form.culqi_activo}
                    onCambio={(v) => poner('culqi_activo', v)}
                    texto={form.culqi_activo ? 'Cobros activados' : 'Cobros desactivados'}
                    descripcion={form.culqi_activo ? 'Los clientes pueden pagar en línea.' : 'Los clientes no pueden pagar en línea.'}
                  />
                  {faltan.length > 0 && (
                    <div className="pagos-alerta" role="status">
                      <Icono nombre="bell" tam={18} />
                      <span>Para activar falta: {faltan.join(' ')}</span>
                    </div>
                  )}
                  {errores.culqi_activo && (
                    <p role="alert" className="campo-error">
                      {errores.culqi_activo}
                    </p>
                  )}
                </div>
              </PanelTarjeta>

              <PanelTarjeta id="pagos-modo" icono="lock" titulo="Modo" descripcion="Las llaves de pruebas y las de producción son distintas.">
                <div className="pagos-modos" role="group" aria-label="Modo de cobro">
                  {Object.entries(MODOS).map(([valor, m]) => (
                    <button key={valor} type="button" className="pagos-modo" aria-pressed={form.culqi_modo === valor} onClick={() => poner('culqi_modo', valor)}>
                      <strong>{m.texto}</strong>
                      <small>{m.detalle}</small>
                    </button>
                  ))}
                </div>
                {form.culqi_modo === 'PRODUCCION' && (
                  <div className="pagos-alerta peligro" role="alert">
                    <Icono nombre="bell" tam={18} />
                    <span>
                      <strong>Cobra dinero real.</strong> Asegúrate de haber probado todo en modo Pruebas y de usar las llaves «live» de tu cuenta de Culqi.
                    </span>
                  </div>
                )}
                {errores.culqi_modo && (
                  <p role="alert" className="campo-error">
                    {errores.culqi_modo}
                  </p>
                )}
              </PanelTarjeta>

              <PanelTarjeta id="pagos-llaves" icono="key" titulo="Llaves de Culqi" descripcion="La pública la ve el navegador del cliente; la secreta solo la usa el servidor.">
                <div className="pagos-rejilla">
                  <Campo etiqueta="Llave pública" error={errores.culqi_llave_publica} ayuda={`Empieza con «${MODOS[form.culqi_modo].prefijos[0]}».`}>
                    {(p) => (
                      <input
                        {...p}
                        name="culqi_llave_publica"
                        autoComplete="off"
                        spellCheck={false}
                        maxLength={MAX_LLAVE}
                        value={form.culqi_llave_publica}
                        onChange={(e) => poner('culqi_llave_publica', e.target.value)}
                      />
                    )}
                  </Campo>
                  <Campo
                    etiqueta="Llave secreta"
                    error={errores.culqi_llave_secreta}
                    ayuda={`Empieza con «${MODOS[form.culqi_modo].prefijos[1]}». Se guarda cifrada y no se puede volver a ver.`}
                  >
                    {(p) => (
                      <div className="pagos-secreta">
                        <input
                          {...p}
                          name="culqi_llave_secreta"
                          type="password"
                          autoComplete="new-password"
                          spellCheck={false}
                          maxLength={MAX_LLAVE}
                          disabled={(hayLlaveGuardada && !cambiandoSecreta) || quitandoSecreta}
                          placeholder={
                            quitandoSecreta
                              ? 'Se quitará al guardar'
                              : hayLlaveGuardada
                                ? `••••••••${datos.llave_secreta_final} (guardada)`
                                : 'Pega aquí tu llave secreta'
                          }
                          value={form.culqi_llave_secreta}
                          onChange={(e) => poner('culqi_llave_secreta', e.target.value)}
                        />
                        {hayLlaveGuardada && !cambiandoSecreta && !quitandoSecreta && (
                          <>
                            <button type="button" onClick={() => setCambiandoSecreta(true)}>
                              Cambiar
                            </button>
                            <button type="button" className="peligro" onClick={() => poner('quitar_llave_secreta', true)}>
                              Quitar
                            </button>
                          </>
                        )}
                        {cambiandoSecreta && (
                          <button
                            type="button"
                            onClick={() => {
                              setCambiandoSecreta(false)
                              poner('culqi_llave_secreta', '')
                            }}
                          >
                            Cancelar
                          </button>
                        )}
                        {quitandoSecreta && (
                          <button type="button" onClick={() => poner('quitar_llave_secreta', false)}>
                            Deshacer
                          </button>
                        )}
                      </div>
                    )}
                  </Campo>
                </div>
              </PanelTarjeta>

              <PanelTarjeta id="pagos-medios" icono="coins" titulo="Medios de pago y cuenta" descripcion="Qué ofrece la tienda y a qué empresa le llega el dinero.">
                <div className="pagos-rejilla">
                  <Interruptor activo={form.acepta_tarjeta} onCambio={(v) => poner('acepta_tarjeta', v)} texto="Tarjeta de crédito o débito" descripcion="Visa, Mastercard, American Express y Diners." />
                  <Interruptor activo={form.acepta_yape} onCambio={(v) => poner('acepta_yape', v)} texto="Yape" descripcion="El cliente paga con el código de su app Yape." />
                  <Campo etiqueta="Empresa que recibe los pagos" error={errores.empresa_cobra} ayuda="La empresa dueña de la cuenta de Culqi; el dinero llega a su banco.">
                    {(p) => (
                      <select {...p} name="empresa_cobra" value={form.empresa_cobra} onChange={(e) => poner('empresa_cobra', e.target.value)}>
                        <option value="">Elige una empresa…</option>
                        {empresas.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.razon_social} · RUC {e.ruc}
                          </option>
                        ))}
                      </select>
                    )}
                  </Campo>
                </div>
              </PanelTarjeta>

              <PanelTarjeta
                id="pagos-adelanto"
                icono="coins"
                titulo="Pago con adelanto"
                descripcion="Para pedidos que se recogen en tienda: el cliente paga una parte ahora y el resto al recoger. Solo si todos los productos son de la empresa que recibe los pagos."
              >
                <Interruptor
                  activo={form.adelanto_activo}
                  onCambio={(v) => poner('adelanto_activo', v)}
                  texto={form.adelanto_activo ? 'Adelanto ofrecido' : 'Adelanto desactivado'}
                  descripcion={form.adelanto_activo ? 'Al recoger en tienda, el cliente puede elegir pagar solo el adelanto.' : 'Los pedidos se pagan completos.'}
                />
                <div className="pagos-rejilla">
                  <Campo etiqueta="Porcentaje del adelanto (%)" error={errores.adelanto_pct} ayuda="Qué parte del total se paga ahora (de 1 a 90).">
                    {(p) => <input {...p} name="adelanto_pct" inputMode="decimal" value={form.adelanto_pct} onChange={(e) => poner('adelanto_pct', e.target.value)} />}
                  </Campo>
                  <Campo etiqueta="Desde qué monto del pedido (S/)" error={errores.adelanto_minimo} ayuda="Con IGV. En pedidos menores se paga completo.">
                    {(p) => <input {...p} name="adelanto_minimo" inputMode="decimal" value={form.adelanto_minimo} onChange={(e) => poner('adelanto_minimo', e.target.value)} />}
                  </Campo>
                  <Campo etiqueta="Días para recoger" error={errores.adelanto_dias} ayuda="Mientras tanto el producto queda apartado para el cliente.">
                    {(p) => <input {...p} name="adelanto_dias" inputMode="numeric" value={form.adelanto_dias} onChange={(e) => poner('adelanto_dias', e.target.value)} />}
                  </Campo>
                </div>
                <fieldset className="cupon-tipos">
                  <legend>Si el cliente no recoge a tiempo</legend>
                  <div className="pagos-modos" role="group" aria-label="Qué pasa si no recoge">
                    {Object.entries(SI_NO_RECOGE).map(([valor, o]) => (
                      <button key={valor} type="button" className="pagos-modo" aria-pressed={form.adelanto_si_no_recoge === valor} onClick={() => poner('adelanto_si_no_recoge', valor)}>
                        <strong>{o.texto}</strong>
                        <small>{o.detalle}</small>
                      </button>
                    ))}
                  </div>
                </fieldset>
                <div className="pagos-rejilla">
                  {form.adelanto_si_no_recoge === 'PENALIDAD' ? (
                    <Campo etiqueta="Qué parte del adelanto se retiene (%)" error={errores.adelanto_penalidad_pct} ayuda="100 = se pierde todo el adelanto. El resto se devuelve al cliente.">
                      {(p) => <input {...p} name="adelanto_penalidad_pct" inputMode="decimal" value={form.adelanto_penalidad_pct} onChange={(e) => poner('adelanto_penalidad_pct', e.target.value)} />}
                    </Campo>
                  ) : (
                    <>
                      <Campo etiqueta="Comisión de la pasarela (%)" error={errores.comision_pasarela_pct} ayuda="Lo que cobra Culqi por cada pago (con IGV). Se descuenta al devolver.">
                        {(p) => <input {...p} name="comision_pasarela_pct" inputMode="decimal" value={form.comision_pasarela_pct} onChange={(e) => poner('comision_pasarela_pct', e.target.value)} />}
                      </Campo>
                      <Campo etiqueta="Comisión fija por pago (S/)" error={errores.comision_pasarela_fija} ayuda="Si la pasarela cobra un monto fijo además del porcentaje.">
                        {(p) => <input {...p} name="comision_pasarela_fija" inputMode="decimal" value={form.comision_pasarela_fija} onChange={(e) => poner('comision_pasarela_fija', e.target.value)} />}
                      </Campo>
                    </>
                  )}
                </div>
                <p className="celda-suave">El cliente ve estas condiciones antes de pagar. Los pedidos ya hechos conservan las condiciones con que se crearon.</p>
              </PanelTarjeta>

              <PanelTarjeta
                id="pagos-transferencia"
                icono="wallet"
                titulo="Transferencia o depósito"
                descripcion="El cliente paga desde su banco a una de tus cuentas y sube la foto del comprobante; tú verificas que el dinero llegó. Solo para pedidos con productos de una sola empresa (la dueña de la cuenta)."
              >
                <Interruptor
                  activo={form.transferencia_activa}
                  onCambio={(v) => poner('transferencia_activa', v)}
                  texto={form.transferencia_activa ? 'Transferencia ofrecida' : 'Transferencia desactivada'}
                  descripcion={form.transferencia_activa ? 'El cliente puede elegir pagar por transferencia o depósito.' : 'Solo se paga con tarjeta o Yape.'}
                />
                {errores.transferencia_activa && (
                  <p role="alert" className="campo-error">
                    {errores.transferencia_activa}
                  </p>
                )}
                <fieldset className="cupon-tipos">
                  <legend>Cuentas que se muestran al cliente</legend>
                  {cuentasPosibles.length === 0 ? (
                    <p className="celda-suave">No hay cuentas de banco o billetera en soles. Créalas primero en Caja y bancos → Cuentas.</p>
                  ) : (
                    <ul className="pedido-lista-simple">
                      {cuentasPosibles.map((c) => (
                        <li key={c.id}>
                          <label>
                            <input
                              type="checkbox"
                              checked={form.cuentas_transferencia.includes(c.id)}
                              onChange={(e) => poner('cuentas_transferencia', e.target.checked ? [...form.cuentas_transferencia, c.id] : form.cuentas_transferencia.filter((x) => x !== c.id))}
                            />{' '}
                            <b>{c.nombre}</b> · {c.empresa}
                            <span className="sub-texto">
                              {[c.banco, c.numero && `N.º ${c.numero}`, c.cci && `CCI ${c.cci}`].filter(Boolean).join(' · ')}
                            </span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                  {errores.cuentas_transferencia && (
                    <p role="alert" className="campo-error">
                      {errores.cuentas_transferencia}
                    </p>
                  )}
                </fieldset>
                <div className="pagos-rejilla">
                  <Campo etiqueta="Horas para pagar" error={errores.transferencia_horas} ayuda="Mientras tanto el stock queda apartado. Entre 1 y 168 horas.">
                    {(p) => <input {...p} name="transferencia_horas" inputMode="numeric" value={form.transferencia_horas} onChange={(e) => poner('transferencia_horas', e.target.value)} />}
                  </Campo>
                </div>
                <Campo etiqueta="Indicaciones para el cliente (opcional)" error={errores.transferencia_instrucciones} ayuda="Ej.: «Escribe tu número de pedido en el concepto de la transferencia».">
                  {(p) => <textarea {...p} name="transferencia_instrucciones" rows={3} maxLength={600} value={form.transferencia_instrucciones} onChange={(e) => poner('transferencia_instrucciones', e.target.value)} />}
                </Campo>
              </PanelTarjeta>

              {errores._general && !hayErrorDeCampo && (
                <p role="alert" className="campo-error">
                  {errores._general}
                </p>
              )}

              <div className="pagos-pie">
                <button type="submit" className="primario" disabled={!hayCambios || guardar.isPending}>
                  {guardar.isPending ? 'Guardando…' : 'Guardar'}
                </button>
                <button type="button" onClick={probarConexion} disabled={!hayLlaveGuardada || secretaPendiente || probar.isPending}>
                  {probar.isPending ? 'Probando…' : 'Probar conexión'}
                </button>
                {secretaPendiente && hayLlaveGuardada && <small className="celda-suave">Guarda primero para probar con la llave nueva.</small>}
              </div>
              {resultado && (
                <p role="status" className={`pagos-alerta pagos-resultado ${resultado.ok ? 'ok' : 'peligro'}`}>
                  <Icono nombre={resultado.ok ? 'checklist' : 'bell'} tam={18} />
                  <span>{resultado.mensaje}</span>
                </p>
              )}
            </form>
          </>
        )}
      </EstadoConsulta>

      {confirmarProduccion && (
        <ConfirmarModal
          titulo="¿Activar cobros en producción?"
          mensaje="Desde este momento la tienda cobrará dinero real a los clientes con tu cuenta de Culqi. ¿Ya probaste todo en modo Pruebas?"
          textoConfirmar="Sí, activar"
          enviando={guardar.isPending}
          onConfirmar={enviar}
          onCerrar={() => setConfirmarProduccion(false)}
        />
      )}
    </main>
  )
}
