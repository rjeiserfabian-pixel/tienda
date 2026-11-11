import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useMemo, useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import {
  agruparPorSeccion,
  campoVacio,
  cuerpoDeCampos,
  desdeServidor,
  MAX_CAMPOS,
  moverCampo,
  moverSeccion,
  revisarCampos,
  SECCION_INICIAL,
  sumarOpciones,
  TIPOS_CAMPO,
} from '../especificaciones'
import './especificaciones.css'

const url = (categoria, extra = '') => `/mantenimiento/categorias/${categoria}/especificaciones/${extra}`
const instantanea = (campos) => JSON.stringify(campos.map(({ uid, ...resto }) => resto)) // eslint-disable-line no-unused-vars

/** Opciones de una lista: etiquetas que se agregan con Enter o coma y se quitan con la equis. */
function Opciones({ valor, onCambio, deshabilitado, error }) {
  const [texto, setTexto] = useState('')
  const agregar = () => {
    if (!texto.trim()) return
    onCambio(sumarOpciones(valor, texto))
    setTexto('')
  }
  return (
    <div className="esp-opciones">
      <span className="esp-etiqueta">Opciones de la lista</span>
      <div className="esp-chips">
        {valor.map((o) => (
          <span key={o} className="esp-chip">
            {o}
            {!deshabilitado && (
              <button type="button" aria-label={`Quitar la opción ${o}`} onClick={() => onCambio(valor.filter((x) => x !== o))}>
                <Icono nombre="cerrar" tam={13} />
              </button>
            )}
          </span>
        ))}
        {valor.length === 0 && <small className="esp-suave">Sin opciones: se escribirá el valor libremente.</small>}
      </div>
      {!deshabilitado && (
        <div className="esp-agregar">
          <input
            value={texto}
            maxLength={60}
            placeholder="Escribe una opción y pulsa Enter (o pega varias separadas por coma)"
            aria-label="Nueva opción"
            aria-invalid={Boolean(error)}
            onChange={(e) => setTexto(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                agregar()
              }
            }}
            onPaste={(e) => {
              const pegado = e.clipboardData.getData('text')
              if (/[\n,;]/.test(pegado)) {
                e.preventDefault()
                onCambio(sumarOpciones(valor, pegado))
              }
            }}
          />
          <button type="button" onClick={agregar} disabled={!texto.trim()}>Agregar</button>
        </div>
      )}
    </div>
  )
}

/** Un dato de la plantilla: nombre, tipo, unidad, sección, opciones y los dos interruptores. */
function CampoEditor({ campo, error, deshabilitado, listaSecciones, primero, ultimo, onCambio, onMover, onQuitar }) {
  const esNumero = campo.tipo === 'NUMERO'
  const esLista = campo.tipo === 'LISTA'
  const esTexto = campo.tipo === 'TEXTO'
  return (
    <li className={`esp-campo${error ? ' con-error' : ''}`}>
      <div className="esp-fila">
        <label className="esp-control esp-nombre">
          <span className="esp-etiqueta">Nombre del dato</span>
          <input
            value={campo.nombre}
            maxLength={80}
            placeholder="Ej. Memoria RAM"
            aria-invalid={Boolean(error)}
            onChange={(e) => onCambio({ nombre: e.target.value })}
          />
        </label>
        <label className="esp-control">
          <span className="esp-etiqueta">Tipo</span>
          <select value={campo.tipo} onChange={(e) => onCambio({ tipo: e.target.value, ...(e.target.value === 'TEXTO' ? { es_filtro: false } : {}) })}>
            {TIPOS_CAMPO.map(([valor, texto]) => (
              <option key={valor} value={valor}>{texto}</option>
            ))}
          </select>
        </label>
        {esNumero && (
          <label className="esp-control esp-unidad">
            <span className="esp-etiqueta">Unidad</span>
            <input value={campo.unidad} maxLength={20} placeholder="GB, MHz…" onChange={(e) => onCambio({ unidad: e.target.value })} />
          </label>
        )}
        <label className="esp-control">
          <span className="esp-etiqueta">Sección</span>
          <input value={campo.seccion} maxLength={60} list={listaSecciones} placeholder={SECCION_INICIAL} onChange={(e) => onCambio({ seccion: e.target.value })} />
        </label>
      </div>
      {esLista && <Opciones valor={campo.opciones} deshabilitado={deshabilitado} onCambio={(opciones) => onCambio({ opciones })} />}
      <div className="esp-pie">
        <label className="casilla" title={esTexto ? 'Un texto libre no sirve como filtro: usa una lista o un número.' : undefined}>
          <input type="checkbox" checked={campo.es_filtro && !esTexto} disabled={esTexto} onChange={(e) => onCambio({ es_filtro: e.target.checked })} />
          <span>Filtro en la tienda</span>
        </label>
        <label className="casilla">
          <input type="checkbox" checked={campo.en_tarjeta} onChange={(e) => onCambio({ en_tarjeta: e.target.checked })} />
          <span>Se ve en la tarjeta del listado</span>
        </label>
        {!deshabilitado && (
          <span className="esp-acciones">
            <button type="button" className="accion-icono" title="Subir" aria-label={`Subir ${campo.nombre || 'el dato'}`} disabled={primero} onClick={() => onMover(-1)}>
              <span className="esp-subir"><Icono nombre="chevronAbajo" tam={18} /></span>
            </button>
            <button type="button" className="accion-icono" title="Bajar" aria-label={`Bajar ${campo.nombre || 'el dato'}`} disabled={ultimo} onClick={() => onMover(1)}>
              <Icono nombre="chevronAbajo" tam={18} />
            </button>
            <button type="button" className="accion-icono peligro-suave" title="Quitar" aria-label={`Quitar ${campo.nombre || 'el dato'}`} onClick={onQuitar}>
              <Icono nombre="papelera" tam={18} />
            </button>
          </span>
        )}
      </div>
      {error && <small role="alert" className="campo-error">{error}</small>}
    </li>
  )
}

/**
 * Editor de las especificaciones técnicas de una categoría: qué datos se piden a sus productos
 * (RAM, DPI, socket…), cómo se agrupan, cuáles filtran en la tienda y cuáles salen en la tarjeta.
 */
export default function EspecificacionesModal({ categoria, puedeEditar, onCerrar }) {
  const idSecciones = useId()
  const [campos, setCampos] = useState(null)
  const [base, setBase] = useState('')
  const [errores, setErrores] = useState({ general: '', porCampo: {} })
  const [plantilla, setPlantilla] = useState('')
  const [confirmar, setConfirmar] = useState(null) // 'plantilla' | 'cerrar'

  const consulta = useQuery({
    queryKey: ['categorias', 'especificaciones', categoria.id],
    queryFn: ({ signal }) => api.get(url(categoria.id), { signal }).then((r) => r.data),
  })
  const plantillas = useQuery({
    queryKey: ['categorias', 'plantillas-especificaciones'],
    queryFn: ({ signal }) => api.get('/mantenimiento/categorias/plantillas-especificaciones/', { signal }).then((r) => r.data),
    enabled: puedeEditar,
    staleTime: 600_000,
  })

  const cargarDesdeServidor = (lista) => {
    const locales = lista.map(desdeServidor)
    setCampos(locales)
    setBase(instantanea(locales))
  }
  useEffect(() => {
    // Se espera a que termine de refrescar: así nunca se parte de una copia vieja tras guardar.
    if (consulta.data && !consulta.isFetching && campos === null) cargarDesdeServidor(consulta.data)
  }, [consulta.data, consulta.isFetching]) // eslint-disable-line react-hooks/exhaustive-deps

  const modificado = campos !== null && instantanea(campos) !== base
  const vigentes = useMemo(() => (campos ?? []).filter((c) => !c.quitado), [campos])
  const quitados = useMemo(() => (campos ?? []).filter((c) => c.quitado), [campos])
  const grupos = useMemo(() => agruparPorSeccion(vigentes), [vigentes])
  const seccionesUsadas = useMemo(() => grupos.map((g) => g.seccion), [grupos])

  const cambiar = (uid, parcial) => setCampos((lista) => lista.map((c) => (c.uid === uid ? { ...c, ...parcial } : c)))
  const quitar = (campo) =>
    setCampos((lista) => (campo.id ? lista.map((c) => (c.uid === campo.uid ? { ...c, quitado: true } : c)) : lista.filter((c) => c.uid !== campo.uid)))
  const reusar = (uid) =>
    setCampos((lista) => {
      const campo = lista.find((c) => c.uid === uid)
      return [...lista.filter((c) => c.uid !== uid), { ...campo, quitado: false }]
    })
  const agregar = (seccion) => {
    if (vigentes.length >= MAX_CAMPOS) return
    setCampos((lista) => [...lista.filter((c) => !c.quitado), campoVacio(seccion), ...lista.filter((c) => c.quitado)])
  }

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.post(url(categoria.id), cuerpo).then((r) => r.data),
    invalidar: [['categorias']],
    exito: 'Especificaciones guardadas.',
    alExito: onCerrar,
    avisarError: false,
  })
  const cargarPlantilla = useMutacion({
    mutationFn: (clave) => api.post(url(categoria.id, 'plantilla/'), { plantilla: clave }).then((r) => r.data),
    invalidar: [['categorias']],
    exito: 'Plantilla cargada. Revísala y ajusta lo que necesites.',
    alExito: (lista) => {
      cargarDesdeServidor(lista)
      setPlantilla('')
      setConfirmar(null)
      setErrores({ general: '', porCampo: {} })
    },
  })

  const enviar = () => {
    if (guardar.isPending || !puedeEditar) return
    const revision = revisarCampos(campos)
    setErrores(revision)
    if (revision.general) return
    guardar.mutate(cuerpoDeCampos(campos), {
      onError: (error) => setErrores({ general: erroresDeCampo(error).campos || 'No se pudo guardar.', porCampo: {} }),
    })
  }
  const pedirPlantilla = () => {
    if (!plantilla) return
    if (modificado) setConfirmar('plantilla')
    else cargarPlantilla.mutate(plantilla)
  }
  const cerrar = () => (modificado ? setConfirmar('cerrar') : onCerrar())
  const elegida = (plantillas.data ?? []).find((p) => p.clave === plantilla)

  return (
    <>
    <Modal titulo={`Especificaciones de ${categoria.nombre}`} subtitulo="Los datos técnicos que se piden a los productos de esta categoría." onCerrar={cerrar} ancho={980}>
      <p className="esp-ayuda">
        Define aquí los datos que describen a estos productos (por ejemplo memoria RAM, tamaño de pantalla o tipo de conexión). Un dato marcado como <strong>filtro</strong> permite que el cliente de la tienda
        filtre por él; uno marcado para la <strong>tarjeta</strong> se muestra junto al producto sin abrirlo.
      </p>
      <EstadoConsulta consulta={consulta} hayDatos={campos !== null}>
        <datalist id={idSecciones}>
          {seccionesUsadas.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>

        {puedeEditar && (
          <div className="esp-barra">
            <div className="esp-plantilla">
              <label className="esp-control">
                <span className="esp-etiqueta">Empezar desde una plantilla</span>
                <select value={plantilla} onChange={(e) => setPlantilla(e.target.value)} disabled={plantillas.isLoading || cargarPlantilla.isPending}>
                  <option value="">Elige una plantilla…</option>
                  {(plantillas.data ?? []).map((p) => (
                    <option key={p.clave} value={p.clave}>{p.nombre} · {p.campos} datos</option>
                  ))}
                </select>
              </label>
              <button type="button" onClick={pedirPlantilla} disabled={!plantilla || cargarPlantilla.isPending}>
                {cargarPlantilla.isPending ? 'Cargando…' : 'Cargar plantilla'}
              </button>
            </div>
            <button type="button" className="primario" onClick={() => agregar(grupos.at(-1)?.seccion ?? SECCION_INICIAL)} disabled={vigentes.length >= MAX_CAMPOS}>
              <Icono nombre="agregar" tam={18} /> Nuevo dato
            </button>
          </div>
        )}
        {puedeEditar && elegida && (
          <p className="esp-nota">
            La plantilla «{elegida.nombre}» suma {elegida.campos} datos en las secciones: {elegida.secciones.join(', ')}. Los datos que la categoría ya tiene no se tocan.
          </p>
        )}

        <fieldset className="esp-lista" disabled={!puedeEditar || guardar.isPending}>
          {vigentes.length === 0 && (
            <p className="esp-vacio">
              Esta categoría todavía no pide datos técnicos. {puedeEditar ? 'Carga una plantilla o agrega el primer dato con «Nuevo dato».' : ''}
            </p>
          )}
          {grupos.map((g, indice) => (
            <section key={g.seccion} className="esp-seccion" aria-label={`Sección ${g.seccion}`}>
              <header>
                <h4>{g.seccion} <small>{g.campos.length} {g.campos.length === 1 ? 'dato' : 'datos'}</small></h4>
                {puedeEditar && (
                  <span className="esp-acciones">
                    <button type="button" className="accion-icono" title="Subir la sección" aria-label={`Subir la sección ${g.seccion}`} disabled={indice === 0} onClick={() => setCampos((l) => moverSeccion(l, g.seccion, -1))}>
                      <span className="esp-subir"><Icono nombre="chevronAbajo" tam={18} /></span>
                    </button>
                    <button type="button" className="accion-icono" title="Bajar la sección" aria-label={`Bajar la sección ${g.seccion}`} disabled={indice === grupos.length - 1} onClick={() => setCampos((l) => moverSeccion(l, g.seccion, 1))}>
                      <Icono nombre="chevronAbajo" tam={18} />
                    </button>
                    <button type="button" onClick={() => agregar(g.seccion)} disabled={vigentes.length >= MAX_CAMPOS}>+ Dato aquí</button>
                  </span>
                )}
              </header>
              <ul>
                {g.campos.map((c, i) => (
                  <CampoEditor
                    key={c.uid}
                    campo={c}
                    error={errores.porCampo[c.uid]}
                    deshabilitado={!puedeEditar}
                    listaSecciones={idSecciones}
                    primero={i === 0}
                    ultimo={i === g.campos.length - 1}
                    onCambio={(parcial) => cambiar(c.uid, parcial)}
                    onMover={(sentido) => setCampos((l) => moverCampo(l, c.uid, sentido))}
                    onQuitar={() => quitar(c)}
                  />
                ))}
              </ul>
            </section>
          ))}
        </fieldset>

        {quitados.length > 0 && (
          <details className="esp-quitados">
            <summary>Datos quitados ({quitados.length})</summary>
            <p className="esp-suave">No se piden a los productos. Los valores que ya tenían se descartan la próxima vez que se guarde cada producto.</p>
            <ul>
              {quitados.map((c) => (
                <li key={c.uid}>
                  <span>{c.nombre || 'Sin nombre'} <small className="esp-suave">· {c.seccion}</small></span>
                  {puedeEditar && <button type="button" onClick={() => reusar(c.uid)}>Volver a usar</button>}
                </li>
              ))}
            </ul>
          </details>
        )}

        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          {modificado && <span className="esp-pendiente" role="status">Hay cambios sin guardar</span>}
          <button type="button" onClick={cerrar} disabled={guardar.isPending}>{puedeEditar ? 'Cancelar' : 'Cerrar'}</button>
          {puedeEditar && (
            <button type="button" className="primario" onClick={enviar} disabled={guardar.isPending || !modificado}>
              {guardar.isPending ? 'Guardando…' : 'Guardar especificaciones'}
            </button>
          )}
        </div>
      </EstadoConsulta>

    </Modal>
      {confirmar === 'plantilla' && (
        <ConfirmarModal
          titulo="Cargar plantilla"
          mensaje="Tienes cambios sin guardar. Al cargar la plantilla se perderán. ¿Continuar?"
          textoConfirmar="Cargar plantilla"
          enviando={cargarPlantilla.isPending}
          onConfirmar={() => cargarPlantilla.mutate(plantilla)}
          onCerrar={() => setConfirmar(null)}
        />
      )}
      {confirmar === 'cerrar' && (
        <ConfirmarModal titulo="Descartar cambios" mensaje="Hay cambios sin guardar. ¿Cerrar y descartarlos?" textoConfirmar="Descartar" onConfirmar={onCerrar} onCerrar={() => setConfirmar(null)} />
      )}
    </>
  )
}
