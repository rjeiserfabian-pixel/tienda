import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta, paraServidor } from '../../almacen/inventario'
import { dinero, validarImportacion } from '../caja'

/**
 * Importar el estado de cuenta del banco (Excel o CSV). Primero se REVISA el archivo sin guardar nada
 * (qué columnas se reconocieron, cuántas líneas son nuevas, si alguna tiene problemas); recién
 * entonces se importa.
 */
export default function ImportarExtractoModal({ cuentas, onCerrar }) {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const entrada = useRef(null)
  const bancarias = cuentas.filter((c) => c.tipo !== 'CAJA' && c.estado === 'ACTIVO')
  const [f, setF] = useState({ cuenta: bancarias.length === 1 ? String(bancarias[0].cuenta) : '', archivo: null, saldoInicial: '', saldoFinal: '' })
  const [revision, setRevision] = useState(null)
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const elegida = bancarias.find((c) => String(c.cuenta) === f.cuenta)
  const moneda = elegida?.moneda ?? 'PEN'

  const cuerpo = () => {
    const datos = new FormData()
    datos.append('empresa', empresaActivaId)
    datos.append('cuenta', f.cuenta)
    datos.append('archivo', f.archivo)
    if (String(f.saldoInicial).trim()) datos.append('saldo_inicial', paraServidor(f.saldoInicial))
    if (String(f.saldoFinal).trim()) datos.append('saldo_final', paraServidor(f.saldoFinal))
    return datos
  }

  const revisar = useMutacion({
    mutationFn: () => api.post('/caja/extractos/previsualizar/', cuerpo(), { timeout: 60_000 }).then((r) => r.data),
    alExito: setRevision,
    avisarError: false,
  })
  const importar = useMutacion({
    mutationFn: () => api.post('/caja/extractos/', cuerpo(), { timeout: 60_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: (e) => `Estado de cuenta ${String(e.numero).padStart(6, '0')} importado.`,
    alExito: (e) => {
      onCerrar()
      navegar(`/caja/conciliacion/${e.id}`)
    },
    avisarError: false,
  })

  const alFallar = (error) => {
    const campos = erroresDeCampo(error)
    setErrores({ archivo: campos.archivo, cuenta: campos.cuenta })
    setGeneral(campos.archivo || campos.cuenta ? '' : mensajeDeError(error))
  }
  const elegirArchivo = (evento) => {
    const archivo = evento.target.files?.[0] ?? null
    evento.target.value = ''
    setF((p) => ({ ...p, archivo }))
    setRevision(null)
    setErrores({})
  }
  const pedirRevision = (evento) => {
    evento.preventDefault()
    if (revisar.isPending) return
    const locales = validarImportacion(f)
    setErrores(locales)
    setGeneral('')
    if (Object.keys(locales).length) return
    revisar.mutate(undefined, { onError: alFallar })
  }
  const confirmar = () => {
    if (importar.isPending) return
    setGeneral('')
    importar.mutate(undefined, { onError: alFallar })
  }

  const ocupado = revisar.isPending || importar.isPending
  return (
    <Modal titulo="Importar estado de cuenta" subtitulo="Sube el extracto que descargas del banco. Se revisa antes de guardar." onCerrar={onCerrar} ancho={860}>
      <form onSubmit={pedirRevision} noValidate>
        <fieldset disabled={ocupado} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="fila-campos">
            <Campo etiqueta="Cuenta del banco" tipo="select" requerido error={errores.cuenta}>
              {(p) => (
                <select
                  {...p}
                  value={f.cuenta}
                  onChange={(e) => {
                    setF((previo) => ({ ...previo, cuenta: e.target.value }))
                    setRevision(null)
                  }}
                >
                  <option value="">Elija la cuenta</option>
                  {bancarias.map((c) => (
                    <option key={c.cuenta} value={c.cuenta}>
                      {c.nombre} ({c.moneda === 'USD' ? 'US$' : 'S/'})
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Archivo del banco" requerido error={errores.archivo} ayuda="Excel (.xlsx) o CSV, hasta 2 MB.">
              {() => (
                <>
                  <input ref={entrada} type="file" accept=".xlsx,.csv,text/csv" hidden onChange={elegirArchivo} />
                  <button type="button" className="boton-cabecera" onClick={() => entrada.current?.click()}>
                    <Icono nombre="importar" tam={18} /> {f.archivo ? f.archivo.name : 'Elegir archivo'}
                  </button>
                </>
              )}
            </Campo>
          </div>
          <div className="fila-campos">
            <Campo etiqueta={`Saldo inicial según el banco (${moneda === 'USD' ? 'US$' : 'S/'})`} error={errores.saldoInicial} ayuda="Opcional. Con los dos saldos se comprueba que no falte ninguna línea.">
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.saldoInicial} onChange={(e) => setF((previo) => ({ ...previo, saldoInicial: e.target.value }))} />}
            </Campo>
            <Campo etiqueta={`Saldo final según el banco (${moneda === 'USD' ? 'US$' : 'S/'})`} error={errores.saldoFinal}>
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={f.saldoFinal} onChange={(e) => setF((previo) => ({ ...previo, saldoFinal: e.target.value }))} />}
            </Campo>
          </div>
        </fieldset>

        {revision && <Revision r={revision} moneda={moneda} />}

        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={ocupado}>
            Cancelar
          </button>
          {revision ? (
            <button type="button" className="primario" disabled={ocupado || revision.nuevas === 0 || revision.con_error > 0} onClick={confirmar}>
              {importar.isPending ? 'Importando…' : `Importar ${revision.nuevas} líneas`}
            </button>
          ) : (
            <button type="submit" className="primario" disabled={ocupado}>
              {revisar.isPending ? 'Revisando…' : 'Revisar el archivo'}
            </button>
          )}
        </div>
      </form>
    </Modal>
  )
}

const TITULOS = { fecha: 'Fecha', descripcion: 'Descripción', referencia: 'N° de operación', cargo: 'Cargos', abono: 'Abonos', monto: 'Importe', saldo: 'Saldo' }

function Revision({ r, moneda }) {
  return (
    <section aria-label="Revisión del archivo" className="conteo">
      <dl className="conteo-resumen">
        <div>
          <dt>Líneas nuevas</dt>
          <dd>{r.nuevas}</dd>
        </div>
        <div>
          <dt>Ya importadas antes</dt>
          <dd>{r.repetidas}</dd>
        </div>
        <div>
          <dt>Abonos</dt>
          <dd>{dinero(r.abonos, moneda)}</dd>
        </div>
        <div>
          <dt>Cargos</dt>
          <dd>{dinero(r.cargos, moneda)}</dd>
        </div>
        {r.desde && (
          <div>
            <dt>Periodo</dt>
            <dd>
              {fechaCorta(r.desde)} – {fechaCorta(r.hasta)}
            </dd>
          </div>
        )}
      </dl>
      <p className="celda-suave">
        Columnas reconocidas:{' '}
        {Object.entries(r.columnas)
          .map(([campo, titulo]) => `${TITULOS[campo]} («${titulo}»)`)
          .join(' · ')}
        {r.ignoradas > 0 ? `. Se omitieron ${r.ignoradas} filas sin importe.` : ''}
      </p>
      {r.con_error > 0 && (
        <div role="alert" className="campo-error">
          <strong>{r.con_error} filas tienen problemas; corrígelas en el archivo y vuelve a subirlo:</strong>
          <ul>
            {r.errores.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Descripción</th>
              <th>Operación</th>
              <th className="num">Importe</th>
            </tr>
          </thead>
          <tbody>
            {r.muestra.map((m, i) => (
              <tr key={`${m.fecha}-${m.referencia}-${i}`} className={m.repetida ? 'anulado' : undefined}>
                <td>{fechaCorta(m.fecha)}</td>
                <td className="col-texto">
                  {m.descripcion}
                  {m.repetida && <span className="sub-texto">Ya importada antes</span>}
                </td>
                <td className="celda-suave">{m.referencia}</td>
                <td className={`num ${Number(m.monto) > 0 ? 'caja-ingreso' : 'caja-egreso'}`}>{dinero(m.monto, moneda)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {r.total > r.muestra.length && <p className="celda-suave">Se muestran las primeras {r.muestra.length} de {r.total} líneas.</p>}
    </section>
  )
}
