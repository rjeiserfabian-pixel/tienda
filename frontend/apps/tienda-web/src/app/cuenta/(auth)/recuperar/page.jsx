import FormRecuperar from '@/components/cuenta/FormRecuperar'

export const metadata = { title: 'Recuperar contraseña', robots: { index: false, follow: false } }

export default function Pagina() {
  return (
    <main id="contenido">
      <FormRecuperar />
    </main>
  )
}
