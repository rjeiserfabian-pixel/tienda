'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import { soles } from '@/lib/format'
import { abrirCulqi, claseEstado, estaPagado, fechaCorta, textoEstado } from '@/lib/pago'
import Icono from './Icono'
import { useCuenta } from './Proveedores'

const PASOS = [
  { estado: 'PAGADO', texto: 'Pagado' },
  { estado: 'EN_PREPARACION', texto: 'En preparación' },
  { estado: 'ENVIADO', texto: 'En camino' },
  { estado: 'ENTREGADO', texto: 'Entregado' },
]
const ORDEN = ['PAGADO', 'EN_PREPARACION', 'LISTO_PARA_RECOJO', 'ENVIADO', 'ENTREGADO']
const ESPERA_REFRESCO_MS = 4000
const MAX_REFRESCOS = 12

function useRegresiva(iso, alVencer) {
  const [segundos, setSegundos] = useState(null)
  const avisado = useRef(false)
  useEffect(() => {
    avisado.current = false
    if (!iso) return undefined
    const calcular = () => {
      const s = Math.max(0, Math.floor((new Date(iso).getTime() - Date.now()) / 1000))
      setSegundos(s)
      if (s === 0 && !avisado.current) {
        avisado.current = true
        alVencer?.()
      }
    }
    calcular()
    const id = setInterval(calcular, 1000)
    return () => clearInterval(id)
  }, [iso, alVencer])
  return segundos
}

const formatoTiempo = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

function Progreso({ estado, modalidad }) {
  const actual = ORDEN.indexOf(estado === 'LISTO_PARA_RECOJO' ? 'ENVIADO' : estado)
  if (actual < 0) return null
  return (
    <ol className="ped-progreso" aria-label="Avance del pedido">
      {PASOS.map((p, i) => {
        const texto = p.estado === 'ENVIADO' ? (modalidad === 'RECOJO' ? 'Listo para recoger' : 'En camino') : p.texto
        const hecho = ORDEN.indexOf(p.estado) <= actual
        return (
          <li key={p.estado} className={hecho ? 'hecho' : ''} aria-current={ORDEN.indexOf(p.estado) === actual ? 'step' : undefined}>
            <span className="ped-punto">{hecho ? <Icono nombre="check" tam={14} /> : i + 1}</span>
            {texto}
          </li>
        )
      })}
    </ol>
  )
}

/**
 * Un pedido del cliente: estado, comprobantes, entrega y totales. `gracias` es la pantalla que se
 * ve justo después de pagar (se refresca sola un rato si el pedido aún se está confirmando).
 */
export default function PedidoDetalle({ numero, gracias = false }) {
  const cuenta = useCuenta()
  const [pedido, setPedido] = useState(null)
  const [error, setError] = useState(null)
  const [pagoCfg, setPagoCfg] = useState(null)
  const [tienda, setTienda] = useState(null)
  const [fase, setFase] = useState('libre') // libre | pagando | procesando | cancelando
  const [mensaje, setMensaje] = useState(null)
  const refrescos = useRef(0)
  const cerrar = useRef(null)

  const cargar = useCallback(async () => {
    try {
      setPedido(await llamar(`pedidos/${encodeURIComponent(numero)}`))
      setError(null)
    } catch (e) {
      setError(e instanceof ErrorTienda ? e : new ErrorTienda(0, 'error', 'No pudimos cargar tu pedido.'))
    }
  }, [numero])

  useEffect(() => {
    if (cuenta?.autenticado) cargar()
  }, [cuenta?.autenticado, cargar])

  useEffect(() => {
    llamar('pagos/configuracion').then(setPagoCfg).catch(() => setPagoCfg({ activo: false }))
    llamar('configuracion').then(setTienda).catch(() => {})
    return () => cerrar.current?.()
  }, [])

  // Justo después de pagar: se vuelve a preguntar un rato mientras el pedido se termina de confirmar.
  useEffect(() => {
    if (!gracias || !pedido) return undefined
    const enEspera = pedido.estado === 'PENDIENTE_PAGO' || pedido.estado === 'PAGADO_SIN_COMPROBANTE'
    if (!enEspera || refrescos.current >= MAX_REFRESCOS) return undefined
    const id = setTimeout(() => {
      refrescos.current += 1
      cargar()
    }, ESPERA_REFRESCO_MS)
    return () => clearTimeout(id)
  }, [gracias, pedido, cargar])

  const vigente = pedido?.estado === 'PENDIENTE_PAGO'
  const segundos = useRegresiva(vigente ? pedido?.expira_en : null, cargar)

  async function cobrar(token) {
    setFase('procesando')
    setMensaje(null)
    try {
      await llamar(`pedidos/${encodeURIComponent(numero)}/pagar`, { metodo: 'POST', cuerpo: { token } })
      window.location.assign(`/compra/gracias?pedido=${encodeURIComponent(numero)}`)
    } catch (e) {
      if (e instanceof ErrorTienda && (e.codigo === 'pago_rechazado' || e.codigo === 'correo_sin_confirmar' || e.codigo === 'pago_no_disponible')) {
        setMensaje(e.message)
        setFase('libre')
      } else if (e instanceof ErrorTienda && e.codigo === 'pedido_vencido') {
        setFase('libre')
        cargar()
      } else {
        setMensaje('No pudimos confirmar tu pago. No vuelvas a pagar: si tu banco ya cobró, tu pedido se confirmará solo en unos minutos.')
        setFase('libre')
        cargar()
      }
    }
  }

  async function pagarAhora() {
    if (!pedido || !pagoCfg?.activo) return
    setMensaje(null)
    setFase('pagando')
    try {
      cerrar.current = await abrirCulqi({
        llavePublica: pagoCfg.llave_publica,
        titulo: tienda?.nombre,
        total: pedido.total,
        tarjeta: pagoCfg.tarjeta,
        yape: pagoCfg.yape,
        alToken: cobrar,
        alError: (m) => {
          setMensaje(m)
          setFase('libre')
        },
      })
    } catch {
      setMensaje('No pudimos abrir el formulario de pago. Revisa tu conexión e inténtalo de nuevo.')
      setFase('libre')
    }
  }

  async function cancelar() {
    setFase('cancelando')
    setMensaje(null)
    try {
      setPedido(await llamar(`pedidos/${encodeURIComponent(numero)}/cancelar`, { metodo: 'POST', cuerpo: {} }))
    } catch (e) {
      setMensaje(e instanceof ErrorTienda ? e.message : 'No pudimos cancelar el pedido.')
    } finally {
      setFase('libre')
    }
  }

  if (error && !pedido) {
    return (
      <div className="alerta error" role="alert">
        <Icono nombre="info" tam={18} />
        <span>
          {error.codigo === 'pedido_no_encontrado' ? 'No encontramos ese pedido en tu cuenta.' : error.message}{' '}
          <Link href="/cuenta/pedidos" className="enlace">
            Ver mis pedidos
          </Link>
        </span>
      </div>
    )
  }
  if (!pedido) return <span className="esqueleto" style={{ height: 320, borderRadius: 14 }} aria-busy="true" />

  const e = pedido.entrega ?? {}
  const imp = pedido.importes ?? {}
  const pagado = estaPagado(pedido.estado)
  const esperando = pedido.estado === 'PENDIENTE_PAGO' || pedido.estado === 'PAGADO_SIN_COMPROBANTE'

  return (
    <div className="ped">
      {gracias && (
        <header className="ped-gracias">
          <span className={`ped-check${pagado ? '' : ' espera'}`} aria-hidden="true">
            <Icono nombre={pagado ? 'check' : 'reloj'} tam={30} />
          </span>
          <h1>{pagado ? '¡Gracias por tu compra!' : 'Estamos confirmando tu pedido'}</h1>
          <p className="sub">
            {pagado
              ? pedido.estado === 'PAGADO_SIN_COMPROBANTE'
                ? 'Recibimos tu pago. Estamos emitiendo tu comprobante; en unos minutos lo verás aquí y te llegará por correo.'
                : 'Recibimos tu pago y ya estamos con tu pedido. Te enviamos un correo con el resumen.'
              : 'Esto puede tardar unos segundos. Esta página se actualiza sola; no vuelvas a pagar.'}
          </p>
        </header>
      )}

      <div className="ped-cabecera">
        {!gracias && <h1>Pedido {pedido.numero}</h1>}
        {gracias && <p className="ped-numero">Pedido {pedido.numero}</p>}
        <span className={`insignia ${claseEstado(pedido.estado)}`}>{textoEstado(pedido.estado)}</span>
        <span className="com-chico">{fechaCorta(pedido.creado_en)}</span>
      </div>

      {pedido.estado === 'PAGADO_FUERA_DE_PLAZO' && (
        <p className="alerta aviso" role="status">
          <Icono nombre="info" tam={18} />
          <span>Tu pago llegó cuando el pedido ya había vencido. Nuestro equipo lo está revisando y te contactará pronto.</span>
        </p>
      )}
      {['REEMBOLSO_PENDIENTE', 'REEMBOLSADO_PARCIAL', 'REEMBOLSADO'].includes(pedido.estado) && (
        <div className="alerta" role="status">
          <Icono nombre="info" tam={18} />
          <div>
            {pedido.estado === 'REEMBOLSO_PENDIENTE' ? (
              <p>Estamos devolviendo tu dinero. Te avisaremos por correo apenas esté hecho.</p>
            ) : (
              <p>
                Te devolvimos {soles(pedido.reembolsos?.filter((r) => r.estado === 'APROBADO').reduce((s, r) => s + Number(r.monto), 0) ?? 0)}.
                El dinero vuelve al mismo medio con el que pagaste; cuánto demora en verse depende de tu banco o billetera.
              </p>
            )}
            {pedido.reembolsos?.filter((r) => r.estado === 'APROBADO').map((r, i) => (
              <p key={i} className="com-chico">
                {soles(r.monto)} · {fechaCorta(r.fecha)}
              </p>
            ))}
          </div>
        </div>
      )}
      {esperando && !pagado && !gracias && segundos !== null && (
        <p className="alerta aviso" role="status">
          <Icono nombre="reloj" tam={18} />
          <span>
            Pásalo a pago antes de que venza: <strong>{formatoTiempo(segundos)}</strong>
          </span>
        </p>
      )}
      {(pedido.estado === 'CANCELADO' || pedido.estado === 'EXPIRADO') && (
        <p className="alerta" role="status">
          <Icono nombre="info" tam={18} />
          <span>{pedido.estado === 'CANCELADO' ? 'Cancelaste este pedido.' : 'Este pedido venció sin pago y soltamos los productos.'} Puedes volver a armarlo desde el carrito.</span>
        </p>
      )}
      {mensaje && (
        <p className="alerta error" role="alert">
          <Icono nombre="info" tam={18} /> <span>{mensaje}</span>
        </p>
      )}

      {pagado && pedido.estado !== 'PAGADO_SIN_COMPROBANTE' && pedido.estado !== 'PAGADO_FUERA_DE_PLAZO' && <Progreso estado={pedido.estado} modalidad={pedido.modalidad} />}

      <div className="ped-rejilla">
        <section className="com-paso" aria-labelledby="ped-lineas-t">
          <h2 id="ped-lineas-t">Productos</h2>
          <ul className="ped-lineas">
            {pedido.lineas?.filter((l) => !l.es_envio).map((l, i) => (
              <li key={`${l.producto}-${i}`}>
                <div>
                  <p className="com-linea-nombre">{l.descripcion}</p>
                  <p className="com-chico">
                    {l.cantidad} × {soles(l.precio_unitario)}
                  </p>
                  {Array.isArray(l.series) && l.series.length > 0 && (
                    <p className="com-chico">
                      {l.series.length === 1 ? 'Número de serie' : 'Números de serie'}: <strong>{l.series.join(', ')}</strong>
                    </p>
                  )}
                </div>
                <strong>{soles(l.total)}</strong>
              </li>
            ))}
          </ul>
          <dl className="ped-totales">
            <div>
              <dt>Productos</dt>
              <dd>{soles(imp.subtotal_productos)}</dd>
            </div>
            <div>
              <dt>Envío</dt>
              <dd>{pedido.modalidad === 'RECOJO' ? 'Recojo en tienda' : e.paga_en_destino ? 'Lo pagas al recibir' : Number(imp.costo_envio) === 0 ? 'Gratis' : soles(imp.costo_envio)}</dd>
            </div>
            <div className="com-igv">
              <dt>{imp.igv_exonerado ? 'IGV' : 'IGV incluido'}</dt>
              <dd>{imp.igv_exonerado ? 'Exonerado' : soles(imp.igv)}</dd>
            </div>
            <div className="car-total">
              <dt>Total</dt>
              <dd>{soles(imp.total ?? pedido.total)}</dd>
            </div>
          </dl>
          {imp.igv_exonerado && imp.motivo_igv && <p className="com-chico">{imp.motivo_igv}</p>}
        </section>

        <div className="ped-lado">
          <section className="com-paso" aria-labelledby="ped-entrega-t">
            <h2 id="ped-entrega-t">{pedido.modalidad === 'RECOJO' ? 'Recojo en tienda' : 'Envío a domicilio'}</h2>
            {pedido.modalidad === 'RECOJO' ? (
              <p>
                <strong>{e.punto}</strong>
                <br />
                <span className="com-chico">Te avisaremos por correo cuando esté listo para recoger.</span>
              </p>
            ) : (
              <p>
                <strong>{e.receptor}</strong> · {e.celular}
                <br />
                {e.direccion}, {e.ubicacion}
                {e.referencia ? ` (Ref.: ${e.referencia})` : ''}
                <br />
                <span className="com-chico">
                  {[e.zona, e.plazo].filter(Boolean).join(' · ')}
                  {e.paga_en_destino ? ' · El flete lo pagas a la agencia al recibir.' : ''}
                </span>
                {e.detalle && (
                  <>
                    <br />
                    <span className="com-chico">{e.detalle}</span>
                  </>
                )}
              </p>
            )}
          </section>

          <section className="com-paso" aria-labelledby="ped-comp-t">
            <h2 id="ped-comp-t">Comprobante</h2>
            {pedido.comprobantes?.length > 0 ? (
              <ul className="ped-comprobantes">
                {pedido.comprobantes.map((c) => (
                  <li key={c.numero}>
                    <strong>{c.numero}</strong>
                    <span className="com-chico">{c.empresa}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="com-chico">{pagado ? 'Se está emitiendo.' : 'Se emite cuando se confirme el pago.'}</p>
            )}
            <p className="com-chico">
              {pedido.comprobante?.tipo === '01' ? 'Factura' : 'Boleta'}
              {pedido.comprobante?.documento_numero ? ` · ${pedido.comprobante.documento_tipo} ${pedido.comprobante.documento_numero}` : ''}
              {pedido.comprobante?.nombre ? ` · ${pedido.comprobante.nombre}` : ''}
            </p>
          </section>
        </div>
      </div>

      <div className="form-acciones ped-acciones">
        {pedido.estado === 'PENDIENTE_PAGO' && pagoCfg?.activo && (
          <button type="button" className="boton grande" onClick={pagarAhora} disabled={fase === 'procesando' || fase === 'cancelando'}>
            <Icono nombre="candado" tam={18} /> {fase === 'procesando' ? 'Procesando tu pago…' : `Pagar ahora ${soles(pedido.total)}`}
          </button>
        )}
        {pedido.estado === 'PENDIENTE_PAGO' && (
          <button type="button" className="boton secundario" onClick={cancelar} disabled={fase === 'procesando' || fase === 'cancelando'}>
            {fase === 'cancelando' ? 'Cancelando…' : 'Cancelar pedido'}
          </button>
        )}
        {gracias && (
          <Link href="/cuenta/pedidos" className="boton secundario">
            Ver mis pedidos
          </Link>
        )}
        {gracias ? (
          <Link href="/" className="boton fantasma">
            Seguir comprando
          </Link>
        ) : (
          <Link href="/cuenta/pedidos" className="boton fantasma">
            Volver a mis pedidos
          </Link>
        )}
      </div>

      {fase === 'procesando' && (
        <div className="com-procesando" role="alertdialog" aria-modal="true" aria-labelledby="ped-proc-t">
          <div>
            <span className="com-spinner" aria-hidden="true" />
            <h2 id="ped-proc-t">Procesando tu pago…</h2>
            <p>No cierres ni recargues esta página. Esto toma unos segundos.</p>
          </div>
        </div>
      )}
    </div>
  )
}
