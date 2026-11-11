import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import { Icono } from '../../../shared/components/IconosPanel'
import { MAX_PROVEEDORES } from '../cotizaciones'

/** Proveedores a los que se les pedirá precio: se buscan por nombre o RUC y se pueden quitar. */
export default function ProveedoresElegidos({ proveedores, onProveedores, error, disabled }) {
  const llena = proveedores.length >= MAX_PROVEEDORES
  const agregar = (p) => {
    if (proveedores.some((x) => x.id === p.id) || llena) return
    onProveedores((previos) => [...previos, p])
  }
  const quitar = (id) => onProveedores((previos) => previos.filter((p) => p.id !== id))

  return (
    <div className="campo">
      <span className="compra-etiqueta">
        Proveedores a cotizar{' '}
        <small className="celda-suave">
          ({proveedores.length} de {MAX_PROVEEDORES})
        </small>
      </span>
      <BuscadorAsincrono
        clave="proveedores-cotizacion"
        url="/mantenimiento/proveedores/"
        parametros={{ estado: 'ACTIVO' }}
        etiqueta="Buscar proveedor"
        placeholder={llena ? 'Llegaste al máximo de proveedores' : 'Busca por razón social o RUC…'}
        icono="handshake"
        disabled={disabled || llena}
        onElegir={agregar}
        mostrar={(p) => (
          <>
            <strong>{p.nombre}</strong>
            <span className="sub-texto">
              {p.tipo_documento} {p.numero_documento}
              {p.ciudad ? ` · ${p.ciudad}` : ''}
            </span>
          </>
        )}
      />
      {proveedores.length === 0 ? (
        <small className="campo-ayuda">Puedes guardarla sin proveedores y sumarlos después desde su ficha.</small>
      ) : (
        <ul className="cotiz-chips" aria-label="Proveedores elegidos">
          {proveedores.map((p) => (
            <li key={p.id} className="compra-proveedor-elegido">
              <div className="compra-proveedor-datos">
                <strong>{p.nombre}</strong>
                <span className="sub-texto">
                  {p.tipo_documento} {p.numero_documento}
                </span>
              </div>
              {!disabled && (
                <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar a ${p.nombre}`} title="Quitar" onClick={() => quitar(p.id)}>
                  <Icono nombre="papelera" tam={19} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <small role="alert" className="campo-error">
          {error}
        </small>
      )}
    </div>
  )
}
