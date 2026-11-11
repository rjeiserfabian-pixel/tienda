import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Campo from '../../../shared/components/Campo'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { agruparPorSeccion, valoresHuerfanos } from '../../mantenimiento/especificaciones'

const etiquetaDe = (c) => (c.unidad ? `${c.nombre} (${c.unidad})` : c.nombre)

/** Un dato técnico según su tipo: texto, número, lista de opciones o sí/no. */
function EntradaDato({ campo, valor, error, onCambio }) {
  const etiqueta = etiquetaDe(campo)
  if (campo.tipo === 'SI_NO') {
    const actual = valor === true ? 'si' : valor === false ? 'no' : ''
    return (
      <Campo etiqueta={etiqueta} tipo="select" error={error}>
        {(p) => (
          <select
            {...p}
            value={actual}
            onChange={(e) => onCambio(campo.clave, e.target.value === '' ? undefined : e.target.value === 'si')}
          >
            <option value="">—</option>
            <option value="si">Sí</option>
            <option value="no">No</option>
          </select>
        )}
      </Campo>
    )
  }
  if (campo.tipo === 'LISTA' && campo.opciones.length) {
    const texto = valor === undefined || valor === null ? '' : String(valor)
    const fuera = texto && !campo.opciones.includes(texto)
    return (
      <Campo etiqueta={etiqueta} tipo="select" error={error}>
        {(p) => (
          <select {...p} value={texto} onChange={(e) => onCambio(campo.clave, e.target.value || undefined)}>
            <option value="">—</option>
            {fuera && <option value={texto}>{texto}</option>}
            {campo.opciones.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        )}
      </Campo>
    )
  }
  const esNumero = campo.tipo === 'NUMERO'
  return (
    <Campo etiqueta={etiqueta} error={error}>
      {(p) => (
        <input
          {...p}
          value={valor === undefined || valor === null ? '' : String(valor)}
          maxLength={esNumero ? 14 : 200}
          inputMode={esNumero ? 'decimal' : undefined}
          placeholder={esNumero ? '0' : undefined}
          onChange={(e) => onCambio(campo.clave, e.target.value === '' ? undefined : e.target.value)}
        />
      )}
    </Campo>
  )
}

/**
 * Datos técnicos del producto según la plantilla de su categoría, agrupados por sección en bloques
 * plegables. Solo guarda los que se llenan; los vacíos no se envían.
 */
export default function EspecificacionesProducto({ categoriaId, campos, cargando, huboError, valores, errores, puedeDefinir, onCambio }) {
  const grupos = useMemo(() => agruparPorSeccion(campos.map((c) => ({ ...c, seccion: c.seccion }))), [campos])
  const sobran = useMemo(() => valoresHuerfanos(campos, valores), [campos, valores])
  // Lo que la persona abrió o cerró a mano; lo que no tocó se abre por defecto (las primeras tres).
  const [manual, setManual] = useState({})
  const raiz = useRef(null)

  // Al guardar con errores: se despliegan las secciones afectadas (aunque se hayan cerrado a mano)
  // y se lleva el cursor al primer dato con error, para que se vea qué corregir.
  useEffect(() => {
    const conError = grupos.filter((g) => g.campos.some((c) => errores?.[c.clave])).map((g) => g.seccion)
    if (conError.length === 0) return undefined
    setManual((previo) => ({ ...previo, ...Object.fromEntries(conError.map((s) => [s, true])) }))
    const espera = setTimeout(() => {
      const primero = raiz.current?.querySelector('[data-con-error="si"] input, [data-con-error="si"] select')
      if (primero) {
        primero.scrollIntoView({ block: 'center', behavior: 'smooth' })
        primero.focus({ preventScroll: true })
      }
    }, 80)
    return () => clearTimeout(espera)
  }, [errores, grupos])

  if (!categoriaId) return null
  if (cargando) {
    return (
      <PanelTarjeta id="especificaciones" icono="checklist" titulo="Especificaciones" descripcion="Los datos técnicos de este tipo de producto.">
        <p className="celda-suave" aria-live="polite">Cargando los datos de la categoría…</p>
      </PanelTarjeta>
    )
  }
  if (huboError) {
    return (
      <PanelTarjeta id="especificaciones" icono="checklist" titulo="Especificaciones" descripcion="Los datos técnicos de este tipo de producto.">
        <p role="alert" className="campo-error">No se pudieron cargar los datos técnicos de la categoría. Recarga la página para intentarlo de nuevo.</p>
      </PanelTarjeta>
    )
  }
  if (campos.length === 0) {
    return (
      <PanelTarjeta id="especificaciones" icono="checklist" titulo="Especificaciones" descripcion="Los datos técnicos de este tipo de producto.">
        <p className="celda-suave">
          Esta categoría aún no pide datos técnicos.{' '}
          {puedeDefinir ? (
            <>
              Defínelos en <Link to="/mantenimiento/clasificacion">Familias y categorías</Link>, con el botón «Especificaciones» de la categoría.
            </>
          ) : (
            'Pide a quien administra el catálogo que los defina.'
          )}
        </p>
        {sobran > 0 && <p className="espe-aviso" role="status">{sobran} dato(s) guardados antes ya no se piden y se descartarán al guardar.</p>}
      </PanelTarjeta>
    )
  }

  const llenos = campos.filter((c) => valores?.[c.clave] !== undefined && valores?.[c.clave] !== '').length
  return (
    <PanelTarjeta
      id="especificaciones"
      icono="checklist"
      titulo="Especificaciones"
      descripcion={`${llenos} de ${campos.length} datos completados. Llena los que conozcas: los vacíos no se muestran en la tienda.`}
    >
      {sobran > 0 && (
        <p className="espe-aviso" role="status">
          {sobran} dato(s) cargados antes no los pide esta categoría y se descartarán al guardar el producto.
        </p>
      )}
      {errores?._general && <p role="alert" className="campo-error">{errores._general}</p>}
      <div className="espe-secciones" ref={raiz}>
        {grupos.map((g, i) => {
          const errores_ = g.campos.filter((c) => errores?.[c.clave]).length
          const abierta = manual[g.seccion] ?? i < 3
          return (
            <details
              key={g.seccion}
              className="espe-seccion"
              open={abierta}
              onToggle={(e) => {
                const ahora = e.currentTarget.open
                setManual((previo) => (previo[g.seccion] === ahora ? previo : { ...previo, [g.seccion]: ahora }))
              }}
            >
              <summary>
                <span>{g.seccion}</span>
                {errores_ > 0 && <span className="espe-error-chip" role="status">{errores_ === 1 ? '1 por corregir' : `${errores_} por corregir`}</span>}
                <small>{g.campos.filter((c) => valores?.[c.clave] !== undefined && valores?.[c.clave] !== '').length}/{g.campos.length}</small>
              </summary>
              <div className="maestro-campos">
                {g.campos.map((c) => (
                  <div key={c.clave} className="espe-dato" data-con-error={errores?.[c.clave] ? 'si' : undefined}>
                    <EntradaDato campo={c} valor={valores?.[c.clave]} error={errores?.[c.clave]} onCambio={onCambio} />
                  </div>
                ))}
              </div>
            </details>
          )
        })}
      </div>
    </PanelTarjeta>
  )
}
