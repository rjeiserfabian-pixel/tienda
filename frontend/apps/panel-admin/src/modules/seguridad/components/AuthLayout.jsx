import { useId } from 'react'
import { MARCA } from '../../../core/marca'
import { IconoCategoria, LogoMarca } from './Iconos'
import './auth.css'

/**
 * Marco de las pantallas de acceso: columna de marca a la izquierda y la tarjeta a la derecha.
 * En pantallas pequeñas solo queda el logo y la tarjeta.
 */
export default function AuthLayout({ children }) {
  return (
    <div className="auth">
      <section className="auth-marca" aria-label={MARCA.nombre}>
        <div className="auth-cabecera">
          <LogoMarca />
          <div>
            <p className="auth-wordmark" role="img" aria-label={MARCA.nombre}>
              <span aria-hidden="true">{MARCA.nombrePrincipal}</span>
              <span className="acento" aria-hidden="true">
                {MARCA.nombreAcento}
              </span>
            </p>
            <p className="auth-lema">{MARCA.lema}</p>
          </div>
        </div>

        <ul className="auth-categorias" aria-hidden="true">
          {MARCA.categorias.map((c) => (
            <li key={c.texto}>
              <IconoCategoria nombre={c.icono} />
              {c.texto}
            </li>
          ))}
        </ul>

        <img className="auth-hero" src="/login-hero.jpg" alt="" aria-hidden="true" decoding="async" />

        <p className="auth-eslogan" aria-hidden="true">
          {MARCA.eslogan[0]}
          <span>{MARCA.eslogan[1]}</span>
          <svg viewBox="0 0 120 14" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
            <path d="M2 10c25-8 55-9 116-6" />
          </svg>
        </p>
      </section>

      <div className="auth-brillo">
        <div className="auth-borde">
          <main className="auth-tarjeta">{children}</main>
        </div>
      </div>
    </div>
  )
}

/**
 * Campo con icono y mensaje de error asociado. La etiqueta existe para lectores de pantalla
 * (el diseño usa el texto de ayuda dentro del campo).
 *
 *   <CampoAuth icono={<IconoUsuario />} etiqueta="Usuario o correo" error={e}>
 *     {(props) => <input {...props} placeholder="Usuario o correo" />}
 *   </CampoAuth>
 */
export function CampoAuth({ icono, etiqueta, error, derecha, children }) {
  const id = useId()
  const idError = `${id}-error`
  return (
    <div className="auth-campo">
      <label htmlFor={id} className="sr-only">
        {etiqueta}
      </label>
      <div className="auth-input" data-invalido={Boolean(error)}>
        {icono}
        {children({ id, 'aria-invalid': Boolean(error), 'aria-describedby': error ? idError : undefined })}
        {derecha}
      </div>
      {error && (
        <small id={idError} role="alert" className="auth-error">
          {error}
        </small>
      )}
    </div>
  )
}
