import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const CLAVE = ['tienda', 'armador-datos']
const MAX_BYTES = 5 * 1024 * 1024

/** Descarga un archivo que el servidor entrega solo con sesión. */
async function descargar(ruta, nombre, params) {
  const r = await api.get(ruta, { params, responseType: 'blob' })
  const direccion = URL.createObjectURL(r.data)
  const enlace = document.createElement('a')
  enlace.href = direccion
  enlace.download = nombre
  enlace.click()
  setTimeout(() => URL.revokeObjectURL(direccion), 30_000)
}

/** Qué productos están completos para «Arma tu PC» y carga de los datos que faltan por Excel. */
export default function DatosArmadorTarjeta() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/tienda/admin/armador/datos/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const d = consulta.data
  const entrada = useRef(null)
  const [archivo, setArchivo] = useState(null)
  const [revision, setRevision] = useState(null)
  const [error, setError] = useState('')
  const [bajando, setBajando] = useState(false)

  const enviar = useMutacion({
    mutationFn: ({ aplicar }) => {
      const datos = new FormData()
      datos.append('archivo', archivo)
      datos.append('aplicar', aplicar ? 'true' : 'false')
      return api.post('/tienda/admin/armador/datos/importar/', datos, { timeout: 120_000 }).then((r) => r.data)
    },
    invalidar: [CLAVE],
    avisarError: false,
    alExito: (r) => {
      setRevision(r)
      setError('')
      if (r.aplicado) {
        setArchivo(null)
        if (entrada.current) entrada.current.value = ''
      }
    },
  })
  const llamar = (aplicar) => enviar.mutate({ aplicar }, { onError: (e) => setError(mensajeDeError(e)) })

  const bajar = async (todos) => {
    setBajando(true)
    setError('')
    try {
      await descargar('/tienda/admin/armador/datos/plantilla/', 'datos-arma-tu-pc.xlsx', todos ? { todos: 1 } : undefined)
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setBajando(false)
    }
  }

  const elegir = (evento) => {
    const f = evento.target.files?.[0] ?? null
    setRevision(null)
    setError('')
    if (f && f.size > MAX_BYTES) {
      setArchivo(null)
      return setError('El archivo pesa más de 5 MB.')
    }
    setArchivo(f)
  }

  if (!d) return null
  const hayEspacios = d.espacios.length > 0

  return (
    <PanelTarjeta
      id="armador-datos"
      icono="checklist"
      titulo="Datos de los productos"
      descripcion="«Arma tu PC» solo asegura que dos piezas son compatibles si ambas tienen los datos que se comparan (socket, tipo de memoria…). Aquí ves qué productos les falta y los completas con un Excel."
    >
      {!hayEspacios ? (
        <p className="celda-suave">Elige las categorías de al menos un espacio para ver qué datos faltan.</p>
      ) : (
        <>
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Espacio</th>
                  <th className="num">Productos</th>
                  <th className="num">Completos</th>
                  <th className="num">Les falta algún dato</th>
                </tr>
              </thead>
              <tbody>
                {d.espacios.map((e) => (
                  <tr key={e.clave}>
                    <td data-etiqueta="Espacio" className="col-texto">
                      <b>{e.nombre}</b>
                      {e.faltan_por_dato.filter((x) => x.faltan > 0).map((x) => (
                        <span key={x.clave} className="sub-texto">
                          {x.faltan} sin «{x.clave}» ({x.regla})
                        </span>
                      ))}
                    </td>
                    <td data-etiqueta="Productos" className="num">
                      {e.total}
                    </td>
                    <td data-etiqueta="Completos" className="num">
                      {e.completos}
                    </td>
                    <td data-etiqueta="Les falta algún dato" className="num">
                      {e.incompletos}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {d.espacios.some((e) => e.categorias_sin_el_campo.length > 0) && (
            <div className="pagos-alerta" role="status">
              <Icono nombre="bell" tam={18} />
              <div>
                <b>Algunas categorías no tienen el campo que el armador necesita.</b>
                <ul className="pedido-lista-simple">
                  {d.espacios.flatMap((e) =>
                    e.categorias_sin_el_campo.map((c) => (
                      <li key={`${e.clave}-${c.categoria}-${c.clave}`}>
                        {c.categoria}: falta el dato «{c.clave}» ({c.regla})
                      </li>
                    )),
                  )}
                </ul>
                <span className="sub-texto">En Tienda › Especificaciones puedes cargar la plantilla de cada categoría o crear ese campo con esa clave.</span>
              </div>
            </div>
          )}

          <div className="pagos-pie">
            <button type="button" onClick={() => bajar(false)} disabled={bajando || d.total_incompletos === 0}>
              <Icono nombre="exportar" tam={16} /> Descargar Excel de los incompletos ({d.total_incompletos})
            </button>
            <button type="button" onClick={() => bajar(true)} disabled={bajando}>
              Descargar Excel de todos
            </button>
          </div>

          <div className="envios-form">
            <label htmlFor="armador-excel">Subir el Excel completado</label>
            <input ref={entrada} id="armador-excel" type="file" accept=".xlsx" onChange={elegir} />
            <small className="celda-suave">Solo se llenan las celdas que escribas: nunca se borra un dato existente. Primero se revisa, y recién después se aplica.</small>
            <div className="pagos-pie">
              <button type="button" disabled={!archivo || enviar.isPending} onClick={() => llamar(false)}>
                {enviar.isPending && !revision ? 'Revisando…' : 'Revisar el archivo'}
              </button>
              {revision && !revision.aplicado && revision.con_cambios > 0 && (
                <button type="button" className="primario" disabled={enviar.isPending} onClick={() => llamar(true)}>
                  {enviar.isPending ? 'Aplicando…' : `Aplicar a ${revision.con_cambios} productos`}
                </button>
              )}
            </div>
          </div>

          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}

          {revision && (
            <div role="status" className="armador-revision">
              <p>
                <b>{revision.aplicado ? 'Listo, se aplicó.' : 'Esto pasaría:'}</b> {revision.con_cambios} productos con datos nuevos, {revision.sin_cambios} sin cambios, {revision.con_error} con problemas (de {revision.filas} filas).
              </p>
              {revision.detalle.filter((x) => x.error).length > 0 && (
                <ul className="pedido-lista-simple" aria-label="Filas con problemas">
                  {revision.detalle
                    .filter((x) => x.error)
                    .map((x) => (
                      <li key={`${x.fila}-${x.codigo}`}>
                        Fila {x.fila} ({x.codigo}): {x.error}
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}

          {d.incompletos.length > 0 && (
            <details>
              <summary>Ver productos incompletos ({d.total_incompletos})</summary>
              <ul className="pedido-lista-simple" aria-label="Productos incompletos">
                {d.incompletos.map((p) => (
                  <li key={p.id}>
                    <b>{p.nombre}</b> ({p.codigo}) · {p.espacio} · falta: {p.faltan.join(', ')}
                  </li>
                ))}
              </ul>
              {d.hay_mas && <p className="sub-texto">Se muestran los primeros 200. Descarga el Excel para ver todos.</p>}
            </details>
          )}
        </>
      )}
    </PanelTarjeta>
  )
}
