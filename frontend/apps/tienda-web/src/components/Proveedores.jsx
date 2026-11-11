'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { llamar } from '@/lib/cliente'

/**
 * Estado compartido del navegador: la cuenta del cliente y su carrito.
 *
 * CUENTA: la sesión vive en una cookie HttpOnly (el código de la página no la puede leer); aquí solo
 * se sabe si hay sesión preguntándole a la API.
 *
 * CARRITO: el navegador guarda SOLO ids y cantidades (localStorage). Nombre, foto, precio y
 * disponibilidad los calcula siempre el servidor, así un dato viejo no engaña a nadie. Si el cliente
 * tiene cuenta, el carrito también se guarda en el servidor (se ve en otro equipo) y al ingresar se
 * junta con el que traía como invitado.
 */
const CLAVE = 'tienda:carrito:v1'
const MAX_CANTIDAD = 99
const ESPERA_CALCULO_MS = 250
const ESPERA_GUARDADO_MS = 700

const CuentaContexto = createContext(null)
const CarritoContexto = createContext(null)

export const useCuenta = () => useContext(CuentaContexto)
export const useCarrito = () => useContext(CarritoContexto)

function leerGuardado() {
  try {
    const crudo = window.localStorage.getItem(CLAVE)
    const lista = crudo ? JSON.parse(crudo) : []
    return Array.isArray(lista) ? limpiar(lista) : []
  } catch {
    return []
  }
}

function guardarLocal(items) {
  try {
    window.localStorage.setItem(CLAVE, JSON.stringify(items))
  } catch {
    // modo privado o sin espacio: el carrito sigue funcionando mientras la página esté abierta
  }
}

/** Deja solo líneas válidas (ids y cantidades enteras), sin repetidos. */
function limpiar(lista) {
  const mapa = new Map()
  for (const fila of lista) {
    const producto = Number(fila?.producto)
    const cantidad = Number(fila?.cantidad)
    if (!Number.isInteger(producto) || producto < 1 || !Number.isInteger(cantidad) || cantidad < 1) continue
    mapa.set(producto, Math.min((mapa.get(producto) ?? 0) + cantidad, MAX_CANTIDAD))
  }
  return [...mapa].map(([producto, cantidad]) => ({ producto, cantidad }))
}

export default function Proveedores({ children }) {
  // ------------------------------------------------------------------ cuenta
  const [estado, setEstado] = useState('cargando') // cargando | anonimo | autenticado
  const [perfil, setPerfil] = useState(null)

  const recargar = useCallback(async () => {
    try {
      const datos = await llamar('cuenta/sesion')
      setPerfil(datos.perfil)
      setEstado(datos.autenticado ? 'autenticado' : 'anonimo')
    } catch {
      // sin conexión u otro fallo: no se cierra nada, se vuelve a intentar al recargar
      setEstado((actual) => (actual === 'cargando' ? 'anonimo' : actual))
    }
  }, [])

  useEffect(() => {
    recargar()
  }, [recargar])

  const ingresar = useCallback(async (correo, password) => {
    const datos = await llamar('cuenta/ingresar', { metodo: 'POST', cuerpo: { correo, password } })
    setPerfil(datos)
    setEstado('autenticado')
    return datos
  }, [])

  const salir = useCallback(async () => {
    try {
      await llamar('cuenta/salir', { metodo: 'POST', cuerpo: {} })
    } finally {
      setPerfil(null)
      setEstado('anonimo')
    }
  }, [])

  const cuenta = useMemo(
    () => ({ estado, perfil, autenticado: estado === 'autenticado', recargar, ingresar, salir, setPerfil }),
    [estado, perfil, recargar, ingresar, salir],
  )

  // ----------------------------------------------------------------- carrito
  const [items, setItems] = useState([])
  const [listo, setListo] = useState(false)
  const [resumen, setResumen] = useState(null)
  const [calculando, setCalculando] = useState(false)
  const [aviso, setAviso] = useState(null) // último producto agregado (para el aviso en pantalla)
  const iniciado = useRef(false) // ya se empezó a juntar el carrito guardado de la cuenta
  const [fusionado, setFusionado] = useState(false) // ya se juntó: recién ahora se puede guardar
  const estadoAnterior = useRef('cargando')

  useEffect(() => {
    setItems(leerGuardado())
    setListo(true)
    // otra pestaña cambió el carrito
    const alCambiar = (e) => e.key === CLAVE && setItems(leerGuardado())
    window.addEventListener('storage', alCambiar)
    return () => window.removeEventListener('storage', alCambiar)
  }, [])

  useEffect(() => {
    if (listo) guardarLocal(items)
  }, [items, listo])

  // Precios, disponibilidad y totales: siempre del servidor.
  useEffect(() => {
    if (!listo) return undefined
    if (items.length === 0) {
      setResumen(null)
      setCalculando(false)
      return undefined
    }
    const control = new AbortController()
    setCalculando(true)
    const espera = setTimeout(async () => {
      try {
        const datos = await llamar('carrito/calcular', { metodo: 'POST', cuerpo: { lineas: items }, signal: control.signal })
        setResumen(datos)
        if (datos.quitados?.length) {
          // productos que ya no se venden: salen del carrito
          setItems((actual) => actual.filter((l) => !datos.quitados.includes(l.producto)))
        }
      } catch (error) {
        if (error?.name !== 'AbortError') setResumen((actual) => actual) // se deja lo último que había
      } finally {
        if (!control.signal.aborted) setCalculando(false)
      }
    }, ESPERA_CALCULO_MS)
    return () => {
      clearTimeout(espera)
      control.abort()
    }
  }, [items, listo])

  // Al ingresar: se junta el carrito de invitado con el guardado en la cuenta (se queda lo mayor).
  // Al salir: se vacía el carrito de este equipo (puede ser un equipo compartido).
  useEffect(() => {
    const antes = estadoAnterior.current
    estadoAnterior.current = estado
    if (!listo) return
    if (estado === 'autenticado' && !iniciado.current) {
      iniciado.current = true
      ;(async () => {
        try {
          const guardado = await llamar('cuenta/carrito')
          const mapa = new Map(items.map((l) => [l.producto, l.cantidad]))
          for (const l of guardado.lineas) {
            mapa.set(l.producto, Math.max(mapa.get(l.producto) ?? 0, l.cantidad))
          }
          setItems(limpiar([...mapa].map(([producto, cantidad]) => ({ producto, cantidad }))))
          setFusionado(true)
        } catch {
          iniciado.current = false
        }
      })()
    } else if (estado === 'anonimo' && antes === 'autenticado') {
      iniciado.current = false
      setFusionado(false)
      setItems([])
    }
    // solo reacciona al cambio de sesión
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estado, listo])

  // Con cuenta, cada cambio se guarda también en el servidor (sin apuro: se junta lo que cambie seguido).
  useEffect(() => {
    if (estado !== 'autenticado' || !fusionado || !listo) return undefined
    const espera = setTimeout(() => {
      llamar('cuenta/carrito', { metodo: 'PUT', cuerpo: { lineas: items } }).catch(() => {})
    }, ESPERA_GUARDADO_MS)
    return () => clearTimeout(espera)
  }, [items, estado, fusionado, listo])

  const agregar = useCallback((producto, cantidad = 1, datos = null) => {
    const id = Number(producto)
    if (!Number.isInteger(id) || id < 1) return
    setItems((actual) => {
      const existente = actual.find((l) => l.producto === id)
      if (existente) {
        return actual.map((l) =>
          l.producto === id ? { ...l, cantidad: Math.min(l.cantidad + cantidad, MAX_CANTIDAD) } : l,
        )
      }
      return [...actual, { producto: id, cantidad: Math.min(cantidad, MAX_CANTIDAD) }]
    })
    setAviso({ producto: id, cantidad, ...(datos ?? {}), momento: Date.now() })
  }, [])

  const fijar = useCallback((producto, cantidad) => {
    const n = Math.min(Math.floor(Number(cantidad)), MAX_CANTIDAD)
    setItems((actual) =>
      Number.isFinite(n) && n >= 1
        ? actual.map((l) => (l.producto === producto ? { ...l, cantidad: n } : l))
        : actual.filter((l) => l.producto !== producto),
    )
  }, [])

  const quitar = useCallback((producto) => setItems((actual) => actual.filter((l) => l.producto !== producto)), [])
  const vaciar = useCallback(() => setItems([]), [])
  const cerrarAviso = useCallback(() => setAviso(null), [])

  const cantidadTotal = useMemo(() => items.reduce((suma, l) => suma + l.cantidad, 0), [items])

  const carrito = useMemo(
    () => ({
      /** Lo que guarda el navegador: [{ producto, cantidad }] */
      items,
      /** Lo que calcula el servidor (líneas con precio, subtotal, problemas…) o `null` si está vacío. */
      resumen,
      calculando,
      listo,
      cantidadTotal,
      aviso,
      agregar,
      fijar,
      quitar,
      vaciar,
      cerrarAviso,
    }),
    [items, resumen, calculando, listo, cantidadTotal, aviso, agregar, fijar, quitar, vaciar, cerrarAviso],
  )

  return (
    <CuentaContexto.Provider value={cuenta}>
      <CarritoContexto.Provider value={carrito}>{children}</CarritoContexto.Provider>
    </CuentaContexto.Provider>
  )
}
