'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import { enlaceWhatsapp, soles, urlFoto } from '@/lib/format'
import { abrirCulqi } from '@/lib/pago'
import ComprobanteForm, { COMPROBANTE_INICIAL, comprobanteParaApi, validarComprobante } from './ComprobanteForm'
import DireccionForm from './cuenta/DireccionForm'
import Icono from './Icono'
import { useCarrito, useCuenta } from './Proveedores'

const CLAVE = 'tienda:compra:v1'
const CLAVE_COMPROBANTE = 'tienda:comprobante:v1'
const CLAVE_PEDIDO = 'tienda:pedido:v1'

function leerSesion(clave) {
  try {
    const dato = JSON.parse(window.sessionStorage.getItem(clave) ?? 'null')
    return dato && typeof dato === 'object' ? dato : null
  } catch {
    return null
  }
}

function guardarSesion(clave, valor) {
  try {
    if (valor === null) window.sessionStorage.removeItem(clave)
    else window.sessionStorage.setItem(clave, JSON.stringify(valor))
  } catch {
    // sin almacenamiento: solo dura mientras la página esté abierta
  }
}

/** Clave única por pedido: así un reintento del navegador no crea dos pedidos. */
function nuevaClave() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  const hex = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join('')
  return `${hex(8)}-${hex(4)}-4${hex(3)}-a${hex(3)}-${hex(12)}`
}

function leerEleccion() {
  try {
    const dato = JSON.parse(window.sessionStorage.getItem(CLAVE) ?? '{}')
    return dato && typeof dato === 'object' ? dato : {}
  } catch {
    return {}
  }
}

function guardarEleccion(valor) {
  try {
    window.sessionStorage.setItem(CLAVE, JSON.stringify(valor))
  } catch {
    // sin almacenamiento: la elección solo dura mientras la página esté abierta
  }
}

/** Texto del pedido para enviarlo por WhatsApp mientras el pago en línea no está activo. */
function mensajePedido({ nombreTienda, cot, direccion, entrega }) {
  const lineas = cot.lineas.map((l) => `• ${l.cantidad} × ${l.nombre} — ${soles(l.subtotal)}`)
  const envio =
    entrega.modalidad === 'ENVIO'
      ? entrega.envio?.paga_en_destino
        ? 'Envío por agencia (el flete se paga al recibir)'
        : `Envío a domicilio: ${Number(cot.costo_envio) === 0 ? 'gratis' : soles(cot.costo_envio)}`
      : 'Recojo en tienda'
  const donde =
    entrega.modalidad === 'ENVIO' && direccion
      ? [
          `Entregar a: ${direccion.receptor} · ${direccion.celular}`,
          `${direccion.direccion}, ${direccion.ubicacion}${direccion.referencia ? ` (Ref.: ${direccion.referencia})` : ''}`,
        ]
      : entrega.punto
        ? [`Recojo en: ${entrega.punto.nombre} — ${entrega.punto.direccion}`]
        : []
  return [
    `Hola, quiero hacer este pedido en ${nombreTienda}:`,
    ...lineas,
    '',
    `Subtotal: ${soles(cot.subtotal)}`,
    envio,
    `Total: ${soles(cot.total)}`,
    ...(cot.nota_pago ? [cot.nota_pago] : []),
    '',
    ...donde,
  ].join('\n')
}

function Cargando() {
  return (
    <div className="com-rejilla" aria-busy="true" aria-label="Cargando">
      <div className="com-pasos">
        <span className="esqueleto" style={{ height: 160, borderRadius: 14 }} />
        <span className="esqueleto" style={{ height: 160, borderRadius: 14 }} />
      </div>
      <span className="esqueleto" style={{ height: 260, borderRadius: 14 }} />
    </div>
  )
}

function SinSesion() {
  const volver = encodeURIComponent('/compra')
  return (
    <section className="tarjeta-centrada" aria-labelledby="com-sin-t">
      <h1 id="com-sin-t">Ingresa o crea tu cuenta para terminar tu compra</h1>
      <p className="sub">Tu carrito se conserva. Con tu cuenta guardamos tus direcciones y puedes volver a comprar más rápido.</p>
      <div className="form-acciones" style={{ display: 'grid' }}>
        <Link href={`/cuenta/ingresar?volver=${volver}`} className="boton grande">
          Ingresar
        </Link>
        <Link href={`/cuenta/registro?volver=${volver}`} className="boton secundario grande">
          Crear mi cuenta
        </Link>
      </div>
      <p className="pie-tarjeta">
        <Link href="/carrito" className="enlace">
          Volver al carrito
        </Link>
      </p>
    </section>
  )
}

function CarritoVacio() {
  return (
    <section className="tarjeta-centrada" aria-labelledby="com-vacio-t">
      <h1 id="com-vacio-t">Tu carrito está vacío</h1>
      <p className="sub">Agrega productos para continuar con tu compra.</p>
      <Link href="/buscar?nuevo=1" className="boton grande">
        Ver novedades
      </Link>
    </section>
  )
}

function AvisoCorreo({ recargar }) {
  const [estado, setEstado] = useState(null) // null | enviando | enviado | error
  async function reenviar() {
    setEstado('enviando')
    try {
      await llamar('cuenta/reenviar-verificacion', { metodo: 'POST', cuerpo: {} })
      setEstado('enviado')
    } catch {
      setEstado('error')
    }
  }
  return (
    <div className="alerta aviso" role="status">
      <Icono nombre="info" tam={18} />
      <div className="com-correo">
        <p>
          <strong>Confirma tu correo para poder pagar.</strong> Te enviamos un enlace; revisa también la carpeta de spam.
        </p>
        <div className="com-correo-botones">
          <button type="button" className="boton chico secundario" onClick={reenviar} disabled={estado === 'enviando' || estado === 'enviado'}>
            {estado === 'enviando' ? 'Enviando…' : estado === 'enviado' ? 'Correo enviado' : 'Reenviar correo'}
          </button>
          <button type="button" className="boton chico fantasma" onClick={recargar}>
            Ya lo confirmé
          </button>
        </div>
        {estado === 'error' && <p className="campo-error">No pudimos enviarlo ahora. Inténtalo en unos minutos.</p>}
      </div>
    </div>
  )
}

export default function CompraVista() {
  const cuenta = useCuenta()
  const router = useRouter()
  const { items, listo, vaciar } = useCarrito()
  const [direcciones, setDirecciones] = useState(null)
  const [modalidad, setModalidad] = useState(null)
  const [direccionId, setDireccionId] = useState(null)
  const [puntoId, setPuntoId] = useState(null)
  const [agregando, setAgregando] = useState(false)
  const [cot, setCot] = useState(null)
  const [errorCot, setErrorCot] = useState(null)
  const [cargandoCot, setCargandoCot] = useState(false)
  const [config, setConfig] = useState(null)
  const [intento, setIntento] = useState(0)
  const [pagoCfg, setPagoCfg] = useState(null) // /pagos/configuracion (null = cargando)
  const [comp, setComp] = useState(COMPROBANTE_INICIAL)
  const [erroresComp, setErroresComp] = useState({})
  const [fase, setFase] = useState('libre') // libre | creando | pagando | procesando | incierto | vencido
  const [mensajePago, setMensajePago] = useState(null)
  const [numeroPedido, setNumeroPedido] = useState(null)
  const cerrarCulqi = useRef(null)

  // Elección guardada y datos fijos
  useEffect(() => {
    const e = leerEleccion()
    setModalidad(e.modalidad ?? null)
    setDireccionId(e.direccion ?? null)
    setPuntoId(e.punto ?? null)
    llamar('configuracion')
      .then(setConfig)
      .catch(() => {})
    llamar('pagos/configuracion')
      .then(setPagoCfg)
      .catch(() => setPagoCfg({ activo: false }))
    const guardado = leerSesion(CLAVE_COMPROBANTE)
    if (guardado) setComp({ ...COMPROBANTE_INICIAL, ...guardado })
  }, [])

  // Los datos del comprobante se recuerdan mientras dure la visita (no se guardan en el equipo).
  useEffect(() => {
    guardarSesion(CLAVE_COMPROBANTE, comp)
  }, [comp])

  // El nombre de la boleta se propone con el de la cuenta.
  useEffect(() => {
    const nombre = [cuenta?.perfil?.nombres, cuenta?.perfil?.apellidos].filter(Boolean).join(' ')
    if (nombre) setComp((c) => (c.nombre ? c : { ...c, nombre }))
  }, [cuenta?.perfil?.nombres, cuenta?.perfil?.apellidos])

  // Mientras se procesa el pago, el navegador avisa antes de cerrar o recargar la página.
  useEffect(() => {
    if (fase !== 'procesando') return undefined
    const avisar = (e) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', avisar)
    return () => window.removeEventListener('beforeunload', avisar)
  }, [fase])

  useEffect(() => () => cerrarCulqi.current?.(), [])

  useEffect(() => {
    if (!cuenta?.autenticado) return
    llamar('cuenta/direcciones')
      .then((lista) => {
        setDirecciones(lista)
        setAgregando(lista.length === 0)
      })
      .catch(() => setDirecciones([]))
  }, [cuenta?.autenticado])

  // Dirección por defecto: la guardada en esta sesión, si no la principal, si no la primera.
  useEffect(() => {
    if (!direcciones || direcciones.length === 0) return
    setDireccionId((actual) => {
      if (direcciones.some((d) => d.id === actual)) return actual
      return (direcciones.find((d) => d.es_principal) ?? direcciones[0]).id
    })
  }, [direcciones])

  // Cotización: el servidor decide precios, envío y disponibilidad.
  useEffect(() => {
    if (!cuenta?.autenticado || !listo || items.length === 0) return undefined
    const control = new AbortController()
    setCargandoCot(true)
    const espera = setTimeout(async () => {
      const cuerpo = { lineas: items }
      if (modalidad === 'ENVIO' && direccionId) {
        cuerpo.modalidad = 'ENVIO'
        cuerpo.direccion = direccionId
      } else if (modalidad === 'RECOJO') {
        cuerpo.modalidad = 'RECOJO'
        if (puntoId) cuerpo.punto = puntoId
      }
      try {
        const datos = await llamar('compra/cotizar', { metodo: 'POST', cuerpo, signal: control.signal })
        setCot(datos)
        setErrorCot(null)
      } catch (error) {
        if (error?.name === 'AbortError') return
        setErrorCot(error instanceof ErrorTienda ? error : new ErrorTienda(0, 'error', 'No pudimos calcular tu pedido.'))
      } finally {
        if (!control.signal.aborted) setCargandoCot(false)
      }
    }, 200)
    return () => {
      clearTimeout(espera)
      control.abort()
    }
  }, [cuenta?.autenticado, listo, items, modalidad, direccionId, puntoId, intento])

  const opciones = cot?.entrega?.opciones
  // Modalidad por defecto cuando se sabe qué ofrece la tienda.
  useEffect(() => {
    if (!opciones) return
    setModalidad((actual) => {
      if (actual === 'ENVIO' && opciones.envio) return actual
      if (actual === 'RECOJO' && opciones.recojo) return actual
      return opciones.envio ? 'ENVIO' : opciones.recojo ? 'RECOJO' : null
    })
  }, [opciones])

  // Con un solo punto de recojo disponible se elige solo.
  useEffect(() => {
    const puntos = cot?.entrega?.puntos
    if (modalidad !== 'RECOJO' || !puntos) return
    const disponibles = puntos.filter((p) => p.disponible)
    if (disponibles.length === 1 && puntoId !== disponibles[0].id) setPuntoId(disponibles[0].id)
    else if (puntoId && !disponibles.some((p) => p.id === puntoId)) setPuntoId(null)
  }, [cot, modalidad, puntoId])

  useEffect(() => {
    if (modalidad) guardarEleccion({ modalidad, direccion: direccionId, punto: puntoId })
  }, [modalidad, direccionId, puntoId])

  const recargarPerfil = useCallback(() => cuenta?.recargar(), [cuenta])

  const direccion = useMemo(() => direcciones?.find((d) => d.id === direccionId) ?? null, [direcciones, direccionId])

  // --------------------------------------------------------------- pantallas previas
  if (!listo || cuenta?.estado === 'cargando') return <Cargando />
  if (items.length === 0) return <CarritoVacio />
  if (!cuenta.autenticado) return <SinSesion />

  const entrega = cot?.entrega
  const envio = entrega?.envio
  const tot = cot?.totales ?? null
  const totalPagar = tot?.total ?? cot?.total
  const pagoActivo = pagoCfg?.activo === true
  const correoOk = cuenta.perfil?.correo_verificado !== false
  const ocupado = fase === 'creando' || fase === 'procesando'

  /** Cobra el pedido con el token de Culqi y deja la pantalla en el estado que corresponda. */
  async function cobrar(numero, token) {
    setFase('procesando')
    setMensajePago(null)
    try {
      await llamar(`pedidos/${numero}/pagar`, { metodo: 'POST', cuerpo: { token } })
      guardarSesion(CLAVE_PEDIDO, null)
      vaciar()
      router.push(`/compra/gracias?pedido=${encodeURIComponent(numero)}`)
    } catch (error) {
      if (error instanceof ErrorTienda && error.codigo === 'pago_rechazado') {
        setFase('libre')
        setMensajePago(error.message)
      } else if (error instanceof ErrorTienda && error.codigo === 'pedido_vencido') {
        guardarSesion(CLAVE_PEDIDO, null)
        setFase('vencido')
      } else if (error instanceof ErrorTienda && ['correo_sin_confirmar', 'pago_no_disponible', 'sesion_no_valida'].includes(error.codigo)) {
        setFase('libre')
        setMensajePago(error.message)
      } else {
        // Sin respuesta clara: el cobro pudo haberse hecho. No se deja pagar de nuevo.
        setFase('incierto')
      }
    }
  }

  /** Crea el pedido (o reutiliza el mismo si nada cambió) y abre el formulario de pago de Culqi. */
  async function iniciarPago() {
    setMensajePago(null)
    const errores = validarComprobante(comp)
    setErroresComp(errores)
    if (Object.keys(errores).length > 0) {
      setMensajePago('Revisa los datos de tu comprobante.')
      document.getElementById('com-comprobante-t')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
    if (!cot?.puede_continuar || !tot || !modalidad) return
    setFase('creando')
    try {
      const cuerpo = {
        lineas: items,
        modalidad,
        ...(modalidad === 'ENVIO' ? { direccion: direccionId } : { punto: puntoId }),
        comprobante: comprobanteParaApi(comp),
      }
      const firma = JSON.stringify(cuerpo)
      let ref = leerSesion(CLAVE_PEDIDO)
      if (!ref || ref.firma !== firma) {
        // Cambió algo: el pedido anterior sin pagar se cancela para soltar su stock.
        if (ref?.numero) llamar(`pedidos/${ref.numero}/cancelar`, { metodo: 'POST', cuerpo: {} }).catch(() => {})
        ref = { clave: nuevaClave(), firma }
      }
      const pedido = await llamar('pedidos', { metodo: 'POST', cuerpo: { ...cuerpo, clave_idempotencia: ref.clave } })
      guardarSesion(CLAVE_PEDIDO, { ...ref, numero: pedido.numero })
      setNumeroPedido(pedido.numero)
      cerrarCulqi.current = await abrirCulqi({
        llavePublica: pagoCfg.llave_publica,
        titulo: nombreTienda,
        total: pedido.total,
        tarjeta: pagoCfg.tarjeta,
        yape: pagoCfg.yape,
        alToken: (token) => cobrar(pedido.numero, token),
        alError: (mensaje) => {
          setFase('libre')
          setMensajePago(mensaje)
        },
      })
      setFase('pagando')
    } catch (error) {
      setFase('libre')
      if (error instanceof ErrorTienda) {
        setMensajePago(error.message)
        if (error.codigo === 'correo_sin_confirmar') cuenta.recargar()
      } else {
        setMensajePago('No pudimos abrir el formulario de pago. Revisa tu conexión (o desactiva el bloqueador de anuncios) e inténtalo de nuevo.')
      }
    }
  }
  const nombreTienda = config?.nombre ?? 'la tienda'
  const whatsapp = cot && entrega?.valida && cot.puede_continuar ? enlaceWhatsapp(mensajePedido({ nombreTienda, cot, direccion, entrega }), config?.contacto?.whatsapp) : null
  const sinOpciones = opciones && !opciones.envio && !opciones.recojo

  if (fase === 'incierto') {
    return (
      <section className="tarjeta-centrada" aria-labelledby="com-inc-t" role="status">
        <h1 id="com-inc-t">Estamos confirmando tu pago</h1>
        <p className="sub">
          No pudimos confirmar el resultado en este momento. <strong>No vuelvas a pagar</strong>: si tu banco ya cobró, tu pedido se confirmará solo en unos minutos y te
          enviaremos un correo.
        </p>
        <div className="form-acciones" style={{ display: 'grid' }}>
          <Link href={numeroPedido ? `/cuenta/pedidos/${numeroPedido}` : '/cuenta/pedidos'} className="boton grande">
            Ver mi pedido
          </Link>
          <Link href="/cuenta/pedidos" className="boton secundario grande">
            Mis pedidos
          </Link>
        </div>
      </section>
    )
  }
  if (fase === 'vencido') {
    return (
      <section className="tarjeta-centrada" aria-labelledby="com-ven-t" role="alert">
        <h1 id="com-ven-t">Tu pedido venció</h1>
        <p className="sub">Pasó el tiempo para pagarlo y soltamos tus productos. Tu carrito sigue ahí: puedes intentarlo de nuevo.</p>
        <Link href="/carrito" className="boton grande" onClick={() => setFase('libre')}>
          Volver al carrito
        </Link>
      </section>
    )
  }

  const textoEnvio = !cot
    ? '…'
    : entrega?.modalidad === 'ENVIO' && envio?.disponible
      ? envio.paga_en_destino
        ? 'Lo pagas al recibir'
        : envio.gratis
          ? 'Gratis'
          : soles(tot?.costo_envio ?? cot.costo_envio)
      : entrega?.modalidad === 'RECOJO'
        ? 'Gratis (recojo)'
        : 'Elige cómo recibirlo'

  return (
    <>
      <h1 className="titulo-pagina">Terminar mi compra</h1>
      {cuenta.perfil && !cuenta.perfil.correo_verificado && <AvisoCorreo recargar={recargarPerfil} />}
      {errorCot && (
        <p className="alerta error" role="alert">
          <Icono nombre="info" tam={18} />
          <span>
            {errorCot.message}{' '}
            <button type="button" className="enlace" onClick={() => setIntento((n) => n + 1)}>
              Reintentar
            </button>
          </span>
        </p>
      )}
      <div className="com-rejilla">
        <div className="com-pasos">
          <section className="com-paso" aria-labelledby="com-entrega-t">
            <h2 id="com-entrega-t">
              <span className="com-num">1</span> ¿Cómo quieres recibirlo?
            </h2>
            {sinOpciones && <p className="alerta aviso">Por ahora la tienda no tiene formas de entrega activas. Escríbenos por WhatsApp.</p>}
            <div className="com-modalidades" role="radiogroup" aria-labelledby="com-entrega-t">
              {(!opciones || opciones.envio) && (
                <label className={`com-opcion${modalidad === 'ENVIO' ? ' activa' : ''}`}>
                  <input type="radio" name="modalidad" value="ENVIO" checked={modalidad === 'ENVIO'} onChange={() => setModalidad('ENVIO')} />
                  <Icono nombre="camion" tam={22} />
                  <span>
                    <strong>Envío a domicilio</strong>
                    <small>Te lo llevamos a tu dirección</small>
                  </span>
                </label>
              )}
              {(!opciones || opciones.recojo) && (
                <label className={`com-opcion${modalidad === 'RECOJO' ? ' activa' : ''}`}>
                  <input type="radio" name="modalidad" value="RECOJO" checked={modalidad === 'RECOJO'} onChange={() => setModalidad('RECOJO')} />
                  <Icono nombre="tienda" tam={22} />
                  <span>
                    <strong>Recojo en tienda</strong>
                    <small>Sin costo, cuando esté listo</small>
                  </span>
                </label>
              )}
            </div>

            {modalidad === 'ENVIO' && (
              <div className="com-detalle">
                <h3>Dirección de entrega</h3>
                {!direcciones && <span className="esqueleto" style={{ height: 80, borderRadius: 12 }} />}
                {direcciones && direcciones.length > 0 && (
                  <ul className="com-direcciones" role="radiogroup" aria-label="Direcciones guardadas">
                    {direcciones.map((d) => (
                      <li key={d.id}>
                        <label className={`com-opcion chica${direccionId === d.id ? ' activa' : ''}`}>
                          <input type="radio" name="direccion" checked={direccionId === d.id} onChange={() => setDireccionId(d.id)} />
                          <Icono nombre="pin" tam={20} />
                          <span>
                            <strong>
                              {d.etiqueta || d.receptor}
                              {d.es_principal && <em className="com-principal">Principal</em>}
                            </strong>
                            <small>
                              {d.direccion}, {d.ubicacion}
                            </small>
                            <small>
                              {d.receptor} · {d.celular}
                            </small>
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
                {direcciones &&
                  (agregando ? (
                    <div className="com-nueva">
                      <h4>{direcciones.length === 0 ? 'Agrega tu dirección de entrega' : 'Nueva dirección'}</h4>
                      <DireccionForm
                        nombreSugerido={[cuenta.perfil?.nombres, cuenta.perfil?.apellidos].filter(Boolean).join(' ')}
                        celularSugerido={cuenta.perfil?.celular ?? ''}
                        alGuardar={(lista) => {
                          const antes = new Set((direcciones ?? []).map((d) => d.id))
                          const nueva = lista.find((d) => !antes.has(d.id)) ?? lista.find((d) => d.es_principal)
                          setDirecciones(lista)
                          if (nueva) setDireccionId(nueva.id)
                          setAgregando(false)
                        }}
                        alCancelar={direcciones.length > 0 ? () => setAgregando(false) : undefined}
                      />
                    </div>
                  ) : (
                    <button type="button" className="boton secundario chico" onClick={() => setAgregando(true)}>
                      <Icono nombre="mas" tam={16} /> Agregar otra dirección
                    </button>
                  ))}

                {direccion && envio && (
                  <div className={`com-envio${envio.disponible ? '' : ' sin'}`} role="status" aria-live="polite">
                    {envio.disponible ? (
                      <>
                        <p>
                          <strong>{envio.zona?.nombre}</strong>
                          {envio.plazo && <span> · {envio.plazo}</span>}
                        </p>
                        <p className="com-envio-costo">
                          {envio.paga_en_destino ? 'Flete por pagar al recibir' : envio.gratis ? 'Envío gratis' : `Envío: ${soles(cot.costo_envio)}`}
                        </p>
                        {envio.detalle && <p className="com-chico">{envio.detalle}</p>}
                        {cot.nota_pago && (
                          <p className="alerta aviso">
                            <Icono nombre="info" tam={16} /> <span>{cot.nota_pago}</span>
                          </p>
                        )}
                      </>
                    ) : (
                      <>
                        <p className="alerta aviso">
                          <Icono nombre="info" tam={16} /> <span>{envio.motivo}</span>
                        </p>
                        {opciones?.recojo && (
                          <button type="button" className="boton secundario chico" onClick={() => setModalidad('RECOJO')}>
                            Recoger en tienda
                          </button>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {modalidad === 'RECOJO' && (
              <div className="com-detalle">
                <h3>¿En qué tienda lo recoges?</h3>
                {!entrega?.puntos && <span className="esqueleto" style={{ height: 80, borderRadius: 12 }} />}
                {entrega?.puntos?.length === 0 && <p className="alerta aviso">{entrega.motivo ?? 'No hay tiendas disponibles para recoger por ahora.'}</p>}
                {entrega?.puntos?.length > 0 && (
                  <ul className="com-direcciones" role="radiogroup" aria-label="Tiendas">
                    {entrega.puntos.map((p) => (
                      <li key={p.id}>
                        <label className={`com-opcion chica${puntoId === p.id ? ' activa' : ''}${p.disponible ? '' : ' apagada'}`}>
                          <input type="radio" name="punto" checked={puntoId === p.id} disabled={!p.disponible} onChange={() => setPuntoId(p.id)} />
                          <Icono nombre="tienda" tam={20} />
                          <span>
                            <strong>{p.nombre}</strong>
                            <small>{p.direccion}</small>
                            {p.horario && <small>Horario: {p.horario}</small>}
                            {p.listo_en && <small>{p.listo_en}</small>}
                            {p.indicaciones && <small>{p.indicaciones}</small>}
                            {!p.disponible && <small className="com-no-disp">No tiene todo tu pedido</small>}
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
                {entrega?.puntos?.length > 0 && !puntoId && entrega.motivo && <p className="com-chico">{entrega.motivo}</p>}
              </div>
            )}
          </section>

          <section className="com-paso" aria-labelledby="com-comprobante-t">
            <h2 id="com-comprobante-t">
              <span className="com-num">2</span> Datos para tu comprobante
            </h2>
            <ComprobanteForm valor={comp} onChange={setComp} errores={erroresComp} deshabilitado={ocupado} />
          </section>

          <section className="com-paso" aria-labelledby="com-pago-t">
            <h2 id="com-pago-t">
              <span className="com-num">3</span> Pago
            </h2>
            {pagoCfg === null && <span className="esqueleto" style={{ height: 56, borderRadius: 12 }} />}
            {pagoCfg && pagoActivo && (
              <p className="alerta" role="note">
                <Icono nombre="candado" tam={18} />
                <span>
                  Pagas de forma segura con{' '}
                  {[pagoCfg.tarjeta && 'tarjeta', pagoCfg.yape && 'Yape'].filter(Boolean).join(' o ')}. Tus datos de pago los recibe Culqi directamente: esta tienda nunca los ve ni los guarda.
                </span>
              </p>
            )}
            {pagoCfg && !pagoActivo && (
              <p className="alerta aviso" role="note">
                <Icono nombre="info" tam={18} />
                <span>El pago en línea estará disponible pronto. Mientras tanto puedes enviarnos tu pedido por WhatsApp y lo coordinamos.</span>
              </p>
            )}
          </section>
        </div>

        <aside className="com-resumen" aria-label="Resumen de tu pedido" aria-busy={cargandoCot}>
          <h2>Tu pedido</h2>
          {cot ? (
            <>
              <ul className="com-lineas">
                {cot.lineas.map((l) => (
                  <li key={l.producto}>
                    {l.foto ? <img src={urlFoto(l.foto)} alt="" width={48} height={48} loading="lazy" /> : <span className="com-sin-foto" />}
                    <div>
                      <p className="com-linea-nombre">{l.nombre}</p>
                      <p className="com-chico">
                        {l.cantidad} × {soles(l.precio_unitario) ?? '—'}
                      </p>
                      {l.problema && <p className="com-no-disp">{l.problema}</p>}
                    </div>
                    <strong>{soles(l.subtotal) ?? '—'}</strong>
                  </li>
                ))}
              </ul>
              <dl>
                <div>
                  <dt>Productos</dt>
                  <dd>{soles(tot?.subtotal_productos ?? cot.subtotal)}</dd>
                </div>
                <div>
                  <dt>Envío</dt>
                  <dd>{textoEnvio}</dd>
                </div>
                {tot && (
                  <div className="com-igv">
                    <dt>{tot.igv_exonerado ? 'IGV' : 'IGV incluido'}</dt>
                    <dd>{tot.igv_exonerado ? 'Exonerado' : soles(tot.igv)}</dd>
                  </div>
                )}
                <div className="car-total">
                  <dt>Total a pagar</dt>
                  <dd>{soles(totalPagar)}</dd>
                </div>
              </dl>
              {tot?.igv_exonerado && (
                <p className="alerta ok" role="note">
                  <Icono nombre="info" tam={16} />
                  <span>Exonerado de IGV por la zona de entrega (Amazonía). Por eso el total puede ser menor al precio que viste en el catálogo.</span>
                </p>
              )}
              {tot?.por_empresa?.length > 1 && (
                <p className="com-chico">
                  Recibirás {tot.por_empresa.length} comprobantes, uno por cada empresa que vende tus productos:{' '}
                  {tot.por_empresa.map((e) => `${e.razon_social} (${soles(e.total)})`).join(' y ')}.
                </p>
              )}
              {cot.totales_error && (
                <p className="alerta aviso" role="alert">
                  <Icono nombre="info" tam={16} /> <span>{cot.totales_error}</span>
                </p>
              )}
              {cot.nota_pago && <p className="com-chico">{cot.nota_pago}</p>}
              {cot.problemas > 0 && (
                <p className="alerta aviso" role="alert">
                  <Icono nombre="info" tam={16} />{' '}
                  <span>
                    Hay productos con avisos. <Link href="/carrito" className="enlace">Revisa tu carrito</Link>.
                  </span>
                </p>
              )}
            </>
          ) : (
            <span className="esqueleto" style={{ height: 180, borderRadius: 12 }} />
          )}
          {pagoActivo && (
            <>
              {mensajePago && (
                <p className="alerta error" role="alert">
                  <Icono nombre="info" tam={16} /> <span>{mensajePago}</span>
                </p>
              )}
              <button
                type="button"
                className="boton grande"
                onClick={iniciarPago}
                disabled={ocupado || !cot?.puede_continuar || !tot || !correoOk || cargandoCot}
              >
                <Icono nombre="candado" tam={18} />{' '}
                {fase === 'creando' ? 'Preparando tu pedido…' : fase === 'procesando' ? 'Procesando tu pago…' : `Pagar ${soles(totalPagar) ?? ''}`}
              </button>
              {!correoOk && <p className="com-chico com-centrado">Confirma tu correo para poder pagar.</p>}
              {correoOk && cot && !cot.puede_continuar && <p className="com-chico com-centrado">{cot.problemas > 0 ? 'Revisa los avisos de tu carrito.' : (entrega?.motivo ?? 'Elige cómo quieres recibir tu pedido.')}</p>}
            </>
          )}
          {whatsapp && !pagoActivo && (
            <a className="boton whatsapp grande" href={whatsapp} target="_blank" rel="noopener noreferrer">
              <Icono nombre="chat" tam={20} /> Enviar mi pedido por WhatsApp
            </a>
          )}
          <Link href="/carrito" className="boton fantasma">
            Volver al carrito
          </Link>
        </aside>
      </div>
      {fase === 'procesando' && (
        <div className="com-procesando" role="alertdialog" aria-modal="true" aria-labelledby="com-proc-t" aria-describedby="com-proc-d">
          <div>
            <span className="com-spinner" aria-hidden="true" />
            <h2 id="com-proc-t">Procesando tu pago…</h2>
            <p id="com-proc-d">No cierres ni recargues esta página. Esto toma unos segundos.</p>
          </div>
        </div>
      )}
    </>
  )
}
