import { useRef, useState } from 'react'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import Can from '../../../shared/components/Can'
import { Icono } from '../../../shared/components/IconosPanel'
import MaestroModal from '../../mantenimiento/components/MaestroModal'
import { CLIENTES } from '../../mantenimiento/maestros'

/** El cliente que deja el equipo: se busca por nombre o documento, o se registra uno nuevo sin salir de la pantalla. */
export default function ClienteIngreso({ cliente, onElegir, error, disabled }) {
  const [creando, setCreando] = useState(false)
  const entrada = useRef(null)

  return (
    <div className="campo">
      <span className="compra-etiqueta">
        Cliente <span className="requerido" aria-hidden="true">*</span>
      </span>
      {cliente ? (
        <div className="compra-proveedor-elegido">
          <span className="compra-proveedor-icono" aria-hidden="true">
            <Icono nombre="user" tam={22} />
          </span>
          <div className="compra-proveedor-datos">
            <strong>{cliente.nombre}</strong>
            <span className="sub-texto">
              {cliente.tipo_documento} {cliente.numero_documento}
              {cliente.telefono ? ` · ${cliente.telefono}` : ''}
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
            clave="clientes-servicio"
            url="/mantenimiento/clientes/"
            parametros={{ estado: 'ACTIVO' }}
            etiqueta="Buscar cliente"
            placeholder="Busca por nombre, DNI o RUC…"
            icono="user"
            inputRef={entrada}
            disabled={disabled}
            onElegir={onElegir}
            mostrar={(c) => (
              <>
                <strong>{c.nombre}</strong>
                <span className="sub-texto">
                  {c.tipo_documento} {c.numero_documento}
                </span>
              </>
            )}
          />
          <Can permiso="MANTENIMIENTO.CLIENTES.CREAR" organizacion>
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
      {creando && <MaestroModal config={CLIENTES} onCerrar={() => setCreando(false)} alCrear={onElegir} />}
    </div>
  )
}
