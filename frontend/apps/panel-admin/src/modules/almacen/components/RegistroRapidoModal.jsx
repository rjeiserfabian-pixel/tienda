import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

// Qué se pide y a dónde se envía cada tipo. El alta completa sigue estando en Mantenimiento.
const TIPOS = {
  familia: { titulo: 'Nueva familia', url: '/mantenimiento/familias/', campos: [['nombre', 'Nombre de la familia', 'Ej. Periféricos', 100]] },
  categoria: { titulo: 'Nueva categoría', url: '/mantenimiento/categorias/', campos: [['nombre', 'Nombre de la categoría', 'Ej. Teclados', 100]] },
  marca: { titulo: 'Nueva marca', url: '/mantenimiento/marcas/', campos: [['nombre', 'Nombre de la marca', 'Ej. Logitech', 100]] },
  unidad: {
    titulo: 'Nueva unidad de medida',
    url: '/mantenimiento/unidades/',
    campos: [
      ['nombre', 'Nombre', 'Ej. Kilogramo', 100],
      ['abreviatura', 'Abreviatura', 'Ej. KG', 10],
    ],
  },
}

/** Alta rápida de un catálogo sin salir del producto. Al guardar devuelve el registro creado. */
export default function RegistroRapidoModal({ tipo, extra = {}, subtitulo, onCreado, onCerrar }) {
  const config = TIPOS[tipo]
  const [f, setF] = useState({})
  const [errores, setErrores] = useState({})

  const crear = useMutacion({
    mutationFn: (datos) => api.post(config.url, datos).then((r) => r.data),
    invalidar: [['opciones'], ['clasificacion'], ['marcas'], ['unidades']],
    exito: 'Registrado.',
    alExito: (creado) => onCreado(creado),
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    evento.stopPropagation() // no debe enviar el formulario del producto que está detrás
    if (crear.isPending) return
    const locales = {}
    for (const [campo, etiqueta] of config.campos) {
      if (!String(f[campo] ?? '').trim()) locales[campo] = `Ingrese ${etiqueta.toLowerCase()}.`
    }
    setErrores(locales)
    if (Object.keys(locales).length) return
    const datos = { ...extra }
    for (const [campo] of config.campos) datos[campo] = String(f[campo]).trim()
    crear.mutate(datos, { onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }) })
  }

  return (
    <Modal titulo={config.titulo} subtitulo={subtitulo ?? 'Se guarda y queda elegida en el producto.'} onCerrar={onCerrar} ancho={480}>
      <form onSubmit={enviar} noValidate>
        {config.campos.map(([campo, etiqueta, ejemplo, max], i) => (
          <Campo key={campo} etiqueta={etiqueta} requerido error={errores[campo]}>
            {(p) => (
              <input {...p} name={`rapido_${campo}`} autoFocus={i === 0} maxLength={max} placeholder={ejemplo} value={f[campo] ?? ''} disabled={crear.isPending} onChange={(e) => setF((previo) => ({ ...previo, [campo]: e.target.value }))} />
            )}
          </Campo>
        ))}
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={crear.isPending}>{crear.isPending ? 'Guardando…' : 'Guardar'}</button>
        </div>
      </form>
    </Modal>
  )
}
