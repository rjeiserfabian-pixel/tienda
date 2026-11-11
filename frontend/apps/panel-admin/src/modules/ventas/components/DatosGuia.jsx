import Campo from '../../../shared/components/Campo'
import { hoyIso } from '../../almacen/inventario'
import DatoLectura from './DatoLectura'

/**
 * Los datos de cabecera de toda guía: el motivo del traslado, la serie (con su próximo número) y las fechas.
 * `motivos` son `{ codigo, nombre, disponible }`; los no disponibles se muestran apagados.
 */
export default function DatosGuia({ f, poner, motivos, series, serie, onSerie, disabled }) {
  return (
    <div className="pos-bloques">
      <div className="fila-campos">
        <Campo etiqueta="Motivo" tipo="select" requerido>
          {(p) => (
            <select {...p} value={f.motivo} disabled={disabled} onChange={(ev) => poner('motivo', ev.target.value)}>
              {motivos.map((m) => (
                <option key={m.codigo} value={m.codigo} disabled={m.disponible === false}>
                  {m.nombre}
                  {m.disponible === false ? ' (se emite desde un traspaso de inventario)' : ''}
                </option>
              ))}
            </select>
          )}
        </Campo>
        {series.length > 1 ? (
          <Campo etiqueta="Serie · próximo N°" tipo="select" requerido>
            {(p) => (
              <select {...p} value={serie} disabled={disabled} onChange={(ev) => onSerie(ev.target.value)}>
                {!serie && <option value="">Elige la serie</option>}
                {series.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.proximo}
                    {s.nombre ? ` · ${s.nombre}` : ''}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        ) : (
          <DatoLectura etiqueta="Serie · próximo N°" valor={series[0]?.proximo ?? 'Sin serie'} />
        )}
        <Campo etiqueta="Fecha de emisión" icono="calendario" ayuda="Siempre la de hoy.">
          {(p) => <input {...p} type="date" value={hoyIso()} readOnly disabled />}
        </Campo>
        <Campo etiqueta="Fecha de traslado" icono="calendario" requerido>
          {(p) => <input {...p} type="date" min={hoyIso()} value={f.fechaTraslado} disabled={disabled} onChange={(ev) => poner('fechaTraslado', ev.target.value)} />}
        </Campo>
      </div>
    </div>
  )
}
