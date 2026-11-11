/** Marca "N" en 3D: pilar plateado a la izquierda, rojo a la derecha y diagonal entre ambos. */
export function LogoMarca({ tam = 96 }) {
  return (
    <svg width={tam} height={tam * 1.1} viewBox="0 0 100 110" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="plata" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#8f949e" />
        </linearGradient>
        <linearGradient id="rojo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ff4630" />
          <stop offset="1" stopColor="#b3000d" />
        </linearGradient>
        <linearGradient id="rojoOscuro" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e5121f" />
          <stop offset="1" stopColor="#6b0008" />
        </linearGradient>
      </defs>
      <polygon points="6,24 36,8 36,98 6,84" fill="url(#plata)" />
      <polygon points="36,8 52,16 94,86 94,102 78,96 36,30" fill="url(#rojoOscuro)" />
      <polygon points="64,16 94,32 94,102 64,88" fill="url(#rojo)" />
      <polygon points="36,8 64,16 64,30 36,22" fill="#ffffff" opacity="0.55" />
    </svg>
  )
}
