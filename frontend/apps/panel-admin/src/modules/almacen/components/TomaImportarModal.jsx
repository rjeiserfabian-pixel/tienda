import { useRef, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { cantidad } from '../inventario'
import { numeroToma } from '../tomas'
import '../../mantenimiento/components/maestros.css'
import '../tomas.css'

const TAMANO_MAXIMO = 2 * 1024 * 1024
const MODOS = [
  ['automatico', 'Automático: código de barras y, si no, el nombre'],
  ['codigo', 'Por el código del producto (columna «codigo»)'],
]

const enviar = ({ tomaId, archivo, modo, importarCeros, accion }) => {
  const datos = new FormData()
  datos.append('archivo', archivo)
  datos.append('accion', accion)
  datos.append('modo', modo)
  datos.append('importar_ceros', importarCeros ? 'true' : 'false')
  return api.post(`/inventario/tomas/${tomaId}/importar/`, datos, { timeout: 120_000 }).then((r) => r.data)
}

/** Lo que no se importa, por motivo: cuántas filas y las primeras con su problema. */
function Omitidas({ categorias }) {
  const lista = Object.entries(categorias)
  if (lista.length === 0) return null
  return (
    <div className="toma-omitidas">
      {lista.map(([clave, { titulo, cantidad: n, detalle }]) => (
        <details key={clave}>
          <summary>
            {titulo} <strong>({cantidad(n)})</strong>
          </summary>
          <div className="import-problemas" tabIndex={0} aria-label={titulo}>
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th className="centrado">Fila</th>
                  <th>En el archivo</th>
                  <th>Motivo</th>
                </tr>
              </thead>
              <tbody>
                {detalle.map((f) => (
                  <tr key={`${clave}-${f.fila}`}>
                    <td className="centrado">{f.fila}</td>
                    <td>{f.texto || '—'}</td>
                    <td>{f.motivo}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {n > detalle.length && <p className="campo-ayuda">Se muestran las primeras {detalle.length} filas.</p>}
        </details>
      ))}
    </div>
  )
}

/**
 * Trae a la toma un conteo hecho antes en un Excel (p. ej. la hoja de trabajo de la tienda), en dos pasos: se REVISA el
 * archivo (no guarda nada) y, si el informe convence, se importan los conteos válidos. Nada se sobrescribe: lo que ya
 * tiene conteo, o no se puede emparejar con un solo producto, se informa y se deja afuera.
 */
export default function TomaImportarModal({ toma, onCerrar }) {
  const notificar = useNotificar()
  const [archivo, setArchivo] = useState(null)
  const [modo, setModo] = useState('automatico')
  const [importarCeros, setImportarCeros] = useState(false)
  const [informe, setInforme] = useState(null)
  const [error, setError] = useState('')
  const pedido = useRef(0) // una respuesta vieja no pisa la de la última opción elegida

  const revisar = useMutacion({ mutationFn: enviar, avisarError: false })
  const importar = useMutacion({
    mutationFn: enviar,
    invalidar: [['tomas']],
    avisarError: false,
    alExito: (datos) => {
      notificar('exito', datos.importados === 1 ? 'Se importó 1 conteo.' : `Se importaron ${datos.importados} conteos.`)
      onCerrar()
    },
  })
  const ocupado = revisar.isPending || importar.isPending

  const pedirRevision = (f, opciones) => {
    const numero = ++pedido.current
    setInforme(null)
    setError('')
    revisar.mutate(
      { tomaId: toma.id, archivo: f, accion: 'revisar', ...opciones },
      {
        onSuccess: (datos) => numero === pedido.current && setInforme(datos),
        onError: (e) => numero === pedido.current && setError(erroresDeCampo(e).archivo || mensajeDeError(e)),
      },
    )
  }

  const elegir = (evento) => {
    const f = evento.target.files?.[0]
    evento.target.value = '' // permite volver a elegir el mismo archivo tras corregirlo
    if (!f) return
    setArchivo(f)
    if (!f.name.toLowerCase().endsWith('.xlsx')) return setError('Sube un archivo Excel (.xlsx).')
    if (f.size > TAMANO_MAXIMO) return setError('El archivo pesa más de 2 MB.')
    pedirRevision(f, { modo, importarCeros })
  }

  const cambiar = (nuevo) => {
    const opciones = { modo, importarCeros, ...nuevo }
    setModo(opciones.modo)
    setImportarCeros(opciones.importarCeros)
    if (archivo) pedirRevision(archivo, opciones)
  }

  const confirmar = () => {
    if (ocupado || !informe?.a_importar) return
    setError('')
    importar.mutate(
      { tomaId: toma.id, archivo, accion: 'importar', modo, importarCeros },
      { onError: (e) => setError(erroresDeCampo(e).archivo || mensajeDeError(e)) },
    )
  }

  return (
    <Modal titulo="Importar conteo desde Excel" subtitulo={`${numeroToma(toma.numero)} · ${toma.almacen_nombre}. Primero se revisa; nada se guarda hasta que confirmes.`} onCerrar={onCerrar} ancho={820}>
      <ol className="import-pasos">
        <li>Sube la hoja de trabajo (.xlsx). Se lee la columna «STOCK INVENT.»; una celda vacía es «todavía no se cuenta».</li>
        <li>Cada producto se empareja por su código de barras o su nombre. Lo que no coincide con UN solo producto de la toma queda afuera y se te dice por qué.</li>
        <li>Si trae FECHA y HORA FIN, cada conteo queda con esa fecha: al aprobar se descuenta lo que se vendió o compró desde entonces.</li>
      </ol>

      <fieldset className="toma-fieldset" disabled={ocupado}>
        <Campo etiqueta="Cómo emparejar los productos" tipo="select">
          {(p) => (
            <select {...p} value={modo} onChange={(e) => cambiar({ modo: e.target.value })}>
              {MODOS.map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <Interruptor
          activo={importarCeros}
          onCambio={(valor) => cambiar({ importarCeros: valor })}
          texto="Importar también los contados en 0"
          descripcion="En una hoja de cálculo un 0 suele significar «no lo encontré». Apagado, esos productos quedan pendientes para contarlos bien."
        />
        <label className="import-archivo">
          <Icono nombre="importar" tam={20} />
          <span>{archivo ? archivo.name : 'Elegir archivo (.xlsx, hasta 2 MB)'}</span>
          <input type="file" accept=".xlsx" onChange={elegir} />
        </label>
      </fieldset>

      {revisar.isPending && <p className="campo-ayuda">Revisando el archivo…</p>}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}

      {informe && (
        <section aria-label="Informe de la revisión">
          <ul className="import-resumen">
            <li>
              <strong>{cantidad(informe.total)}</strong> filas con datos
            </li>
            <li>
              <strong>{cantidad(informe.con_conteo)}</strong> con conteo
            </li>
            <li className="ok">
              <strong>{cantidad(informe.a_importar)}</strong> listas para importar
            </li>
            <li className={informe.con_conteo - informe.a_importar > 0 ? 'aviso' : ''}>
              <strong>{cantidad(informe.con_conteo - informe.a_importar)}</strong> se dejan afuera
            </li>
          </ul>
          <p className="celda-suave">
            {cantidad(informe.sin_conteo)} filas no traen conteo y se ignoran.
            {informe.turnos > 0 ? ` Se crearán ${informe.turnos} turno(s) con la fecha y el horario del archivo.` : ''}
          </p>
          {informe.columnas_ignoradas.length > 0 && <p className="campo-ayuda">No se usarán estas columnas: {informe.columnas_ignoradas.join(', ')}.</p>}
          <Omitidas categorias={informe.categorias} />
        </section>
      )}

      {importar.isPending && (
        <p className="campo-ayuda" aria-live="polite">
          Importando… con muchos productos puede tardar unos segundos. No cierres esta ventana.
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={importar.isPending}>
          Cancelar
        </button>
        <button type="button" className="primario" onClick={confirmar} disabled={ocupado || !informe?.a_importar}>
          {importar.isPending ? 'Importando…' : informe?.a_importar ? `Importar ${cantidad(informe.a_importar)} ${informe.a_importar === 1 ? 'conteo' : 'conteos'}` : 'Importar'}
        </button>
      </div>
    </Modal>
  )
}
