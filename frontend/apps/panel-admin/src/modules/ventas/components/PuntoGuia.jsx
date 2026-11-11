import Campo from '../../../shared/components/Campo'
import SelectorUbigeo from '../../../shared/components/SelectorUbigeo'

/** Una dirección con su ubigeo: el punto de partida o el de llegada de una guía. */
export default function PuntoGuia({ titulo, direccion, ubigeo, onDireccion, onUbigeo, disabled }) {
  return (
    <div className="pos-bloques">
      <Campo etiqueta={`Dirección del punto de ${titulo}`} requerido contador={{ actual: direccion.length, max: 250 }}>
        {(p) => <input {...p} maxLength={250} value={direccion} disabled={disabled} onChange={(e) => onDireccion(e.target.value)} />}
      </Campo>
      <Campo etiqueta={`Ubigeo del punto de ${titulo}`} icono="ubicacion">
        {(p) => <SelectorUbigeo {...p} valor={ubigeo} disabled={disabled} onCambio={onUbigeo} />}
      </Campo>
    </div>
  )
}
