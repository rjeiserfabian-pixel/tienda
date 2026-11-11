import Campo from '../../../shared/components/Campo'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'

/**
 * Cuando el carrito mezcla productos de las dos empresas: dos comprobantes (lo normal) o uno solo.
 * Con uno solo, lo de la otra empresa le pasa antes a la que factura, al costo y sin margen.
 * Solo lo ve quien tiene el permiso de venta interna (la pantalla ya lo decide).
 */
export default function VentaInternaVenta({ empresas, empresasDelCarrito, facturarPor, documento, documentos, disabled, onFacturarPor, onDocumento }) {
  const enCarrito = empresas.filter((e) => empresasDelCarrito.includes(e.id))
  const quien = enCarrito.find((e) => e.id === facturarPor)
  const otras = enCarrito.filter((e) => e.id !== facturarPor)
  const elegido = documentos.find((d) => d.codigo === documento)

  return (
    <PanelTarjeta icono="swap" titulo="Cómo se emite" descripcion="Este carrito tiene productos de las dos empresas. Normalmente cada una emite su comprobante; si lo prefieres, se emite uno solo.">
      <div className="pos-bloques">
        <div className="segmentos" role="radiogroup" aria-label="Cómo se emite la venta">
          <button type="button" role="radio" aria-checked={!facturarPor} className={!facturarPor ? 'activo' : undefined} disabled={disabled} onClick={() => onFacturarPor(null)}>
            Dos comprobantes
          </button>
          {enCarrito.map((e) => (
            <button key={e.id} type="button" role="radio" aria-checked={facturarPor === e.id} className={facturarPor === e.id ? 'activo' : undefined} disabled={disabled} onClick={() => onFacturarPor(e.id)}>
              Uno solo · {e.nombre}
            </button>
          ))}
        </div>
        {quien && (
          <>
            <p className="celda-suave" role="status">
              {otras.map((e) => e.nombre).join(' y ')} le pasa a {quien.nombre} lo que vende, al costo y sin margen. Después {quien.nombre} lo vende al cliente en un solo comprobante y el cobro entra a su caja.
            </p>
            <Campo etiqueta="Respaldo de lo que pasa entre las empresas" tipo="select" ayuda={elegido?.motivo || undefined}>
              {(p) => (
                <select {...p} value={documento} disabled={disabled} onChange={(e) => onDocumento(e.target.value)}>
                  {documentos.map((d) => (
                    <option key={d.codigo} value={d.codigo} disabled={Boolean(d.motivo)}>
                      {d.nombre}
                      {d.motivo ? ' (todavía no disponible)' : ''}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
          </>
        )}
      </div>
    </PanelTarjeta>
  )
}
