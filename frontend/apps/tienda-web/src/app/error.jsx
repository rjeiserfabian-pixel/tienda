'use client'

/** Algo falló al armar una página (por ejemplo, la API no respondió): un mensaje claro y reintentar. */
export default function ErrorDePagina({ reset }) {
  return (
    <main id="contenido" className="contenedor pagina">
      <div className="estado-vacio">
        <h1 className="titulo-pagina">No pudimos cargar esta página</h1>
        <p>Es un problema pasajero. Intenta de nuevo en unos segundos.</p>
        <button type="button" className="boton" onClick={() => reset()}>
          Reintentar
        </button>
      </div>
    </main>
  )
}
