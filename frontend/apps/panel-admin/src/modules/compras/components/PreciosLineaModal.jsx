import { useState } from 'react'
import { Link } from 'react-router-dom'
import Modal from '../../../shared/components/Modal'
import { aNumero } from '../../almacen/utilidades'
import { inicialPrecios } from '../compras'
import { BloqueProducto } from './ActualizarPreciosModal'

/**
 * «PV» de una línea: deja preparados los precios de venta del producto mientras se arma la compra.
 * No se guarda nada todavía: los precios se aplican al registrar la compra, con el costo definitivo
 * (flete e IGV ya repartidos), en la ventana «Actualizar precios de venta». Así, si la compra no
 * se registra, los precios del producto no cambian.
 */
export default function PreciosLineaModal({ linea, costoUnitario, listas, onGuardar, onCerrar }) {
  const { producto } = linea
  const [estado, setEstado] = useState(() => inicialPrecios(costoUnitario ?? 0, producto, linea.ventaPrecios))

  const aplicar = () => {
    // Solo lo que tiene precio: las listas vacías no se tocan.
    const precios = Object.fromEntries(Object.entries(estado.precios).filter(([, p]) => aNumero(p.precio) !== null).map(([lista, p]) => [lista, { precio: p.precio }]))
    onGuardar(Object.keys(precios).length ? precios : null)
  }

  return (
    <Modal titulo="Precios de venta" subtitulo="Quedan preparados y se aplican al registrar la compra." onCerrar={onCerrar} ancho={720}>
      {costoUnitario ? (
        <p className="celda-suave">El costo mostrado es provisional (el de esta compra con el IGV y el flete que lleve). Al registrar se confirma con el valor definitivo.</p>
      ) : (
        <p className="compra-aviso">Todavía no hay costo calculado: elige el proveedor y escribe el precio de compra para ver la ganancia.</p>
      )}
      {listas.length === 0 && (
        <p className="compra-aviso">
          Aún no hay listas de precios. <Link to="/mantenimiento/listas-precio">Créalas aquí</Link> para poner precios de venta.
        </p>
      )}
      <div className="precios-lista">
        <BloqueProducto producto={{ nombre: producto.nombre, codigo: producto.codigo }} detalle={producto} listas={listas} estado={estado} costoFijo onCambio={setEstado} />
      </div>
      <div className="modal-pie">
        {linea.ventaPrecios && (
          <button type="button" onClick={() => onGuardar(null)}>
            Quitar lo preparado
          </button>
        )}
        <button type="button" onClick={onCerrar}>
          Cancelar
        </button>
        <button type="button" className="primario" onClick={aplicar}>
          Dejar preparado
        </button>
      </div>
    </Modal>
  )
}
