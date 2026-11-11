import { useId } from 'react'
import { Icono } from './IconosPanel'
import './modal.css'

/**
 * Campo de formulario accesible: etiqueta, control y mensaje de error asociados.
 *
 *   <Campo etiqueta="Nombre" requerido icono="user" error={errores.nombre}>
 *     {(props) => <input {...props} value={...} onChange={...} />}
 *   </Campo>
 *
 * Opciones: `icono` (dibujado dentro del campo), `requerido` (asterisco), `derecha` (elemento a
 * la derecha, p. ej. el ojo de la contraseña), `contador` ({actual, max}) y `tipo="select"`
 * (agrega la flecha de lista). `clase` agrega una clase al contenedor (p. ej. para fijar su ancho).
 */
export default function Campo({ etiqueta, error, ayuda, icono, requerido, derecha, contador, tipo, clase, children }) {
  const id = useId()
  const idError = `${id}-error`
  const idAyuda = `${id}-ayuda`
  const propiedades = {
    id,
    'aria-invalid': Boolean(error),
    'aria-describedby': [error && idError, ayuda && idAyuda].filter(Boolean).join(' ') || undefined,
    'aria-required': requerido || undefined,
  }
  const control = children(propiedades)

  return (
    <div className={clase ? `campo ${clase}` : 'campo'}>
      <label htmlFor={id}>
        {etiqueta}
        {requerido && (
          <span className="requerido" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {icono || derecha || tipo === 'select' ? (
        <div className="campo-icono">
          {icono && <Icono nombre={icono} tam={20} className="icono-izq" />}
          {control}
          {tipo === 'select' && <Icono nombre="chevronAbajo" tam={18} className="icono-der" />}
          {derecha}
        </div>
      ) : (
        control
      )}
      {contador && (
        <small className="campo-contador" aria-hidden="true">
          {contador.actual}/{contador.max}
        </small>
      )}
      {ayuda && (
        <small id={idAyuda} className="campo-ayuda">
          {ayuda}
        </small>
      )}
      {error && (
        <small id={idError} role="alert" className="campo-error">
          {error}
        </small>
      )}
    </div>
  )
}
