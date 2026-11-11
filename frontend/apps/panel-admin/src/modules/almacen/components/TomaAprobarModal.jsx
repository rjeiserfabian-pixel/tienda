import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useListado } from '../../../shared/hooks/useListado'
import { useAccionToma, useAjustesConSerie } from '../hooks/useToma'
import { cantidad, hoyIso, parsearSeries, serieValida } from '../inventario'
import { numeroToma, soles } from '../tomas'
import '../inventario.css'
import '../tomas.css'
import TomaSeriesAjuste from './TomaSeriesAjuste'

/** Fecha local (AAAA-MM-DD) de un instante ISO del servidor. */
const fechaLocal = (iso) => (iso ? new Date(iso).toLocaleDateString('en-CA') : hoyIso())

/** Revisa lo escrito en las series de cada producto: la cantidad exacta, el formato y que no se repitan. */
function revisarSeries(filas, textos) {
  const errores = {}
  for (const fila of filas) {
    const series = parsearSeries(textos[fila.producto] ?? '')
    const necesarias = Number(fila.cantidad)
    const mala = series.find((s) => !serieValida(s))
    if (series.length !== necesarias) errores[fila.producto] = `Indique ${necesarias} serie(s); escribió ${series.length}.`
    else if (mala) errores[fila.producto] = `«${mala}» no es válida (3 a 40 letras, números, guiones o puntos).`
    else if (new Set(series).size !== series.length) errores[fila.producto] = 'Hay series repetidas.'
  }
  return errores
}

function TarjetasResumen({ resumen }) {
  return (
    <dl className="toma-resumen">
      <div>
        <dt>Productos a ajustar</dt>
        <dd>{cantidad(resumen.productos_a_ajustar)}</dd>
        <dt>de {cantidad(resumen.productos_contados)} contados</dt>
      </div>
      <div data-tono={resumen.sobrantes ? 'sobra' : undefined}>
        <dt>Entran (sobrantes)</dt>
        <dd>{soles(resumen.importe_sobrante)}</dd>
        <dt>{cantidad(resumen.unidades_sobrantes)} unidades</dt>
      </div>
      <div data-tono={resumen.faltantes ? 'falta' : undefined}>
        <dt>Salen (faltantes)</dt>
        <dd>{soles(resumen.importe_faltante)}</dd>
        <dt>{cantidad(resumen.unidades_faltantes)} unidades</dt>
      </div>
      <div data-tono={Number(resumen.importe_neto) < 0 ? 'falta' : Number(resumen.importe_neto) > 0 ? 'sobra' : undefined}>
        <dt>Efecto neto en el inventario</dt>
        <dd>{soles(resumen.importe_neto)}</dd>
      </div>
    </dl>
  )
}

/**
 * Revisión y aprobación de una toma cerrada. Muestra QUÉ se va a entrar y sacar del Kardex (operación 28 de
 * SUNAT, «Ajuste por diferencia de inventario»), pide las series de los productos que las llevan y, al
 * aprobar, genera el ajuste. Todo o nada: si algo no se puede registrar, no se guarda nada.
 */
export default function TomaAprobarModal({ toma, onCerrar }) {
  const [fecha, setFecha] = useState(hoyIso())
  const [nota, setNota] = useState('')
  const [textos, setTextos] = useState({})
  const [errores, setErrores] = useState({})
  const [problemas, setProblemas] = useState([])
  const [general, setGeneral] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(10)

  const vista = useListado(['tomas', 'ajustes', toma.id], `/inventario/tomas/${toma.id}/ajustes/`, { page: pagina, page_size: tamano })
  const conSerie = useAjustesConSerie(toma.id)
  const filas = vista.data?.results ?? []
  const resumen = vista.data?.resumen
  const productosConSerie = conSerie.data ?? []

  const aprobar = useAccionToma(toma.id, 'aprobar', { exito: 'Toma aprobada: el ajuste ya está en el Kardex.', alExito: onCerrar })
  const listo = Boolean(resumen) && conSerie.isSuccess

  const enviar = (evento) => {
    evento.preventDefault()
    if (aprobar.isPending || !listo) return
    const revision = {}
    if (!fecha) revision.fecha = 'Indique la fecha del ajuste.'
    else if (fecha > hoyIso()) revision.fecha = 'La fecha no puede ser futura.'
    else if (fecha < fechaLocal(toma.fecha_corte)) revision.fecha = 'No puede ser anterior al corte de la toma.'
    const delasSeries = revisarSeries(productosConSerie, textos)
    setErrores({ ...revision, series: delasSeries })
    setProblemas([])
    setGeneral('')
    if (Object.keys(revision).length || Object.keys(delasSeries).length) return
    aprobar.mutate(
      {
        fecha,
        ...(nota.trim() ? { nota: nota.trim() } : {}),
        series: productosConSerie.map((f) => ({ producto: f.producto, series: parsearSeries(textos[f.producto]) })),
      },
      {
        onError: (error) => {
          const detalle = error?.response?.data?.error?.detalle
          if (codigoDeError(error) === 'ajuste_imposible' && Array.isArray(detalle?.productos)) setProblemas(detalle.productos)
          const delServidor = erroresDeCampo(error)
          if (delServidor.fecha) setErrores({ fecha: delServidor.fecha, series: {} })
          setGeneral(mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo="Revisar y aprobar la toma" subtitulo={`${numeroToma(toma.numero)} · ${toma.almacen_nombre}`} onCerrar={onCerrar} ancho={980}>
      <form onSubmit={enviar} noValidate>
        <p className="modal-aviso" role="status">
          Al aprobar se registran en el Kardex las entradas (sobrantes) y salidas (faltantes) de abajo, con la operación 28 de SUNAT. Se ajusta la diferencia real: antes se descuenta lo que ventas, compras y traspasos movieron entre el corte y el conteo de cada producto.
        </p>

        <EstadoConsulta consulta={vista} hayDatos={Boolean(vista.data)}>
          {resumen && <TarjetasResumen resumen={resumen} />}
          {resumen?.sin_costo > 0 && (
            <p className="campo-ayuda" role="status">
              {resumen.sin_costo} producto(s) no tenían costo al abrir la toma: si sobran, entran al costo promedio de hoy.
            </p>
          )}
          {resumen?.productos_a_ajustar === 0 && <p className="celda-suave">No hay diferencias que ajustar: al aprobar solo queda constancia del conteo.</p>}

          {filas.length > 0 && (
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th className="num">Sistema al corte</th>
                    <th className="num">Movido hasta el conteo</th>
                    <th className="num">Contado</th>
                    <th className="num">Ajuste</th>
                    <th className="num">Importe (costo)</th>
                  </tr>
                </thead>
                <tbody>
                  {filas.map((f) => (
                    <tr key={f.producto}>
                      <td>
                        <strong>{f.producto_nombre}</strong>
                        <span className="sub-texto">
                          {f.producto_codigo}
                          {f.lleva_serie ? ' · lleva serie' : ''}
                        </span>
                      </td>
                      <td className="num">{cantidad(f.stock_sistema)}</td>
                      <td className="num">{cantidad(f.movimientos_posteriores)}</td>
                      <td className="num">{cantidad(f.cantidad_contada)}</td>
                      <td className={`num ${f.tipo === 'SALIDA' ? 'toma-falta' : 'toma-sobra'}`}>
                        {f.tipo === 'SALIDA' ? 'Sale' : 'Entra'} {cantidad(f.cantidad)}
                      </td>
                      <td className="num">{soles(f.tipo === 'SALIDA' ? -Number(f.importe_estimado) : f.importe_estimado)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Paginacion pagina={pagina} tamano={tamano} total={vista.data?.count ?? 0} onPagina={setPagina} onTamano={(t) => { setTamano(t); setPagina(1) }} tamanos={[10, 25, 50]} />
          <p className="campo-ayuda">Una salida se valoriza al costo promedio del Kardex en la fecha del ajuste; el importe de la lista es una estimación al costo del corte.</p>
        </EstadoConsulta>

        {conSerie.isError && (
          <p role="alert" className="campo-error">
            No se pudo cargar la lista de productos con serie. {mensajeDeError(conSerie.error)}
          </p>
        )}
        {productosConSerie.length > 0 && (
          <fieldset className="toma-fieldset toma-series-bloque" disabled={aprobar.isPending}>
            <legend>Series de los productos que las llevan</legend>
            {productosConSerie.map((f) => (
              <TomaSeriesAjuste
                key={f.producto}
                fila={f}
                empresa={toma.empresa}
                almacen={toma.almacen}
                texto={textos[f.producto] ?? ''}
                onTexto={(texto) => setTextos((previo) => ({ ...previo, [f.producto]: texto }))}
                error={errores.series?.[f.producto]}
              />
            ))}
          </fieldset>
        )}

        <fieldset className="toma-fieldset" disabled={aprobar.isPending}>
          <div className="fila-campos">
            <Campo etiqueta="Fecha del ajuste" icono="calendario" requerido error={errores.fecha} ayuda="Hoy, o un día desde el corte de la toma.">
              {(p) => <input {...p} type="date" min={fechaLocal(toma.fecha_corte)} max={hoyIso()} value={fecha} onChange={(e) => setFecha(e.target.value)} />}
            </Campo>
            <Campo etiqueta="Nota de la aprobación" contador={{ actual: nota.length, max: 250 }}>
              {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={nota} onChange={(e) => setNota(e.target.value)} />}
            </Campo>
          </div>
        </fieldset>

        {problemas.length > 0 && (
          <div role="alert" className="campo-error">
            <strong>No se pudo generar el ajuste. Corrija esto y vuelva a intentar:</strong>
            <ul>
              {problemas.map((p) => (
                <li key={`${p.producto}-${p.motivo}`}>
                  {p.nombre ? `${p.nombre}: ` : ''}
                  {p.motivo}
                </li>
              ))}
            </ul>
          </div>
        )}
        {general && problemas.length === 0 && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}

        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={aprobar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={aprobar.isPending || !listo}>
            {aprobar.isPending ? 'Aprobando…' : 'Aprobar y ajustar el Kardex'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
