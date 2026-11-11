import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import ActivarMfa, { CodigosRecuperacion } from '../components/ActivarMfa'

/** Operaciones sensibles del factor: piden contraseña Y un código vigente. */
function ModalCredenciales({ titulo, textoBoton, onCerrar, enviar, alExito }) {
  const [f, setF] = useState({ password: '', codigo: '' })
  const [errores, setErrores] = useState({})
  const accion = useMutacion({ mutationFn: enviar, avisarError: false, alExito })

  return (
    <Modal titulo={titulo} subtitulo="Por seguridad, confirma tu contraseña y un código de verificación." onCerrar={onCerrar} ancho={480}>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (accion.isPending) return
          const locales = {}
          if (!f.password) locales.password = 'Ingrese su contraseña.'
          if (!f.codigo.trim()) locales.codigo = 'Ingrese un código.'
          setErrores(locales)
          if (Object.keys(locales).length) return
          accion.mutate(f, {
            onError: (error) => setErrores({ general: mensajeDeError(error), ...erroresDeCampo(error) }),
          })
        }}
      >
        <Campo etiqueta="Contraseña" icono="lock" error={errores.password}>
          {(p) => <input {...p} placeholder="Tu contraseña actual" type="password" autoComplete="current-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />}
        </Campo>
        <Campo etiqueta="Código del autenticador (o de recuperación)" icono="shield" error={errores.codigo}>
          {(p) => <input {...p} placeholder="Código de 6 dígitos o de recuperación" autoComplete="one-time-code" value={f.codigo} onChange={(e) => setF({ ...f, codigo: e.target.value })} />}
        </Campo>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={accion.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={accion.isPending}>
            {accion.isPending ? 'Procesando…' : textoBoton}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function CuentaSeguridadPage() {
  const { usuario, renovarSesion } = useAuth()
  const [activando, setActivando] = useState(false)
  const [modal, setModal] = useState(null) // 'desactivar' | 'codigos'
  const [nuevosCodigos, setNuevosCodigos] = useState(null)

  const consulta = useQuery({
    queryKey: ['mfa', 'estado'],
    queryFn: ({ signal }) => api.get('/seguridad/mfa/', { signal }).then((r) => r.data),
  })
  const estado = consulta.data

  return (
    <main className="listado">
      <CabeceraListado
        icono="lock"
        titulo="Mi seguridad"
        descripcion="Protege tu cuenta: verificación en dos pasos, contraseña y sesiones abiertas."
      />
      {usuario.debe_configurar_mfa && (
        <p role="alert" className="campo-error">
          Su organización exige la verificación en dos pasos. Actívela para seguir usando el sistema.
        </p>
      )}

      <div className="rejilla-paneles">
        <PanelTarjeta id="mfa" icono="shield" titulo="Verificación en dos pasos" descripcion="Un código de tu celular además de la contraseña.">
          <EstadoConsulta consulta={consulta} hayDatos={Boolean(estado)}>
            {estado && (
              <>
                <p>
                  <span className="texto-pildora-fila">
                    <span className={`estado-pildora ${estado.activo ? 'activo' : 'inactivo'}`}>
                      {estado.activo ? 'Activada' : 'Desactivada'}
                    </span>
                    {estado.obligatorio && <span className="pildora" data-tono="ambar">Obligatoria en tu organización</span>}
                  </span>
                </p>
                {estado.activo ? (
                  <>
                    <p className="celda-suave">Códigos de recuperación disponibles: <strong style={{ color: '#fff' }}>{estado.codigos_restantes}</strong></p>
                    <div className="fila-botones">
                      <button type="button" className="boton-cabecera" onClick={() => setModal('codigos')}>
                        <Icono nombre="reactivar" tam={19} /> Generar códigos nuevos
                      </button>
                      {!estado.obligatorio && (
                        <button type="button" className="peligro boton-cabecera" onClick={() => setModal('desactivar')}>
                          <Icono nombre="apagar" tam={19} /> Desactivar
                        </button>
                      )}
                    </div>
                  </>
                ) : activando ? (
                  <ActivarMfa onTerminado={() => setActivando(false)} />
                ) : (
                  <button type="button" className="primario boton-cabecera" onClick={() => setActivando(true)}>
                    <Icono nombre="shield" tam={19} /> Activar verificación
                  </button>
                )}
              </>
            )}
          </EstadoConsulta>
        </PanelTarjeta>

        <PanelTarjeta icono="key" titulo="Contraseña" descripcion="Cámbiala si sospechas que alguien la conoce.">
          <p className="celda-suave">Al cambiarla se cerrarán tus otras sesiones abiertas.</p>
          <Link to="/cuenta/password" className="boton-cabecera primario">
            <Icono nombre="lapiz" tam={19} /> Cambiar contraseña
          </Link>
        </PanelTarjeta>

        <PanelTarjeta icono="devices" titulo="Sesiones" descripcion="Dispositivos donde tienes la sesión abierta.">
          <p className="celda-suave">Revisa y cierra las sesiones que no reconozcas.</p>
          <Link to="/seguridad/sesiones" className="boton-cabecera">
            <Icono nombre="ojo" tam={19} /> Ver mis sesiones
          </Link>
        </PanelTarjeta>
      </div>

      {modal === 'desactivar' && (
        <ModalCredenciales
          titulo="Desactivar verificación en dos pasos"
          textoBoton="Desactivar"
          onCerrar={() => setModal(null)}
          enviar={(f) => api.post('/seguridad/mfa/desactivar/', f)}
          alExito={async () => {
            setModal(null)
            await renovarSesion()
            consulta.refetch()
          }}
        />
      )}
      {modal === 'codigos' && !nuevosCodigos && (
        <ModalCredenciales
          titulo="Generar códigos de recuperación"
          textoBoton="Generar"
          onCerrar={() => setModal(null)}
          enviar={(f) => api.post('/seguridad/mfa/codigos-recuperacion/', f).then((r) => r.data)}
          alExito={(datos) => {
            setNuevosCodigos(datos.codigos_recuperacion)
            consulta.refetch()
          }}
        />
      )}
      {nuevosCodigos && (
        <Modal titulo="Códigos de recuperación" subtitulo="Guárdalos en un lugar seguro." onCerrar={() => { setNuevosCodigos(null); setModal(null) }}>
          <p>Los códigos anteriores dejaron de valer.</p>
          <CodigosRecuperacion codigos={nuevosCodigos} onListo={() => { setNuevosCodigos(null); setModal(null) }} />
        </Modal>
      )}
    </main>
  )
}
