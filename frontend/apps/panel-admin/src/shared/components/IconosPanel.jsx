// Iconos del panel en SVG propio (sin librerías): ligeros, sin pedir nada a internet y con
// el color del texto (`currentColor`). Se piden por nombre: <Icono nombre="cart" />.

const RUTAS = {
  inicio: (
    <>
      <path d="M3.5 11.2 12 4l8.5 7.2" />
      <path d="M5.5 10v9.5h4.5v-5.5h4v5.5h4.5V10" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7.5 3v5.5c0 4.6-3.1 8.2-7.5 9.5-4.4-1.3-7.5-4.9-7.5-9.5V6L12 3z" />
      <path d="M8.8 12.2l2.3 2.3 4.2-4.6" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8.5" r="3.2" />
      <path d="M3 19.5c.6-3.3 3-5 6-5s5.4 1.7 6 5" />
      <path d="M16 5.6a3.2 3.2 0 0 1 0 5.8M18.2 14.8c1.7.6 2.6 2.1 2.9 4.2" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3.6" />
      <path d="M4.5 20c.8-3.6 3.7-5.6 7.5-5.6s6.7 2 7.5 5.6" />
    </>
  ),
  key: (
    <>
      <circle cx="8" cy="12" r="3.6" />
      <path d="M11.6 12H21M17 12v3M20 12v2.4" />
    </>
  ),
  building: (
    <>
      <path d="M5 20.5V4.5h9v16M14 9.5h5v11M3 20.5h18" />
      <path d="M8 8h3M8 11.5h3M8 15h3" />
    </>
  ),
  store: (
    <>
      <path d="M4 9.5 5.6 4.5h12.8L20 9.5M4 9.5v10.5h16V9.5M4 9.5c0 1.6 1.3 2.6 2.7 2.6S9.3 11 9.3 9.5c0 1.5 1.3 2.6 2.7 2.6s2.7-1.1 2.7-2.6c0 1.6 1.3 2.6 2.7 2.6S20 11.1 20 9.5" />
      <path d="M10 20v-4.5h4V20" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v2.4M12 18.6V21M3 12h2.4M18.6 12H21M5.6 5.6l1.7 1.7M16.7 16.7l1.7 1.7M5.6 18.4l1.7-1.7M16.7 7.3l1.7-1.7" />
    </>
  ),
  devices: (
    <>
      <rect x="3" y="5" width="14" height="10" rx="1.4" />
      <path d="M1.5 18.5h17M17 9h3.5a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H17" />
    </>
  ),
  history: (
    <>
      <path d="M4 12a8 8 0 1 0 2.5-5.8L4 8.5M4 4v4.5h4.5" />
      <path d="M12 8v4.2l3 1.8" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10.5" width="14" height="10" rx="2.2" />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    </>
  ),
  cart: (
    <>
      <path d="M3 4h2.5l2.2 10.2h9.6L19.5 7H6.4" />
      <circle cx="9.5" cy="18.5" r="1.4" />
      <circle cx="16.5" cy="18.5" r="1.4" />
    </>
  ),
  checklist: (
    <>
      <path d="M9 3.5h6a.5.5 0 0 1 .5.5v1.5h-7V4a.5.5 0 0 1 .5-.5z" />
      <path d="M8.5 5.5H6.5A1.5 1.5 0 0 0 5 7v12a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19V7a1.5 1.5 0 0 0-1.5-1.5h-2" />
      <path d="m9 13.5 2.2 2.2L15.5 11" />
    </>
  ),
  scan: (
    <>
      <path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
      <path d="M4 12h16" />
    </>
  ),
  file: (
    <>
      <path d="M7 3.5h7l4 4V20.5H7z" />
      <path d="M14 3.5v4h4M9.5 12h5.5M9.5 15.5h5.5" />
    </>
  ),
  boxes: (
    <>
      <path d="M12 3.5 20 8v8l-8 4.5L4 16V8z" />
      <path d="M4 8l8 4.5L20 8M12 12.5v8" />
    </>
  ),
  box: (
    <>
      <path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5z" />
      <path d="M4 8.5 12 13l8-4.5M12 13v7" />
    </>
  ),
  ubicacion: (
    <>
      <path d="M12 21s6.5-5.6 6.5-11a6.5 6.5 0 0 0-13 0c0 5.4 6.5 11 6.5 11z" />
      <circle cx="12" cy="10" r="2.4" />
    </>
  ),
  package: (
    <>
      <path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5z" />
      <path d="M8 6.3 16 11M12 13v7M4 8.5 12 13l8-4.5" />
    </>
  ),
  swap: (
    <>
      <path d="M4 8h14M14 4l4 4-4 4M20 16H6M10 12l-4 4 4 4" />
    </>
  ),
  truck: (
    <>
      <path d="M2.5 6.5h11v10h-11zM13.5 10h4l3 3.2v3.3h-7" />
      <circle cx="7" cy="17.5" r="1.7" />
      <circle cx="17" cy="17.5" r="1.7" />
    </>
  ),
  wallet: (
    <>
      <path d="M4 7.5A2.5 2.5 0 0 1 6.5 5H18v3" />
      <rect x="3.5" y="7.5" width="17" height="12" rx="2.2" />
      <path d="M16 13.5h4.5" />
      <circle cx="16.3" cy="13.5" r="0.6" fill="currentColor" />
    </>
  ),
  tags: (
    <>
      <path d="M3.5 12.4V4.5h7.9l8.1 8.1a1.5 1.5 0 0 1 0 2.1l-5.8 5.8a1.5 1.5 0 0 1-2.1 0z" />
      <circle cx="8" cy="9" r="1.2" />
    </>
  ),
  handshake: (
    <>
      <path d="M2.5 11.5 6 8l4 1.5 3-1.5 4 2 3.5-1.5v6.5l-4.5 3-3-1-2 1.5-3.2-1.6-1.8.6-3.5-3z" />
    </>
  ),
  wrench: (
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />
  ),
  megaphone: (
    <>
      <path d="M4 10v4l11 4.5V5.5z" />
      <path d="M15 9.5c1.7.4 3 1.4 3 2.5s-1.3 2.1-3 2.5M7 14.5l1 5h3l-.8-3.4" />
    </>
  ),
  coins: (
    <>
      <ellipse cx="9" cy="7.5" rx="5.5" ry="2.5" />
      <path d="M3.5 7.5v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5v-4M3.5 11.5v4c0 1.4 2.5 2.5 5.5 2.5M14 9.8c3 .2 6 1.2 6 2.7v4c0 1.4-2.5 2.5-5.5 2.5s-5.5-1.1-5.5-2.5" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20V4M4 20h16" />
      <path d="M8 16v-4M12 16V8M16 16v-6" />
    </>
  ),
  layers: (
    <>
      <path d="m12 4 8.5 4.5L12 13 3.5 8.5z" />
      <path d="m3.5 12.5 8.5 4.5 8.5-4.5M3.5 16.5 12 21l8.5-4.5" />
    </>
  ),
  calculator: (
    <>
      <rect x="5" y="3.5" width="14" height="17" rx="2" />
      <rect x="8" y="6.5" width="8" height="3" rx="0.6" />
      <path d="M8.5 13h.01M12 13h.01M15.5 13h.01M8.5 16.5h.01M12 16.5h.01M15.5 16.5h.01" strokeWidth="2.2" />
    </>
  ),
  bell: (
    <>
      <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z" />
      <path d="M10 20.5a2.2 2.2 0 0 0 4 0" />
    </>
  ),
  chat: (
    <>
      <path d="M4 5.5h16v10.5H11l-4.5 3.8V16H4z" />
    </>
  ),
  expandir: (
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  ),
  contraer: (
    <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
  ),
  calendario: (
    <>
      <rect x="4" y="5.5" width="16" height="14.5" rx="2" />
      <path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" />
    </>
  ),
  reloj: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  chevron: <path d="m9 6 6 6-6 6" />,
  chevronAbajo: <path d="m6 9 6 6 6-6" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  cerrar: <path d="M6 6l12 12M18 6 6 18" />,
  salir: (
    <>
      <path d="M10 4.5H6.5a1.5 1.5 0 0 0-1.5 1.5v12a1.5 1.5 0 0 0 1.5 1.5H10" />
      <path d="M14 8l4 4-4 4M18 12H9" />
    </>
  ),
  cotizacion: (
    <>
      <path d="M7 3.5h7l4 4V20.5H7z" />
      <path d="M14 3.5v4h4M9.5 12.5h5.5M9.5 16h3.5" />
    </>
  ),
  agregar: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 8v8M8 12h8" />
    </>
  ),
  tablero: (
    <>
      <rect x="4" y="4.5" width="16" height="15.5" rx="2" />
      <path d="M8 14v3M12 10v7M16 12.5V17" />
    </>
  ),
  tendencia: <path d="M3 17l5-5 4 3.5L20 7M15 7h5v5" />,
  buscar: (
    <>
      <circle cx="10.5" cy="10.5" r="6.3" />
      <path d="m15.4 15.4 5 5" />
    </>
  ),
  filtro: <path d="M3.5 5h17l-6.6 7.6v5.9l-3.8 2v-7.9z" />,
  exportar: (
    <>
      <path d="M12 15V4M8 8l4-4 4 4" />
      <path d="M4 14.5v4A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5v-4" />
    </>
  ),
  ojo: (
    <>
      <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  lapiz: (
    <>
      <path d="M4 20l1-4.2L16.6 4.2a2.1 2.1 0 0 1 3 0l.2.2a2.1 2.1 0 0 1 0 3L8.2 19z" />
      <path d="m14.5 6.3 3.2 3.2" />
    </>
  ),
  importar: (
    <>
      <path d="M12 4v11M8 11l4 4 4-4" />
      <path d="M4 14.5v4A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5v-4" />
    </>
  ),
  papelera: (
    <>
      <path d="M4 7h16M9 7V4.5h6V7" />
      <path d="M6.5 7l.8 12a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12" />
      <path d="M10 11v5M14 11v5" />
    </>
  ),
  apagar: (
    <>
      <path d="M12 3.5v8" />
      <path d="M6.8 6.6a7.5 7.5 0 1 0 10.4 0" />
    </>
  ),
  reactivar: (
    <>
      <path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5M20 4v4.5h-4.5" />
      <path d="M20 12a8 8 0 0 1-13.7 5.6L4 15.5M4 20v-4.5h4.5" />
    </>
  ),
  ordenar: <path d="M8 9l4-4 4 4M8 15l4 4 4-4" />,
  ordenarAsc: <path d="M8 14l4-4 4 4" />,
  ordenarDesc: <path d="M8 10l4 4 4-4" />,
  chevronIzq: <path d="m15 6-6 6 6 6" />,
  correo: (
    <>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <path d="m3.5 7 8.5 6.2L20.5 7" />
    </>
  ),
  telefono: (
    <path d="M6.6 3.5h2.7l1.5 4-1.9 1.4a11 11 0 0 0 5.2 5.2l1.4-1.9 4 1.5v2.7a2 2 0 0 1-2.2 2A15.500 15.500 0 0 1 4.600 5.700a2 2 0 0 1 2-2.200z" />
  ),
  documento: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <circle cx="9" cy="11" r="2.2" />
      <path d="M5.8 16.2c.5-1.600 1.700-2.400 3.200-2.400s2.700.8 3.200 2.400M14.500 10h4M14.500 13.500h3" />
    </>
  ),
  camara: (
    <>
      <path d="M4 8.500A1.500 1.500 0 0 1 5.500 7H8l1.200-2h5.600L16 7h2.500A1.500 1.500 0 0 1 20 8.500v9a1.500 1.500 0 0 1-1.500 1.500h-13A1.500 1.500 0 0 1 4 17.500z" />
      <circle cx="12" cy="13" r="3.400" />
    </>
  ),
  usuarioMas: (
    <>
      <circle cx="9.500" cy="8" r="3.400" />
      <path d="M3 20c.700-3.500 3.200-5.500 6.500-5.500s5.800 2 6.500 5.500M18.500 8v6M15.500 11h6" />
    </>
  ),
  ojoOculto: (
    <>
      <path d="M3 3l18 18" />
      <path d="M10.6 6a10 10 0 0 1 1.4-.1c6.4 0 10 6.1 10 6.1a17 17 0 0 1-3 3.7M6.4 7.6A17 17 0 0 0 2 12s3.6 6.1 10 6.1a9.7 9.7 0 0 0 3.5-.7" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </>
  ),
}

/** Punto genérico para nombres de icono que aún no tienen dibujo. */
const PUNTO = <circle cx="12" cy="12" r="3" />

export function Icono({ nombre, tam = 22, trazo = 1.7, ...resto }) {
  return (
    <svg
      width={tam}
      height={tam}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={trazo}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...resto}
    >
      {RUTAS[nombre] ?? PUNTO}
    </svg>
  )
}
