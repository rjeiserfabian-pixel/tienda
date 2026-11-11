import FormNuevaClave from '@/components/cuenta/FormNuevaClave'

export const metadata = { title: 'Nueva contraseña', robots: { index: false, follow: false } }

export default function Pagina() {
  return (
    <main id="contenido">
      <FormNuevaClave />
    </main>
  )
}
