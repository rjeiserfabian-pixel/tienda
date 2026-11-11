import Campo from '../../../shared/components/Campo'

/** Un dato que se llena solo (al buscar la venta o elegir de una lista): se ve, no se escribe. */
export default function DatoLectura({ etiqueta, valor, clase }) {
  return <Campo etiqueta={etiqueta} clase={clase}>{(p) => <input {...p} value={valor ?? ''} readOnly disabled />}</Campo>
}
