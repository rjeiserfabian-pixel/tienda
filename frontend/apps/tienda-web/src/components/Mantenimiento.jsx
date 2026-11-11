/** Lo que ve el cliente cuando la tienda está cerrada o la API no responde. */
export default function Mantenimiento({ cerrada }) {
  return (
    <main id="contenido" className="mantenimiento">
      <div className="mantenimiento-caja">
        <h1>{cerrada ? 'Estamos preparando la tienda' : 'Volvemos en un momento'}</h1>
        <p>
          {cerrada
            ? 'Muy pronto podrás ver y comprar nuestros productos aquí. ¡Gracias por tu paciencia!'
            : 'No pudimos cargar la tienda ahora mismo. Intenta de nuevo en unos minutos.'}
        </p>
        <a className="boton" href="/">
          Reintentar
        </a>
      </div>
    </main>
  )
}
