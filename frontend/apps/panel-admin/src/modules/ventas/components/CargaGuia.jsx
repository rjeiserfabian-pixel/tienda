import Campo from '../../../shared/components/Campo'

/** La carga de la guía: bultos, peso total (por defecto la suma de los pesos de los productos) y observaciones. */
export default function CargaGuia({ f, poner, pesoSugerido, disabled }) {
  return (
    <div className="pos-bloques">
      <div className="fila-campos">
        <Campo etiqueta="Bultos" requerido>
          {(p) => <input {...p} inputMode="numeric" value={f.bultos} disabled={disabled} onChange={(ev) => poner('bultos', ev.target.value.replace(/\D/g, ''))} />}
        </Campo>
        <Campo etiqueta="Peso total (kg)" ayuda={`Si lo dejas vacío se usa la suma de los pesos de los productos (${pesoSugerido.toFixed(3)} kg).`}>
          {(p) => <input {...p} inputMode="decimal" placeholder={pesoSugerido.toFixed(3)} value={f.pesoEscrito} disabled={disabled} onChange={(ev) => poner('pesoEscrito', ev.target.value.replace(',', '.'))} />}
        </Campo>
      </div>
      <Campo etiqueta="Observaciones" contador={{ actual: f.observacion.length, max: 250 }}>
        {(p) => <textarea {...p} rows={3} maxLength={250} value={f.observacion} disabled={disabled} onChange={(ev) => poner('observacion', ev.target.value)} />}
      </Campo>
    </div>
  )
}
