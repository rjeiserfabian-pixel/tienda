import { useEffect, useRef, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { bannerDesdeServidor, bannerVacio, errorDeArchivo, formularioDeBanner, revisarBanner, TIPOS_IMAGEN } from '../ofertas'

const CLAVE = ['tienda', 'banners']

/** Vista previa de una imagen: la recién elegida o, si no hay, la guardada (se pide con sesión). */
function Vista({ archivo, bannerId, tam, existe, version, vacio }) {
  const [direccion, setDireccion] = useState(null)
  useEffect(() => {
    if (archivo) {
      const url = URL.createObjectURL(archivo)
      setDireccion(url)
      return () => URL.revokeObjectURL(url)
    }
    if (!existe || !bannerId) {
      setDireccion(null)
      return undefined
    }
    const control = new AbortController()
    let url = null
    api
      .get(`/tienda/admin/banners/${bannerId}/imagen/${tam}/`, { responseType: 'blob', signal: control.signal })
      .then((r) => {
        url = URL.createObjectURL(r.data)
        setDireccion(url)
      })
      .catch(() => !control.signal.aborted && setDireccion(null))
    return () => {
      control.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [archivo, bannerId, tam, existe, version])
  return <div className={`banner-vista banner-vista-${tam}`}>{direccion ? <img src={direccion} alt="" /> : <span className="celda-suave">{vacio}</span>}</div>
}

/** Crear o editar un banner del inicio de la tienda. */
export default function BannerModal({ banner, onCerrar }) {
  const [form, setForm] = useState(() => (banner ? bannerDesdeServidor(banner) : bannerVacio()))
  const [escritorio, setEscritorio] = useState(null)
  const [movil, setMovil] = useState(null)
  const [quitarMovil, setQuitarMovil] = useState(false)
  const [errores, setErrores] = useState({})
  const refEscritorio = useRef(null)
  const refMovil = useRef(null)

  const cambiar = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined }))
  }

  const elegir = (tipo) => (evento) => {
    const archivo = evento.target.files?.[0]
    evento.target.value = ''
    if (!archivo) return
    const clave = tipo === 'escritorio' ? 'imagen_escritorio' : 'imagen_movil'
    const mensaje = errorDeArchivo(archivo)
    setErrores((e) => ({ ...e, [clave]: mensaje || undefined }))
    if (mensaje) return
    if (tipo === 'escritorio') setEscritorio(archivo)
    else {
      setMovil(archivo)
      setQuitarMovil(false)
    }
  }

  const guardar = useMutacion({
    mutationFn: (cuerpo) => (form.id ? api.patch(`/tienda/admin/banners/${form.id}/`, cuerpo) : api.post('/tienda/admin/banners/', cuerpo)).then((r) => r.data),
    invalidar: [CLAVE],
    exito: form.id ? 'Banner actualizado.' : 'Banner creado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const alGuardar = (evento) => {
    evento.preventDefault()
    const locales = revisarBanner(form, { escritorio, requiereEscritorio: true })
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    guardar.mutate(formularioDeBanner(form, { escritorio, movil, quitarMovil }), {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }
  const otroError = errores._general && !Object.keys(errores).some((k) => k !== '_general' && errores[k])
  const hayMovil = Boolean(movil) || (form.tiene_movil && !quitarMovil)

  return (
    <Modal titulo={form.id ? 'Editar banner' : 'Nuevo banner'} subtitulo="Una imagen promocional para el inicio de la tienda." onCerrar={onCerrar} ancho={760}>
      <form onSubmit={alGuardar} noValidate className="envios-form">
        <fieldset className="banner-imagenes">
          <legend>Imágenes</legend>
          <div>
            <p className="campo-etiqueta">Para computadora (recomendado 1600 × 600)</p>
            <Vista archivo={escritorio} bannerId={form.id} tam="escritorio" existe={form.tiene_escritorio} version={form.version} vacio="Sin imagen" />
            <input ref={refEscritorio} type="file" accept={TIPOS_IMAGEN.join(',')} hidden onChange={elegir('escritorio')} />
            <button type="button" className="boton-cabecera" onClick={() => refEscritorio.current?.click()}>
              {escritorio || form.tiene_escritorio ? 'Cambiar imagen' : 'Subir imagen'}
            </button>
            {errores.imagen_escritorio && (
              <p role="alert" className="campo-error">
                {errores.imagen_escritorio}
              </p>
            )}
          </div>
          <div>
            <p className="campo-etiqueta">
              Para celular <span className="campo-opcional">(opcional, cuadrada 800 × 800)</span>
            </p>
            <Vista archivo={movil} bannerId={form.id} tam="movil" existe={form.tiene_movil && !quitarMovil} version={form.version} vacio="Se usa la de computadora" />
            <input ref={refMovil} type="file" accept={TIPOS_IMAGEN.join(',')} hidden onChange={elegir('movil')} />
            <div className="banner-botones">
              <button type="button" className="boton-cabecera" onClick={() => refMovil.current?.click()}>
                {hayMovil ? 'Cambiar imagen' : 'Subir imagen'}
              </button>
              {hayMovil && (
                <button
                  type="button"
                  className="boton-cabecera"
                  onClick={() => {
                    setMovil(null)
                    setQuitarMovil(true)
                  }}
                >
                  Quitar
                </button>
              )}
            </div>
            {errores.imagen_movil && (
              <p role="alert" className="campo-error">
                {errores.imagen_movil}
              </p>
            )}
          </div>
          <p className="campo-ayuda">JPG, PNG o WEBP de hasta 3 MB. La imagen se recorta al tamaño del banner: deja lo importante al centro.</p>
        </fieldset>

        <div className="maestro-campos">
          <Campo etiqueta="Título" requerido error={errores.titulo}>
            {(p) => <input {...p} name="titulo" value={form.titulo} maxLength={100} onChange={(e) => cambiar('titulo', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Subtítulo (opcional)" error={errores.subtitulo}>
            {(p) => <input {...p} name="subtitulo" value={form.subtitulo} maxLength={160} onChange={(e) => cambiar('subtitulo', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Texto del botón (opcional)" error={errores.boton_texto} ayuda="Ej.: Ver ofertas.">
            {(p) => <input {...p} name="boton_texto" value={form.boton_texto} maxLength={30} onChange={(e) => cambiar('boton_texto', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Enlace (opcional)" error={errores.enlace} ayuda="Una página de la tienda (ej.: /ofertas, /categoria/laptops) o una URL que empiece con https://.">
            {(p) => <input {...p} name="enlace" value={form.enlace} maxLength={300} placeholder="/ofertas" onChange={(e) => cambiar('enlace', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Descripción de la imagen" requerido error={errores.alt} ayuda="La leen quienes usan lector de pantalla. Ej.: Laptops y monitores con descuento.">
            {(p) => <input {...p} name="alt" value={form.alt} maxLength={150} onChange={(e) => cambiar('alt', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Orden" error={errores.orden} ayuda="El 0 sale primero.">
            {(p) => <input {...p} name="orden" inputMode="numeric" value={form.orden} onChange={(e) => cambiar('orden', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Se muestra desde (opcional)" error={errores.desde}>
            {(p) => <input {...p} name="desde" type="datetime-local" value={form.desde} onChange={(e) => cambiar('desde', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Se muestra hasta (opcional)" error={errores.hasta}>
            {(p) => <input {...p} name="hasta" type="datetime-local" value={form.hasta} onChange={(e) => cambiar('hasta', e.target.value)} />}
          </Campo>
        </div>

        <Interruptor
          activo={form.activo}
          onCambio={(v) => cambiar('activo', v)}
          texto={form.activo ? 'Banner activo' : 'Banner pausado'}
          descripcion={form.activo ? 'Se muestra en el inicio dentro de sus fechas.' : 'No se muestra a los clientes.'}
        />

        {otroError && (
          <p role="alert" className="campo-error">
            {errores._general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar banner'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
