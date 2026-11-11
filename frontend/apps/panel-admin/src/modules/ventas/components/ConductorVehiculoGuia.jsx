import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { MAX_VEHICULOS_SECUNDARIOS } from '../ventas'
import BotonMas from './BotonMas'
import DatoLectura from './DatoLectura'

const VACIO = []

/**
 * El conductor y los vehículos de la guía, elegidos de las listas de Mantenimiento: el conductor con su
 * documento y su licencia, el vehículo principal y los secundarios (los que van enganchados).
 */
export default function ConductorVehiculoGuia({ f, poner, conductores = VACIO, vehiculos = VACIO, disabled, onCrear, onAgregarSecundario, onQuitarSecundario }) {
  const conductor = conductores.find((c) => String(c.id) === f.conductor)
  const principal = vehiculos.find((v) => String(v.id) === f.vehiculo)
  const secundarios = f.secundarios.map((id) => vehiculos.find((v) => String(v.id) === id)).filter(Boolean)
  const posibles = vehiculos.filter((v) => String(v.id) !== f.vehiculo && !f.secundarios.includes(String(v.id)))

  return (
    <div className="pos-bloques">
      <div className="guia-fila-con-boton">
        <Campo etiqueta="Conductor" tipo="select" requerido={f.modalidad === '02' && !f.m1l}>
          {(p) => (
            <select {...p} value={f.conductor} disabled={disabled} onChange={(e) => poner('conductor', e.target.value)}>
              <option value="">{conductores.length === 0 ? 'No hay conductores registrados' : 'Elige el conductor'}</option>
              {conductores.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.nombre} · {c.numero_documento}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <BotonMas etiqueta="Registrar un conductor nuevo" disabled={disabled} onClick={() => onCrear('conductor')} />
      </div>
      <div className="fila-campos">
        <DatoLectura etiqueta="Documento" valor={conductor ? `${conductor.tipo_documento} ${conductor.numero_documento}` : ''} />
        <DatoLectura etiqueta="Licencia de conducir" valor={conductor?.licencia} />
      </div>
      <div className="guia-fila-con-boton">
        <Campo etiqueta="Vehículo principal" tipo="select" requerido={f.modalidad === '02' && !f.m1l}>
          {(p) => (
            <select {...p} value={f.vehiculo} disabled={disabled} onChange={(e) => poner('vehiculo', e.target.value)}>
              <option value="">{vehiculos.length === 0 ? 'No hay vehículos registrados' : 'Elige el vehículo'}</option>
              {vehiculos.map((v) => (
                <option key={v.id} value={String(v.id)}>
                  {v.descripcion}
                </option>
              ))}
            </select>
          )}
        </Campo>
        <BotonMas etiqueta="Registrar un vehículo nuevo" disabled={disabled} onClick={() => onCrear('vehiculo')} />
      </div>
      {principal && <p className="celda-suave">Placa principal: {principal.placa}</p>}
      <Campo etiqueta="Placas secundarias" tipo="select" ayuda={`Opcional: remolque o carreta (hasta ${MAX_VEHICULOS_SECUNDARIOS}).`}>
        {(p) => (
          <select {...p} value="" disabled={disabled || posibles.length === 0 || f.secundarios.length >= MAX_VEHICULOS_SECUNDARIOS} onChange={(e) => e.target.value && onAgregarSecundario(e.target.value)}>
            <option value="">{posibles.length === 0 ? 'No hay más vehículos para agregar' : 'Agregar una placa secundaria'}</option>
            {posibles.map((v) => (
              <option key={v.id} value={String(v.id)}>
                {v.descripcion}
              </option>
            ))}
          </select>
        )}
      </Campo>
      {secundarios.length > 0 && (
        <ul className="guia-chips" aria-label="Placas secundarias elegidas">
          {secundarios.map((v) => (
            <li key={v.id}>
              <span>{v.descripcion}</span>
              <button type="button" aria-label={`Quitar la placa ${v.placa}`} title="Quitar" disabled={disabled} onClick={() => onQuitarSecundario(String(v.id))}>
                <Icono nombre="cerrar" tam={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
