/** Mientras llega una página: un esqueleto con la forma de lo que viene (no un círculo girando). */
export default function Cargando() {
  return (
    <main id="contenido" className="contenedor pagina" aria-busy="true" aria-label="Cargando">
      <div className="esqueleto" style={{ height: 28, width: 'min(320px, 70%)', marginBottom: 24 }} />
      <div className="esqueleto-rejilla">
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="esqueleto" style={{ aspectRatio: '3 / 4' }} />
        ))}
      </div>
    </main>
  )
}
