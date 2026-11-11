import { useState } from 'react'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { cantidad } from '../inventario'
import { soles } from '../tomas'
import '../tomas.css'

/**
 * Resultado del conteo: conformes, faltantes y sobrantes, valorizados al costo del corte. Solo lo ven
 * quienes pueden ver el stock del sistema (en un conteo a ciegas, quien aprueba). Se calcula en vivo.
 */
export default function TomaResultado({ toma, resultado, puedeDescargar }) {
  const notificar = useNotificar()
  const [descargando, setDescargando] = useState('')
  const neto = Number(resultado.importe_neto)

  const descargar = async (formato) => {
    if (descargando) return
    setDescargando(formato)
    try {
      const nombre = await descargarArchivo(`/inventario/tomas/${toma.id}/reporte/`, { formato })
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (error) {
      notificar('error', await mensajeDeErrorDescarga(error))
    } finally {
      setDescargando('')
    }
  }

  return (
    <section className="toma-panel" aria-label="Resultado del conteo">
      <header className="toma-panel-cabecera">
        <h3>Resultado</h3>
        {puedeDescargar && (
          <span className="toma-etiquetas">
            <button type="button" disabled={Boolean(descargando)} onClick={() => descargar('xlsx')}>
              {descargando === 'xlsx' ? 'Generando…' : 'Descargar Excel'}
            </button>
            <button type="button" disabled={Boolean(descargando)} onClick={() => descargar('pdf')}>
              {descargando === 'pdf' ? 'Generando…' : 'Descargar PDF'}
            </button>
          </span>
        )}
      </header>

      <dl className="toma-resumen">
        <div>
          <dt>Conformes</dt>
          <dd>{cantidad(resultado.conformes)}</dd>
        </div>
        <div data-tono={resultado.faltantes ? 'falta' : undefined}>
          <dt>Faltantes</dt>
          <dd>{soles(resultado.importe_faltante)}</dd>
          <dt>
            {cantidad(resultado.faltantes)} producto(s) · {cantidad(Math.abs(Number(resultado.unidades_faltantes)))} unidades
          </dt>
        </div>
        <div data-tono={resultado.sobrantes ? 'sobra' : undefined}>
          <dt>Sobrantes</dt>
          <dd>{soles(resultado.importe_sobrante)}</dd>
          <dt>
            {cantidad(resultado.sobrantes)} producto(s) · {cantidad(resultado.unidades_sobrantes)} unidades
          </dt>
        </div>
        <div data-tono={neto < 0 ? 'falta' : neto > 0 ? 'sobra' : undefined}>
          <dt>Diferencia neta</dt>
          <dd>{soles(resultado.importe_neto)}</dd>
        </div>
      </dl>
      <p className="campo-ayuda">
        Valorizado al costo promedio que tenía cada producto al abrir la toma, no al precio de venta. Mientras el conteo sigue abierto, el resultado se actualiza solo.
      </p>
    </section>
  )
}
