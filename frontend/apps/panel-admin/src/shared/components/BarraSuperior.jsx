import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../core/auth/AuthContext'
import { useEmpresas } from '../contexts/EmpresasContext'
import ChipsEmpresa from './ChipsEmpresa'
import { Icono } from './IconosPanel'

const FECHA = new Intl.DateTimeFormat('es-PE', { day: 'numeric', month: 'long', year: 'numeric' })
const HORA = new Intl.DateTimeFormat('es-PE', { hour: 'numeric', minute: '2-digit', hour12: true })

/** Fecha y hora actuales, refrescadas cada 15 s (suficiente para mostrar minutos). */
function useReloj() {
  const [ahora, setAhora] = useState(() => new Date())
  useEffect(() => {
    const intervalo = setInterval(() => setAhora(new Date()), 15_000)
    return () => clearInterval(intervalo)
  }, [])
  return ahora
}

function useCerrarAlClicFuera(abierto, cerrar) {
  const ref = useRef(null)
  useEffect(() => {
    if (!abierto) return undefined
    const alClic = (e) => ref.current && !ref.current.contains(e.target) && cerrar()
    const alTecla = (e) => e.key === 'Escape' && cerrar()
    document.addEventListener('mousedown', alClic)
    document.addEventListener('keydown', alTecla)
    return () => {
      document.removeEventListener('mousedown', alClic)
      document.removeEventListener('keydown', alTecla)
    }
  }, [abierto, cerrar])
  return ref
}

function iniciales(usuario) {
  const nombre = [usuario.nombres, usuario.apellidos].filter(Boolean).join(' ') || usuario.username
  return nombre
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('')
}

function MenuUsuario() {
  const { usuario, cerrarSesion } = useAuth()
  const { empresaActiva } = useEmpresas()
  const [abierto, setAbierto] = useState(false)
  const ref = useCerrarAlClicFuera(abierto, () => setAbierto(false))
  const nombre = usuario.nombres || usuario.username
  const cargo = empresaActiva?.cargo || (usuario.es_admin_plataforma ? 'Administrador de plataforma' : 'Usuario')

  return (
    <div className="usuario-menu" ref={ref}>
      <button
        type="button"
        className="usuario-boton"
        aria-haspopup="true"
        aria-expanded={abierto}
        onClick={() => setAbierto((v) => !v)}
      >
        <span className="avatar" aria-hidden="true">{iniciales(usuario)}</span>
        <span className="usuario-datos">
          <strong>{nombre}</strong>
          <small>{cargo}</small>
        </span>
        <Icono nombre="chevronAbajo" tam={16} />
      </button>
      {abierto && (
        <ul className="usuario-desplegable">
          <li><Link to="/cuenta/seguridad" onClick={() => setAbierto(false)}>Mi seguridad</Link></li>
          <li><Link to="/cuenta/password" onClick={() => setAbierto(false)}>Cambiar contraseña</Link></li>
          <li><Link to="/seguridad/sesiones" onClick={() => setAbierto(false)}>Mis sesiones</Link></li>
          <li className="separador" role="separator" />
          <li>
            <button type="button" onClick={cerrarSesion}>
              <Icono nombre="salir" tam={18} /> Cerrar sesión
            </button>
          </li>
        </ul>
      )}
    </div>
  )
}

function PantallaCompleta() {
  const [activa, setActiva] = useState(Boolean(document.fullscreenElement))
  useEffect(() => {
    const alCambiar = () => setActiva(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', alCambiar)
    return () => document.removeEventListener('fullscreenchange', alCambiar)
  }, [])

  const alternar = () => {
    // Puede rechazarse (p. ej. el navegador lo bloquea): no es un error para el usuario.
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
    else document.documentElement.requestFullscreen?.().catch(() => {})
  }
  return (
    <button
      type="button"
      className="barra-icono"
      onClick={alternar}
      aria-label={activa ? 'Salir de pantalla completa' : 'Pantalla completa'}
      aria-pressed={activa}
      title={activa ? 'Salir de pantalla completa' : 'Pantalla completa'}
    >
      <Icono nombre={activa ? 'contraer' : 'expandir'} tam={21} />
    </button>
  )
}

/** Barra superior: título de la sección, empresa activa, fecha y hora, accesos y usuario. */
export default function BarraSuperior({ titulo, iconoTitulo = 'inicio', alAbrirMenu }) {
  const ahora = useReloj()

  return (
    <header className="barra-superior">
      <button type="button" className="barra-icono solo-movil" onClick={alAbrirMenu} aria-label="Abrir menú">
        <Icono nombre="menu" tam={24} />
      </button>
      <h1 className="barra-titulo">
        <Icono nombre={iconoTitulo} tam={22} />
        <span>{titulo}</span>
      </h1>
      <div className="barra-empresas">
        <ChipsEmpresa />
      </div>
      <div className="barra-derecha">
        <span className="barra-dato oculto-medio">
          <Icono nombre="calendario" tam={19} />
          {FECHA.format(ahora)}
        </span>
        <span className="barra-dato">
          <Icono nombre="reloj" tam={19} />
          {HORA.format(ahora)}
        </span>
        {/* Notificaciones y mensajes aún no existen: se muestran deshabilitados, sin acción falsa. */}
        <button type="button" className="barra-icono oculto-medio" disabled title="Notificaciones: próximamente" aria-label="Notificaciones (próximamente)">
          <Icono nombre="bell" tam={21} />
        </button>
        <button type="button" className="barra-icono oculto-medio" disabled title="Mensajes: próximamente" aria-label="Mensajes (próximamente)">
          <Icono nombre="chat" tam={21} />
        </button>
        <PantallaCompleta />
        <MenuUsuario />
      </div>
    </header>
  )
}
