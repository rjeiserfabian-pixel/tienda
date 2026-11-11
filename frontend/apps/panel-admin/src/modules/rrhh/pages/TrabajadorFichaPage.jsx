import { useState } from 'react'
import { useParams } from 'react-router-dom'
import BotonVolver from '../../../shared/components/BotonVolver'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import ContratosTab from '../components/ContratosTab'
import DatosLaboralesForm from '../components/DatosLaboralesForm'
import { useTrabajador } from '../hooks/useTrabajadores'
import { fechaCorta } from '../rrhh'
import '../rrhh.css'

const PESTANAS = [
  ['datos', 'Datos laborales'],
  ['contratos', 'Contratos'],
]

/** La ficha laboral de un trabajador: sus datos laborales y su historial de contratos. */
export default function TrabajadorFichaPage() {
  const { id } = useParams()
  const [pestana, setPestana] = useState('datos')
  const consulta = useTrabajador(id)
  const ficha = consulta.data
  const p = ficha?.personal

  return (
    <main className="listado">
      <BotonVolver ruta="/rrhh/trabajadores" texto="Trabajadores" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(ficha)}>
        {ficha && (
          <>
            <header className="rh-tarjeta">
              <h2 style={{ margin: 0 }}>{p.nombre_completo}</h2>
              <dl className="rh-datos">
                <div>
                  <dt>Documento</dt>
                  <dd>
                    {p.tipo_documento} {p.numero_documento}
                  </dd>
                </div>
                <div>
                  <dt>Cargo</dt>
                  <dd>{p.cargo || '—'}</dd>
                </div>
                <div>
                  <dt>Ingreso</dt>
                  <dd>{fechaCorta(p.fecha_ingreso)}</dd>
                </div>
                <div>
                  <dt>Teléfono</dt>
                  <dd>{p.telefono || '—'}</dd>
                </div>
              </dl>
              <p className="celda-suave">Los datos de identificación se corrigen en Mantenimiento › Personal.</p>
            </header>

            {ficha.faltantes.length > 0 && (
              <div className="rh-aviso" role="status">
                Para poder calcularle la planilla falta:
                <ul>
                  {ficha.faltantes.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="rh-pestanas" role="tablist" aria-label="Secciones de la ficha">
              {PESTANAS.map(([valor, texto]) => (
                <button key={valor} type="button" role="tab" aria-selected={pestana === valor} onClick={() => setPestana(valor)}>
                  {texto}
                </button>
              ))}
            </div>

            {pestana === 'datos' && <DatosLaboralesForm key={JSON.stringify(ficha.datos_laborales)} trabajadorId={p.id} datos={ficha.datos_laborales} permisos={ficha.permisos} />}
            {pestana === 'contratos' && <ContratosTab trabajador={{ id: p.id, nombre_completo: p.nombre_completo, cargo: p.cargo, fecha_ingreso: p.fecha_ingreso }} contratos={ficha.contratos} permisos={ficha.permisos} />}
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
