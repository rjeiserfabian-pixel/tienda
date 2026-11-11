'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import { soles, textoDisponibilidad, urlFoto } from '@/lib/format'
import Icono from './Icono'
import { useCarrito } from './Proveedores'

const CLAVE_LOCAL = 'tienda:armado:v1'
const MAX_PARAM = 30
const ESPERA_MS = 250

/** «12:1,15:2» → [{producto: 12, cantidad: 1}, …] solo con enteros válidos (el servidor valida otra vez). */
function leerParametro(texto) {
  const filas = []
  for (const trozo of String(texto || '').split(',').slice(0, MAX_PARAM)) {
    const [p, c = '1'] = trozo.split(':')
    const producto = Number(p)
    const cantidad = Number(c)
    if (Number.isInteger(producto) && producto > 0 && Number.isInteger(cantidad) && cantidad > 0 && cantidad <= 99) {
      filas.push({ producto, cantidad })
    }
  }
  return filas
}

const aTexto = (elegidos) => elegidos.map((e) => `${e.producto}:${e.cantidad}`).join(',')

function leerLocal() {
  try {
    const crudo = window.localStorage.getItem(CLAVE_LOCAL)
    return crudo ? leerParametro(crudo) : []
  } catch {
    return []
  }
}

function guardarLocal(elegidos) {
  try {
    if (elegidos.length) window.localStorage.setItem(CLAVE_LOCAL, aTexto(elegidos))
    else window.localStorage.removeItem(CLAVE_LOCAL)
  } catch {
    // modo privado: el armado sigue funcionando mientras la página esté abierta
  }
}

const TEXTO_ESTADO = {
  COMPATIBLE: 'Compatible con lo que elegiste',
  NO_VERIFICABLE: 'No pudimos verificar la compatibilidad',
  INCOMPATIBLE: 'No encaja con lo que elegiste',
}

/**
 * Armador guiado de PC. El servidor decide qué es compatible (con las especificaciones de cada
 * producto) y cuánto cuesta; aquí solo se elige, se muestra y se agrega al carrito.
 */
export default function ArmadorVista({ config }) {
  const carrito = useCarrito()
  const espacios = config.espacios
  const [elegidos, setElegidos] = useState([]) // [{ producto, cantidad, espacio }]
  const [info, setInfo] = useState({}) // id → { nombre, foto, marca, precio }
  const [resumen, setResumen] = useState(null)
  const [listo, setListo] = useState(false)
  const [activo, setActivo] = useState(espacios[0]?.clave)
  const [todas, setTodas] = useState(false)
  const [opciones, setOpciones] = useState({ cargando: true, filas: [], pagina: 1, paginas: 1, error: null })
  const [mensaje, setMensaje] = useState(null)
  const [agregado, setAgregado] = useState(false)
  const definicion = useMemo(() => Object.fromEntries(espacios.map((e) => [e.clave, e])), [espacios])

  // Al entrar: el armado del enlace (?p=) o el último guardado en este equipo.
  useEffect(() => {
    let vigente = true
    const delEnlace = leerParametro(new URLSearchParams(window.location.search).get('p'))
    const inicial = delEnlace.length ? delEnlace : leerLocal()
    if (!inicial.length) {
      setListo(true)
      return undefined
    }
    llamar('armador/validar', { metodo: 'POST', cuerpo: { lineas: inicial } })
      .then((r) => {
        if (!vigente) return
        setElegidos(r.lineas.filter((l) => l.espacio).map((l) => ({ producto: l.producto, cantidad: l.cantidad, espacio: l.espacio })))
        setInfo(Object.fromEntries(r.lineas.map((l) => [l.producto, { nombre: l.nombre, foto: l.foto, marca: l.marca, precio: l.precio_unitario }])))
        setResumen(r)
      })
      .catch(() => {})
      .finally(() => vigente && setListo(true))
    return () => {
      vigente = false
    }
  }, [])

  const texto = useMemo(() => aTexto(elegidos), [elegidos])

  // Compatibilidad, faltantes y total: siempre del servidor.
  useEffect(() => {
    if (!listo) return undefined
    guardarLocal(elegidos)
    if (!elegidos.length) {
      setResumen(null)
      return undefined
    }
    const control = new AbortController()
    const espera = setTimeout(async () => {
      try {
        const r = await llamar('armador/validar', {
          metodo: 'POST',
          cuerpo: { lineas: elegidos.map(({ producto, cantidad }) => ({ producto, cantidad })) },
          signal: control.signal,
        })
        setResumen(r)
        if (r.quitados?.length) setElegidos((a) => a.filter((e) => !r.quitados.includes(e.producto)))
      } catch (error) {
        if (error?.name !== 'AbortError') setMensaje(error instanceof ErrorTienda ? error.message : 'No pudimos revisar tu armado.')
      }
    }, ESPERA_MS)
    return () => {
      clearTimeout(espera)
      control.abort()
    }
    // `texto` representa a `elegidos`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [texto, listo])

  // Opciones del paso activo, marcadas según lo ya elegido.
  const cargarOpciones = useCallback(
    async (pagina, reemplazar, signal) => {
      try {
        const q = new URLSearchParams({ espacio: activo, page: String(pagina), page_size: '12' })
        if (texto) q.set('p', texto)
        if (todas) q.set('todas', '1')
        const r = await llamar(`armador/opciones?${q}`, { signal })
        setOpciones((o) => ({
          cargando: false,
          filas: reemplazar ? r.results : [...o.filas, ...r.results],
          pagina: r.page,
          paginas: r.paginas,
          total: r.count,
          error: null,
        }))
      } catch (error) {
        if (error?.name === 'AbortError') return
        setOpciones((o) => ({ ...o, cargando: false, error: error instanceof ErrorTienda ? error.message : 'No pudimos cargar las piezas.' }))
      }
    },
    [activo, texto, todas],
  )

  useEffect(() => {
    if (!listo || !activo) return undefined
    const control = new AbortController()
    setOpciones((o) => ({ ...o, cargando: true }))
    cargarOpciones(1, true, control.signal)
    return () => control.abort()
  }, [cargarOpciones, listo, activo])

  const elegir = (tarjeta, espacio) => {
    const def = definicion[espacio]
    setAgregado(false)
    setMensaje(null)
    setInfo((i) => ({ ...i, [tarjeta.id]: { nombre: tarjeta.nombre, foto: tarjeta.foto, marca: tarjeta.marca?.nombre, precio: tarjeta.precio_mostrar } }))
    setElegidos((actual) => {
      if (def.max_unidades === 1) return [...actual.filter((e) => e.espacio !== espacio), { producto: tarjeta.id, cantidad: 1, espacio }]
      const del = actual.filter((e) => e.espacio === espacio)
      const unidades = del.reduce((s, e) => s + e.cantidad, 0)
      if (unidades >= def.max_unidades) {
        setMensaje(`En «${def.nombre}» puedes elegir hasta ${def.max_unidades} unidades.`)
        return actual
      }
      const existente = actual.find((e) => e.producto === tarjeta.id)
      return existente
        ? actual.map((e) => (e.producto === tarjeta.id ? { ...e, cantidad: e.cantidad + 1 } : e))
        : [...actual, { producto: tarjeta.id, cantidad: 1, espacio }]
    })
  }

  const cambiarCantidad = (producto, delta) => {
    setAgregado(false)
    setMensaje(null)
    setElegidos((actual) => {
      const fila = actual.find((e) => e.producto === producto)
      if (!fila) return actual
      const def = definicion[fila.espacio]
      const unidades = actual.filter((e) => e.espacio === fila.espacio).reduce((s, e) => s + e.cantidad, 0)
      if (delta > 0 && unidades >= def.max_unidades) {
        setMensaje(`En «${def.nombre}» puedes elegir hasta ${def.max_unidades} unidades.`)
        return actual
      }
      const nueva = fila.cantidad + delta
      return nueva < 1 ? actual.filter((e) => e.producto !== producto) : actual.map((e) => (e.producto === producto ? { ...e, cantidad: nueva } : e))
    })
  }

  const quitar = (producto) => {
    setAgregado(false)
    setElegidos((actual) => actual.filter((e) => e.producto !== producto))
  }

  const vaciar = () => {
    setElegidos([])
    setAgregado(false)
    setMensaje(null)
  }

  const agregarAlCarrito = () => {
    if (!resumen?.puede_agregar) return
    for (const l of resumen.lineas) carrito.agregar(l.producto, l.cantidad, { nombre: l.nombre, foto: l.foto })
    setAgregado(true)
  }

  const copiarEnlace = async () => {
    const url = `${window.location.origin}/arma-tu-pc?p=${aTexto(elegidos)}`
    window.history.replaceState(null, '', `/arma-tu-pc?p=${aTexto(elegidos)}`)
    try {
      await navigator.clipboard.writeText(url)
      setMensaje('Copiamos el enlace de tu armado. Pégalo donde quieras para compartirlo.')
    } catch {
      setMensaje('Copia el enlace desde la barra de direcciones de tu navegador.')
    }
  }

  const porEspacio = (clave) => elegidos.filter((e) => e.espacio === clave)
  const incompatibles = resumen?.compatibilidades.filter((c) => c.estado === 'INCOMPATIBLE') ?? []
  const sinVerificar = resumen?.compatibilidades.filter((c) => c.estado === 'NO_VERIFICABLE') ?? []
  const compatibles = resumen?.compatibilidades.filter((c) => c.estado === 'COMPATIBLE') ?? []
  const total = resumen ? soles(resumen.subtotal) : soles(0)
  const cantidad = elegidos.reduce((s, e) => s + e.cantidad, 0)

  return (
    <div className="arm">
      <div className="arm-pasos">
        {espacios.map((esp, i) => {
          const propios = porEspacio(esp.clave)
          const abierto = activo === esp.clave
          return (
            <section key={esp.clave} className={`arm-paso${abierto ? ' abierto' : ''}`} aria-labelledby={`arm-t-${esp.clave}`}>
              <h2 id={`arm-t-${esp.clave}`}>
                <button type="button" className="arm-paso-cab" aria-expanded={abierto} aria-controls={`arm-c-${esp.clave}`} onClick={() => setActivo(esp.clave)}>
                  <span className={`arm-num${propios.length ? ' hecho' : ''}`} aria-hidden="true">
                    {propios.length ? <Icono nombre="check" tam={16} /> : i + 1}
                  </span>
                  <span className="arm-paso-titulo">
                    <strong>{esp.nombre}</strong>
                    <small>
                      {esp.obligatorio ? 'Obligatorio' : 'Opcional'}
                      {esp.max_unidades > 1 ? ` · hasta ${esp.max_unidades}` : ''} · {esp.ayuda}
                    </small>
                  </span>
                  <Icono nombre="chevron" tam={18} className="arm-chevron" />
                </button>
              </h2>

              {propios.length > 0 && (
                <ul className="arm-elegidos">
                  {propios.map((e) => {
                    const d = info[e.producto] ?? {}
                    return (
                      <li key={e.producto} className="arm-elegido">
                        {d.foto ? <img src={urlFoto(d.foto)} alt="" width={48} height={48} loading="lazy" decoding="async" /> : <span className="arm-sin-foto" aria-hidden="true" />}
                        <span className="arm-elegido-nombre">{d.nombre ?? `Producto ${e.producto}`}</span>
                        {esp.max_unidades > 1 && (
                          <span className="arm-cantidad" role="group" aria-label={`Cantidad de ${d.nombre ?? 'la pieza'}`}>
                            <button type="button" onClick={() => cambiarCantidad(e.producto, -1)} aria-label="Una menos">
                              <Icono nombre="menos" tam={14} />
                            </button>
                            <output aria-live="polite">{e.cantidad}</output>
                            <button type="button" onClick={() => cambiarCantidad(e.producto, 1)} aria-label="Una más">
                              <Icono nombre="mas" tam={14} />
                            </button>
                          </span>
                        )}
                        <button type="button" className="arm-quitar" onClick={() => quitar(e.producto)}>
                          Quitar
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}

              {abierto && (
                <div className="arm-cuerpo" id={`arm-c-${esp.clave}`}>
                  <label className="campo-check arm-todas">
                    <input type="checkbox" checked={todas} onChange={(ev) => setTodas(ev.target.checked)} />
                    <span>Mostrar también las piezas que no encajan con mi armado</span>
                  </label>
                  {opciones.error && (
                    <p className="alerta error" role="alert">
                      {opciones.error}
                    </p>
                  )}
                  <ul className="arm-opciones" aria-busy={opciones.cargando}>
                    {opciones.cargando && opciones.filas.length === 0
                      ? Array.from({ length: 4 }, (_, k) => <li key={k} className="arm-op esqueleto" style={{ minHeight: 150 }} />)
                      : opciones.filas.map((t) => (
                          <Opcion key={t.id} t={t} espacio={esp} elegida={porEspacio(esp.clave).some((e) => e.producto === t.id)} alElegir={() => elegir(t, esp.clave)} />
                        ))}
                  </ul>
                  {!opciones.cargando && !opciones.error && opciones.filas.length === 0 && (
                    <p className="arm-vacio">
                      {todas
                        ? 'Todavía no hay piezas en esta categoría.'
                        : 'No hay piezas compatibles con lo que elegiste. Cambia una pieza o marca la casilla de arriba para verlas todas.'}
                    </p>
                  )}
                  {opciones.pagina < opciones.paginas && (
                    <button type="button" className="boton secundario" disabled={opciones.cargando} onClick={() => cargarOpciones(opciones.pagina + 1, false)}>
                      Ver más piezas
                    </button>
                  )}
                </div>
              )}
            </section>
          )
        })}
      </div>

      <aside className="arm-resumen" id="arm-resumen" aria-label="Resumen de tu armado">
        <h2>Tu armado</h2>
        {cantidad === 0 ? (
          <p className="arm-vacio">Todavía no elegiste ninguna pieza. Empieza por el primer paso.</p>
        ) : (
          <ul className="arm-lista">
            {elegidos.map((e) => {
              const d = info[e.producto] ?? {}
              const linea = resumen?.lineas.find((l) => l.producto === e.producto)
              return (
                <li key={e.producto}>
                  <span>
                    <small>{definicion[e.espacio]?.nombre}</small>
                    {d.nombre ?? `Producto ${e.producto}`}
                    {e.cantidad > 1 ? ` × ${e.cantidad}` : ''}
                    {linea?.problema && <em className="arm-problema">{linea.problema}</em>}
                  </span>
                  <strong>{linea?.subtotal ? soles(linea.subtotal) : ''}</strong>
                </li>
              )
            })}
          </ul>
        )}

        <p className="arm-total">
          <span>Total estimado</span>
          <strong>{total}</strong>
        </p>
        <p className="arm-nota">Precios con IGV cuando corresponde. El total exacto se confirma al comprar.</p>

        <div aria-live="polite" className="arm-avisos">
          {incompatibles.map((c, k) => (
            <p key={`i${k}`} className="alerta error">
              <Icono nombre="info" tam={18} /> {c.mensaje}
            </p>
          ))}
          {resumen?.faltantes?.length > 0 && cantidad > 0 && (
            <p className="alerta aviso">
              <Icono nombre="info" tam={18} /> Te falta elegir: {resumen.faltantes.map((f) => f.nombre).join(', ')}.
            </p>
          )}
          {sinVerificar.length > 0 && (
            <details className="arm-detalle">
              <summary>
                <Icono nombre="info" tam={16} /> {sinVerificar.length} {sinVerificar.length === 1 ? 'verificación pendiente' : 'verificaciones pendientes'}
              </summary>
              <ul>
                {sinVerificar.map((c, k) => (
                  <li key={k}>{c.mensaje}</li>
                ))}
              </ul>
            </details>
          )}
          {compatibles.length > 0 && incompatibles.length === 0 && (
            <p className="alerta ok">
              <Icono nombre="check" tam={18} /> {compatibles.length} {compatibles.length === 1 ? 'verificación' : 'verificaciones'} de compatibilidad correcta{compatibles.length === 1 ? '' : 's'}.
            </p>
          )}
          {mensaje && <p className="alerta">{mensaje}</p>}
        </div>

        <div className="arm-acciones">
          <button type="button" className="boton grande" disabled={!resumen?.puede_agregar} onClick={agregarAlCarrito}>
            <Icono nombre="carrito" tam={20} /> Agregar todo al carrito
          </button>
          {agregado && (
            <p className="alerta ok" role="status">
              Agregamos tu armado al carrito. <Link href="/carrito" className="enlace">Ver carrito</Link>
            </p>
          )}
          <div className="arm-secundarias">
            <button type="button" className="boton secundario" onClick={copiarEnlace} disabled={cantidad === 0}>
              Copiar enlace de mi armado
            </button>
            <button type="button" className="boton fantasma" onClick={vaciar} disabled={cantidad === 0}>
              Empezar de nuevo
            </button>
          </div>
          <p className="arm-nota">Tu armado se guarda en este equipo mientras lo armas.</p>
        </div>
      </aside>

      <div className="arm-barra" role="region" aria-label="Total de tu armado">
        <span>
          <small>{cantidad} {cantidad === 1 ? 'pieza' : 'piezas'}</small>
          <strong>{total}</strong>
        </span>
        <a href="#arm-resumen" className="boton chico">
          Ver mi armado
        </a>
      </div>
    </div>
  )
}

/** Una pieza que se puede elegir, con lo que el servidor dice de su compatibilidad. */
function Opcion({ t, espacio, elegida, alElegir }) {
  const estado = t.compatibilidad?.estado ?? 'LIBRE'
  const agotado = t.disponibilidad === 'agotado'
  const sinPrecio = t.consultar_precio
  const bloqueada = estado === 'INCOMPATIBLE' || agotado || sinPrecio
  const motivo = t.compatibilidad?.motivos?.[0]
  return (
    <li className={`arm-op ${estado.toLowerCase()}${elegida ? ' elegida' : ''}`}>
      <div className="arm-op-foto">{t.foto ? <img src={urlFoto(t.foto)} alt="" width={96} height={96} loading="lazy" decoding="async" /> : <span className="arm-sin-foto" aria-hidden="true" />}</div>
      <div className="arm-op-cuerpo">
        {t.marca && <small className="arm-op-marca">{t.marca.nombre}</small>}
        <Link href={`/producto/${t.slug}`} className="arm-op-nombre" target="_blank" rel="noopener">
          {t.nombre}
        </Link>
        {t.tarjeta?.length > 0 && (
          <ul className="arm-op-specs">
            {t.tarjeta.slice(0, 3).map((d) => (
              <li key={d.nombre}>
                {d.nombre} <b>{d.valor}</b>
              </li>
            ))}
          </ul>
        )}
        <p className="arm-op-precio">
          <strong>{soles(t.precio_mostrar) ?? 'Consultar'}</strong>
          <span className={`insignia ${agotado ? 'agotado' : t.disponibilidad === 'pocas' ? 'poco' : 'ok'}`}>{textoDisponibilidad(t)}</span>
        </p>
        {estado !== 'LIBRE' && (
          <p className={`arm-compat ${estado.toLowerCase()}`}>
            <Icono nombre={estado === 'COMPATIBLE' ? 'check' : 'info'} tam={16} />
            <span>{estado === 'COMPATIBLE' ? TEXTO_ESTADO.COMPATIBLE : (motivo ?? TEXTO_ESTADO[estado])}</span>
          </p>
        )}
      </div>
      <button type="button" className={`boton chico${elegida ? ' secundario' : ''}`} onClick={alElegir} disabled={bloqueada || (elegida && espacio.max_unidades === 1)}>
        {elegida ? (espacio.max_unidades > 1 ? 'Agregar otra' : 'Elegida') : estado === 'INCOMPATIBLE' ? 'No encaja' : agotado ? 'Agotado' : sinPrecio ? 'Consultar' : espacio.max_unidades > 1 ? 'Agregar' : 'Elegir'}
      </button>
    </li>
  )
}
