import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { ATAJOS_RANGO } from '../../almacen/reportes'
import { dinero } from '../compras'
import '../../almacen/inventario.css'
import '../compras.css'

const TOTALES = [
  ['gravada', 'Base gravada'],
  ['igv', 'IGV'],
  ['exonerada', 'Exonerada'],
  ['inafecta', 'Inafecta'],
  ['total', 'Total'],
]

/** Registro de compras: lo comprado en un rango de fechas, para ver en pantalla y descargar en Excel (contador). */
export default function RegistroComprasPage() {
  const { empresaActivaId } = useEmpresas()
  const notificar = useNotificar()
  const [rango, setRango] = useState(() => ATAJOS_RANGO[0].rango())
  const [incluirGastos, setIncluirGastos] = useState(true)
  const [incluirDevoluciones, setIncluirDevoluciones] = useState(true)
  const [descargando, setDescargando] = useState(false)
  const [errorDescarga, setErrorDescarga] = useState('')

  const pendiente = (() => {
    if (!empresaActivaId) return 'Elija una empresa.'
    if (!rango.desde || !rango.hasta) return 'Indique desde y hasta.'
    if (rango.desde > rango.hasta) return '«Desde» no puede ser posterior a «Hasta».'
    if (rango.hasta > hoyIso()) return '«Hasta» no puede ser una fecha futura.'
    return ''
  })()
  const params = { empresa: empresaActivaId, ...rango, incluir_gastos: incluirGastos ? 1 : 0, incluir_devoluciones: incluirDevoluciones ? 1 : 0 }

  const vista = useQuery({
    queryKey: ['compras', 'registro-vista', params],
    queryFn: ({ signal }) => api.get('/compras/reportes/registro-compras/vista/', { params, signal }).then((r) => r.data),
    enabled: !pendiente,
    staleTime: 30_000,
    retry: false,
  })
  const datos = vista.data

  const descargar = async () => {
    if (descargando || pendiente) return
    setErrorDescarga('')
    setDescargando(true)
    try {
      const nombre = await descargarArchivo('/compras/reportes/registro-compras/', params)
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (e) {
      setErrorDescarga(await mensajeDeErrorDescarga(e))
    } finally {
      setDescargando(false)
    }
  }

  return (
    <main className="listado">
      <CabeceraListado icono="documento" titulo="Registro de compras" descripcion="Los comprobantes de compra vigentes de la empresa, con base, IGV y total en soles. Las compras anuladas no aparecen y las devoluciones a proveedores restan." />
      <div className="panel-reportes">
        <div className="fila-campos">
          <Campo etiqueta="Desde" icono="calendario">
            {(p) => <input {...p} type="date" max={hoyIso()} value={rango.desde} onChange={(e) => setRango((r) => ({ ...r, desde: e.target.value }))} />}
          </Campo>
          <Campo etiqueta="Hasta" icono="calendario">
            {(p) => <input {...p} type="date" max={hoyIso()} value={rango.hasta} onChange={(e) => setRango((r) => ({ ...r, hasta: e.target.value }))} />}
          </Campo>
        </div>
        <label className="casilla">
          <input type="checkbox" checked={incluirGastos} onChange={(e) => setIncluirGastos(e.target.checked)} /> Incluir los gastos con comprobante (luz, alquiler, internet…)
        </label>
        <label className="casilla">
          <input type="checkbox" checked={incluirDevoluciones} onChange={(e) => setIncluirDevoluciones(e.target.checked)} /> Incluir las devoluciones a proveedores (notas de crédito, restan)
        </label>
        <div className="atajos" aria-label="Atajos de periodo">
          {ATAJOS_RANGO.map((a) => {
            const activo = a.rango().desde === rango.desde && a.rango().hasta === rango.hasta
            return (
              <button key={a.id} type="button" className={`atajo${activo ? ' activo' : ''}`} aria-pressed={activo} onClick={() => setRango(a.rango())}>
                {a.texto}
              </button>
            )
          })}
        </div>
        <div className="acciones-reporte">
          <span className="celda-suave">{pendiente || 'El archivo trae todas las filas del periodo.'}</span>
          <button type="button" className="primario" disabled={descargando || Boolean(pendiente)} onClick={descargar}>
            <Icono nombre="exportar" tam={19} /> {descargando ? 'Generando…' : 'Excel'}
          </button>
        </div>
        {errorDescarga && (
          <p role="alert" className="campo-error">
            {errorDescarga}
          </p>
        )}
      </div>

      {pendiente ? (
        <p className="estado-vacio">{pendiente}</p>
      ) : (
        <EstadoConsulta consulta={vista} hayDatos={Boolean(datos)}>
          {datos && (
            <>
              <dl className="cxp-tarjetas" aria-label="Totales en soles">
                {TOTALES.map(([clave, texto]) => (
                  <div key={clave}>
                    <dt>{texto}</dt>
                    <dd>{dinero(datos.totales[clave])}</dd>
                    <small>En soles</small>
                  </div>
                ))}
              </dl>
              <div className="marco-tabla">
                <table className="tabla-datos">
                  <thead>
                    <tr>
                      <th>N°</th>
                      <th>Emisión</th>
                      <th>Comprobante</th>
                      <th>Proveedor</th>
                      <th className="num">Gravada</th>
                      <th className="num">IGV</th>
                      <th className="num">Exonerada</th>
                      <th className="num">Inafecta</th>
                      <th className="num">Total</th>
                      <th className="num">Total en soles</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datos.filas.length === 0 && <FilaVacia columnas={10} icono="documento" titulo="No hay compras en ese periodo" descripcion="Prueba con otro rango de fechas." />}
                    {datos.filas.map((f) => (
                      <tr key={`${f.origen}-${f.numero}`}>
                        <td className="celda-suave">{String(f.numero).padStart(6, '0')}</td>
                        <td>{fechaCorta(f.fecha)}</td>
                        <td>
                          {f.serie ? `${f.serie}-` : ''}
                          {f.comprobante}
                          <span className="sub-texto">
                            {f.tipo_nombre}
                            {f.origen === 'GASTO' ? ' · Gasto' : ''}
                            {f.origen === 'DEVOLUCION' ? ` · Devolución · modifica ${f.modifica}` : ''}
                          </span>
                        </td>
                        <td className="col-texto">
                          {f.proveedor}
                          <span className="sub-texto">{f.tipo_documento} {f.documento}</span>
                        </td>
                        <td className="num">{dinero(f.gravada, f.moneda)}</td>
                        <td className="num">{dinero(f.igv, f.moneda)}</td>
                        <td className="num">{dinero(f.exonerada, f.moneda)}</td>
                        <td className="num">{dinero(f.inafecta, f.moneda)}</td>
                        <td className="num">{dinero(f.total, f.moneda)}</td>
                        <td className="num">{dinero(f.total_soles)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {datos.truncado && <p className="celda-suave">Se muestran las primeras {datos.filas.length} de {datos.total_filas} filas. El Excel trae todas.</p>}
            </>
          )}
        </EstadoConsulta>
      )}
    </main>
  )
}
