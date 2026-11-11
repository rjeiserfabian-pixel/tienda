import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { coincideRuta, estaDisponible } from '../../core/router/rutasDisponibles'
import { Icono } from './IconosPanel'

function EtiquetaPronto() {
  return <span className="menu-pronto">Pronto</span>
}

/** Ítem final (sin hijos): enlace si la pantalla existe; si no, entrada deshabilitada "Pronto". */
function ItemHoja({ nodo, nivel, rutaActual, alNavegar, compacto }) {
  const icono = nivel === 0 ? <Icono nombre={nodo.icono} tam={22} /> : null
  if (!estaDisponible(nodo.ruta)) {
    return (
      <li>
        <span className={`menu-item nivel-${nivel} pronto`} aria-disabled="true" title="Disponible próximamente">
          {icono}
          <span className="menu-texto">{nodo.nombre}</span>
          <EtiquetaPronto />
        </span>
      </li>
    )
  }
  const activo = coincideRuta(nodo.ruta, rutaActual)
  return (
    <li>
      <Link
        to={nodo.ruta}
        className={`menu-item nivel-${nivel}${activo ? ' activo' : ''}`}
        aria-current={activo ? 'page' : undefined}
        onClick={alNavegar}
        title={compacto ? nodo.nombre : undefined}
      >
        {icono}
        <span className="menu-texto">{nodo.nombre}</span>
      </Link>
    </li>
  )
}

function Grupo({ nodo, eleccion, alternar, rutaActual, alNavegar, compacto, alExpandir }) {
  const contieneActivo = nodo.hijos.some((h) => coincideRuta(h.ruta, rutaActual))
  // Sin elección del usuario, el grupo de la pantalla actual aparece abierto.
  const abierto = eleccion ?? contieneActivo
  const idSub = `submenu-${nodo.codigo}`
  return (
    <li>
      <button
        type="button"
        className={`menu-item nivel-0 grupo${contieneActivo ? ' contiene-activo' : ''}`}
        aria-expanded={abierto}
        aria-controls={idSub}
        title={compacto ? nodo.nombre : undefined}
        onClick={() => {
          // Comprimido, un grupo solo tiene ícono: se expande el menú y se abre ese grupo.
          if (compacto) {
            alExpandir()
            if (!abierto) alternar(nodo.codigo, abierto)
            return
          }
          alternar(nodo.codigo, abierto)
        }}
      >
        <Icono nombre={nodo.icono} tam={22} />
        <span className="menu-texto">{nodo.nombre}</span>
        <Icono nombre="chevronAbajo" tam={16} className={`menu-flecha${abierto ? ' abierta' : ''}`} />
      </button>
      {abierto && (
        <ul id={idSub} className="menu-sub">
          {nodo.hijos.map((h) => (
            <ItemHoja key={h.codigo} nodo={h} nivel={1} rutaActual={rutaActual} alNavegar={alNavegar} compacto={compacto} />
          ))}
        </ul>
      )}
    </li>
  )
}

/** Menú lateral dinámico: los módulos que el usuario puede ver, con grupos plegables. */
export default function MenuLateral({ menu, cargando, error, alNavegar, compacto = false, alExpandir = () => {} }) {
  const { pathname } = useLocation()
  // Lo que el usuario abrió o cerró a mano: { codigo: true | false }.
  const [elecciones, setElecciones] = useState({})
  const alternar = (codigo, abiertoAhora) => setElecciones((previas) => ({ ...previas, [codigo]: !abiertoAhora }))

  return (
    <nav className="menu" aria-label="Menú principal">
      <ul className="menu-lista">
        <li>
          <Link
            to="/"
            className={`menu-item nivel-0${pathname === '/' ? ' activo' : ''}`}
            aria-current={pathname === '/' ? 'page' : undefined}
            onClick={alNavegar}
            title={compacto ? 'Inicio' : undefined}
          >
            <Icono nombre="inicio" tam={22} />
            <span className="menu-texto">Inicio</span>
          </Link>
        </li>
        {cargando && <li className="menu-estado" aria-busy="true">Cargando menú…</li>}
        {error && <li className="menu-estado error" role="alert">No se pudo cargar el menú.</li>}
        {(menu ?? []).map((nodo) =>
          nodo.hijos.length > 0 ? (
            <Grupo
              key={nodo.codigo}
              nodo={nodo}
              eleccion={elecciones[nodo.codigo]}
              alternar={alternar}
              rutaActual={pathname}
              alNavegar={alNavegar}
              compacto={compacto}
              alExpandir={alExpandir}
            />
          ) : (
            <ItemHoja key={nodo.codigo} nodo={nodo} nivel={0} rutaActual={pathname} alNavegar={alNavegar} compacto={compacto} />
          ),
        )}
      </ul>
    </nav>
  )
}
