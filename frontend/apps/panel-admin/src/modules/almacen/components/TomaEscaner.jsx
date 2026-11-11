import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { cantidad, paraServidor } from '../inventario'
import { ESTADOS_FISICOS, revisarCantidad } from '../tomas'
import '../inventario.css'
import '../tomas.css'

const coincide = (fila, texto) => [fila.codigo_barras, fila.producto_codigo].some((c) => c && c.toUpperCase() === texto.toUpperCase())

/**
 * Cuenta con lector de códigos de barras (o escribiendo el código): se escanea, aparece el producto,
 * se escribe la cantidad y Enter la registra. El foco vuelve al lector para el siguiente producto.
 * Mientras se escribe aparecen sugerencias (con retraso de 300 ms, desde 2 letras): se elige una con el ratón
 * o con las flechas y Enter. Con el lector, Enter busca de inmediato: un código que coincide exacto con un
 * solo producto se elige solo.
 */
export default function TomaEscaner({ toma, turno, registro }) {
  const notificar = useNotificar()
  const lector = useRef(null)
  const campoCantidad = useRef(null)
  const busqueda = useRef(null)
  const [codigo, setCodigo] = useState('')
  const [buscando, setBuscando] = useState(false)
  const [mensaje, setMensaje] = useState('')
  const [opciones, setOpciones] = useState([])
  const [fila, setFila] = useState(null)
  const [valor, setValor] = useState('')
  const [estadoFisico, setEstadoFisico] = useState('BUENO')
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [abierto, setAbierto] = useState(false)
  const [activo, setActivo] = useState(-1)
  const texto = useDebounce(codigo.trim(), 300)

  // Sugerencias mientras se escribe. En reconteo solo los productos que faltan recontar.
  const sugerencias = useQuery({
    queryKey: ['tomas', 'sugerencias', toma.id, toma.estado, texto],
    queryFn: ({ signal }) =>
      api
        .get(`/inventario/tomas/${toma.id}/detalle/`, { params: { q: texto, page_size: 8, ...(toma.estado === 'EN_RECONTEO' ? { reconteo: 1 } : {}) }, signal })
        .then((r) => r.data.results),
    enabled: abierto && !fila && texto.length >= 2,
    staleTime: 10_000,
  })
  const lista = sugerencias.data ?? []
  const mostrarLista = abierto && !fila && codigo.trim().length >= 2

  // Al desmontar se cancela la búsqueda en curso (no queda nada colgando).
  useEffect(() => () => busqueda.current?.abort(), [])
  useEffect(() => {
    // Con un producto elegido el foco va a la cantidad; si no, queda listo el lector para el siguiente código.
    if (fila) campoCantidad.current?.focus()
    else if (!buscando) lector.current?.focus()
  }, [fila, buscando])

  const limpiar = () => {
    setFila(null)
    setOpciones([])
    setValor('')
    setNota('')
    setEstadoFisico('BUENO')
    setError('')
    setEnviando(false)
  }

  const elegir = (elegida) => {
    if (toma.estado === 'EN_RECONTEO' && !elegida.requiere_reconteo) {
      setMensaje(`${elegida.producto_nombre} no está en la lista de reconteo.`)
      return
    }
    setMensaje('')
    setOpciones([])
    setCodigo('')
    setAbierto(false)
    setActivo(-1)
    setFila(elegida)
    setValor('')
    setNota('')
    setError('')
    setEstadoFisico(elegida.estado_fisico || 'BUENO')
  }

  const buscar = async (evento) => {
    evento.preventDefault()
    const buscado = codigo.trim()
    if (!buscado || buscando) return
    setAbierto(false)
    busqueda.current?.abort()
    busqueda.current = new AbortController()
    setBuscando(true)
    setMensaje('')
    setOpciones([])
    try {
      const { data } = await api.get(`/inventario/tomas/${toma.id}/detalle/`, { params: { q: buscado, page_size: 10 }, signal: busqueda.current.signal })
      const filas = data.results
      const exactas = filas.filter((f) => coincide(f, buscado))
      const unica = exactas.length === 1 ? exactas[0] : filas.length === 1 ? filas[0] : null
      if (unica) elegir(unica)
      else if (filas.length === 0) setMensaje(`«${buscado}» no está en esta toma.`)
      else setOpciones(filas)
    } catch (e) {
      if (e?.code !== 'ERR_CANCELED') setMensaje(mensajeDeError(e))
    } finally {
      setBuscando(false)
    }
  }

  const alTeclear = (evento) => {
    if (!mostrarLista || lista.length === 0) return
    if (evento.key === 'ArrowDown') {
      evento.preventDefault()
      setActivo((i) => (i + 1) % lista.length)
    } else if (evento.key === 'ArrowUp') {
      evento.preventDefault()
      setActivo((i) => (i <= 0 ? lista.length - 1 : i - 1))
    } else if (evento.key === 'Enter' && activo >= 0 && lista[activo]) {
      evento.preventDefault() // elige la sugerencia marcada en lugar de buscar
      elegir(lista[activo])
    } else if (evento.key === 'Escape') {
      setAbierto(false)
    }
  }

  const guardar = (evento) => {
    evento.preventDefault()
    if (enviando || !fila) return
    const problema = revisarCantidad(valor, fila.admite_decimales)
    if (problema) return setError(problema)
    setError('')
    setEnviando(true)
    registro.registrar(
      {
        producto: fila.producto,
        cantidad: paraServidor(valor),
        estado_fisico: estadoFisico,
        ...(nota.trim() ? { nota: nota.trim() } : {}),
        ...(turno ? { turno: Number(turno) } : {}),
      },
      {
        alExito: (detalle) => {
          notificar('exito', `${fila.producto_nombre}: contado ${cantidad(detalle.cantidad_contada)} ${fila.unidad}`)
          limpiar()
        },
        alError: (texto) => {
          setEnviando(false)
          if (texto) setError(texto)
        },
      },
    )
  }

  return (
    <section className="toma-panel" aria-label="Contar con lector de códigos">
      <header className="toma-panel-cabecera">
        <h3>
          <Icono nombre="scan" tam={20} /> Contar con lector
        </h3>
      </header>
      <form onSubmit={buscar} className="toma-lector" noValidate>
        <div className="selector-producto">
          <Campo etiqueta="Escanea o escribe el código" icono="scan" ayuda="Código de barras, código del producto o parte del nombre. Elige de la lista, o pulsa Enter.">
            {(p) => (
              <input
                {...p}
                ref={lector}
                value={codigo}
                autoComplete="off"
                role="combobox"
                aria-expanded={mostrarLista}
                aria-autocomplete="list"
                disabled={buscando || Boolean(fila)}
                onChange={(e) => {
                  setCodigo(e.target.value)
                  setAbierto(true)
                  setActivo(-1)
                  setMensaje('')
                }}
                onFocus={() => setAbierto(true)}
                onKeyDown={alTeclear}
                onBlur={() => setTimeout(() => setAbierto(false), 150)}
              />
            )}
          </Campo>
          {mostrarLista && (
            <ul role="listbox" aria-label="Productos encontrados">
              {(sugerencias.isLoading || sugerencias.isFetching) && lista.length === 0 && <li className="sin-resultados">Buscando…</li>}
              {sugerencias.isError && <li className="sin-resultados">No se pudo buscar. Intenta de nuevo.</li>}
              {sugerencias.isSuccess && !sugerencias.isFetching && lista.length === 0 && <li className="sin-resultados">No hay productos con ese texto en esta toma.</li>}
              {lista.map((o, i) => (
                <li key={o.id} role="option" aria-selected={i === activo}>
                  <button type="button" className={i === activo ? 'toma-sugerencia-activa' : undefined} onMouseDown={(e) => e.preventDefault()} onClick={() => elegir(o)}>
                    <strong>{o.producto_nombre}</strong>
                    <span className="sub-texto">
                      {o.producto_codigo}
                      {o.codigo_barras ? ` · ${o.codigo_barras}` : ''} · {o.unidad}
                      {o.cantidad_contada !== null && o.cantidad_contada !== undefined ? ` · ya contado: ${cantidad(o.cantidad_contada)}` : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </form>

      {mensaje && (
        <p role="alert" className="campo-error">
          {mensaje}
        </p>
      )}

      {opciones.length > 0 && (
        <ul className="toma-opciones" aria-label="Productos encontrados">
          {opciones.map((o) => (
            <li key={o.id}>
              <button type="button" onClick={() => elegir(o)}>
                <strong>{o.producto_nombre}</strong>
                <span className="sub-texto">
                  {o.producto_codigo}
                  {o.codigo_barras ? ` · ${o.codigo_barras}` : ''} · {o.unidad}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {fila && (
        <form onSubmit={guardar} className="toma-contar" noValidate>
          <div>
            <strong>{fila.producto_nombre}</strong>
            <span className="sub-texto">
              {fila.producto_codigo}
              {fila.codigo_barras ? ` · ${fila.codigo_barras}` : ''} · {fila.categoria_nombre} · se cuenta en {fila.unidad}
            </span>
            {fila.cantidad_contada !== null && fila.cantidad_contada !== undefined && (
              <span className="sub-texto toma-aviso-previo">
                Ya se contó {cantidad(fila.cantidad_contada)}. Al registrar, se cuenta de nuevo.
              </span>
            )}
          </div>
          <fieldset disabled={enviando} className="toma-fieldset toma-contar-campos">
            <Campo etiqueta="Cantidad contada" requerido error={error}>
              {(p) => <input {...p} ref={campoCantidad} inputMode="decimal" autoComplete="off" value={valor} onChange={(e) => setValor(e.target.value)} />}
            </Campo>
            <Campo etiqueta="Estado físico" tipo="select">
              {(p) => (
                <select {...p} value={estadoFisico} onChange={(e) => setEstadoFisico(e.target.value)}>
                  {Object.entries(ESTADOS_FISICOS).map(([v, texto]) => (
                    <option key={v} value={v}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Nota">
              {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={nota} onChange={(e) => setNota(e.target.value)} />}
            </Campo>
          </fieldset>
          <div className="toma-contar-pie">
            <button type="button" onClick={limpiar} disabled={enviando}>
              Cancelar
            </button>
            <button type="submit" className="primario" disabled={enviando}>
              {enviando ? 'Registrando…' : 'Registrar conteo'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
