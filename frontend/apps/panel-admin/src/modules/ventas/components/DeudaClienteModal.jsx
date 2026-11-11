import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import { estadoDeCuota } from '../ventas'
import AbonarModal from './AbonarModal'

/**
 * Lo que un cliente debe a la empresa: cada comprobante con sus cuotas y un botón para cobrar.
 * Al cobrar, la lista y los totales se actualizan solos.
 */
export default function DeudaClienteModal({ cliente, empresaId, onCerrar }) {
  const navegar = useNavigate()
  const [cobrando, setCobrando] = useState(null)
  const consulta = useQuery({
    queryKey: ['ventas', 'por-cobrar-cliente', empresaId, cliente.cliente],
    queryFn: ({ signal }) => api.get(`/ventas/por-cobrar/clientes/${cliente.cliente}/`, { params: { empresa: empresaId }, signal }).then((r) => r.data),
    staleTime: 0,
  })
  const datos = consulta.data
  const hoy = hoyIso()

  return (
    <>
      <Modal titulo={cliente.cliente_nombre} subtitulo={`${cliente.tipo_documento} ${cliente.numero_documento}${cliente.telefono ? ` · ${cliente.telefono}` : ''}`} onCerrar={onCerrar} ancho={1000}>
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && (
            <>
              <p className="celda-suave">
                {datos.cliente.credito.sin_limite ? 'Crédito sin tope' : `Límite de crédito S/ ${Number(datos.cliente.credito.limite).toFixed(2)}`} · debe en total (todas las empresas) S/ {Number(datos.cliente.credito.deuda).toFixed(2)}
                {datos.cliente.credito.sin_limite ? '.' : ` · puede comprar S/ ${Number(datos.cliente.credito.disponible).toFixed(2)} más.`}
              </p>
              {datos.comprobantes.length === 0 && <p className="estado-vacio">Este cliente ya no debe nada a esta empresa.</p>}
              {datos.comprobantes.map((c) => (
                <section key={c.id} className="cobranza-comprobante">
                  <header>
                    <div>
                      <strong>
                        {c.tipo_nombre} {c.numero_completo}
                      </strong>
                      <span className="sub-texto">
                        Venta N° {String(c.venta_numero).padStart(6, '0')} · {fechaCorta(c.fecha)} · total {dinero(c.total, c.moneda)}
                      </span>
                    </div>
                    <div className="cobranza-saldo">
                      <span className="sub-texto">Debe</span>
                      <strong>{dinero(c.saldo, c.moneda)}</strong>
                      {c.dias_atraso > 0 && (
                        <span className="pildora" data-tono="rojo">
                          Vencida hace {c.dias_atraso} {c.dias_atraso === 1 ? 'día' : 'días'}
                        </span>
                      )}
                    </div>
                    <div className="venta-acciones">
                      <button type="button" className="boton-cabecera" onClick={() => navegar(`/ventas/historial/${c.venta}`)}>
                        Ver la venta
                      </button>
                      <Can permiso="VENTAS.COBRAR">
                        <button type="button" className="primario boton-cabecera" onClick={() => setCobrando(c)}>
                          Cobrar
                        </button>
                      </Can>
                    </div>
                  </header>
                  <ul className="pos-cuotas">
                    {c.cuotas.map((q) => {
                      const estado = estadoDeCuota(q, hoy)
                      return (
                        <li key={q.id}>
                          <span>
                            Cuota {q.numero} · vence {fechaCorta(q.fecha_vencimiento)}
                          </span>
                          <span>
                            {dinero(q.saldo, c.moneda)}{' '}
                            <span className="pildora" data-tono={estado.tono}>
                              {estado.texto}
                            </span>
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              ))}
            </>
          )}
        </EstadoConsulta>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar}>
            Cerrar
          </button>
        </div>
      </Modal>
      {cobrando && <AbonarModal comprobante={cobrando} onCerrar={() => setCobrando(null)} />}
    </>
  )
}
