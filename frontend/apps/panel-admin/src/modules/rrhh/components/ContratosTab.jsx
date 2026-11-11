import { useState } from 'react'
import { fechaCorta, soles } from '../rrhh'
import { ContratoModal, FinalizarModal, SueldoModal } from './ContratoModales'
import '../rrhh.css'

/** Un contrato con su estado, sueldo (si se puede ver), historial de sueldos y acciones. */
function ContratoTarjeta({ contrato, permisos, onAccion }) {
  const vigente = contrato.estado === 'VIGENTE'
  const dias = contrato.dias_para_vencer
  return (
    <article className="rh-tarjeta">
      <header>
        <h3>
          {contrato.cargo}{' '}
          <span className="pildora mas" data-tono={vigente ? 'verde' : 'gris'}>
            {vigente ? 'Vigente' : 'Finalizado'}
          </span>
          {vigente && contrato.fecha_fin && dias !== null && dias <= 30 && (
            <span className="pildora mas" data-tono={dias < 0 ? 'rojo' : 'ambar'}>
              {dias < 0 ? `Venció hace ${-dias} día(s)` : dias === 0 ? 'Vence hoy' : `Vence en ${dias} día(s)`}
            </span>
          )}
        </h3>
        {vigente && (
          <div className="rh-acciones">
            {permisos.editar && (
              <button type="button" className="boton-cabecera" onClick={() => onAccion('editar', contrato)}>
                Corregir
              </button>
            )}
            {permisos.editar_sueldos && (
              <button type="button" className="boton-cabecera" onClick={() => onAccion('sueldo', contrato)}>
                Cambiar sueldo
              </button>
            )}
            {permisos.editar && (
              <button type="button" className="boton-cabecera" onClick={() => onAccion('finalizar', contrato)}>
                Finalizar
              </button>
            )}
          </div>
        )}
      </header>
      <dl className="rh-datos">
        <div>
          <dt>Régimen</dt>
          <dd>{contrato.regimen_nombre}</dd>
        </div>
        <div>
          <dt>Tipo</dt>
          <dd>
            {contrato.tipo_nombre} · {contrato.categoria_nombre}
          </dd>
        </div>
        <div>
          <dt>Inicio</dt>
          <dd>{fechaCorta(contrato.fecha_inicio)}</dd>
        </div>
        <div>
          <dt>Fin del contrato</dt>
          <dd>{contrato.fecha_fin ? fechaCorta(contrato.fecha_fin) : 'No vence'}</dd>
        </div>
        {permisos.ver_sueldos && vigente && (
          <div>
            <dt>Sueldo actual</dt>
            <dd>
              <strong>{soles(contrato.sueldo_actual)}</strong>
            </dd>
          </div>
        )}
        {!vigente && (
          <>
            <div>
              <dt>Cese</dt>
              <dd>{fechaCorta(contrato.fecha_cese)}</dd>
            </div>
            <div>
              <dt>Motivo del cese</dt>
              <dd>{contrato.motivo_cese || '—'}</dd>
            </div>
          </>
        )}
        {contrato.observacion && (
          <div>
            <dt>Observación</dt>
            <dd>{contrato.observacion}</dd>
          </div>
        )}
      </dl>
      {permisos.ver_sueldos && contrato.cambios_sueldo?.length > 0 && (
        <div className="marco-tabla">
          <table className="tabla-datos">
            <caption className="sr-only">Historial de sueldos</caption>
            <thead>
              <tr>
                <th>Rige desde</th>
                <th>Sueldo mensual</th>
                <th>Motivo</th>
              </tr>
            </thead>
            <tbody>
              {contrato.cambios_sueldo.map((c) => (
                <tr key={c.id}>
                  <td>{fechaCorta(c.vigente_desde)}</td>
                  <td>{soles(c.monto)}</td>
                  <td>{c.motivo || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  )
}

/** Pestaña de contratos de un trabajador: el historial y las acciones sobre el vigente. */
export default function ContratosTab({ trabajador, contratos, permisos }) {
  const [modal, setModal] = useState(null) // { tipo: 'nuevo' | 'editar' | 'sueldo' | 'finalizar', contrato }
  const [avisos, setAvisos] = useState([])
  const hayVigente = contratos.some((c) => c.estado === 'VIGENTE')
  const cerrar = () => setModal(null)
  const abrir = (tipo, contrato) => {
    setAvisos([])
    setModal({ tipo, contrato })
  }

  return (
    <section className="rh-opciones" aria-label="Contratos">
      {avisos.length > 0 && (
        <div className="rh-aviso" role="status">
          Se guardó, pero revise:
          <ul>
            {avisos.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}
      {permisos.editar_sueldos && !hayVigente && (
        <div className="rh-acciones">
          <button type="button" className="boton-cabecera primario" onClick={() => abrir('nuevo')}>
            Nuevo contrato
          </button>
        </div>
      )}
      {!permisos.editar_sueldos && !hayVigente && <p className="rh-aviso">Este trabajador no tiene contrato vigente. Registrarlo exige el permiso de sueldos (lleva el sueldo inicial).</p>}
      {contratos.length === 0 && <p className="celda-suave">Todavía no hay contratos registrados.</p>}
      {contratos.map((c) => (
        <ContratoTarjeta key={c.id} contrato={c} permisos={permisos} onAccion={abrir} />
      ))}

      {modal?.tipo === 'nuevo' && <ContratoModal trabajador={trabajador} verSueldos={permisos.ver_sueldos} onCerrar={cerrar} onAviso={setAvisos} />}
      {modal?.tipo === 'editar' && <ContratoModal trabajador={trabajador} contrato={modal.contrato} verSueldos={permisos.ver_sueldos} onCerrar={cerrar} onAviso={setAvisos} />}
      {modal?.tipo === 'finalizar' && <FinalizarModal trabajador={trabajador} contrato={modal.contrato} onCerrar={cerrar} />}
      {modal?.tipo === 'sueldo' && <SueldoModal trabajador={trabajador} contrato={modal.contrato} onCerrar={cerrar} onAviso={setAvisos} />}
    </section>
  )
}
