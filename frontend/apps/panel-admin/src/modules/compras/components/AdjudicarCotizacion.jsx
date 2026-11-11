import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { cantidad as formatoCantidad } from '../../almacen/inventario'
import { dinero } from '../compras'
import { armarCuerpoAdjudicacion, ganadoresIniciales, maximoDe, precioUnitario, validarGanadores } from '../cotizaciones'

/**
 * Elegir ganadores: por cada producto, qué proveedor se lleva el pedido (por defecto el de menor
 * precio) y cuánta cantidad. De los ganadores salen órdenes de compra en borrador, una por proveedor.
 * Pueden ganar proveedores distintos por producto.
 */
export default function AdjudicarCotizacion({ cotizacion: c }) {
  const comp = c.comparativo
  const [elegidos, setElegidos] = useState(() => ganadoresIniciales(comp))
  const [abierto, setAbierto] = useState(false)
  const [error, setError] = useState('')
  const validacion = validarGanadores(comp, elegidos)
  const cuerpo = armarCuerpoAdjudicacion(comp, elegidos)
  const clave = useClaveIdempotente(cuerpo)
  const respondidas = comp.proveedores.filter((p) => p.estado === 'RESPONDIDA')

  const adjudicar = useMutacion({
    mutationFn: () => api.post(`/compras/cotizaciones/${c.id}/adjudicar/`, cuerpo, { headers: { 'Idempotency-Key': clave }, timeout: 60_000 }).then((r) => r.data),
    invalidar: [['compras']],
    exito: 'Cotización adjudicada. Se crearon las órdenes de compra en borrador.',
    alExito: () => setAbierto(false),
    avisarError: false,
  })

  const poner = (linea, campo, valor) => setElegidos((previos) => ({ ...previos, [linea]: { ...previos[linea], [campo]: valor } }))
  const elegirProveedor = (l, respuesta) => {
    const oferta = l.ofertas.find((o) => String(o.respuesta) === respuesta && o.precio_unitario !== null)
    setElegidos((previos) => ({ ...previos, [l.linea]: { respuesta, cantidad: oferta ? String(maximoDe(l, oferta)) : '' } }))
  }
  const confirmar = () => {
    if (adjudicar.isPending) return
    setError('')
    adjudicar.mutate(undefined, { onError: (e) => setError(Object.values(erroresDeCampo(e)).join(' ') || mensajeDeError(e)) })
  }

  if (respondidas.length === 0) return null
  return (
    <>
      <div className="marco-tabla compra-tabla">
        <table className="tabla-datos">
          <caption className="sr-only">Elegir el proveedor ganador de cada producto</caption>
          <thead>
            <tr>
              <th scope="col">Producto</th>
              <th scope="col">Proveedor ganador</th>
              <th scope="col" className="num">
                Cantidad
              </th>
              <th scope="col" className="num">
                Importe
              </th>
            </tr>
          </thead>
          <tbody>
            {comp.lineas.map((l) => {
              const g = elegidos[l.linea] ?? { respuesta: '', cantidad: '' }
              const oferta = l.ofertas.find((o) => String(o.respuesta) === g.respuesta && o.precio_unitario !== null)
              const importe = oferta ? Number(oferta.precio_unitario) * (Number(String(g.cantidad).replace(',', '.')) || 0) : 0
              const falla = validacion.porLinea[l.linea]
              const cotizaron = l.ofertas.filter((o) => o.precio_unitario !== null)
              return (
                <tr key={l.linea}>
                  <td className="col-texto">
                    {l.producto_nombre}
                    <span className="sub-texto">
                      Pedido: {formatoCantidad(l.cantidad)} {l.unidad}
                    </span>
                  </td>
                  <td>
                    <select aria-label={`Proveedor ganador de ${l.producto_nombre}`} value={g.respuesta} disabled={adjudicar.isPending || cotizaron.length === 0} onChange={(e) => elegirProveedor(l, e.target.value)}>
                      <option value="">{cotizaron.length === 0 ? 'Nadie cotizó' : 'No comprar este producto'}</option>
                      {cotizaron.map((o) => (
                        <option key={o.respuesta} value={o.respuesta}>
                          {comp.proveedores.find((p) => p.respuesta === o.respuesta)?.proveedor_nombre} · {precioUnitario(o.precio_unitario, comp.moneda)}
                          {o.es_mejor ? ' (mejor precio)' : ''}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="num">
                    <input aria-label={`Cantidad a comprar de ${l.producto_nombre}`} className="compra-numero" inputMode="decimal" value={g.cantidad} disabled={adjudicar.isPending || !g.respuesta} aria-invalid={Boolean(falla)} onChange={(e) => poner(l.linea, 'cantidad', e.target.value)} />
                    {falla && (
                      <small role="alert" className="campo-error">
                        {falla}
                      </small>
                    )}
                  </td>
                  <td className="num">{g.respuesta ? dinero(importe, comp.moneda) : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="cotiz-adjudicar-pie" aria-live="polite">
        <p>
          {validacion.asignadas > 0 ? (
            <>
              Se crearán <strong>{validacion.ordenes}</strong> {validacion.ordenes === 1 ? 'orden de compra' : 'órdenes de compra'} en borrador, por un estimado de <strong>{dinero(validacion.estimado, comp.moneda)}</strong> ({comp.precios_incluyen_igv ? 'con' : 'sin'} IGV). Las revisas y las emites desde Órdenes de compra.
            </>
          ) : (
            'Elige el proveedor de al menos un producto.'
          )}
        </p>
        {validacion.faltan.length > 0 && validacion.asignadas === 0 && Object.keys(validacion.porLinea).length > 0 && (
          <p role="alert" className="campo-error">
            {validacion.faltan.join(' ')}
          </p>
        )}
        <button type="button" className="primario boton-cabecera" disabled={!validacion.valido || adjudicar.isPending} onClick={() => setAbierto(true)}>
          <Icono nombre="checklist" tam={19} /> Adjudicar y crear órdenes
        </button>
      </div>

      {abierto && (
        <Modal titulo="Adjudicar cotización" subtitulo={c.codigo} onCerrar={() => !adjudicar.isPending && setAbierto(false)} ancho={520}>
          <p>
            Se crearán <strong>{validacion.ordenes}</strong> {validacion.ordenes === 1 ? 'orden de compra' : 'órdenes de compra'} en borrador con los precios y condiciones de cada ganador. Después de adjudicar, la cotización ya no se puede cambiar. ¿Continuar?
          </p>
          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}
          <div className="modal-pie">
            <button type="button" onClick={() => setAbierto(false)} disabled={adjudicar.isPending}>
              Cancelar
            </button>
            <button type="button" className="primario" onClick={confirmar} disabled={adjudicar.isPending}>
              {adjudicar.isPending ? 'Creando órdenes…' : 'Adjudicar'}
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

/** Lo que pasó al adjudicar: quién ganó cada producto, las órdenes creadas y lo ahorrado. */
export function ResultadoAdjudicacion({ cotizacion: c }) {
  const comp = c.comparativo
  const nombre = (respuesta) => comp.proveedores.find((p) => p.respuesta === respuesta)?.proveedor_nombre ?? '—'
  const ordenes = c.proveedores.filter((p) => p.orden)
  return (
    <>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Producto</th>
              <th>Ganador</th>
              <th className="num">Cantidad</th>
              <th className="num">Precio</th>
            </tr>
          </thead>
          <tbody>
            {comp.lineas.map((l) => {
              const oferta = l.ofertas.find((o) => o.respuesta === l.adjudicada_a)
              return (
                <tr key={l.linea}>
                  <td className="col-texto">{l.producto_nombre}</td>
                  <td>{l.adjudicada_a ? nombre(l.adjudicada_a) : <span className="celda-suave">No se compró</span>}</td>
                  <td className="num">{l.cantidad_adjudicada ? formatoCantidad(l.cantidad_adjudicada) : '—'}</td>
                  <td className="num">{oferta ? precioUnitario(oferta.precio_unitario, comp.moneda) : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {ordenes.length > 0 && (
        <ul className="cotiz-ordenes" aria-label="Órdenes de compra creadas">
          {ordenes.map((p) => (
            <li key={p.respuesta}>
              <Link to={`/compras/ordenes/${p.orden}`}>
                {p.orden_codigo} · {p.nombre}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {comp.ahorro !== null && Number(comp.ahorro) > 0 && (
        <p className="cotiz-ahorro" role="status">
          Ahorro frente al precio más alto cotizado: <strong>{dinero(comp.ahorro, comp.moneda)}</strong>
        </p>
      )}
    </>
  )
}
