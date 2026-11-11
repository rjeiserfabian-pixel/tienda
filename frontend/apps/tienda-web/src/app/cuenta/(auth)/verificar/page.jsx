import VerificarCorreo from '@/components/cuenta/VerificarCorreo'

export const metadata = { title: 'Confirmar correo', robots: { index: false, follow: false } }

export default function Pagina() {
  return (
    <main id="contenido">
      <VerificarCorreo />
    </main>
  )
}
