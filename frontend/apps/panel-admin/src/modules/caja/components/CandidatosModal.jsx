import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { dinero, origen } from '../caja'

const MARGENES = [
  [5, '5 días'],
  [15, '15 días'],
  [31, '31 días'],
]

/** Movimientos del libro con el mismo importe que una línea del banco, para unirlos a mano. */
export default function CandidatosModal({ linea, moneda, onCerrar }) {
  const [dias, setDias] = useState(5)
  const [error, setError] = useState('')
  const consulta = useQuery({
    queryKey: ['caja', 'candidatos', linea.id, dias],
    queryFn: ({ signal }) => api.get(`/caja/lineas-extracto/${linea.id}/candidatos/`, { params: { dias }, signal }).then((r) => r.data),
  })

  const unir = useMutacion({
    mutationFn: (movimiento) => api.post(`/caja/lineas-extracto/${linea.id}/conciliar/`, { movimiento }).then((r) => r.data),
    invalidar: [['caja']],
    exito: 'Línea conciliada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const lista = consulta.data ?? []
  return (
    <Modal titulo="Buscar el movimiento" subtitulo={`${fechaCorta(linea.fecha)} · ${linea.descripcion || 'Sin descripción'} · ${dinero(linea.monto, moneda)}`} onCerrar={onCerrar} ancho={820}>
      <div className="segmentos" role="radiogroup" aria-label="Margen de fechas">
        {MARGENES.map(([valor, texto]) => (
          <button key={valor} type="button" role="radio" aria-checked={dias === valor} className={dias === valor ? 'activo' : undefined} onClick={() => setDias(valor)}>
            Hasta {texto} de diferencia
          </button>
        ))}
      </div>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {lista.length === 0 ? (
          <p className="estado-vacio">No hay movimientos sin conciliar con ese importe en esas fechas. Si el banco cobró algo que no estaba anotado, usa «Registrar».</p>
        ) : (
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>N°</th>
                  <th>Concepto</th>
                  <th>Origen</th>
                  <th className="num">Importe</th>
                  <th className="centrado">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {lista.map((m) => {
                  const o = origen(m.origen_tipo)
                  return (
                    <tr key={m.id}>
                      <td>{fechaCorta(m.fecha)}</td>
                      <td className="celda-suave">{String(m.numero).padStart(6, '0')}</td>
                      <td className="col-texto">
                        {m.concepto_nombre}
                        {(m.glosa || m.referencia) && (
                          <span className="sub-texto">
                            {m.glosa}
                            {m.referencia ? ` · Operación ${m.referencia}` : ''}
                          </span>
                        )}
                      </td>
                      <td>
                        <span className="pildora" data-tono={o.tono}>
                          {o.texto}
                        </span>
                      </td>
                      <td className={`num ${m.tipo === 'INGRESO' ? 'caja-ingreso' : 'caja-egreso'}`}>{dinero(m.monto, moneda)}</td>
                      <td className="centrado">
                        <button type="button" className="primario boton-cabecera" disabled={unir.isPending} onClick={() => unir.mutate(m.id, { onError: (e) => setError(mensajeDeError(e)) })}>
                          Unir
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </EstadoConsulta>
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          Cerrar
        </button>
      </div>
    </Modal>
  )
}
