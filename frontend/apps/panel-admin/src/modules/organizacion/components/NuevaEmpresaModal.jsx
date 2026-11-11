import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

export default function NuevaEmpresaModal({ onCerrar, onCreada }) {
  const { renovarSesion } = useAuth()
  const [f, setF] = useState({ ruc: '', razon_social: '', nombre_comercial: '' })
  const [errores, setErrores] = useState({})

  const crear = useMutacion({
    mutationFn: async (datos) => {
      const { data } = await api.post('/organizacion/empresas/', datos)
      // El token fija las empresas habilitadas: se renueva para operar la nueva ya mismo.
      await renovarSesion()
      return data
    },
    invalidar: [['empresas'], ['usuarios']],
    exito: 'Empresa creada con su sucursal principal.',
    alExito: onCreada,
    avisarError: false,
  })

  const cambiar = (e) => setF((p) => ({ ...p, [e.target.name]: e.target.value }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const locales = {}
    if (!/^\d{11}$/.test(f.ruc)) locales.ruc = 'El RUC tiene 11 dígitos.'
    if (!f.razon_social.trim()) locales.razon_social = 'Ingrese la razón social.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    crear.mutate(f, {
      onError: (error) => setErrores({ general: 'No se pudo crear la empresa.', ...erroresDeCampo(error) }),
    })
  }

  return (
    <Modal titulo="Nueva empresa" subtitulo="Registra una empresa con su RUC. Se crea con su sucursal principal." onCerrar={onCerrar}>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="RUC" icono="documento" error={errores.ruc} ayuda="No se puede cambiar después.">
          {(p) => (
            <input {...p} name="ruc" placeholder="Ej. 20123456789" inputMode="numeric" maxLength={11} value={f.ruc} onChange={(e) => setF({ ...f, ruc: e.target.value.replace(/\D/g, '') })} />
          )}
        </Campo>
        <Campo etiqueta="Razón social" icono="building" error={errores.razon_social}>
          {(p) => <input {...p} placeholder="Ej. Mi Empresa S.A.C." name="razon_social" value={f.razon_social} onChange={cambiar} />}
        </Campo>
        <Campo etiqueta="Nombre comercial" icono="store" error={errores.nombre_comercial}>
          {(p) => <input {...p} placeholder="Ej. Mi Empresa" name="nombre_comercial" value={f.nombre_comercial} onChange={cambiar} />}
        </Campo>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={crear.isPending}>
            {crear.isPending ? 'Creando…' : 'Crear empresa'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
