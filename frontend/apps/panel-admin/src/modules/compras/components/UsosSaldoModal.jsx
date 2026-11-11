import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Can from '../../../shared/components/Can'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, numeroInterno } from '../compras'

/** Formulario corto: deshace un uso del saldo con su motivo. */
function DeshacerUso({ credito, uso, onListo, onCancelar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const deshacer = useMutacion({
    mutationFn: (texto) => api.post(`/compras/creditos/${credito.id}/aplicaciones/${uso.id}/deshacer/`, { motivo: texto }).then((r) => r.data),
    invalidar: [['compras']],
    exito: 'Uso deshecho. La compra vuelve a deber esas cuotas.',
    alExito: onListo,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (deshacer.isPending) return
    if (!motivo.trim()) return setError('Escriba el motivo.')
    setError('')
    deshacer.mutate(motivo.trim(), { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }
  return (
    <form onSubmit={enviar} noValidate>
      <p>
        Se deshará el uso de {dinero(uso.monto, credito.moneda)} en la compra N° {numeroInterno({ numero: uso.compra_numero })}: sus cuotas vuelven a deberse y el saldo queda disponible otra vez.
      </p>
      <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
        {(p) => <textarea {...p} rows={2} maxLength={250} value={motivo} disabled={deshacer.isPending} placeholder="Ej. Se aplicó a la compra equivocada" onChange={(e) => setMotivo(e.target.value)} />}
      </Campo>
      <div className="modal-pie">
        <button type="button" onClick={onCancelar} disabled={deshacer.isPending}>
          Volver
        </button>
        <button type="submit" className="peligro" disabled={deshacer.isPending}>
          {deshacer.isPending ? 'Deshaciendo…' : 'Deshacer el uso'}
        </button>
      </div>
    </form>
  )
}

/** En qué compras se usó un saldo a favor, y la opción de deshacer un uso. */
export default function UsosSaldoModal({ credito, onCerrar }) {
  const [deshaciendo, setDeshaciendo] = useState(null)
  return (
    <Modal titulo="Usos del saldo a favor" subtitulo={`${credito.proveedor_nombre} · devolución ${credito.devolucion_comprobante}`} onCerrar={onCerrar} ancho={680}>
      {deshaciendo ? (
        <DeshacerUso credito={credito} uso={deshaciendo} onListo={onCerrar} onCancelar={() => setDeshaciendo(null)} />
      ) : (
        <>
          {credito.aplicaciones.length === 0 ? (
            <p className="estado-vacio">Este saldo todavía no se usó.</p>
          ) : (
            <div className="marco-tabla">
              <table className="tabla-datos">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Compra</th>
                    <th>Cuotas</th>
                    <th className="num">Monto</th>
                    <th>Estado</th>
                    <th className="centrado">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {credito.aplicaciones.map((u) => (
                    <tr key={u.id} className={u.anulada ? 'anulado' : undefined}>
                      <td>{fechaCorta(u.fecha)}</td>
                      <td className="col-texto">
                        <Link to={`/compras/registro/${u.compra}`}>N° {numeroInterno({ numero: u.compra_numero })}</Link>
                        <span className="sub-texto">{u.compra_comprobante}</span>
                      </td>
                      <td className="celda-suave">{u.cuotas.map((c) => `${c.numero} (${dinero(c.monto, credito.moneda)})`).join(', ')}</td>
                      <td className="num">{dinero(u.monto, credito.moneda)}</td>
                      <td>{u.anulada ? <span className="estado-pildora inactivo">Deshecho</span> : <span className="estado-pildora activo">Aplicado</span>}</td>
                      <td className="centrado">
                        {!u.anulada && (
                          <Can permiso="COMPRAS.CREDITO_USAR">
                            <button type="button" className="peligro-suave" onClick={() => setDeshaciendo(u)}>
                              Deshacer
                            </button>
                          </Can>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="modal-pie">
            <button type="button" onClick={onCerrar}>
              Cerrar
            </button>
          </div>
        </>
      )}
    </Modal>
  )
}
