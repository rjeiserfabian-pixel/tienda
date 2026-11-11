import PanelCuenta from '@/components/cuenta/PanelCuenta'

export default function LayoutPanel({ children }) {
  return (
    <main id="contenido">
      <PanelCuenta>{children}</PanelCuenta>
    </main>
  )
}
