import { useState } from 'react'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import BoletaVistaPrevia from '../components/BoletaVistaPrevia'
import { useMiResumen } from '../hooks/useReportes'
import { fechaCorta, mesAnio, numero, soles } from '../rrhh'
import '../rrhh.css'

/** Lo propio del trabajador: sus boletas de pago, su saldo de vacaciones y lo que debe de adelantos. */
export default function MiPortalPage() {
  const { empresaActivaId } = useEmpresas()
  const consulta = useMiResumen(empresaActivaId)
  const [boleta, setBoleta] = useState(null)
  const m = consulta.data

  return (
    <main className="listado">
      <CabeceraListado icono="documento" titulo="Mis boletas" descripcion="Tus boletas de pago, tus vacaciones y tus adelantos. Solo ves lo tuyo." />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(m)}>
        {m && (
          <>
            <section className="rh-tarjeta">
              <h3>{m.nombre_completo}</h3>
              {m.vacaciones ? (
                <dl className="rh-datos">
                  <div>
                    <dt>Vacaciones ganadas</dt>
                    <dd>{numero(m.vacaciones.ganados)} días</dd>
                  </div>
                  <div>
                    <dt>Vacaciones tomadas</dt>
                    <dd>{m.vacaciones.tomados} días</dd>
                  </div>
                  <div>
                    <dt>Saldo de vacaciones</dt>
                    <dd>
                      <strong>{numero(m.vacaciones.saldo)} días</strong>
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="celda-suave">Todavía no tienes un contrato registrado.</p>
              )}
            </section>

            <div className="marco-tabla">
              <table className="tabla-datos">
                <caption style={{ textAlign: 'left', padding: '6px 10px' }}>
                  <strong>Boletas de pago</strong>
                </caption>
                <thead>
                  <tr>
                    <th>Mes</th>
                    <th className="derecha">Ingresos</th>
                    <th className="derecha">Descuentos</th>
                    <th className="derecha">Neto</th>
                    <th>Pago</th>
                    <th className="centrado">Boleta</th>
                  </tr>
                </thead>
                <tbody>
                  {m.boletas.length === 0 && <FilaVacia columnas={6} icono="documento" titulo="Todavía no tienes boletas" descripcion="Aparecen cuando se cierra la planilla de cada mes." />}
                  {m.boletas.map((b) => (
                    <tr key={b.planilla}>
                      <td style={{ textTransform: 'capitalize' }}>
                        <strong>{mesAnio(b.periodo)}</strong>
                      </td>
                      <td className="derecha">{soles(b.total_ingresos)}</td>
                      <td className="derecha">{soles(b.total_descuentos)}</td>
                      <td className="derecha">
                        <strong>{soles(b.neto)}</strong>
                      </td>
                      <td>
                        <span className="pildora mas" data-tono={b.fecha_pago ? 'verde' : 'ambar'}>
                          {b.fecha_pago ? `Pagado ${fechaCorta(b.fecha_pago)}` : 'Por pagar'}
                        </span>
                      </td>
                      <td className="centrado">
                        <span className="acciones-fila">
                          <button type="button" className="accion-icono ver" aria-label={`Ver mi boleta de ${mesAnio(b.periodo)}`} title="Ver e imprimir la boleta" onClick={() => setBoleta(b.planilla)}>
                            <Icono nombre="ojo" tam={19} />
                          </button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {m.adelantos.length > 0 && (
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <caption style={{ textAlign: 'left', padding: '6px 10px' }}>
                    <strong>Adelantos y préstamos por descontar</strong>
                  </caption>
                  <thead>
                    <tr>
                      <th>N°</th>
                      <th>Tipo</th>
                      <th>Fecha</th>
                      <th className="derecha">Monto</th>
                      <th className="derecha">Falta descontar</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.adelantos.map((a) => (
                      <tr key={a.numero}>
                        <td>{String(a.numero).padStart(6, '0')}</td>
                        <td>{a.tipo_nombre}</td>
                        <td>{fechaCorta(a.fecha)}</td>
                        <td className="derecha">{soles(a.monto)}</td>
                        <td className="derecha">
                          <strong>{soles(a.pendiente)}</strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </EstadoConsulta>
      {boleta && <BoletaVistaPrevia url={`/rrhh/mi/boletas/${boleta}/?empresa=${empresaActivaId}`} onCerrar={() => setBoleta(null)} />}
    </main>
  )
}
