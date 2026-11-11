import { useState } from 'react'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { useReporte } from '../hooks/useReportes'
import { fechaCorta, soles } from '../rrhh'
import '../rrhh.css'

// Qué pide cada reporte: un mes, un año o nada.
const REPORTES = [
  { tipo: 'planilla', nombre: 'Planilla del mes', pide: 'mes', ayuda: 'Una fila por trabajador y una columna por concepto, como la hoja de Excel de siempre.' },
  { tipo: 'plame', nombre: 'Conceptos para el PLAME', pide: 'mes', ayuda: 'Apoyo para preparar el PLAME: conceptos con su código y la jornada de cada trabajador. Pide la planilla cerrada. No es el archivo oficial de la SUNAT.' },
  { tipo: 't-registro', nombre: 'Datos para el T-Registro', pide: null, ayuda: 'Datos de los trabajadores con contrato vigente, sin sueldos ni cuentas. Es un apoyo, no el archivo oficial.' },
  { tipo: 'anual', nombre: 'Resumen anual', pide: 'anio', ayuda: 'El neto de cada mes por trabajador, los totales del año y la renta de 5.ª retenida (planillas cerradas).' },
]

const hoy = new Date()
const mesActual = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}`

/** Muestra un valor del reporte según su tipo de columna. */
function celda(valor, tipo) {
  if (valor === null || valor === undefined || valor === '') return ''
  if (tipo === 'dinero') return soles(valor)
  if (tipo === 'fecha') return fechaCorta(valor)
  return valor
}

/** Reportes de planilla, PLAME, T-Registro y resumen anual: se ven aquí y se descargan en Excel. */
export default function ReportesPage() {
  const { empresaActivaId } = useEmpresas()
  const notificar = useNotificar()
  const [tipo, setTipo] = useState('planilla')
  const [mes, setMes] = useState(mesActual)
  const [anio, setAnio] = useState(String(hoy.getFullYear()))
  const [pedido, setPedido] = useState(null)
  const [error, setError] = useState('')
  const [bajando, setBajando] = useState(false)
  const reporte = REPORTES.find((r) => r.tipo === tipo)
  const consulta = useReporte(pedido)

  const parametros = () => ({
    empresa: empresaActivaId,
    ...(reporte.pide === 'mes' ? { periodo: mes } : {}),
    ...(reporte.pide === 'anio' ? { anio } : {}),
  })

  const ver = (evento) => {
    evento.preventDefault()
    setError('')
    if (reporte.pide === 'mes' && !/^\d{4}-\d{2}$/.test(mes)) return setError('Elija el mes.')
    if (reporte.pide === 'anio' && !/^\d{4}$/.test(anio)) return setError('Indique un año válido.')
    return setPedido({ tipo, params: parametros() })
  }

  const descargar = async () => {
    setBajando(true)
    setError('')
    try {
      const nombre = await descargarArchivo(`/rrhh/reportes/${pedido.tipo}/excel/`, pedido.params)
      notificar('exito', `Descargado: ${nombre}`)
    } catch (e) {
      setError(await mensajeDeErrorDescarga(e))
    } finally {
      setBajando(false)
    }
  }

  const r = consulta.data

  return (
    <main className="listado">
      <CabeceraListado icono="chart" titulo="Reportes de recursos humanos" descripcion="Para el contador y la gerencia. Se ven aquí y se descargan en Excel; lo que se descarga queda registrado." />

      <form onSubmit={ver} className="rh-tarjeta" noValidate>
        <div className="rh-fila-campos">
          <label className="campo">
            <span className="campo-etiqueta">Reporte</span>
            <select
              value={tipo}
              onChange={(e) => {
                setTipo(e.target.value)
                setPedido(null)
                setError('')
              }}
            >
              {REPORTES.map((x) => (
                <option key={x.tipo} value={x.tipo}>
                  {x.nombre}
                </option>
              ))}
            </select>
          </label>
          {reporte.pide === 'mes' && (
            <label className="campo">
              <span className="campo-etiqueta">Mes</span>
              <input type="month" value={mes} onChange={(e) => setMes(e.target.value)} />
            </label>
          )}
          {reporte.pide === 'anio' && (
            <label className="campo">
              <span className="campo-etiqueta">Año</span>
              <input inputMode="numeric" maxLength={4} value={anio} onChange={(e) => setAnio(e.target.value.replace(/\D/g, ''))} />
            </label>
          )}
        </div>
        <p className="celda-suave">{reporte.ayuda}</p>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="rh-acciones">
          <button type="submit" className="boton-cabecera primario" disabled={!empresaActivaId || consulta.isFetching}>
            {consulta.isFetching ? 'Armando…' : 'Ver reporte'}
          </button>
          {r && (
            <Can permiso="RRHH.REPORTES.EXPORTAR">
              <button type="button" className="boton-cabecera" disabled={bajando} onClick={descargar}>
                {bajando ? 'Descargando…' : 'Descargar Excel'}
              </button>
            </Can>
          )}
        </div>
      </form>

      {pedido && (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(r)}>
          {r && (
            <>
              <header>
                <h2 style={{ margin: 0 }}>{r.titulo}</h2>
                <p className="celda-suave">{r.subtitulo}</p>
              </header>
              {r.avisos.length > 0 && (
                <div className="rh-aviso" role="status">
                  <ul>
                    {r.avisos.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}
              {r.tablas.map((t) => (
                <section key={t.hoja} className="rh-opciones">
                  <h3 style={{ margin: 0 }}>{t.titulo}</h3>
                  <div className="marco-tabla rh-grilla">
                    <table className="tabla-datos">
                      <thead>
                        <tr>
                          {t.columnas.map((c) => (
                            <th key={c.titulo} className={c.tipo === 'dinero' || c.tipo === 'numero' ? 'derecha' : undefined}>
                              {c.titulo}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {t.filas.length === 0 && (
                          <tr>
                            <td colSpan={t.columnas.length}>No hay datos para mostrar.</td>
                          </tr>
                        )}
                        {t.filas.map((fila, i) => (
                          <tr key={`${t.hoja}-${i}`}>
                            {fila.map((valor, j) => (
                              <td key={t.columnas[j].titulo} className={t.columnas[j].tipo === 'dinero' || t.columnas[j].tipo === 'numero' ? 'derecha' : undefined}>
                                {celda(valor, t.columnas[j].tipo)}
                              </td>
                            ))}
                          </tr>
                        ))}
                        {t.totales && (
                          <tr>
                            {t.totales.map((valor, j) => (
                              <td key={t.columnas[j].titulo} className={t.columnas[j].tipo === 'dinero' ? 'derecha' : undefined}>
                                <strong>{celda(valor, t.columnas[j].tipo)}</strong>
                              </td>
                            ))}
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  {t.total_filas > t.filas.length && <p className="celda-suave">Se muestran {t.filas.length} de {t.total_filas} filas. El Excel trae todas.</p>}
                </section>
              ))}
            </>
          )}
        </EstadoConsulta>
      )}
    </main>
  )
}
