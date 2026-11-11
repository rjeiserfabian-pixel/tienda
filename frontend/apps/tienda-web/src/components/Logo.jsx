import Link from 'next/link'

/**
 * La marca de la tienda: su logo (propio de la tienda, subido desde el panel) o, si aún no hay,
 * el nombre con la inicial en un recuadro de color.
 */
export default function Logo({ nombre = 'Tienda', logo = null, claro = false, conNombre = false }) {
  const texto = String(nombre)
  if (logo) {
    return (
      <Link href="/" className={`logo con-imagen${claro ? ' claro' : ''}`} aria-label={`${texto}: ir al inicio`}>
        <img src={logo} alt={conNombre ? '' : texto} height={40} decoding="async" />
        {conNombre && <span className="logo-nombre">{texto}</span>}
      </Link>
    )
  }
  const inicio = texto.slice(0, -1)
  const ultima = texto.slice(-1)
  return (
    <Link href="/" className={`logo${claro ? ' claro' : ''}`} aria-label={`${texto}: ir al inicio`}>
      <span className="logo-marca" aria-hidden="true">
        {texto.charAt(0).toUpperCase()}
      </span>
      <span className="logo-texto" aria-hidden="true">
        {inicio}
        <b>{ultima}</b>
      </span>
    </Link>
  )
}
