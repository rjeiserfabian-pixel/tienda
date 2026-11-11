import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import ImpresionProforma from '../../ventas/components/ImpresionProforma'
import { ESTADOS_REPUESTO, fechaHora } from '../servicio'
import AprobarPresupuestoModal from './AprobarPresupuestoModal'
import EditorPresupuestoModal from './EditorPresupuestoModal'

/** Reserva de nuevo los repuestos que faltaban (por ejemplo, ya llegó la compra). */
function BotonReservar({ orden }) {
  const [aviso, setAviso] = useState('')
  const reservar = useMutacion({
    mutationFn: () => api.post(`/servicio-tecnico/ordenes/${orden.id}/reservar/`, {}).then((r) => r.data),
    invalidar: [['servicio'], ['almacen']],
    alExito: (r) => setAviso(r.reserva.pendientes.length ? `Aún falta: ${r.reserva.pendientes.join('; ')}.` : 'Todos los repuestos quedaron reservados.'),
    avisarError: false,
  })
  return (
    <>
      <button type="button" className="boton-cabecera" disabled={reservar.isPending} onClick={() => reservar.mutate(undefined, { onError: (e) => setAviso(mensajeDeError(e)) })}>
        <Icono nombre="package" tam={18} /> {reservar.isPending ? 'Reservando…' : 'Reservar repuestos'}
      </button>
      {aviso && (
        <span role="status" className="celda-suave">
          {aviso}
        </span>
      )}
    </>
  )
}

/** El presupuesto de la orden: servicios y repuestos con su precio, la aprobación del cliente y el estado del stock. */
export default function PresupuestoOrden({ orden: o }) {
  const [editando, setEditando] = useState(false)
  const [aprobando, setAprobando] = useState(false)
  const [impresion, setImpresion] = useState(null) // cada clic en Imprimir vuelve a montarla
  const p = o.presupuesto
  const varias = p ? new Set(p.lineas.map((l) => l.empresa)).size > 1 : false
  const vencido = p ? p.proforma.valida_hasta < hoyIso() && !p.aprobado : false

  const acciones = (
    <>
      {p?.ve_importes && (
        <button type="button" className="boton-cabecera" onClick={() => setImpresion((previa) => (previa ?? 0) + 1)}>
          <Icono nombre="documento" tam={18} /> Imprimir
        </button>
      )}
      {o.permite.presupuestar && (
        <button type="button" className="boton-cabecera" onClick={() => setEditando(true)}>
          {p ? 'Rehacer' : 'Armar presupuesto'}
        </button>
      )}
      {o.permite.aprobar && (
        <button type="button" className="primario boton-cabecera" disabled={vencido} title={vencido ? 'El presupuesto venció: rehazlo con precios al día.' : undefined} onClick={() => setAprobando(true)}>
          Registrar aprobación
        </button>
      )}
    </>
  )

  return (
    <PanelTarjeta icono="coins" titulo="Presupuesto" descripcion={p ? `Versión ${p.version} · ${p.proforma.numero_completo} · válido hasta ${fechaCorta(p.proforma.valida_hasta)}` : 'Servicios y repuestos que se le cobrarán al cliente.'} acciones={acciones}>
      {!p ? (
        <p className="estado-vacio">Todavía no hay presupuesto. {o.permite.presupuestar ? 'Arma uno con los servicios y repuestos del trabajo.' : 'Lo arma quien presupuesta.'}</p>
      ) : (
        <>
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Descripción</th>
                  <th className="num">Cant.</th>
                  {p.ve_importes && <th className="num">P. unit. sin IGV</th>}
                  {p.ve_importes && <th className="num">Total</th>}
                  <th>Repuesto</th>
                </tr>
              </thead>
              <tbody>
                {p.lineas.map((l) => {
                  const estado = l.repuesto && ESTADOS_REPUESTO[l.repuesto.estado]
                  return (
                    <tr key={l.id}>
                      <td className="col-texto">
                        {l.descripcion}
                        <span className="sub-texto">
                          {l.codigo}
                          {varias ? ` · ${l.empresa_nombre}` : ''}
                        </span>
                      </td>
                      <td className="num">
                        {Number(l.cantidad)} {l.unidad}
                      </td>
                      {p.ve_importes && <td className="num">{dinero(l.precio_unitario, p.proforma.moneda)}</td>}
                      {p.ve_importes && <td className="num">{dinero(l.total, p.proforma.moneda)}</td>}
                      <td>
                        {estado ? (
                          <span className="pildora" data-tono={estado.tono}>
                            {estado.texto}
                          </span>
                        ) : (
                          <span className="celda-suave">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {p.ve_importes && (
            <p>
              <strong>Total con IGV: {dinero(p.total, p.proforma.moneda)}</strong>
            </p>
          )}
          {!p.ve_importes && <p className="celda-suave">Los precios los ve quien presupuesta y la recepción.</p>}
          {vencido && (
            <p role="status" className="campo-error">
              El presupuesto venció el {fechaCorta(p.proforma.valida_hasta)}. Rehazlo para actualizar los precios.
            </p>
          )}
          {p.aprobado && (
            <p role="status">
              <span className="pildora" data-tono="verde">
                Aprobado
              </span>{' '}
              {fechaHora(p.aprobado_en)} · {p.aprobacion_medio_nombre} · {p.aprobado_por_nombre || 'Sistema'}
              <br />
              <span className="celda-suave">{p.aprobacion_nota}</span>
            </p>
          )}
          {p.repuestos_pendientes > 0 && (
            <p role="status" className="compra-aviso">
              Faltan {p.repuestos_pendientes} repuesto(s) por reservar: no hay stock suficiente. Pasa la orden a «Pendiente de repuesto» y, cuando llegue la compra, reserva de nuevo.
            </p>
          )}
          {o.permite.reservar && <BotonReservar orden={o} />}
        </>
      )}
      {editando && <EditorPresupuestoModal orden={o} onCerrar={() => setEditando(false)} />}
      {aprobando && <AprobarPresupuestoModal orden={o} onCerrar={() => setAprobando(false)} />}
      {impresion && p && <ImpresionProforma key={impresion} id={p.proforma.id} />}
    </PanelTarjeta>
  )
}
