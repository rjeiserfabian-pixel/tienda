import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { FOTO_FORMATOS, FOTO_MAX_BYTES, FOTOS_MAX } from '../utilidades'
import ImagenProtegida from './ImagenProtegida'

const url = (producto, foto = '', extra = '') => `/mantenimiento/productos/${producto}/fotos/${foto ? `${foto}/` : ''}${extra}`

/** Galería de fotos del producto: subir, elegir la principal y quitar. La tienda virtual usará estas mismas. */
export default function FotosProducto({ productoId, puedeEditar }) {
  const notificar = useNotificar()
  const entrada = useRef(null)
  const [quitando, setQuitando] = useState(null)
  const [arrastrando, setArrastrando] = useState(false)
  const [moviendo, setMoviendo] = useState(null) // posición de la foto que se arrastra para reordenar
  const [sobre, setSobre] = useState(null)

  const consulta = useQuery({
    queryKey: ['productos', 'fotos', productoId],
    queryFn: ({ signal }) => api.get(url(productoId), { signal }).then((r) => r.data),
  })
  const fotos = consulta.data ?? []
  // Solo las fotos y el listado: la ficha abierta no se recarga (no se pierde lo que se esté escribiendo).
  const invalidar = [['productos', 'fotos'], ['productos', 'lista']]

  const subir = useMutacion({
    mutationFn: (archivo) => {
      const datos = new FormData()
      datos.append('imagen', archivo)
      return api.post(url(productoId), datos, { timeout: 60_000 }).then((r) => r.data)
    },
    invalidar,
    avisarError: false,
  })
  const principal = useMutacion({
    mutationFn: (foto) => api.post(url(productoId, foto, 'principal/')).then((r) => r.data),
    invalidar,
    exito: 'Foto principal actualizada.',
  })
  const ordenar = useMutacion({
    mutationFn: (ids) => api.post(url(productoId, '', 'orden/'), { ids }).then((r) => r.data),
    invalidar,
    exito: 'Orden de las fotos actualizado. La primera es la principal.',
  })
  // Mueve una foto a otra posición enviando TODAS las ids en el orden nuevo (el servidor lo exige así).
  const mover = (desde, hasta) => {
    if (desde === hasta || hasta < 0 || hasta >= fotos.length || ordenar.isPending) return
    const ids = fotos.map((f) => f.id)
    const [movida] = ids.splice(desde, 1)
    ids.splice(hasta, 0, movida)
    ordenar.mutate(ids)
  }
  const quitar = useMutacion({
    mutationFn: (foto) => api.delete(url(productoId, foto)),
    invalidar,
    exito: 'Foto eliminada.',
    alExito: () => setQuitando(null),
  })

  // Valida en el navegador (tipo y peso) antes de gastar la subida; el servidor vuelve a validar todo.
  const elegir = async (lista) => {
    const archivos = [...lista]
    if (fotos.length + archivos.length > FOTOS_MAX) {
      notificar('error', `Un producto admite hasta ${FOTOS_MAX} fotos.`)
      return
    }
    for (const archivo of archivos) {
      if (!FOTO_FORMATOS.includes(archivo.type)) {
        notificar('error', `«${archivo.name}»: usa una foto JPG, PNG o WEBP.`)
        continue
      }
      if (archivo.size > FOTO_MAX_BYTES) {
        notificar('error', `«${archivo.name}» pesa más de 15 MB.`)
        continue
      }
      try {
        await subir.mutateAsync(archivo)
      } catch (error) {
        notificar('error', `«${archivo.name}»: ${mensajeDeError(error)}`)
      }
    }
    if (entrada.current) entrada.current.value = ''
  }

  const alSoltar = (evento) => {
    evento.preventDefault()
    setArrastrando(false)
    if (puedeEditar && !subir.isPending) elegir(evento.dataTransfer.files)
  }

  return (
    <PanelTarjeta id="fotos" icono="camara" titulo="Fotos" descripcion={`Hasta ${FOTOS_MAX} fotos (JPG, PNG o WEBP, máx. 15 MB; se reducen solas). La primera es la principal y es la que se ve en la tienda; arrastra las fotos o usa las flechas para ordenarlas.`}>
      <div className="fotos-grilla">
        {fotos.map((foto, indice) => (
          <figure
            key={foto.id}
            className={`foto-tarjeta${foto.es_principal ? ' principal' : ''}${sobre === indice && moviendo !== null && moviendo !== indice ? ' destino' : ''}`}
            draggable={puedeEditar && fotos.length > 1 && !ordenar.isPending}
            onDragStart={(e) => {
              setMoviendo(indice)
              e.dataTransfer.effectAllowed = 'move'
            }}
            onDragOver={(e) => {
              if (moviendo === null) return // es un archivo que se suelta, no una foto que se reordena
              e.preventDefault()
              setSobre(indice)
            }}
            onDrop={(e) => {
              if (moviendo === null) return
              e.preventDefault()
              mover(moviendo, indice)
              setMoviendo(null)
              setSobre(null)
            }}
            onDragEnd={() => {
              setMoviendo(null)
              setSobre(null)
            }}
          >
            <ImagenProtegida url={url(productoId, foto.id, 'imagen/?tam=mini')} alt={foto.nombre_original || 'Foto del producto'} className="foto-imagen" />
            {foto.es_principal && <span className="foto-insignia">Principal</span>}
            {puedeEditar && fotos.length > 1 && (
              <span className="foto-orden">
                <button type="button" aria-label={`Mover la foto ${indice + 1} a la izquierda`} title="Mover antes" disabled={indice === 0 || ordenar.isPending} onClick={() => mover(indice, indice - 1)}>
                  <Icono nombre="chevronIzq" tam={16} />
                </button>
                <button type="button" aria-label={`Mover la foto ${indice + 1} a la derecha`} title="Mover después" disabled={indice === fotos.length - 1 || ordenar.isPending} onClick={() => mover(indice, indice + 1)}>
                  <Icono nombre="chevron" tam={16} />
                </button>
              </span>
            )}
            {puedeEditar && (
              <figcaption>
                {!foto.es_principal && (
                  <button type="button" disabled={principal.isPending} onClick={() => principal.mutate(foto.id)}>
                    Hacer principal
                  </button>
                )}
                <button type="button" className="peligro" aria-label="Quitar foto" title="Quitar foto" onClick={() => setQuitando(foto)}>
                  <Icono nombre="papelera" tam={17} />
                </button>
              </figcaption>
            )}
          </figure>
        ))}
        {puedeEditar && fotos.length < FOTOS_MAX && (
          <button
            type="button"
            className={`foto-subir${arrastrando ? ' arrastrando' : ''}`}
            disabled={subir.isPending}
            onClick={() => entrada.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setArrastrando(true)
            }}
            onDragLeave={() => setArrastrando(false)}
            onDrop={alSoltar}
          >
            <Icono nombre="camara" tam={26} />
            <span>{subir.isPending ? 'Subiendo…' : 'Agregar fotos'}</span>
            <small>o suéltalas aquí</small>
          </button>
        )}
      </div>
      <input ref={entrada} type="file" hidden multiple accept={FOTO_FORMATOS.join(',')} onChange={(e) => elegir(e.target.files)} />
      {consulta.isSuccess && fotos.length === 0 && !puedeEditar && <p className="celda-suave">Este producto aún no tiene fotos.</p>}
      {quitando && (
        <ConfirmarModal
          titulo="Quitar foto"
          mensaje="¿Quitar esta foto del producto?"
          textoConfirmar="Quitar"
          enviando={quitar.isPending}
          onConfirmar={() => quitar.mutate(quitando.id)}
          onCerrar={() => setQuitando(null)}
        />
      )}
    </PanelTarjeta>
  )
}
