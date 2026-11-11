import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { normalizarSerie, parsearSeries, serieValida } from '../inventario'

const MAXIMO = 2000
const DATOS_MAXIMO = 120
const MENSAJE_FORMATO = (n) => `«${n.slice(0, 40)}» no es válida: use de 3 a 40 letras, números, guiones o puntos.`

/**
 * Ventana para escribir las series o IMEI de un producto: una por una (con el lector basta
 * escanear y pulsar Enter) o pegando una lista. Cada serie puede llevar un dato propio opcional
 * (color, garantía…). Los repetidos se avisan al instante. Se guarda al pulsar «Guardar series».
 */
export default function SeriesModal({ producto, series, conDatos, onGuardar, onCerrar }) {
  const [lista, setLista] = useState(series)
  const [numero, setNumero] = useState('')
  const [otros, setOtros] = useState('')
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')
  const [resaltada, setResaltada] = useState('')
  const [pegando, setPegando] = useState(false)
  const [texto, setTexto] = useState('')
  const [fila, setFila] = useState(null) // { indice, numero, otros } de la fila que se edita
  const [errorFila, setErrorFila] = useState('')
  const entrada = useRef(null)

  useEffect(() => entrada.current?.focus(), [])

  const repetida = (n, ignorar = -1) => lista.some((s, i) => i !== ignorar && s.numero === n)
  const llena = lista.length >= MAXIMO

  const agregar = () => {
    setAviso('')
    const n = normalizarSerie(numero)
    const dato = otros.trim().replace(/\s+/g, ' ')
    if (!n) return setError('Escriba o escanee la serie.')
    if (!serieValida(n)) return setError(MENSAJE_FORMATO(n))
    if (repetida(n)) {
      setResaltada(n)
      return setError(`«${n}» ya está en la lista.`)
    }
    if (dato.length > DATOS_MAXIMO) return setError(`Los otros datos admiten hasta ${DATOS_MAXIMO} caracteres.`)
    if (llena) return setError(`Hasta ${MAXIMO} series por producto.`)
    setLista((previo) => [...previo, { numero: n, otros_datos: dato }])
    setNumero('')
    setOtros('')
    setError('')
    setResaltada('')
    entrada.current?.focus() // lista para escanear la siguiente
  }

  const alTeclear = (evento) => {
    if (evento.key !== 'Enter') return
    evento.preventDefault() // el Enter del lector agrega la serie; no envía el formulario de atrás
    agregar()
  }

  const agregarLista = () => {
    const nuevas = []
    const repetidas = []
    const invalidas = []
    const vistas = new Set(lista.map((s) => s.numero))
    for (const n of parsearSeries(texto)) {
      if (!serieValida(n)) invalidas.push(n)
      else if (vistas.has(n)) repetidas.push(n)
      else {
        vistas.add(n)
        nuevas.push({ numero: n, otros_datos: '' })
      }
    }
    const cupo = MAXIMO - lista.length
    const aceptadas = nuevas.slice(0, cupo)
    setLista((previo) => [...previo, ...aceptadas])
    setTexto('')
    setError('')
    const partes = [`Se agregaron ${aceptadas.length}.`]
    if (repetidas.length) partes.push(`Repetidas (omitidas): ${repetidas.slice(0, 5).join(', ')}${repetidas.length > 5 ? '…' : ''}.`)
    if (invalidas.length) partes.push(`No válidas (omitidas): ${invalidas.slice(0, 5).join(', ')}${invalidas.length > 5 ? '…' : ''}.`)
    if (nuevas.length > cupo) partes.push(`Solo caben ${MAXIMO} series.`)
    setAviso(partes.join(' '))
    if (!repetidas.length && !invalidas.length) setPegando(false)
  }

  const quitar = (indice) => {
    setLista((previo) => previo.filter((_, i) => i !== indice))
    setResaltada('')
    setError('')
    entrada.current?.focus()
  }

  const guardarFila = () => {
    const n = normalizarSerie(fila.numero)
    const dato = fila.otros.trim().replace(/\s+/g, ' ')
    if (!serieValida(n)) return setErrorFila(MENSAJE_FORMATO(n))
    if (repetida(n, fila.indice)) return setErrorFila(`«${n}» ya está en la lista.`)
    if (dato.length > DATOS_MAXIMO) return setErrorFila(`Hasta ${DATOS_MAXIMO} caracteres.`)
    setLista((previo) => previo.map((s, i) => (i === fila.indice ? { numero: n, otros_datos: dato } : s)))
    setFila(null)
    setErrorFila('')
  }

  const ventana = (
    <Modal titulo="Series o IMEI" subtitulo={producto?.nombre} onCerrar={onCerrar} ancho={780}>
      <div className="series-modal">
        <div className={`series-entrada${conDatos ? ' con-datos' : ''}`}>
          <Campo etiqueta="Serie o IMEI" icono="scan" error={error}>
            {(p) => (
              <input {...p} ref={entrada} autoComplete="off" spellCheck={false} placeholder="Escanea o escribe y pulsa Enter" value={numero} onChange={(e) => setNumero(e.target.value)} onKeyDown={alTeclear} />
            )}
          </Campo>
          {conDatos && (
            <Campo etiqueta="Otros datos (opcional)">
              {(p) => <input {...p} autoComplete="off" maxLength={DATOS_MAXIMO} placeholder="Ej. Negro, 128 GB" value={otros} onChange={(e) => setOtros(e.target.value)} onKeyDown={alTeclear} />}
            </Campo>
          )}
          <button type="button" className="primario" onClick={agregar} disabled={llena}>
            <Icono nombre="agregar" tam={19} /> Agregar
          </button>
        </div>

        <div className="series-barra">
          <strong aria-live="polite">{lista.length} {lista.length === 1 ? 'serie' : 'series'}</strong>
          <button type="button" className="enlace-boton" onClick={() => setPegando((v) => !v)}>
            {pegando ? 'Cerrar la lista' : 'Pegar una lista'}
          </button>
        </div>
        {pegando && (
          <div className="series-pegar">
            <textarea aria-label="Lista de series" rows={4} spellCheck={false} placeholder={'Una por línea (o separadas por coma o espacio)\nEj. 356938035643809\nEj. 356938035643810'} value={texto} onChange={(e) => setTexto(e.target.value)} />
            <button type="button" onClick={agregarLista} disabled={!texto.trim()}>Agregar la lista</button>
          </div>
        )}
        {aviso && <p role="status" className="celda-suave">{aviso}</p>}

        {lista.length === 0 ? (
          <p className="estado-vacio">Aún no hay series. Escanea la primera.</p>
        ) : (
          <div className="series-tabla marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th className="centrado">#</th>
                  <th>Serie o IMEI</th>
                  {conDatos && <th>Otros datos</th>}
                  <th className="centrado">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((s, i) => {
                  const editandoEsta = fila?.indice === i
                  return (
                    <tr key={s.numero} className={s.numero === resaltada ? 'serie-repetida' : undefined}>
                      <td className="centrado celda-suave">{i + 1}</td>
                      <td>
                        {editandoEsta ? <input aria-label="Serie" value={fila.numero} onChange={(e) => setFila({ ...fila, numero: e.target.value })} /> : <strong>{s.numero}</strong>}
                      </td>
                      {conDatos && (
                        <td className="celda-suave">
                          {editandoEsta ? <input aria-label="Otros datos" maxLength={DATOS_MAXIMO} value={fila.otros} onChange={(e) => setFila({ ...fila, otros: e.target.value })} /> : s.otros_datos || '—'}
                        </td>
                      )}
                      <td className="centrado">
                        <span className="acciones-fila">
                          {editandoEsta ? (
                            <>
                              <button type="button" className="primario" onClick={guardarFila}>Listo</button>
                              <button type="button" onClick={() => { setFila(null); setErrorFila('') }}>Cancelar</button>
                            </>
                          ) : (
                            <>
                              <button type="button" className="accion-icono editar" aria-label={`Editar la serie ${s.numero}`} title="Editar" onClick={() => { setFila({ indice: i, numero: s.numero, otros: s.otros_datos }); setErrorFila('') }}>
                                <Icono nombre="lapiz" tam={19} />
                              </button>
                              <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar la serie ${s.numero}`} title="Quitar" onClick={() => quitar(i)}>
                                <Icono nombre="papelera" tam={19} />
                              </button>
                            </>
                          )}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {errorFila && <p role="alert" className="campo-error">{errorFila}</p>}
      </div>
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>Cancelar</button>
        <button type="button" className="primario" onClick={() => onGuardar(lista)}>
          Guardar series ({lista.length})
        </button>
      </div>
    </Modal>
  )
  // Fuera del formulario de atrás: así ningún Enter ni botón de aquí lo envía por accidente.
  return createPortal(ventana, document.body)
}
