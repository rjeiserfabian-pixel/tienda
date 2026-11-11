import { useState } from 'react'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { CompletarModal, MarcaModal, RangoModal } from '../components/AsistenciaModales'
import { useGrillaAsistencia } from '../hooks/useAsistencia'
import { numero } from '../rrhh'
import '../rrhh.css'

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

const hoy = new Date()

/** Un casillero de la grilla: el código marcado (o vacío) y, si hay, un punto por horas extra. */
function Casillero({ dia, marca, tipo, cubierto, puedeCargar, onAbrir }) {
  const inactivo = !cubierto || !puedeCargar
  const texto = marca ? marca.tipo : ''
  const conExtra = marca && Number(marca.horas_extra) > 0
  return (
    <td className="rh-celda" data-fuera={!cubierto || undefined} data-semana={dia.descanso_semanal || undefined} data-feriado={dia.feriado ? true : undefined}>
      <button
        type="button"
        data-cat={tipo?.categoria}
        data-vacia={!marca || undefined}
        disabled={inactivo}
        title={marca?.observacion || (cubierto ? undefined : 'Sin contrato este día')}
        aria-label={`${dia.numero}: ${texto || (cubierto ? 'sin marcar' : 'sin contrato')}`}
        onClick={onAbrir}
      >
        {texto}
        {conExtra && <i aria-hidden="true" title={`${numero(marca.horas_extra)} h extra`} />}
      </button>
    </td>
  )
}

/** Asistencia diaria del mes: trabajadores × días, con totales y marcas por casillero. */
export default function AsistenciaPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const permisoCargar = tiene('RRHH.ASISTENCIA.CARGAR')
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [busqueda, setBusqueda] = useState('')
  const [modal, setModal] = useState(null) // { tipo: 'marca' | 'rango' | 'completar', ... }
  const q = useDebounce(busqueda.trim(), 400)

  const consulta = useGrillaAsistencia({ empresa: empresaActivaId, anio, mes, q })
  const grilla = consulta.data
  // Con la planilla del mes cerrada la asistencia queda solo de lectura.
  const puedeCargar = permisoCargar && !grilla?.cerrado
  const porCodigo = Object.fromEntries((grilla?.tipos ?? []).map((t) => [t.codigo, t]))

  const mover = (delta) => {
    const total = anio * 12 + (mes - 1) + delta
    setAnio(Math.floor(total / 12))
    setMes((total % 12) + 1)
  }
  const sinMarcar = (grilla?.trabajadores ?? []).reduce((suma, t) => suma + t.totales.sin_marcar, 0)

  return (
    <main className="listado">
      <CabeceraListado icono="calendario" titulo="Asistencia" descripcion="Marca cada día de cada trabajador. De aquí sale la planilla del mes: lo que no se marca, no se paga ni se descuenta hasta completarlo.">
        <Buscador valor={busqueda} onCambio={setBusqueda} etiqueta="Buscar trabajador" placeholder="Buscar trabajador" />
        {puedeCargar && (
          <>
            <button type="button" className="boton-cabecera" onClick={() => setModal({ tipo: 'rango' })} disabled={!grilla?.trabajadores.length}>
              Marcar varios días
            </button>
            <button type="button" className="boton-cabecera primario" onClick={() => setModal({ tipo: 'completar' })} disabled={!grilla?.trabajadores.length}>
              Completar el mes
            </button>
          </>
        )}
      </CabeceraListado>

      <div className="rh-mes" role="group" aria-label="Mes">
        <button type="button" className="boton-cabecera" aria-label="Mes anterior" onClick={() => mover(-1)}>
          ‹
        </button>
        <strong>
          {MESES[mes - 1]} {anio}
        </strong>
        <button type="button" className="boton-cabecera" aria-label="Mes siguiente" onClick={() => mover(1)}>
          ›
        </button>
        {sinMarcar > 0 && (
          <span className="pildora mas" data-tono="ambar">
            {sinMarcar} día(s) sin marcar
          </span>
        )}
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(grilla)}>
        {grilla?.cerrado && (
          <p className="rh-aviso" role="status">
            La planilla de este mes está cerrada: la asistencia no se puede cambiar. Para corregirla, reabre la planilla en Planilla.
          </p>
        )}
        {grilla && grilla.trabajadores.length === 0 && (
          <p className="rh-aviso" role="status">
            No hay trabajadores con contrato en este mes. Registra el contrato en Trabajadores y vuelve aquí.
          </p>
        )}
        {grilla && grilla.trabajadores.length > 0 && (
          <>
            <div className="marco-tabla rh-grilla">
              <table className="tabla-datos">
                <caption className="sr-only">
                  Asistencia de {MESES[mes - 1]} {anio}
                </caption>
                <thead>
                  <tr>
                    <th className="rh-nombre">Trabajador</th>
                    {grilla.dias.map((d) => (
                      <th key={d.fecha} className="rh-celda" data-semana={d.descanso_semanal || undefined} data-feriado={d.feriado ? true : undefined} title={d.feriado || undefined}>
                        {d.numero}
                        <small>{d.semana}</small>
                      </th>
                    ))}
                    <th title="Días trabajados">Trab.</th>
                    <th title="Faltas">Fal.</th>
                    <th title="Horas extra">H.E.</th>
                    <th title="Días del contrato sin marcar">Pend.</th>
                  </tr>
                </thead>
                <tbody>
                  {grilla.trabajadores.map((t) => {
                    const cubiertos = new Set(t.cubiertos)
                    return (
                      <tr key={t.id}>
                        <th scope="row" className="rh-nombre">
                          {t.nombre_completo}
                          <span className="rh-sub">{t.numero_documento}</span>
                        </th>
                        {grilla.dias.map((d) => {
                          const marca = t.dias[d.fecha]
                          return <Casillero key={d.fecha} dia={d} marca={marca} tipo={marca && porCodigo[marca.tipo]} cubierto={cubiertos.has(d.fecha)} puedeCargar={puedeCargar} onAbrir={() => setModal({ tipo: 'marca', trabajador: t, dia: d, marca })} />
                        })}
                        <td className="centrado">{t.totales.laborados}</td>
                        <td className="centrado">{t.totales.faltas || '—'}</td>
                        <td className="centrado">{Number(t.totales.horas_extra) > 0 ? numero(t.totales.horas_extra) : '—'}</td>
                        <td className="centrado">
                          {t.totales.sin_marcar > 0 ? (
                            <span className="pildora mas" data-tono="ambar">
                              {t.totales.sin_marcar}
                            </span>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <ul className="rh-leyenda" aria-label="Leyenda">
              {grilla.tipos.map((t) => (
                <li key={t.id} data-cat={t.categoria}>
                  <strong>{t.codigo}</strong> {t.nombre}
                </li>
              ))}
            </ul>
          </>
        )}
      </EstadoConsulta>

      {modal?.tipo === 'marca' && <MarcaModal empresa={empresaActivaId} trabajador={modal.trabajador} dia={modal.dia} marca={modal.marca} tipos={grilla.tipos} onCerrar={() => setModal(null)} />}
      {modal?.tipo === 'rango' && <RangoModal empresa={empresaActivaId} anio={anio} mes={mes} trabajadores={grilla.trabajadores} tipos={grilla.tipos} onCerrar={() => setModal(null)} />}
      {modal?.tipo === 'completar' && <CompletarModal empresa={empresaActivaId} anio={anio} mes={mes} nombreMes={MESES[mes - 1]} onCerrar={() => setModal(null)} />}
    </main>
  )
}
