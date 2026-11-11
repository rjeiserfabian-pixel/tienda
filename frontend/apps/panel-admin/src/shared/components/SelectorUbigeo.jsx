import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { api } from '../../core/api/client'
import { useDebounce } from '../hooks/useDebounce'
import { Icono } from './IconosPanel'
import './selector-ubigeo.css'

const MINIMO_LETRAS = 2
const RESULTADOS = 10

/** El departamento, la provincia y el distrito de un ubigeo (se pide una vez y se recuerda). */
function useUbigeo(codigo) {
  return useQuery({
    queryKey: ['ubigeo', codigo],
    queryFn: ({ signal }) => api.get('/mantenimiento/ubigeos/', { params: { codigo }, signal }).then((r) => r.data.results[0] ?? null),
    enabled: Boolean(codigo),
    staleTime: Infinity,
  })
}

/**
 * Elige el distrito (ubigeo del INEI) de una dirección escribiendo su nombre: «tarapoto», «san martin»…
 * Busca en el servidor con un retraso de 300 ms (sin tildes ni mayúsculas) y se maneja con el mouse o
 * con las flechas, Enter y Escape. `valor` es el código de 6 dígitos ('' si no hay) y `onCambio` recibe
 * el código elegido. Se usa dentro de un `Campo`: recibe sus propiedades (id, aria-…) para el cuadro.
 */
export default function SelectorUbigeo({ valor = '', onCambio, lectura = false, disabled = false, placeholder = 'Escribe el distrito. Ej. Tarapoto', ...propiedadesDelCampo }) {
  const idLista = useId()
  const [texto, setTexto] = useState('')
  const [escribiendo, setEscribiendo] = useState(false)
  const [activo, setActivo] = useState(0)
  const actual = useUbigeo(valor)
  const nombreActual = valor ? (actual.data?.nombre_completo ?? valor) : ''

  const q = useDebounce(texto.trim(), 300)
  const buscar = escribiendo && q.length >= MINIMO_LETRAS
  const busqueda = useQuery({
    queryKey: ['ubigeos', q],
    queryFn: ({ signal }) => api.get('/mantenimiento/ubigeos/', { params: { q, page_size: RESULTADOS }, signal }).then((r) => r.data.results),
    enabled: buscar,
    staleTime: 5 * 60_000,
    placeholderData: (previo) => previo,
  })
  const opciones = buscar ? (busqueda.data ?? []) : []

  if (lectura) return <input {...propiedadesDelCampo} readOnly disabled value={nombreActual || 'No registrado'} />

  const cerrar = () => {
    setEscribiendo(false)
    setTexto('')
    setActivo(0)
  }
  const elegir = (ubigeo) => {
    onCambio(ubigeo.codigo)
    cerrar()
  }
  const alTeclear = (evento) => {
    if (evento.key === 'ArrowDown' || evento.key === 'ArrowUp') {
      if (opciones.length === 0) return
      evento.preventDefault()
      setActivo((a) => (evento.key === 'ArrowDown' ? (a + 1) % opciones.length : (a - 1 + opciones.length) % opciones.length))
    } else if (evento.key === 'Enter' && escribiendo) {
      evento.preventDefault() // no envía el formulario: elige la opción resaltada
      if (opciones[activo]) elegir(opciones[activo])
    } else if (evento.key === 'Escape' && escribiendo) {
      evento.stopPropagation() // cierra la lista, no el cuadro de diálogo
      cerrar()
    }
  }

  const aviso = !escribiendo
    ? ''
    : q.length < MINIMO_LETRAS
      ? `Escribe al menos ${MINIMO_LETRAS} letras.`
      : busqueda.isError
        ? 'No se pudo buscar. Intenta de nuevo.'
        : busqueda.isFetching && opciones.length === 0
          ? 'Buscando…'
          : opciones.length === 0
            ? 'No hay distritos con ese nombre.'
            : ''

  return (
    <div className={`selector-ubigeo${valor && !disabled ? ' con-valor' : ''}`}>
      <input
        {...propiedadesDelCampo}
        type="text"
        role="combobox"
        aria-expanded={escribiendo}
        aria-controls={idLista}
        aria-autocomplete="list"
        aria-activedescendant={escribiendo && opciones[activo] ? `${idLista}-${opciones[activo].codigo}` : undefined}
        autoComplete="off"
        maxLength={60}
        disabled={disabled}
        placeholder={placeholder}
        value={escribiendo ? texto : nombreActual}
        onChange={(e) => {
          setTexto(e.target.value)
          setEscribiendo(true)
          setActivo(0)
        }}
        onBlur={cerrar}
        onKeyDown={alTeclear}
      />
      {valor && !disabled && (
        <button type="button" className="selector-ubigeo-quitar" aria-label="Quitar el distrito" title="Quitar" onClick={() => onCambio('')}>
          <Icono nombre="cerrar" tam={16} />
        </button>
      )}
      {escribiendo && (
        <ul id={idLista} role="listbox" className="selector-ubigeo-lista" aria-label="Distritos encontrados">
          {aviso && (
            <li role="presentation" className="selector-ubigeo-aviso">
              {aviso}
            </li>
          )}
          {opciones.map((u, i) => (
            <li
              key={u.codigo}
              id={`${idLista}-${u.codigo}`}
              role="option"
              aria-selected={i === activo}
              className={i === activo ? 'activa' : undefined}
              onMouseDown={(e) => {
                e.preventDefault() // el cuadro no pierde el foco antes de elegir
                elegir(u)
              }}
              onMouseEnter={() => setActivo(i)}
            >
              {u.nombre_completo}
              <small>{u.codigo}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
