'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useId, useMemo, useRef, useState, useTransition } from 'react'
import { enlaceConFiltros } from '@/lib/filtros'
import Icono from './Icono'
import { textoCantidad } from './listado-util'

export const ID_CAJON_FILTROS = 'lis-cajon-filtros'

/** Un precio escrito por la persona → número válido o `null` (vacío) o `NaN` (inválido). */
function leerPrecio(texto) {
  const limpio = String(texto ?? '').trim().replace(',', '.')
  if (limpio === '') return null
  const n = Number(limpio)
  return Number.isFinite(n) && n >= 0 ? n : Number.NaN
}

/** Casilla con su etiqueta y cantidad. */
function Casilla({ id, marcada, texto, cantidad, deshabilitada, alCambiar }) {
  return (
    <li>
      <label className="lis-casilla" htmlFor={id}>
        <input id={id} type="checkbox" checked={marcada} disabled={deshabilitada} onChange={alCambiar} />
        <span className="lis-casilla-texto">{texto}</span>
        {cantidad !== undefined && <span className="lis-casilla-cantidad">{cantidad}</span>}
      </label>
    </li>
  )
}

/** El contenido de los filtros: se dibuja dos veces (columna en computadora, cajón en celular). */
function Contenido({ idBase, filtros, facetas, marcaFija, ir, pendiente }) {
  const [errorPrecio, setErrorPrecio] = useState('')
  const rango = facetas?.precio
  const alternar = (lista, valor) => (lista.includes(valor) ? lista.filter((v) => v !== valor) : [...lista, valor])

  const aplicarPrecio = (e) => {
    e.preventDefault()
    const datos = new FormData(e.currentTarget)
    const min = leerPrecio(datos.get('precio_min'))
    const max = leerPrecio(datos.get('precio_max'))
    if (Number.isNaN(min) || Number.isNaN(max)) {
      setErrorPrecio('Escribe solo números, por ejemplo 150.')
      return
    }
    if (min !== null && max !== null && min > max) {
      setErrorPrecio('El mínimo no puede ser mayor que el máximo.')
      return
    }
    setErrorPrecio('')
    ir({ precio_min: min === null ? '' : String(min), precio_max: max === null ? '' : String(max) })
  }

  return (
    <div className="lis-filtros" aria-busy={pendiente}>
      {!marcaFija && facetas?.marcas?.length > 0 && (
        <fieldset className="lis-grupo">
          <legend>Marca</legend>
          <ul>
            {facetas.marcas.map((m) => (
              <Casilla
                key={m.slug}
                id={`${idBase}-m-${m.slug}`}
                marcada={filtros.marca.includes(m.slug)}
                texto={m.nombre}
                cantidad={m.cantidad}
                alCambiar={() => ir({ marca: alternar(filtros.marca, m.slug) })}
              />
            ))}
          </ul>
        </fieldset>
      )}

      <fieldset className="lis-grupo">
        <legend>Precio (S/)</legend>
        <form
          className="lis-precio"
          key={`${filtros.precio_min}-${filtros.precio_max}`}
          onSubmit={aplicarPrecio}
          noValidate
        >
          <div className="lis-precio-campos">
            <label>
              <span className="sr-solo">Precio mínimo</span>
              <input
                name="precio_min"
                inputMode="decimal"
                placeholder={rango?.minimo ? `Mín. ${Math.floor(Number(rango.minimo))}` : 'Mínimo'}
                defaultValue={filtros.precio_min}
                aria-invalid={Boolean(errorPrecio)}
              />
            </label>
            <span aria-hidden="true">–</span>
            <label>
              <span className="sr-solo">Precio máximo</span>
              <input
                name="precio_max"
                inputMode="decimal"
                placeholder={rango?.maximo ? `Máx. ${Math.ceil(Number(rango.maximo))}` : 'Máximo'}
                defaultValue={filtros.precio_max}
                aria-invalid={Boolean(errorPrecio)}
              />
            </label>
          </div>
          {errorPrecio && (
            <p className="lis-error" role="alert">
              {errorPrecio}
            </p>
          )}
          {rango?.minimo && rango?.maximo && rango.minimo !== rango.maximo && (
            <p className="lis-ayuda">
              Disponible entre S/ {Number(rango.minimo).toLocaleString('es-PE')} y S/ {Number(rango.maximo).toLocaleString('es-PE')}
            </p>
          )}
          <button type="submit" className="boton secundario chico" disabled={pendiente}>
            Aplicar
          </button>
        </form>
      </fieldset>

      <fieldset className="lis-grupo">
        <legend>Disponibilidad</legend>
        <ul>
          <Casilla
            id={`${idBase}-stock`}
            marcada={filtros.disponible}
            texto="Solo con stock"
            alCambiar={() => ir({ disponible: !filtros.disponible })}
          />
        </ul>
      </fieldset>

      {facetas?.especificaciones?.map((campo, i) => {
        const elegidos = filtros.esp[campo.clave] ?? []
        return (
          <details key={campo.clave} className="lis-detalle" open={i < 3 || elegidos.length > 0}>
            <summary>
              <span>{campo.nombre}</span>
              {elegidos.length > 0 && <span className="lis-contador">{elegidos.length}</span>}
              <Icono nombre="chevron" tam={18} />
            </summary>
            <ul>
              {campo.opciones.map((o) => (
                <Casilla
                  key={o.valor}
                  id={`${idBase}-e-${campo.clave}-${o.valor}`}
                  marcada={elegidos.includes(o.valor)}
                  texto={o.etiqueta}
                  cantidad={o.cantidad}
                  alCambiar={() => {
                    const esp = { ...filtros.esp }
                    const nuevos = alternar(elegidos, o.valor)
                    if (nuevos.length) esp[campo.clave] = nuevos
                    else delete esp[campo.clave]
                    ir({ esp })
                  }}
                />
              ))}
            </ul>
          </details>
        )
      })}
    </div>
  )
}

/**
 * Filtros del listado: columna fija en computadora y cajón (<dialog>) en celular y tablet.
 * Cada cambio navega a la dirección con los filtros (el estado vive en la URL) dentro de una
 * transición, así la pantalla no se bloquea y se muestra una barra de progreso.
 */
export default function FiltrosPanel({ rutaBase, rutaLimpia, filtros, facetas, total, marcaFija = false, hayFiltros }) {
  const id = useId()
  const router = useRouter()
  const dialogo = useRef(null)
  const [pendiente, empezar] = useTransition()

  const ir = useMemo(
    () => (cambios) => empezar(() => router.push(enlaceConFiltros(rutaBase, filtros, cambios), { scroll: false })),
    [router, rutaBase, filtros],
  )
  const cerrar = () => dialogo.current?.close()
  const propiedades = { filtros, facetas, marcaFija, ir, pendiente }

  return (
    <>
      {pendiente && <div className="lis-progreso" role="progressbar" aria-label="Actualizando resultados" />}
      <aside className="lis-lateral" aria-label="Filtros">
        <div className="lis-lateral-cabecera">
          <h2>Filtros</h2>
          {hayFiltros && (
            <Link href={rutaLimpia} className="lis-limpiar" scroll={false}>
              Limpiar
            </Link>
          )}
        </div>
        <Contenido idBase={`${id}-lat`} {...propiedades} />
      </aside>

      <dialog
        ref={dialogo}
        id={ID_CAJON_FILTROS}
        className="lis-cajon"
        aria-label="Filtros"
        onClick={(e) => {
          if (e.target === dialogo.current) cerrar()
        }}
      >
        <div className="lis-cajon-caja">
          <div className="lis-cajon-cabecera">
            <h2>Filtros</h2>
            <button type="button" className="cab-icono" aria-label="Cerrar los filtros" onClick={cerrar}>
              <Icono nombre="cerrar" tam={22} />
            </button>
          </div>
          <div className="lis-cajon-cuerpo">
            <Contenido idBase={`${id}-caj`} {...propiedades} />
          </div>
          <div className="lis-cajon-pie">
            {hayFiltros ? (
              <Link href={rutaLimpia} className="boton secundario" scroll={false} onClick={cerrar}>
                Limpiar
              </Link>
            ) : (
              <span />
            )}
            <button type="button" className="boton" onClick={cerrar}>
              {pendiente ? 'Actualizando…' : `Ver ${textoCantidad(total)}`}
            </button>
          </div>
        </div>
      </dialog>
    </>
  )
}
