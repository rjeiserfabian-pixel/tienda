import { useState } from 'react'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'

let contador = 0
const nuevaClave = () => `acc-${++contador}`

/** Lo que el cliente deja junto al equipo: se marcan los de siempre y se agrega cualquier otro. */
export default function AccesoriosIngreso({ catalogo, accesorios, onCambio, error, disabled }) {
  const [otro, setOtro] = useState('')

  const delCatalogo = (id) => accesorios.find((a) => a.accesorio === id)
  const alternar = (item) => {
    if (delCatalogo(item.id)) onCambio(accesorios.filter((a) => a.accesorio !== item.id))
    else onCambio([...accesorios, { clave: nuevaClave(), accesorio: item.id, nombre: item.nombre, cantidad: '1', detalle: '' }])
  }
  const cambiar = (clave, campo, valor) => onCambio(accesorios.map((a) => (a.clave === clave ? { ...a, [campo]: valor } : a)))
  const agregarOtro = () => {
    const nombre = otro.trim()
    if (!nombre) return
    onCambio([...accesorios, { clave: nuevaClave(), accesorio: null, nombre, cantidad: '1', detalle: '' }])
    setOtro('')
  }

  return (
    <>
      {catalogo.length > 0 && (
        <ul className="servicio-fichas" aria-label="Accesorios habituales">
          {catalogo.map((item) => (
            <li key={item.id}>
              <button type="button" className="servicio-ficha-opcion" aria-pressed={Boolean(delCatalogo(item.id))} disabled={disabled} onClick={() => alternar(item)}>
                {item.nombre}
              </button>
            </li>
          ))}
        </ul>
      )}
      {accesorios.length > 0 && (
        <ul className="servicio-accesorios" aria-label="Accesorios que deja el cliente">
          {accesorios.map((a) => (
            <li key={a.clave}>
              <strong>{a.nombre}</strong>
              <input type="number" min={1} max={99} aria-label={`Cantidad de ${a.nombre}`} value={a.cantidad} disabled={disabled} onChange={(ev) => cambiar(a.clave, 'cantidad', ev.target.value)} />
              <input maxLength={150} aria-label={`Detalle de ${a.nombre}`} placeholder="Detalle (opcional)" value={a.detalle} disabled={disabled} onChange={(ev) => cambiar(a.clave, 'detalle', ev.target.value)} />
              <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${a.nombre}`} title="Quitar" disabled={disabled} onClick={() => onCambio(accesorios.filter((x) => x.clave !== a.clave))}>
                <Icono nombre="papelera" tam={18} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="servicio-agregar-otro">
        <Campo etiqueta="Otro accesorio">
          {(p) => (
            <input
              {...p}
              maxLength={80}
              placeholder="Ej. Base enfriadora"
              value={otro}
              disabled={disabled}
              onChange={(ev) => setOtro(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter') {
                  ev.preventDefault()
                  agregarOtro()
                }
              }}
            />
          )}
        </Campo>
        <button type="button" className="boton-cabecera" disabled={disabled || !otro.trim()} onClick={agregarOtro}>
          <Icono nombre="agregar" tam={18} /> Agregar
        </button>
      </div>
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
      {accesorios.length === 0 && <p className="celda-suave">Si el cliente deja solo el equipo, no marques nada: quedará anotado «sin accesorios».</p>}
    </>
  )
}
