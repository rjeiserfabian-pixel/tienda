import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import './maestros.css'

const enviar = (config, archivo, modo) => {
  const datos = new FormData()
  datos.append('archivo', archivo)
  datos.append('modo', modo)
  return api.post(`${config.endpoint}importar/`, datos).then((r) => r.data)
}

/**
 * Importación masiva desde Excel (.xlsx) o CSV en dos pasos: primero se REVISA el archivo (no
 * guarda nada) y, si el informe convence, se importan solo las filas válidas.
 */
export default function ImportarModal({ config, onCerrar }) {
  const notificar = useNotificar()
  const [archivo, setArchivo] = useState(null)
  const [informe, setInforme] = useState(null)
  const [error, setError] = useState('')
  const [descargando, setDescargando] = useState(false)
  const plural = config.titulo.toLowerCase()

  const validar = useMutacion({ mutationFn: (f) => enviar(config, f, 'validar'), avisarError: false })
  const importar = useMutacion({
    mutationFn: () => enviar(config, archivo, 'importar'),
    invalidar: [[config.clave], ['opciones']],
    avisarError: false,
    alExito: (datos) => {
      notificar('exito', datos.creados === 1 ? `1 ${config.singular} importado.` : `${datos.creados} ${plural} importados.`)
      onCerrar()
    },
  })
  const ocupado = validar.isPending || importar.isPending

  const elegir = (evento) => {
    const f = evento.target.files?.[0]
    evento.target.value = '' // permite volver a elegir el mismo archivo tras corregirlo
    if (!f) return
    setArchivo(f)
    setInforme(null)
    setError('')
    validar.mutate(f, {
      onSuccess: setInforme,
      onError: (e) => setError(erroresDeCampo(e).archivo || mensajeDeError(e)),
    })
  }

  const confirmar = () => {
    if (ocupado || !informe?.validas) return
    setError('')
    importar.mutate(undefined, { onError: (e) => setError(erroresDeCampo(e).archivo || mensajeDeError(e)) })
  }

  const descargarPlantilla = async () => {
    setDescargando(true)
    try {
      const { data } = await api.get(`${config.endpoint}plantilla/`, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const enlace = document.createElement('a')
      enlace.href = url
      enlace.download = `plantilla_${config.clave}.csv`
      enlace.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setDescargando(false)
    }
  }

  const problemas = informe ? [...informe.errores.map((x) => ({ ...x, tipo: 'Error' })), ...informe.repetidos_detalle.map((x) => ({ fila: x.fila, mensaje: `${x.documento}: ${x.motivo}`, tipo: 'Repetido' }))].sort((a, b) => a.fila - b.fila) : []

  return (
    <Modal titulo={`Importar ${plural}`} subtitulo="Sube un Excel (.xlsx) o CSV con tu lista. Primero se revisa; nada se guarda hasta que confirmes." onCerrar={onCerrar} ancho={720}>
      <ol className="import-pasos">
        <li>
          Descarga la plantilla y llénala con tus datos.{' '}
          <button type="button" className="boton-consultar import-plantilla" onClick={descargarPlantilla} disabled={descargando}>
            <Icono nombre="documento" tam={17} /> {descargando ? 'Descargando…' : 'Descargar plantilla'}
          </button>
        </li>
        <li>Sube el archivo. Pueden ir menos columnas; solo el documento y el nombre son obligatorios.</li>
        <li>Revisa el informe e importa. Lo que ya existe se omite, nunca se sobrescribe.</li>
      </ol>

      <label className="import-archivo">
        <Icono nombre="importar" tam={20} />
        <span>{archivo ? archivo.name : 'Elegir archivo (.xlsx o .csv, hasta 2 MB y 2000 filas)'}</span>
        <input type="file" accept=".xlsx,.csv" onChange={elegir} disabled={ocupado} />
      </label>

      {validar.isPending && <p className="campo-ayuda">Revisando el archivo…</p>}
      {error && <p role="alert" className="campo-error">{error}</p>}

      {informe && (
        <section aria-label="Informe de la revisión">
          <ul className="import-resumen">
            <li><strong>{informe.total}</strong> filas</li>
            <li className="ok"><strong>{informe.validas}</strong> listas para importar</li>
            <li className={informe.con_error ? 'mal' : ''}><strong>{informe.con_error}</strong> con errores</li>
            <li className={informe.repetidos ? 'aviso' : ''}><strong>{informe.repetidos}</strong> repetidas</li>
          </ul>
          {informe.columnas_ignoradas.length > 0 && (
            <p className="campo-ayuda">No se usarán estas columnas: {informe.columnas_ignoradas.join(', ')}.</p>
          )}
          {problemas.length > 0 && (
            <div className="import-problemas" tabIndex={0} aria-label="Filas con problemas">
              <table className="tabla-datos">
                <thead>
                  <tr><th className="centrado">Fila</th><th>Problema</th><th>Tipo</th></tr>
                </thead>
                <tbody>
                  {problemas.map((p) => (
                    <tr key={`${p.tipo}-${p.fila}`}>
                      <td className="centrado">{p.fila}</td>
                      <td>{p.mensaje}</td>
                      <td><span className="pildora" data-tono={p.tipo === 'Error' ? 'rojo' : 'ambar'} style={{ minWidth: 0 }}>{p.tipo}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {informe.recortado && <p className="campo-ayuda">Se muestran los primeros problemas; corrige estos y vuelve a subir el archivo.</p>}
        </section>
      )}

      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={importar.isPending}>Cancelar</button>
        <button type="button" className="primario" onClick={confirmar} disabled={ocupado || !informe?.validas}>
          {importar.isPending ? 'Importando…' : informe?.validas ? `Importar ${informe.validas} ${informe.validas === 1 ? 'fila' : 'filas'}` : 'Importar'}
        </button>
      </div>
    </Modal>
  )
}
