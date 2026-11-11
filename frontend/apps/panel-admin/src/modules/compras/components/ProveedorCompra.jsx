import { useRef, useState } from 'react'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import Can from '../../../shared/components/Can'
import { Icono } from '../../../shared/components/IconosPanel'
import MaestroModal from '../../mantenimiento/components/MaestroModal'
import { PROVEEDORES } from '../../mantenimiento/maestros'

const ZONAS = {
  DENTRO: { texto: 'En la región', tono: 'verde' },
  FUERA: { texto: 'Fuera de la región', tono: 'azul' },
}

/**
 * Proveedor de la compra: se busca por razón social o RUC mientras se escribe, o se registra uno
 * nuevo sin salir de la pantalla (queda elegido). La zona decide si la compra viene con IGV.
 */
export default function ProveedorCompra({ proveedor, onElegir, error, disabled }) {
  const [creando, setCreando] = useState(false)
  const entrada = useRef(null)
  const zona = ZONAS[proveedor?.zona]

  return (
    <div className="campo">
      <span className="compra-etiqueta">
        Proveedor <span className="requerido" aria-hidden="true">*</span>
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
              {proveedor.ciudad ? ` · ${proveedor.ciudad}` : ''}
            </span>
          </div>
          <span className="pildora" data-tono={zona?.tono ?? 'ambar'} title="La zona del proveedor decide si la compra es exonerada o lleva IGV.">
            {zona?.texto ?? 'Zona sin definir'}
          </span>
          {!disabled && (
            <button type="button" onClick={() => onElegir(null)}>
              Cambiar
            </button>
          )}
        </div>
      ) : (
        <div className="compra-proveedor-buscar">
          <BuscadorAsincrono
            clave="proveedores-compra"
            url="/mantenimiento/proveedores/"
            parametros={{ estado: 'ACTIVO' }}
            etiqueta="Buscar proveedor"
            placeholder="Busca por razón social o RUC…"
            icono="handshake"
            inputRef={entrada}
            autoFocus
            disabled={disabled}
            onElegir={onElegir}
            mostrar={(p) => (
              <>
                <strong>{p.nombre}</strong>
                <span className="sub-texto">
                  {p.tipo_documento} {p.numero_documento}
                  {p.ciudad ? ` · ${p.ciudad}` : ''}
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
      {proveedor && !proveedor.zona && (
        <small className="campo-ayuda">Sin zona definida el sistema asume compra con IGV. Defínela en la ficha del proveedor si es de la región.</small>
      )}
      {creando && <MaestroModal config={PROVEEDORES} onCerrar={() => setCreando(false)} alCrear={onElegir} />}
    </div>
  )
}
