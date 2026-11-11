import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { datosParaEnviar, generoDe } from '../maestros'
import CamposMaestro from './CamposMaestro'

/** Alta de un maestro: formulario premium en ventana, con validación local antes de enviar. `alCrear` recibe el registro creado y `valores` precarga algunos campos. */
export default function MaestroModal({ config, onCerrar, alCrear, valores }) {
  const { empresaActivaId } = useEmpresas()
  const [f, setF] = useState({ ...config.inicial, ...valores, empresa: config.porEmpresa && empresaActivaId ? String(empresaActivaId) : '' })
  const [errores, setErrores] = useState({})

  const crear = useMutacion({
    mutationFn: (datos) => api.post(config.endpoint, datos).then((r) => r.data),
    invalidar: [[config.clave], ['opciones']],
    exito: `${config.singular.charAt(0).toUpperCase()}${config.singular.slice(1)} registrad${generoDe(config).o}.`,
    alExito: (creado) => {
      alCrear?.(creado) // p. ej. Registrar compra deja elegido al proveedor recién creado
      onCerrar()
    },
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const locales = config.validar(f)
    if (config.porEmpresa && !f.empresa) locales.empresa = 'Elija la empresa.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    crear.mutate(datosParaEnviar(config, f, { alta: true }), {
      onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }),
    })
  }

  return (
    <Modal titulo={`${generoDe(config).nuevo} ${config.singular}`} subtitulo="Completa los datos para registrarlo." onCerrar={onCerrar} ancho={760}>
      <form onSubmit={enviar} noValidate>
        <CamposMaestro
          config={config}
          alta
          valores={f}
          errores={errores}
          deshabilitado={crear.isPending}
          onCambio={(campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))}
        />
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={crear.isPending}>
            {crear.isPending ? 'Guardando…' : `Registrar ${config.singular}`}
          </button>
        </div>
      </form>
    </Modal>
  )
}
