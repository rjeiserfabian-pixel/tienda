import { useRef, useState } from 'react'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import Can from '../../../shared/components/Can'
import { Icono } from '../../../shared/components/IconosPanel'
import MaestroModal from '../../mantenimiento/components/MaestroModal'
import { PROVEEDORES } from '../../mantenimiento/maestros'

/**
 * Proveedor del gasto: quien emitió el comprobante (la empresa de luz, el dueño del local). Se busca
 * por razón social o RUC, o se registra uno nuevo sin salir de la pantalla. Con factura es obligatorio.
 */
export default function ProveedorGasto({ proveedor, onElegir, error, obligatorio, disabled }) {
  const [creando, setCreando] = useState(false)
  const entrada = useRef(null)

  return (
    <div className="campo">
      <span className="compra-etiqueta">
        Proveedor {obligatorio && <span className="requerido" aria-hidden="true">*</span>}
      </span>
      {proveedor ? (
        <div className="compra-proveedor-elegido">
          <span className="compra-proveedor-icono" aria-hidden="true">
            <Icono nombre="handshake" tam={24} />
          </span>
          <div className="compra-proveedor-datos">
            <strong>{proveedor.nombre}</strong>
            <span className="sub-texto">
              {proveedor.tipo_documento} {proveedor.numero_documento}
            </span>
          </div>
          {!disabled && (
            <button type="button" onClick={() => onElegir(null)}>
              Cambiar
            </button>
          )}
        </div>
      ) : (
        <div className="compra-proveedor-buscar">
          <BuscadorAsincrono
            clave="proveedores-gasto"
            url="/mantenimiento/proveedores/"
            parametros={{ estado: 'ACTIVO' }}
            etiqueta="Buscar proveedor"
            placeholder="Busca por razón social o RUC…"
            icono="handshake"
            inputRef={entrada}
            disabled={disabled}
            onElegir={onElegir}
            mostrar={(p) => (
              <>
                <strong>{p.nombre}</strong>
                <span className="sub-texto">
                  {p.tipo_documento} {p.numero_documento}
                  {p.nombre_comercial ? ` · ${p.nombre_comercial}` : ''}
                </span>
              </>
            )}
          />
          <Can permiso="MANTENIMIENTO.PROVEEDORES.CREAR" organizacion>
            <button type="button" className="boton-cabecera" disabled={disabled} onClick={() => setCreando(true)}>
              <Icono nombre="agregar" tam={19} /> Nuevo
            </button>
          </Can>
        </div>
      )}
      {error && (
        <small role="alert" className="campo-error">
          {error}
        </small>
      )}
      {!proveedor && !obligatorio && <small className="campo-ayuda">Opcional con boleta, ticket o recibo. Con factura es obligatorio.</small>}
      {creando && <MaestroModal config={PROVEEDORES} onCerrar={() => setCreando(false)} alCrear={onElegir} />}
    </div>
  )
}
