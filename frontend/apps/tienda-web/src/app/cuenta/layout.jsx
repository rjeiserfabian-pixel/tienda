import './cuenta.css'

// Todo lo de la cuenta es privado: los buscadores no deben indexarlo.
export const metadata = { robots: { index: false, follow: false } }

export default function LayoutCuenta({ children }) {
  return children
}
