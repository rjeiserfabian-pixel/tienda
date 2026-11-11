import { useEffect, useMemo, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../core/auth/AuthContext'
import { MARCA } from '../../core/marca'
import { coincideRuta } from '../../core/router/rutasDisponibles'
import { LogoMarca } from '../../modules/seguridad/components/Iconos'
import BarraSuperior from '../components/BarraSuperior'
import { Icono } from '../components/IconosPanel'
import MenuLateral from '../components/MenuLateral'
import { useMenu } from '../hooks/useMenu'
import '../components/listados.css'
import './layout.css'

// Títulos de pantallas que no aparecen en el menú del servidor.
const TITULOS_EXTRA = {
  '/cuenta/password': 'Cambiar contraseña',
  '/cuenta/seguridad': 'Mi seguridad',
}

/** Título e icono de la barra superior: el ítem de menú más específico que coincide con la ruta. */
function seccionDe(menu, ruta) {
  if (ruta === '/') return { titulo: 'Inicio', icono: 'inicio' }
  const hojas = (menu ?? []).flatMap((n) =>
    n.hijos.length ? n.hijos.map((h) => ({ ...h, icono: n.icono, grupo: n.nombre })) : [n],
  )
  const mejor = hojas
    .filter((h) => coincideRuta(h.ruta, ruta))
    .sort((a, b) => b.ruta.length - a.ruta.length)[0]
  if (mejor) return { titulo: mejor.nombre, icono: mejor.icono, grupo: mejor.grupo }
  return { titulo: TITULOS_EXTRA[ruta] ?? 'Panel', icono: ruta.startsWith('/cuenta') ? 'lock' : 'inicio' }
}

const CLAVE_COMPACTO = 'panel.menu.compacto'

function leerCompacto() {
  try {
    return localStorage.getItem(CLAVE_COMPACTO) === '1'
  } catch {
    return false
  }
}

export default function DashboardLayout() {
  const { organizacion } = useAuth()
  const { data: menu, isLoading, isError } = useMenu()
  const { pathname } = useLocation()
  const [menuAbierto, setMenuAbierto] = useState(false)
  // Menú comprimido (solo íconos) en pantallas grandes; se recuerda en este navegador.
  const [compacto, setCompacto] = useState(leerCompacto)
  const cambiarCompacto = (valor) => {
    setCompacto(valor)
    try {
      localStorage.setItem(CLAVE_COMPACTO, valor ? '1' : '0')
    } catch {
      // sin almacenamiento: solo dura esta visita
    }
  }

  // En pantallas pequeñas el menú es un panel deslizable: se cierra al elegir una opción
  // (``alNavegar``), al tocar el velo y con Escape.
  useEffect(() => {
    if (!menuAbierto) return undefined
    const alTecla = (e) => e.key === 'Escape' && setMenuAbierto(false)
    document.addEventListener('keydown', alTecla)
    return () => document.removeEventListener('keydown', alTecla)
  }, [menuAbierto])

  const seccion = useMemo(() => seccionDe(menu, pathname), [menu, pathname])

  return (
    <div className={`panel${compacto ? ' compacto' : ''}`}>
      <aside className={`lateral${menuAbierto ? ' abierto' : ''}`}>
        <div className="lateral-marca">
          <Link to="/" aria-label={`${MARCA.nombre}: ir al inicio`} className="lateral-logo">
            <LogoMarca tam={40} />
            <span className="lateral-wordmark" aria-hidden="true">
              {MARCA.nombrePrincipal}
              <span>{MARCA.nombreAcento}</span>
            </span>
          </Link>
          <button type="button" className="barra-icono solo-movil" onClick={() => setMenuAbierto(false)} aria-label="Cerrar menú">
            <Icono nombre="cerrar" tam={22} />
          </button>
        </div>
        {organizacion?.nombre && <p className="lateral-organizacion">{organizacion.nombre}</p>}

        <button
          type="button"
          className="lateral-comprimir"
          onClick={() => cambiarCompacto(!compacto)}
          aria-label={compacto ? 'Expandir el menú' : 'Comprimir el menú'}
          aria-pressed={compacto}
          title={compacto ? 'Expandir el menú' : 'Comprimir el menú'}
        >
          <Icono nombre={compacto ? 'chevron' : 'chevronIzq'} tam={16} />
        </button>

        <div className="lateral-scroll">
          <MenuLateral
            menu={menu}
            cargando={isLoading}
            error={isError}
            compacto={compacto}
            alExpandir={() => cambiarCompacto(false)}
            alNavegar={() => setMenuAbierto(false)}
          />
        </div>

        <div className="lateral-pie">
          <Link to="/cuenta/seguridad" className="lateral-enlace" title="Configuración">
            <Icono nombre="settings" tam={20} /> <span className="lateral-enlace-texto">Configuración</span>
          </Link>
        </div>
      </aside>

      {menuAbierto && <button type="button" className="panel-velo" aria-label="Cerrar menú" onClick={() => setMenuAbierto(false)} />}

      <div className="panel-contenido">
        <BarraSuperior titulo={seccion.titulo} iconoTitulo={seccion.icono} alAbrirMenu={() => setMenuAbierto(true)} />
        <div className="panel-principal">
          {pathname !== '/' && (
            <nav className="migas" aria-label="Ruta de navegación">
              <Link to="/" aria-label="Inicio">
                <Icono nombre="inicio" tam={18} />
              </Link>
              <Icono nombre="chevron" tam={14} />
              {seccion.grupo && (
                <>
                  <span>{seccion.grupo}</span>
                  <Icono nombre="chevron" tam={14} />
                </>
              )}
              <span aria-current="page">{seccion.titulo}</span>
            </nav>
          )}
          <Outlet />
        </div>
      </div>
    </div>
  )
}
