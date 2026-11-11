import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { hoyIso } from '../inventario'
import { soles } from '../utilidades'
import '../../mantenimiento/components/maestros.css'

const enviar = ({ empresa, fecha, archivo, modo }) => {
  const datos = new FormData()
  datos.append('empresa', empresa)
  datos.append('fecha', fecha)
  datos.append('modo', modo)
  datos.append('archivo', archivo)
  return api.post('/inventario/saldo-inicial/importar/', datos, { timeout: 120_000 }).then((r) => r.data)
}

/**
 * Carga el stock con el que arranca una empresa, desde un Excel o CSV, en dos pasos: primero se
 * REVISA el archivo (no guarda nada) y, si el informe convence, se importan las filas válidas.
 */
export default function ImportarSaldoInicialModal({ onCerrar }) {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const notificar = useNotificar()
  const [fecha, setFecha] = useState(hoyIso())
  const [archivo, setArchivo] = useState(null)
  const [informe, setInforme] = useState(null)
  const [error, setError] = useState('')
  const [descargando, setDescargando] = useState(false)

  const validar = useMutacion({ mutationFn: (datos) => enviar({ ...datos, modo: 'validar' }), avisarError: false })
  const importar = useMutacion({
    mutationFn: () => enviar({ empresa: empresaActivaId, fecha, archivo, modo: 'importar' }),
    invalidar: [['stock'], ['movimientos'], ['kardex']],
    avisarError: false,
    alExito: (datos) => {
      notificar('exito', datos.creados === 1 ? 'Se cargó el saldo inicial de 1 producto.' : `Se cargó el saldo inicial de ${datos.creados} productos.`)
      onCerrar()
    },
  })
  const ocupado = validar.isPending || importar.isPending
  const fechaInvalida = !fecha || fecha > hoyIso()

  const revisar = (f, dia) => {
    setInforme(null)
    setError('')
    validar.mutate(
      { empresa: empresaActivaId, fecha: dia, archivo: f },
      {
        onSuccess: setInforme,
        onError: (e) => setError(erroresDeCampo(e).archivo || mensajeDeError(e)),
      },
    )
  }

  const elegir = (evento) => {
    const f = evento.target.files?.[0]
    evento.target.value = '' // permite volver a elegir el mismo archivo tras corregirlo
    if (!f) return
    setArchivo(f)
    if (fechaInvalida) return setError('Elija primero una fecha que no sea futura.')
    revisar(f, fecha)
  }

  const cambiarFecha = (e) => {
    setFecha(e.target.value)
    setInforme(null)
    if (archivo && e.target.value && e.target.value <= hoyIso()) revisar(archivo, e.target.value)
  }

  const confirmar = () => {
    if (ocupado || !informe?.validas) return
    setError('')
    importar.mutate(undefined, { onError: (e) => setError(erroresDeCampo(e).archivo || mensajeDeError(e)) })
  }

  const plantilla = async () => {
    setDescargando(true)
    setError('')
    try {
      await descargarArchivo('/inventario/saldo-inicial/plantilla/', { empresa: empresaActivaId })
    } catch (e) {
      setError(await mensajeDeErrorDescarga(e))
    } finally {
      setDescargando(false)
    }
  }

  const problemas = informe
    ? [
        ...informe.errores.map((x) => ({ fila: x.fila, mensaje: x.mensaje, tipo: 'Error' })),
        ...informe.repetidos_detalle.map((x) => ({ fila: x.fila, mensaje: `${x.documento}: ${x.motivo}`, tipo: 'Omitida' })),
      ].sort((a, b) => a.fila - b.fila)
    : []

  return (
    <Modal
      titulo="Importar saldo inicial"
      subtitulo={`Stock con el que arranca ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa'}. Primero se revisa; nada se guarda hasta que confirmes.`}
      onCerrar={onCerrar}
      ancho={760}
    >
      <ol className="import-pasos">
        <li>
          Descarga la plantilla: ya trae tus productos, solo llena cantidad y costo (y, si quieres, la ubicación).{' '}
          <button type="button" className="boton-consultar import-plantilla" onClick={plantilla} disabled={descargando || ocupado}>
            <Icono nombre="documento" tam={17} /> {descargando ? 'Descargando…' : 'Descargar plantilla'}
          </button>
        </li>
        <li>Indica la fecha del saldo y sube el archivo. Cada producto se carga una sola vez por almacén.</li>
        <li>Revisa el informe e importa. Para corregir después, usa un ajuste.</li>
      </ol>

      <Campo etiqueta="Fecha del saldo inicial" icono="calendario" requerido ayuda="El día en que empiezas a llevar el inventario en el sistema." error={fecha > hoyIso() ? 'La fecha no puede ser futura.' : undefined}>
        {(p) => <input {...p} type="date" max={hoyIso()} value={fecha} disabled={ocupado} onChange={cambiarFecha} />}
      </Campo>

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
            <li className={informe.repetidos ? 'aviso' : ''}><strong>{informe.repetidos}</strong> omitidas</li>
          </ul>
          {informe.validas > 0 && (
            <p>
              Valor del inventario inicial: <strong>{soles(informe.valor_total)}</strong> · se crearán{' '}
              <strong>{informe.movimientos}</strong> {informe.movimientos === 1 ? 'movimiento' : 'movimientos'} de saldo inicial.
            </p>
          )}
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

      {importar.isPending && <p className="campo-ayuda" aria-live="polite">Importando… con muchos productos puede tardar unos segundos. No cierres esta ventana.</p>}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={importar.isPending}>Cancelar</button>
        <button type="button" className="primario" onClick={confirmar} disabled={ocupado || fechaInvalida || !informe?.validas}>
          {importar.isPending ? 'Importando…' : informe?.validas ? `Importar ${informe.validas} ${informe.validas === 1 ? 'producto' : 'productos'}` : 'Importar'}
        </button>
      </div>
    </Modal>
  )
}
