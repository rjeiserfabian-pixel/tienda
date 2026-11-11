import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { fechaCorta } from '../../almacen/inventario'
import { equipoVacio } from '../servicio'

const VACIO = []

const nombreEquipo = (e) => [e.tipo_nombre, e.marca, e.modelo].filter(Boolean).join(' ')
const veces = (n) => (n === 1 ? '1 vez' : `${n} veces`)

/** Equipos que el cliente ya dejó antes: se elige uno o se registra uno nuevo. */
function EquiposDelCliente({ empresaId, cliente, elegido, onElegir, disabled }) {
  const consulta = useQuery({
    queryKey: ['servicio', 'equipos', empresaId, cliente.id],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/equipos/', { params: { empresa: empresaId, cliente: cliente.id, page_size: 50 }, signal }).then((r) => r.data.results),
    staleTime: 15_000,
  })
  const equipos = consulta.data ?? VACIO
  if (consulta.isLoading) return <p aria-busy="true" className="celda-suave">Buscando los equipos de este cliente…</p>
  if (consulta.isError) return <p role="alert" className="campo-error">No se pudieron cargar los equipos del cliente: puedes registrar uno nuevo.</p>
  if (equipos.length === 0) return null
  return (
    <div role="radiogroup" aria-label="Equipo" className="servicio-equipos">
      {equipos.map((e) => (
        <button key={e.id} type="button" role="radio" aria-checked={elegido?.id === e.id} className="servicio-equipo-opcion" disabled={disabled} onClick={() => onElegir(e)}>
          <span>
            <strong>{nombreEquipo(e)}</strong>
            <span className="sub-texto">
              {e.numero_serie ? `Serie ${e.numero_serie} · ` : ''}
              {e.n_ordenes > 0 ? `Ingresó ${veces(e.n_ordenes)}, el último ${fechaCorta(e.ultimo_ingreso)}` : 'Aún sin ingresos'}
            </span>
          </span>
        </button>
      ))}
      <button type="button" role="radio" aria-checked={!elegido} className="servicio-equipo-opcion" disabled={disabled} onClick={() => onElegir(null)}>
        <span>
          <strong>Es otro equipo</strong>
          <span className="sub-texto">Registrar un equipo nuevo de este cliente.</span>
        </span>
      </button>
    </div>
  )
}

/** Avisa si el número de serie escrito ya ingresó antes (de este cliente o de otro). */
function AvisoSerie({ empresaId, serie, clienteId, onUsar, disabled }) {
  const buscada = useDebounce(serie.trim(), 500)
  const consulta = useQuery({
    queryKey: ['servicio', 'serie', empresaId, buscada],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/equipos/', { params: { empresa: empresaId, serie: buscada, page_size: 10 }, signal }).then((r) => r.data.results),
    enabled: buscada.length >= 3,
    staleTime: 15_000,
  })
  const coincidencias = buscada.length >= 3 ? (consulta.data ?? VACIO) : VACIO
  return coincidencias.map((e) => (
    <p key={e.id} className="servicio-aviso-serie" role="status">
      <span>
        Este número de serie ya ingresó {veces(e.n_ordenes)} ({nombreEquipo(e)}, de {e.cliente_nombre}).
      </span>
      {e.cliente === clienteId && (
        <button type="button" disabled={disabled} onClick={() => onUsar(e)}>
          Usar este equipo
        </button>
      )}
    </p>
  ))
}

/** El equipo que llega: uno que el cliente ya dejó antes, o los datos de uno nuevo. */
export default function EquipoIngreso({ b, poner, errores, tipos, empresaId, disabled }) {
  const nuevo = !b.equipoExistente
  const cambiar = (campo, valor) => poner('equipo', { ...b.equipo, [campo]: valor })
  const elegir = (equipo) => {
    poner('equipoExistente', equipo)
    if (!equipo) poner('equipo', equipoVacio())
  }

  return (
    <>
      {!b.cliente && <p className="celda-suave">Elige primero al cliente: así se ve si este equipo ya entró antes.</p>}
      {b.cliente && <EquiposDelCliente empresaId={empresaId} cliente={b.cliente} elegido={b.equipoExistente} onElegir={elegir} disabled={disabled} />}
      {nuevo && (
        <>
          <div className="fila-campos">
            <Campo etiqueta="Tipo de equipo" tipo="select" requerido error={errores.tipo}>
              {(p) => (
                <select {...p} value={b.equipo.tipo} disabled={disabled} onChange={(ev) => cambiar('tipo', ev.target.value)}>
                  <option value="">Elija el tipo</option>
                  {tipos.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.nombre}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Marca" error={errores.marca}>
              {(p) => <input {...p} maxLength={60} placeholder="Ej. HP" value={b.equipo.marca} disabled={disabled} onChange={(ev) => cambiar('marca', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Modelo">
              {(p) => <input {...p} maxLength={80} placeholder="Ej. Pavilion 15" value={b.equipo.modelo} disabled={disabled} onChange={(ev) => cambiar('modelo', ev.target.value)} />}
            </Campo>
          </div>
          <div className="fila-campos">
            <Campo etiqueta="Número de serie" ayuda="Está en una etiqueta del equipo. Sirve para ver su historial.">
              {(p) => <input {...p} maxLength={80} placeholder="Ej. 5CD123ABC" value={b.equipo.numero_serie} disabled={disabled} onChange={(ev) => cambiar('numero_serie', ev.target.value.toUpperCase())} />}
            </Campo>
            <Campo etiqueta="Color">
              {(p) => <input {...p} maxLength={40} placeholder="Ej. Plateado" value={b.equipo.color} disabled={disabled} onChange={(ev) => cambiar('color', ev.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Características" contador={{ actual: b.equipo.descripcion.length, max: 250 }} ayuda="Opcional: procesador, memoria, disco…">
            {(p) => <input {...p} maxLength={250} placeholder="Ej. Core i5, 8 GB RAM, SSD 256 GB" value={b.equipo.descripcion} disabled={disabled} onChange={(ev) => cambiar('descripcion', ev.target.value)} />}
          </Campo>
          <AvisoSerie empresaId={empresaId} serie={b.equipo.numero_serie} clienteId={b.cliente?.id} onUsar={(e) => poner('equipoExistente', e)} disabled={disabled} />
        </>
      )}
      {errores.equipo && (
        <p role="alert" className="campo-error">
          {typeof errores.equipo === 'string' ? errores.equipo : 'Revise los datos del equipo.'}
        </p>
      )}
    </>
  )
}
