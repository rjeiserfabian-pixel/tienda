import { useState } from 'react'
import Campo from '../../../shared/components/Campo'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import MaestroModal from '../../mantenimiento/components/MaestroModal'
import { CONDUCTORES, EMPRESAS_TRANSPORTE, VEHICULOS } from '../../mantenimiento/maestros'
import BotonMas from './BotonMas'
import ConductorVehiculoGuia from './ConductorVehiculoGuia'
import DatoLectura from './DatoLectura'

const VACIO = []
const ALTAS = { empresa: EMPRESAS_TRANSPORTE, conductor: CONDUCTORES, vehiculo: VEHICULOS }

/**
 * Quién lleva la mercadería. Transporte público: una empresa de transporte de la lista (con su RUC y sus
 * registros del MTC), y el conductor y el vehículo si se quieren indicar. Transporte privado: la propia
 * empresa, con el conductor y el vehículo elegidos. Un traslado en vehículo M1 o L no exige conductor ni placa.
 */
export default function TransporteGuia({ f, poner, remitente, disabled, onAgregarSecundario, onQuitarSecundario }) {
  const [creando, setCreando] = useState(null) // 'empresa' | 'conductor' | 'vehiculo'
  const empresas = useOpciones('/mantenimiento/empresas-transporte/').data ?? VACIO
  const conductores = useOpciones('/mantenimiento/conductores/').data ?? VACIO
  const vehiculos = useOpciones('/mantenimiento/vehiculos/').data ?? VACIO
  const publico = f.modalidad === '01'
  const empresa = empresas.find((e) => String(e.id) === f.transportista)
  // Lo recién registrado queda elegido en su lista.
  const alCrear = (creado) => poner({ empresa: 'transportista', conductor: 'conductor', vehiculo: 'vehiculo' }[creando], String(creado.id))

  return (
    <div className="pos-bloques">
      <div className="fila-campos">
        <div className="segmentos" role="radiogroup" aria-label="Tipo de transporte">
          {[
            ['01', 'Transporte público'],
            ['02', 'Transporte privado'],
          ].map(([valor, texto]) => (
            <button key={valor} type="button" role="radio" aria-checked={f.modalidad === valor} className={f.modalidad === valor ? 'activo' : undefined} disabled={disabled} onClick={() => poner('modalidad', valor)}>
              {texto}
            </button>
          ))}
        </div>
        <label className="nota-reingreso">
          <input type="checkbox" checked={f.m1l} disabled={disabled} onChange={(e) => poner('m1l', e.target.checked)} /> Traslado en vehículos de categoría M1 o L
          <small className="celda-suave"> Vehículos livianos: no se exige conductor ni placa.</small>
        </label>
      </div>

      {publico ? (
        <>
          <div className="guia-fila-con-boton">
            <Campo etiqueta="Empresa de transporte" tipo="select" requerido>
              {(p) => (
                <select {...p} value={f.transportista} disabled={disabled} onChange={(e) => poner('transportista', e.target.value)}>
                  <option value="">{empresas.length === 0 ? 'No hay empresas de transporte registradas' : 'Elige la empresa de transporte'}</option>
                  {empresas.map((e) => (
                    <option key={e.id} value={String(e.id)}>
                      {e.nombre} · {e.ruc}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <BotonMas etiqueta="Registrar una empresa de transporte nueva" disabled={disabled} onClick={() => setCreando('empresa')} />
          </div>
          <div className="fila-campos">
            <DatoLectura etiqueta="RUC" valor={empresa?.ruc} />
            <DatoLectura etiqueta="N° de registro MTC" valor={empresa?.registro_mtc} />
            <DatoLectura etiqueta="Certificado de inspección" valor={empresa?.certificado_inspeccion} />
          </div>
          <label className="nota-reingreso">
            <input type="checkbox" checked={f.conductorEnPublico} disabled={disabled} onChange={(e) => poner('conductorEnPublico', e.target.checked)} /> Registrar también el conductor y el vehículo
            <small className="celda-suave"> Opcional en el transporte público.</small>
          </label>
        </>
      ) : (
        <div className="fila-campos">
          <DatoLectura etiqueta="Empresa de transporte" valor={remitente?.nombre} />
          <DatoLectura etiqueta="RUC" valor={remitente?.ruc} />
        </div>
      )}

      {(!publico || f.conductorEnPublico) && <ConductorVehiculoGuia f={f} poner={poner} conductores={conductores} vehiculos={vehiculos} disabled={disabled} onCrear={setCreando} onAgregarSecundario={onAgregarSecundario} onQuitarSecundario={onQuitarSecundario} />}
      {creando && <MaestroModal config={ALTAS[creando]} onCerrar={() => setCreando(null)} alCrear={alCrear} />}
    </div>
  )
}
