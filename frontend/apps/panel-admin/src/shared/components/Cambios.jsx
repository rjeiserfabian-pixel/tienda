/** ¿El detalle de un evento es una lista de cambios `{campo: [antes, después]}`? */
export const esCambios = (detalle) => {
  const llaves = Object.keys(detalle ?? {})
  return llaves.length > 0 && llaves.every((k) => Array.isArray(detalle[k]) && detalle[k].length === 2)
}

const texto = (valor) => {
  if (valor === null || valor === undefined || valor === '') return '—'
  if (typeof valor === 'object') return JSON.stringify(valor)
  return String(valor)
}

/** El antes y el después de lo que cambió, campo por campo (o el detalle tal cual si no son cambios). */
export default function Cambios({ detalle }) {
  if (!detalle || Object.keys(detalle).length === 0) return null
  if (!esCambios(detalle)) return <pre className="detalle-json">{JSON.stringify(detalle, null, 2)}</pre>
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th>Dato</th>
            <th>Antes</th>
            <th>Después</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(detalle).map(([campo, [antes, despues]]) => (
            <tr key={campo}>
              <td>{campo.replaceAll('_', ' ')}</td>
              <td className="celda-suave">{texto(antes)}</td>
              <td>
                <strong>{texto(despues)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
