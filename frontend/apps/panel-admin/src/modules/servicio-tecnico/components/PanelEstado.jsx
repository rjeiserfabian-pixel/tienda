import { useState } from 'react'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { ESTADOS_ORDEN } from '../servicio'
import CambioEstadoModal from './CambioEstadoModal'
import EntregarEquipoModal from './EntregarEquipoModal'

/** El estado de la orden y los pasos que esta persona puede dar ahora (los decide el servidor). */
export default function PanelEstado({ orden: o }) {
  const [destino, setDestino] = useState(null)
  const [entregando, setEntregando] = useState(false)
  const estado = ESTADOS_ORDEN[o.estado]
  const pausada = o.estado === 'PENDIENTE_REPUESTO' && o.estado_previo

  return (
    <PanelTarjeta icono="settings" titulo="Estado" descripcion={o.destinos.length || o.entrega ? 'Elige el siguiente paso.' : 'No tienes pasos disponibles en esta orden.'}>
      <p>
        <span className="pildora" data-tono={estado?.tono ?? 'gris'}>
          {estado?.texto ?? o.estado_nombre}
        </span>
        {pausada && <span className="celda-suave"> · se reanuda en «{ESTADOS_ORDEN[o.estado_previo]?.texto}»</span>}
      </p>
      {o.abandono.aplica && o.abandono.dias > 0 && (
        <p className="celda-suave" role="status">
          Lleva {o.abandono.dias} días en este estado. Para darlo por abandonado hay que haber avisado al cliente ({o.abandono.avisos} aviso{o.abandono.avisos === 1 ? '' : 's'} registrado{o.abandono.avisos === 1 ? '' : 's'}) y esperar {o.abandono.dias_requeridos} días
          {o.abandono.puede ? ': ya se puede.' : '.'}
        </p>
      )}
      {o.entrega && (
        <div className="servicio-pasos">
          <button type="button" className="primario boton-cabecera" onClick={() => setEntregando(true)}>
            Entregar equipo{o.entrega.cobra ? ' y cobrar' : ''}
          </button>
        </div>
      )}
      {o.destinos.length > 0 && (
        <div className="servicio-pasos" role="group" aria-label="Siguiente paso">
          {o.destinos.map((d) => (
            <button key={d.estado} type="button" className="boton-cabecera" onClick={() => setDestino(d)}>
              {ESTADOS_ORDEN[d.estado]?.texto ?? d.nombre}
            </button>
          ))}
        </div>
      )}
      {entregando && <EntregarEquipoModal orden={o} onCerrar={() => setEntregando(false)} />}
      {destino && <CambioEstadoModal orden={o} destino={destino} onCerrar={() => setDestino(null)} />}
    </PanelTarjeta>
  )
}
