import { RESULTADOS_REVISION } from '../servicio'

/** Cómo se encontró el equipo al recibirlo: una fila por revisión, solo las que valen para su tipo. */
export default function RevisionesIngreso({ catalogo, tipoEquipo, revisiones, onCambio, disabled }) {
  const aplicables = catalogo.filter((r) => !r.tipo_equipo || String(r.tipo_equipo) === String(tipoEquipo))
  if (aplicables.length === 0) return <p className="celda-suave">No hay revisiones de ingreso configuradas. Se agregan en «Revisiones de ingreso».</p>

  const poner = (id, campo, valor) => onCambio({ ...revisiones, [id]: { resultado: '', observacion: '', ...revisiones[id], [campo]: valor } })
  return (
    <ul className="servicio-revisiones" aria-label="Revisiones de ingreso">
      {aplicables.map((r) => {
        const actual = revisiones[r.id] ?? { resultado: '', observacion: '' }
        return (
          <li key={r.id} className={`servicio-revision${actual.resultado === 'FALLA' ? ' servicio-revision-falla' : ''}`}>
            <strong>{r.nombre}</strong>
            <select aria-label={`Resultado de ${r.nombre}`} value={actual.resultado} disabled={disabled} onChange={(ev) => poner(r.id, 'resultado', ev.target.value)}>
              <option value="">Sin revisar</option>
              {RESULTADOS_REVISION.map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
                </option>
              ))}
            </select>
            <input maxLength={250} aria-label={`Observación de ${r.nombre}`} placeholder="Observación (opcional)" value={actual.observacion} disabled={disabled || !actual.resultado} onChange={(ev) => poner(r.id, 'observacion', ev.target.value)} />
          </li>
        )
      })}
    </ul>
  )
}
