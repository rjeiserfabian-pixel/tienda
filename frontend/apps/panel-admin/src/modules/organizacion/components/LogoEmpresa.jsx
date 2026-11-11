import { useRef, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import ImagenProtegida from '../../almacen/components/ImagenProtegida'
import './empresa.css'

const FORMATOS = ['image/jpeg', 'image/png', 'image/webp']
const MAX_BYTES = 2 * 1024 * 1024

/** Logo de la empresa: sale en los comprobantes y documentos que se entregan al cliente. */
export default function LogoEmpresa({ empresa, puedeEditar }) {
  const notificar = useNotificar()
  const entrada = useRef(null)
  const [arrastrando, setArrastrando] = useState(false)
  const url = `/organizacion/empresas/${empresa.id}/logo/`
  const invalidar = [['empresas'], ['imagen']]

  const subir = useMutacion({
    mutationFn: (archivo) => {
      const datos = new FormData()
      datos.append('logo', archivo)
      return api.post(url, datos, { timeout: 60_000 }).then((r) => r.data)
    },
    invalidar,
    exito: 'Logo actualizado.',
    avisarError: false,
  })
  const quitar = useMutacion({
    mutationFn: () => api.delete(url).then((r) => r.data),
    invalidar,
    exito: 'Logo eliminado.',
  })

  // Valida en el navegador (tipo y peso) antes de gastar la subida; el servidor vuelve a validar todo.
  const enviar = (archivo) => {
    if (!archivo) return
    if (!FORMATOS.includes(archivo.type)) return notificar('error', 'Usa un logo JPG, PNG o WEBP.')
    if (archivo.size > MAX_BYTES) return notificar('error', 'El logo pesa más de 2 MB.')
    subir.mutate(archivo, { onError: (error) => notificar('error', mensajeDeError(error)) })
  }
  const elegir = (evento) => {
    const archivo = evento.target.files?.[0]
    evento.target.value = ''
    enviar(archivo)
  }
  const alSoltar = (evento) => {
    evento.preventDefault()
    setArrastrando(false)
    if (!subir.isPending) enviar(evento.dataTransfer.files?.[0])
  }

  return (
    <PanelTarjeta id="logo" icono="camara" titulo="Logo" descripcion="Sale en los comprobantes y documentos. JPG, PNG o WEBP, máx. 2 MB; con fondo transparente se ve mejor.">
      <div className="logo-empresa">
        {empresa.tiene_logo ? (
          <div className="logo-vista">
            <div className="logo-placa">
              <ImagenProtegida url={`${url}?v=${encodeURIComponent(empresa.actualizado_en)}`} alt={`Logo de ${empresa.razon_social}`} className="logo-imagen" />
            </div>
          </div>
        ) : puedeEditar ? (
          <button
            type="button"
            className={`logo-subir${arrastrando ? ' arrastrando' : ''}`}
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
            <span>{subir.isPending ? 'Subiendo…' : 'Subir logo'}</span>
            <small>o suéltalo aquí</small>
          </button>
        ) : (
          <p className="celda-suave">Esta empresa aún no tiene logo.</p>
        )}
        {puedeEditar && empresa.tiene_logo && (
          <div className="logo-acciones">
            <button type="button" className="boton-cabecera" disabled={subir.isPending || quitar.isPending} onClick={() => entrada.current?.click()}>
              <Icono nombre="camara" tam={18} />
              {subir.isPending ? 'Subiendo…' : empresa.tiene_logo ? 'Cambiar logo' : 'Subir logo'}
            </button>
            {empresa.tiene_logo && (
              <button type="button" className="boton-cabecera" disabled={subir.isPending || quitar.isPending} onClick={() => quitar.mutate()}>
                <Icono nombre="papelera" tam={18} />
                Quitar
              </button>
            )}
          </div>
        )}
      </div>
      <input ref={entrada} type="file" hidden accept={FORMATOS.join(',')} onChange={elegir} />
    </PanelTarjeta>
  )
}
