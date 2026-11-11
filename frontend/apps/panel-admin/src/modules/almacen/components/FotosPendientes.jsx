import { useEffect, useRef } from 'react'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { FOTO_FORMATOS, FOTO_MAX_BYTES, FOTOS_MAX } from '../utilidades'

/**
 * Fotos de un producto que todavía no se guarda: se eligen aquí y se suben apenas se registra.
 * Cada elemento es `{ archivo, vista }` (`vista` es la dirección local de la miniatura).
 */
export default function FotosPendientes({ fotos, onCambio, deshabilitado }) {
  const notificar = useNotificar()
  const entrada = useRef(null)
  const ultimas = useRef(fotos)

  useEffect(() => {
    ultimas.current = fotos
  }, [fotos])
  // Al salir de la pantalla se liberan las miniaturas locales.
  useEffect(() => () => ultimas.current.forEach((x) => URL.revokeObjectURL(x.vista)), [])

  const agregar = (lista) => {
    const nuevas = []
    for (const archivo of lista) {
      if (fotos.length + nuevas.length >= FOTOS_MAX) {
        notificar('error', `Un producto admite hasta ${FOTOS_MAX} fotos.`)
        break
      }
      if (!FOTO_FORMATOS.includes(archivo.type)) notificar('error', `«${archivo.name}»: usa una foto JPG, PNG o WEBP.`)
      else if (archivo.size > FOTO_MAX_BYTES) notificar('error', `«${archivo.name}» pesa más de 5 MB.`)
      else nuevas.push({ archivo, vista: URL.createObjectURL(archivo) })
    }
    if (nuevas.length) onCambio([...fotos, ...nuevas])
    if (entrada.current) entrada.current.value = ''
  }
  const quitar = (indice) => {
    URL.revokeObjectURL(fotos[indice].vista)
    onCambio(fotos.filter((_, i) => i !== indice))
  }

  return (
    <PanelTarjeta id="fotos" icono="camara" titulo="Fotos" descripcion={`Elige hasta ${FOTOS_MAX} fotos (JPG, PNG o WEBP, máx. 5 MB). Se suben al registrar el producto; la primera será la principal.`}>
      <div className="fotos-grilla">
        {fotos.map((x, i) => (
          <figure key={x.vista} className={`foto-tarjeta${i === 0 ? ' principal' : ''}`}>
            <img className="foto-imagen" src={x.vista} alt={x.archivo.name} />
            {i === 0 && <span className="foto-insignia">Principal</span>}
            <figcaption>
              <button type="button" className="peligro" disabled={deshabilitado} onClick={() => quitar(i)}>
                <Icono nombre="papelera" tam={17} /> Quitar
              </button>
            </figcaption>
          </figure>
        ))}
        {fotos.length < FOTOS_MAX && (
          <button type="button" className="foto-subir" disabled={deshabilitado} onClick={() => entrada.current?.click()}>
            <Icono nombre="camara" tam={26} />
            <span>Agregar fotos</span>
            <small>JPG, PNG o WEBP</small>
          </button>
        )}
      </div>
      <input ref={entrada} type="file" hidden multiple accept={FOTO_FORMATOS.join(',')} onChange={(e) => agregar([...e.target.files])} />
    </PanelTarjeta>
  )
}
