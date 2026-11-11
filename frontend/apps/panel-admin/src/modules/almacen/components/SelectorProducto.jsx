import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import '../inventario.css'

/**
 * Elige un producto con búsqueda en el servidor (nombre, código o código de barras).
 * Solo bienes activos: los servicios no llevan stock. Busca con 400 ms de retraso y desde 2 letras.
 * `valor` es `{ id, codigo, nombre }` o `null`; `onElegir` recibe el producto elegido (o `null`).
 */
export default function SelectorProducto({ valor, onElegir, etiqueta = 'Producto', error, disabled = false }) {
  const [texto, setTexto] = useState('')
  const [abierto, setAbierto] = useState(false)
  const q = useDebounce(texto.trim(), 400)

  const resultados = useQuery({
    queryKey: ['opciones', 'productos-inventario', q],
    queryFn: ({ signal }) =>
      api
        .get('/mantenimiento/productos/', { params: { q, tipo: 'BIEN', estado: 'ACTIVO', page_size: 10 }, signal })
        .then((r) => r.data.results),
    enabled: abierto && q.length >= 2,
    staleTime: 30_000,
  })

  const elegir = (producto) => {
    onElegir(producto)
    setTexto('')
    setAbierto(false)
  }

  return (
    <Campo etiqueta={etiqueta} icono="package" error={error}>
      {(p) =>
        valor ? (
          <div className="selector-producto">
            <div className="elegido">
              <span>
                <strong>{valor.nombre}</strong>
                {valor.codigo && <span className="sub-texto">Código {valor.codigo}</span>}
              </span>
              {!disabled && (
                <button type="button" onClick={() => onElegir(null)}>
                  Cambiar
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="selector-producto">
            <input
              {...p}
              type="search"
              autoComplete="off"
              placeholder="Escribe 2 letras del nombre o código…"
              value={texto}
              disabled={disabled}
              role="combobox"
              aria-expanded={abierto && q.length >= 2}
              aria-autocomplete="list"
              onFocus={() => setAbierto(true)}
              onChange={(e) => {
                setTexto(e.target.value)
                setAbierto(true)
              }}
              onKeyDown={(e) => e.key === 'Escape' && setAbierto(false)}
              onBlur={() => setTimeout(() => setAbierto(false), 150)}
            />
            {abierto && q.length >= 2 && (
              <ul role="listbox" aria-label="Productos encontrados">
                {resultados.isLoading && <li className="sin-resultados">Buscando…</li>}
                {resultados.isError && <li className="sin-resultados">No se pudo buscar. Intenta de nuevo.</li>}
                {resultados.isSuccess && resultados.data.length === 0 && <li className="sin-resultados">No hay productos con ese texto.</li>}
                {(resultados.data ?? []).map((producto) => (
                  <li key={producto.id} role="option" aria-selected="false">
                    <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => elegir(producto)}>
                      <strong>{producto.nombre}</strong>
                      <span className="sub-texto">
                        {producto.codigo} · {producto.unidad_abreviatura}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )
      }
    </Campo>
  )
}
