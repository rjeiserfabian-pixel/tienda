const PUNTOS = '12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4 6.1 20.5l1.2-6.5L2.5 9.4l6.6-.9z'

/** Estrellas de solo lectura (valor de 0 a 5, con medias estrellas). */
export default function Estrellas({ valor = 0, tam = 18, etiqueta }) {
  const redondeado = Math.round(Math.max(0, Math.min(5, valor)) * 2) / 2
  return (
    <span className="estrellas" role="img" aria-label={etiqueta ?? `${redondeado} de 5 estrellas`}>
      {[1, 2, 3, 4, 5].map((n) => {
        const lleno = redondeado >= n ? 'lleno' : redondeado >= n - 0.5 ? 'medio' : 'vacio'
        return (
          <svg key={n} width={tam} height={tam} viewBox="0 0 24 24" aria-hidden="true" className={`estrella ${lleno}`}>
            <defs>
              <linearGradient id={`media-${n}`} x1="0" x2="1" y1="0" y2="0">
                <stop offset="50%" stopColor="currentColor" />
                <stop offset="50%" stopColor="transparent" />
              </linearGradient>
            </defs>
            <path d={PUNTOS} fill={lleno === 'lleno' ? 'currentColor' : lleno === 'medio' ? `url(#media-${n})` : 'none'} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
        )
      })}
    </span>
  )
}
