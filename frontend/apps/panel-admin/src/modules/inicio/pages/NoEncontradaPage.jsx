import { Link } from 'react-router-dom'

export default function NoEncontradaPage() {
  return (
    <main style={{ padding: 24 }}>
      <h2>Sección no disponible</h2>
      <p>Esta sección todavía está en construcción o la dirección no existe.</p>
      <Link to="/">Volver al inicio</Link>
    </main>
  )
}
