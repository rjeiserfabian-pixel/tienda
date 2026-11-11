import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../hooks/useOpciones'

/**
 * Filtros propios del reporte «Antigüedad del stock» (categoría, marca, solo lo antiguo) y los días
 * a partir de los cuales el stock se considera antiguo (se cambia con el permiso de configurar).
 */
export default function FiltrosAntiguedad({ empresaId, filtros, alCambiar }) {
  const { tiene } = usePermisos()
  const puedeConfigurar = tiene('INVENTARIO.CONFIGURAR')
  const categorias = useOpciones('/mantenimiento/categorias/')
  const marcas = useOpciones('/mantenimiento/marcas/')

  const config = useQuery({
    queryKey: ['antiguedad-config', empresaId],
    queryFn: ({ signal }) => api.get('/inventario/antiguedad/configuracion/', { params: { empresa: empresaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaId),
    staleTime: 60_000,
  })
  // Lo que se está escribiendo; mientras no se toque, se muestra lo guardado.
  const [editado, setEditado] = useState(null)
  const dias = editado ?? (config.data ? String(config.data.dias) : '')
  const setDias = setEditado

  const guardar = useMutacion({
    mutationFn: (valor) => api.patch('/inventario/antiguedad/configuracion/', { empresa: empresaId, dias: valor }).then((r) => r.data),
    invalidar: [['antiguedad-config'], ['reporte-vista'], ['inicio']],
    exito: 'Se guardaron los días.',
    alExito: () => setEditado(null),
  })
  const numero = Number(dias)
  const valido = Number.isInteger(numero) && numero >= 1 && numero <= 3650
  const cambio = config.data && String(config.data.dias) !== dias

  return (
    <div className="fila-campos">
      <Campo etiqueta="Categoría" tipo="select">
        {(p) => (
          <select {...p} value={filtros.categoria} onChange={(e) => alCambiar({ categoria: e.target.value })}>
            <option value="">Todas</option>
            {(categorias.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.nombre}</option>
            ))}
          </select>
        )}
      </Campo>
      <Campo etiqueta="Marca" tipo="select">
        {(p) => (
          <select {...p} value={filtros.marca} onChange={(e) => alCambiar({ marca: e.target.value })}>
            <option value="">Todas</option>
            {(marcas.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>{m.nombre}</option>
            ))}
          </select>
        )}
      </Campo>
      <label className="casilla-filtro">
        <input type="checkbox" checked={filtros.soloAntiguo} onChange={(e) => alCambiar({ soloAntiguo: e.target.checked })} />
        Solo con stock antiguo
      </label>
      <Campo
        etiqueta="Antiguo desde (días)"
        ayuda={puedeConfigurar ? 'El stock que lleva más de estos días se marca como antiguo.' : 'Lo define el administrador.'}
        error={dias !== '' && !valido ? 'Use un número de 1 a 3650.' : undefined}
      >
        {(p) => (
          <span className="campo-con-boton">
            <input {...p} type="number" min={1} max={3650} value={dias} disabled={!puedeConfigurar || config.isPending} onChange={(e) => setDias(e.target.value)} />
            {puedeConfigurar && (
              <button type="button" disabled={!cambio || !valido || guardar.isPending} onClick={() => guardar.mutate(numero)}>
                {guardar.isPending ? 'Guardando…' : 'Guardar'}
              </button>
            )}
          </span>
        )}
      </Campo>
    </div>
  )
}
