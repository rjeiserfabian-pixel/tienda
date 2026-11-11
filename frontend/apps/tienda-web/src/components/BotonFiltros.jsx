'use client'

import Icono from './Icono'

/** El botón «Filtros» de la barra (celular y tablet): abre el cajón de filtros. */
export default function BotonFiltros({ activos = 0 }) {
  return (
    <button
      type="button"
      className="lis-btn-filtros"
      aria-haspopup="dialog"
      onClick={() => document.getElementById('lis-cajon-filtros')?.showModal()}
    >
      <Icono nombre="filtro" tam={18} /> Filtros
      {activos > 0 && (
        <span className="lis-contador" aria-label={`${activos} filtros aplicados`}>
          {activos}
        </span>
      )}
    </button>
  )
}
