import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import { MAX_LUGARES } from '../envios'
import { plano } from '../tienda'

/**
 * Elige los lugares que cubre una zona: departamento → provincia → distrito.
 * Se puede agregar «todo» un departamento o una provincia, o distritos sueltos.
 * Cada lugar queda como una etiqueta que se puede quitar.
 */
export default function LugaresZona({ lugares, onCambio, error }) {
  const [depto, setDepto] = useState('')
  const [provincia, setProvincia] = useState('')
  const [buscar, setBuscar] = useState('')

  const departamentos = useQuery({
    queryKey: ['tienda', 'envios', 'ubigeos'],
    queryFn: ({ signal }) => api.get('/tienda/admin/envios/ubigeos/', { signal }).then((r) => r.data),
    staleTime: Infinity,
  })
  const distritos = useQuery({
    queryKey: ['tienda', 'envios', 'ubigeos', provincia],
    queryFn: ({ signal }) => api.get('/tienda/admin/envios/ubigeos/', { params: { provincia }, signal }).then((r) => r.data),
    enabled: provincia.length === 4,
    staleTime: Infinity,
  })

  const dep = departamentos.data?.find((d) => d.codigo === depto)
  const prov = dep?.provincias.find((p) => p.codigo === provincia)
  const elegidos = useMemo(() => new Set(lugares.map((l) => l.prefijo)), [lugares])
  const lleno = lugares.length >= MAX_LUGARES

  const agregar = (prefijo, nombre) => {
    if (elegidos.has(prefijo) || lleno) return
    onCambio([...lugares, { prefijo, nombre }])
  }
  const quitar = (prefijo) => onCambio(lugares.filter((l) => l.prefijo !== prefijo))

  const visibles = useMemo(() => {
    const q = plano(buscar)
    return (distritos.data ?? []).filter((d) => !q || plano(d.nombre).includes(q))
  }, [distritos.data, buscar])

  // Un lugar ya cubierto por «toda la provincia/departamento» de esta misma zona no se repite.
  const cubierto = (codigo) => elegidos.has(codigo.slice(0, 2)) || elegidos.has(codigo.slice(0, 4))

  return (
    <fieldset className="envios-lugares">
      <legend>Lugares que cubre</legend>
      <p className="campo-ayuda">
        Si un lugar está en dos zonas, gana el más específico: un distrito pesa más que su provincia, y una provincia más que su
        departamento. Así puedes poner «todo Lima» y un precio distinto para un distrito lejano.
      </p>

      {lugares.length > 0 ? (
        <ul className="envios-chips" aria-label="Lugares elegidos">
          {lugares.map((l) => (
            <li key={l.prefijo}>
              <span>{l.nombre}</span>
              <button type="button" aria-label={`Quitar ${l.nombre}`} onClick={() => quitar(l.prefijo)}>
                <Icono nombre="cerrar" tam={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="celda-suave">Todavía no agregaste ningún lugar.</p>
      )}
      {lleno && <p className="campo-error">Llegaste al máximo de {MAX_LUGARES} lugares. Usa «toda la provincia» para ahorrar espacio.</p>}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}

      <div className="envios-lugares-selector">
        {departamentos.isError && (
          <p role="alert" className="campo-error">
            No se pudo cargar la lista de lugares. Cierra y vuelve a abrir.
          </p>
        )}
        <label>
          <span>Departamento</span>
          <select
            value={depto}
            disabled={!departamentos.data}
            onChange={(e) => {
              setDepto(e.target.value)
              setProvincia('')
              setBuscar('')
            }}
          >
            <option value="">{departamentos.isPending ? 'Cargando…' : 'Elige un departamento'}</option>
            {(departamentos.data ?? []).map((d) => (
              <option key={d.codigo} value={d.codigo}>
                {d.nombre}
              </option>
            ))}
          </select>
        </label>
        {dep && (
          <button type="button" disabled={elegidos.has(dep.codigo) || lleno} onClick={() => agregar(dep.codigo, `${dep.nombre} (todo el departamento)`.toUpperCase())}>
            <Icono nombre="agregar" tam={16} /> Todo {dep.nombre}
          </button>
        )}
        {dep && (
          <label>
            <span>Provincia</span>
            <select
              value={provincia}
              onChange={(e) => {
                setProvincia(e.target.value)
                setBuscar('')
              }}
            >
              <option value="">Elige una provincia</option>
              {dep.provincias.map((p) => (
                <option key={p.codigo} value={p.codigo}>
                  {p.nombre}
                </option>
              ))}
            </select>
          </label>
        )}
        {prov && (
          <button
            type="button"
            disabled={elegidos.has(prov.codigo) || elegidos.has(dep.codigo) || lleno}
            onClick={() => agregar(prov.codigo, `${dep.nombre} - ${prov.nombre} (toda la provincia)`.toUpperCase())}
          >
            <Icono nombre="agregar" tam={16} /> Toda la provincia de {prov.nombre}
          </button>
        )}
      </div>

      {prov && (
        <div className="envios-distritos">
          <label>
            <span>Buscar distrito</span>
            <input type="search" value={buscar} placeholder="Ej.: Miraflores" onChange={(e) => setBuscar(e.target.value)} />
          </label>
          {distritos.isPending && <p className="celda-suave">Cargando distritos…</p>}
          {distritos.isError && (
            <p role="alert" className="campo-error">
              No se pudieron cargar los distritos.
            </p>
          )}
          {distritos.data && (
            <ul className="envios-distritos-lista">
              {visibles.map((d) => {
                const ya = elegidos.has(d.codigo)
                const incluido = cubierto(d.codigo)
                return (
                  <li key={d.codigo}>
                    <label className="tienda-casilla">
                      <input
                        type="checkbox"
                        checked={ya || incluido}
                        disabled={incluido && !ya}
                        onChange={() => (ya ? quitar(d.codigo) : agregar(d.codigo, `${dep.nombre} - ${prov.nombre} - ${d.nombre}`.toUpperCase()))}
                      />
                      {d.nombre}
                      {incluido && !ya && <small> (ya incluido)</small>}
                    </label>
                  </li>
                )
              })}
              {visibles.length === 0 && <li className="celda-suave">No hay distritos con ese nombre.</li>}
            </ul>
          )}
        </div>
      )}
    </fieldset>
  )
}
