import { useMemo, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import { Icono } from '../../../shared/components/IconosPanel'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { AREAS, REPORTES } from '../reportes'
import './reportes.css'

const normalizar = (t) => t.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

/** Centro de reportes: reúne en un solo lugar los reportes de todos los módulos. */
export default function CentroReportesPage() {
  const { area } = useParams()
  const { tiene } = usePermisos()
  const [texto, setTexto] = useState('')

  const areaActual = AREAS.find((a) => a.clave === area)
  const visibles = useMemo(() => {
    const q = normalizar(texto.trim())
    return REPORTES.filter((r) => tiene(r.permiso))
      .filter((r) => !areaActual || r.area === areaActual.clave)
      .filter((r) => !q || normalizar(`${r.nombre} ${r.detalle}`).includes(q))
  }, [tiene, areaActual, texto])

  if (area && !areaActual) return <Navigate to="/reportes" replace />

  const grupos = AREAS.map((a) => ({ ...a, items: visibles.filter((r) => r.area === a.clave) })).filter(
    (g) => g.items.length,
  )

  return (
    <main className="centro-reportes">
      <CabeceraListado
        icono="chart"
        titulo={areaActual ? `Reportes de ${areaActual.nombre}` : 'Todos los reportes'}
        descripcion="Entra al reporte que necesitas. Solo ves los que tu rol permite."
      >
        <label className="buscador-reportes">
          <Icono nombre="buscar" tam={18} />
          <input
            type="search"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Buscar reporte…"
            aria-label="Buscar reporte"
          />
        </label>
      </CabeceraListado>

      {grupos.length === 0 && <p className="estado-vacio">No hay reportes que mostrar.</p>}

      {grupos.map((g) => (
        <section key={g.clave} className="reportes-grupo" aria-labelledby={`rep-${g.clave}`}>
          <h3 id={`rep-${g.clave}`}>
            <Icono nombre={g.icono} tam={20} /> {g.nombre}
          </h3>
          <div className="reportes-rejilla">
            {g.items.map((r) => (
              <Link key={r.ruta} to={r.ruta} className="reporte-tarjeta">
                <strong>{r.nombre}</strong>
                <span>{r.detalle}</span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </main>
  )
}
