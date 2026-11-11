import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { fechaCorta } from '../../almacen/inventario'
import { useConfiguracionServicio } from '../hooks/useConfiguracionServicio'
import { ESTADOS_ORDEN, PRIORIDADES } from '../servicio'
import '../../almacen/inventario.css'
import '../servicio-tecnico.css'

const VACIO = []

function Tarjeta({ t }) {
  return (
    <Link to={`/servicio-tecnico/ordenes/${t.id}`} className="tablero-tarjeta">
      <strong>{t.codigo}</strong>
      <span>{t.cliente}</span>
      <span className="sub-texto">{t.equipo}</span>
      <span className="sub-texto">{t.tecnico || 'Sin técnico'}</span>
      <span className="tablero-marcas">
        {t.prioridad === 'URGENTE' && (
          <span className="pildora" data-tono="rojo">
            Urgente
          </span>
        )}
        {t.es_garantia && (
          <span className="pildora" data-tono="cian">
            Garantía
          </span>
        )}
        {t.atrasada && (
          <span className="pildora" data-tono="ambar" title={`Prometida para el ${fechaCorta(t.fecha_promesa)}`}>
            Atrasada
          </span>
        )}
        {t.por_abandonar && (
          <span className="pildora" data-tono="rosa">
            Por abandonar
          </span>
        )}
        {t.dias_en_estado >= 1 && <span className="sub-texto">{t.dias_en_estado} d aquí</span>}
      </span>
    </Link>
  )
}

/** El taller de un vistazo: una columna por estado con las órdenes abiertas. Se actualiza solo cada minuto. */
export default function TableroPage() {
  const { empresaActivaId } = useEmpresas()
  const [filtros, setFiltros] = useState({ tecnico: '', prioridad: '', mias: false })
  const tecnicos = useConfiguracionServicio(empresaActivaId).data?.tecnicos ?? VACIO
  const params = { empresa: empresaActivaId, ...(filtros.tecnico ? { tecnico: filtros.tecnico } : {}), ...(filtros.prioridad ? { prioridad: filtros.prioridad } : {}), ...(filtros.mias ? { mias: 1 } : {}) }
  const consulta = useQuery({
    queryKey: ['servicio', 'tablero', params],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/tablero/', { params, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
    refetchInterval: 60_000,
    staleTime: 15_000,
  })
  const columnas = consulta.data?.columnas ?? VACIO
  const total = columnas.reduce((suma, c) => suma + c.cantidad, 0)

  return (
    <main className="listado">
      <CabeceraListado icono="tablero" titulo="Tablero del taller" descripcion={`${total} equipos en el taller. Cada columna es un estado; abre una orden para avanzarla.`}>
        <label className="campo-inline">
          <span className="sr-only">Técnico</span>
          <select value={filtros.tecnico} onChange={(e) => setFiltros({ ...filtros, tecnico: e.target.value })}>
            <option value="">Todos los técnicos</option>
            {tecnicos.map((t) => (
              <option key={t.id} value={t.id}>
                {t.nombre}
              </option>
            ))}
          </select>
        </label>
        <label className="campo-inline">
          <span className="sr-only">Prioridad</span>
          <select value={filtros.prioridad} onChange={(e) => setFiltros({ ...filtros, prioridad: e.target.value })}>
            <option value="">Todas las prioridades</option>
            {PRIORIDADES.map(([valor, texto]) => (
              <option key={valor} value={valor}>
                {texto}
              </option>
            ))}
          </select>
        </label>
        <label className="campo-inline">
          <input type="checkbox" checked={filtros.mias} onChange={(e) => setFiltros({ ...filtros, mias: e.target.checked })} /> Solo las mías
        </label>
      </CabeceraListado>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="tablero" role="list" aria-label="Estados del taller">
          {columnas.map((c) => (
            <section key={c.estado} className="tablero-columna" role="listitem" aria-label={c.nombre} data-vacia={c.cantidad === 0 ? 'si' : undefined}>
              <header>
                <span className="pildora" data-tono={ESTADOS_ORDEN[c.estado]?.tono ?? 'gris'}>
                  {c.nombre}
                </span>
                <b>{c.cantidad}</b>
              </header>
              {c.tarjetas.map((t) => (
                <Tarjeta key={t.id} t={t} />
              ))}
              {c.cantidad > c.tarjetas.length && <p className="sub-texto">Y {c.cantidad - c.tarjetas.length} más: búscalas en «Órdenes de servicio».</p>}
            </section>
          ))}
        </div>
      </EstadoConsulta>
    </main>
  )
}
