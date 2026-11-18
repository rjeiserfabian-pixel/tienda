import ConsultaGarantia from '@/components/garantia/ConsultaGarantia'
import Migas from '@/components/Migas'
import '../servicio-tecnico.css'

export const metadata = {
  title: 'Consulta tu garantía',
  description: 'Revisa si la garantía de tu producto sigue vigente con su serie y tu documento, o con el código de tu certificado.',
  alternates: { canonical: '/garantia' },
}

export default function Garantia() {
  return (
    <main id="contenido" className="contenedor st-pagina">
      <Migas items={[{ nombre: 'Inicio', href: '/' }, { nombre: 'Consulta tu garantía' }]} />
      <header className="st-cabecera">
        <h1>Consulta tu garantía</h1>
        <p className="st-intro">Mira hasta cuándo vale la garantía de tu producto y si tienes un reclamo en curso.</p>
      </header>
      <section className="st-tarjeta" aria-labelledby="titulo-consulta">
        <h2 id="titulo-consulta">¿Cómo quieres consultar?</h2>
        <ConsultaGarantia />
      </section>
    </main>
  )
}
