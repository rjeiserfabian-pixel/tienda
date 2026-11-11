// Iconos en SVG propio (sin librerías externas): ligeros y sin pedir nada a internet.

const trazo = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Base({ tam = 24, children, ...resto }) {
  return (
    <svg width={tam} height={tam} viewBox="0 0 24 24" aria-hidden="true" focusable="false" {...trazo} {...resto}>
      {children}
    </svg>
  )
}

export { LogoMarca } from '../../../shared/components/LogoMarca'

export const IconoUsuario = (p) => (
  <Base {...p}>
    <circle cx="12" cy="8" r="3.6" />
    <path d="M4.5 20c.8-3.6 3.7-5.6 7.5-5.6s6.7 2 7.5 5.6" />
  </Base>
)

export const IconoCandado = (p) => (
  <Base {...p}>
    <rect x="5" y="10.5" width="14" height="10" rx="2.2" />
    <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    <circle cx="12" cy="15.5" r="1.2" fill="currentColor" stroke="none" />
  </Base>
)

export const IconoOjo = (p) => (
  <Base {...p}>
    <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
    <circle cx="12" cy="12" r="3" />
  </Base>
)

export const IconoOjoTachado = (p) => (
  <Base {...p}>
    <path d="M3 3l18 18" />
    <path d="M10.6 6a10 10 0 0 1 1.4-.1c6.4 0 10 6.1 10 6.1a17 17 0 0 1-3 3.7M6.4 7.6A17 17 0 0 0 2 12s3.6 6.1 10 6.1a9.7 9.7 0 0 0 3.5-.7" />
    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
  </Base>
)

export const IconoFlecha = (p) => (
  <Base {...p}>
    <path d="M4 12h15M13 6l6 6-6 6" />
  </Base>
)

export const IconoEscudo = (p) => (
  <Base {...p}>
    <path d="M12 3l7.5 3v5.5c0 4.6-3.1 8.2-7.5 9.5-4.4-1.3-7.5-4.9-7.5-9.5V6L12 3z" />
    <path d="M8.8 12.2l2.3 2.3 4.2-4.6" />
  </Base>
)

export function IconoGoogle({ tam = 24 }) {
  return (
    <svg width={tam} height={tam} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.9 2.4 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4 7.1-10 7.1-17.5z" />
      <path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 0 1 0-9.4l-7.9-6.1a24 24 0 0 0 0 21.6l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  )
}

export function IconoMicrosoft({ tam = 24 }) {
  return (
    <svg width={tam} height={tam} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="9.5" height="9.5" fill="#f25022" />
      <rect x="12.5" y="2" width="9.5" height="9.5" fill="#7fba00" />
      <rect x="2" y="12.5" width="9.5" height="9.5" fill="#00a4ef" />
      <rect x="12.5" y="12.5" width="9.5" height="9.5" fill="#ffb900" />
    </svg>
  )
}

const CATEGORIAS = {
  laptop: (
    <>
      <rect x="4.5" y="5" width="15" height="11" rx="1.2" />
      <path d="M2 19.5h20M9.5 19.5l.6-3.5h3.8l.6 3.5" />
    </>
  ),
  repuestos: (
    <>
      <rect x="7" y="7" width="10" height="10" rx="1.4" />
      <rect x="10" y="10" width="4" height="4" />
      <path d="M9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4" />
    </>
  ),
  auriculares: (
    <>
      <path d="M4 14v-2a8 8 0 0 1 16 0v2" />
      <rect x="3.5" y="14" width="4" height="6.5" rx="1.4" />
      <rect x="16.5" y="14" width="4" height="6.5" rx="1.4" />
    </>
  ),
  cpu: (
    <>
      <rect x="5" y="5" width="14" height="14" rx="2" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
      <path d="M8 2v3M12 2v3M16 2v3M8 19v3M12 19v3M16 19v3M2 8h3M2 12h3M2 16h3M19 8h3M19 12h3M19 16h3" />
    </>
  ),
  ram: (
    <>
      <rect x="2" y="7" width="20" height="9" rx="1.2" />
      <path d="M6 10.5v2M10 10.5v2M14 10.5v2M18 10.5v2M5 16v3M9 16v3M13 16v3M17 16v3" />
    </>
  ),
  gpu: (
    <>
      <rect x="2" y="6.5" width="17" height="10" rx="1.4" />
      <circle cx="8" cy="11.5" r="2.8" />
      <circle cx="14.5" cy="11.5" r="2.2" />
      <path d="M19 9h3v6h-3M5 16.5V19" />
    </>
  ),
  cargador: (
    <>
      <path d="M9 3v4M15 3v4M6 7h12v4a6 6 0 0 1-12 0z" />
      <path d="M12 17v4" />
    </>
  ),
  servicio: (
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />
  ),
}

export const IconoCategoria = ({ nombre, tam = 34 }) => <Base tam={tam}>{CATEGORIAS[nombre]}</Base>
