/** Iconos de la tienda (trazo simple, heredan el color del texto). */
const TRAZOS = {
  lupa: 'M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm10 2-4.3-4.3',
  menu: 'M4 6h16M4 12h16M4 18h16',
  comparar: 'M8 4 4 8l4 4M4 8h13M16 12l4 4-4 4M20 16H7',
  cerrar: 'M6 6l12 12M18 6 6 18',
  chevron: 'm6 9 6 6 6-6',
  derecha: 'm9 6 6 6-6 6',
  izquierda: 'm15 6-6 6 6 6',
  filtro: 'M4 5h16M7 12h10M10 19h4',
  camion: 'M3 7h11v9H3zM14 10h4l3 3v3h-7M7 19a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM17 19a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z',
  escudo: 'M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6l-7-3Zm-3 9 2.2 2.2L15.5 10',
  llave: 'M14.7 6.3a4 4 0 0 0-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 0 0 5.2-5.4l-2.4 2.4-2.3-.6-.6-2.3 2.3-2.5Z',
  tienda: 'M4 9l1.5-5h13L20 9M4 9v11h16V9M4 9c0 1.7 1.3 3 3 3s3-1.3 3-3c0 1.7 1.3 3 3 3s3-1.3 3-3c0 1.7 1.3 3 3 3',
  chat: 'M4 5h16v11H9l-5 4V5Z',
  check: 'm5 12 5 5 9-10',
  info: 'M12 8h.01M11 12h1v5h1M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Z',
  zoom: 'M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm10 2-4.3-4.3M11 8v6M8 11h6',
  etiqueta: 'M3 12V4h8l9 9-8 8-9-9Zm5-4h.01',
  tarjeta: 'M3 6h18v12H3zM3 10h18M7 15h3',
  usuario: 'M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm-8 9c0-4.4 3.6-7 8-7s8 2.6 8 7',
  carrito: 'M3 4h2.5l2.2 10.2a1 1 0 0 0 1 .8h8.6a1 1 0 0 0 1-.8L20 8H6.2M10 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2Zm7 0a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z',
  pin: 'M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11Zm0-8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z',
  basura: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
  mas: 'M12 5v14M5 12h14',
  menos: 'M5 12h14',
  candado: 'M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3',
  reloj: 'M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Zm0-13v4.5l3 1.5',
  casa: 'M3 11 12 4l9 7M5 10v10h14V10M10 20v-6h4v6',
  cuadricula: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  cpu: 'M7 7h10v10H7zM10 10h4v4h-4zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3',
}

export default function Icono({ nombre, tam = 20, titulo, ...resto }) {
  const trazo = TRAZOS[nombre]
  if (!trazo) return null
  return (
    <svg
      width={tam}
      height={tam}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={titulo ? 'img' : undefined}
      aria-label={titulo}
      aria-hidden={titulo ? undefined : 'true'}
      focusable="false"
      {...resto}
    >
      <path d={trazo} />
    </svg>
  )
}
