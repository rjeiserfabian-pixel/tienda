import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import { BANCOS } from '../../mantenimiento/maestros'
import { useGuardarDatosLaborales } from '../hooks/useTrabajadores'
import { AFPS, entero } from '../rrhh'
import '../rrhh.css'

const PENSIONES = [
  ['NINGUNO', 'Sin definir o no afiliado'],
  ['ONP', 'ONP'],
  ['AFP', 'AFP'],
]
const COMISIONES = [
  ['', 'Elegir'],
  ['FLUJO', 'Sobre el flujo (remuneración)'],
  ['MIXTA', 'Mixta'],
]
const METODOS = [
  ['TRANSFERENCIA', 'Transferencia a su cuenta'],
  ['EFECTIVO', 'Efectivo'],
  ['OTRO', 'Otro medio'],
]
const SEXOS = [
  ['', 'Sin indicar'],
  ['M', 'Masculino'],
  ['F', 'Femenino'],
]

/** Estado inicial del formulario a partir de lo guardado (la cuenta nunca llega completa). */
const inicial = (d) => ({
  sexo: d?.sexo ?? '',
  nacionalidad: d?.nacionalidad ?? 'Peruana',
  sistema_pension: d?.sistema_pension ?? 'NINGUNO',
  afp: d?.afp ?? '',
  tipo_comision: d?.tipo_comision ?? '',
  cuspp: d?.cuspp ?? '',
  asignacion_familiar: d?.asignacion_familiar ?? false,
  paga_renta_5ta: d?.paga_renta_5ta ?? false,
  subsidio_descanso_medico: d?.subsidio_descanso_medico ?? false,
  metodo_pago: d?.metodo_pago ?? 'TRANSFERENCIA',
  banco: d?.banco ?? '',
  numero_cuenta: '',
  cci: '',
})

/** Revisa el formulario antes de enviarlo; devuelve `{ campo: mensaje }` (vacío si está bien). */
function revisar(f) {
  const e = {}
  if (!f.nacionalidad.trim()) e.nacionalidad = 'Indique la nacionalidad.'
  if (f.sistema_pension === 'AFP') {
    if (!f.afp) e.afp = 'Elija la AFP.'
    if (!f.tipo_comision) e.tipo_comision = 'Elija el tipo de comisión.'
  }
  if (f.cuspp && !/^[A-Za-z0-9]{12}$/.test(f.cuspp.trim())) e.cuspp = 'El CUSPP tiene 12 letras y números.'
  if (f.numero_cuenta && !/^[0-9-]{4,30}$/.test(f.numero_cuenta)) e.numero_cuenta = 'Use de 4 a 30 números (y guiones).'
  if (f.cci && !/^\d{20}$/.test(f.cci)) e.cci = 'El CCI tiene 20 dígitos.'
  return e
}

/**
 * Datos laborales de un trabajador: pensión, opciones propias (asignación familiar, renta de 5.ª,
 * descanso médico) y forma de pago. Banco y cuenta solo se muestran con el permiso de sueldos; la
 * cuenta completa nunca vuelve del servidor: se muestran sus últimos dígitos y, para cambiarla,
 * se escribe una nueva (vacío = se conserva).
 */
export default function DatosLaboralesForm({ trabajadorId, datos, permisos }) {
  const [f, setF] = useState(() => inicial(datos))
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const guardar = useGuardarDatosLaborales(trabajadorId, {
    exito: 'Datos laborales guardados.',
    alExito: () => setF((previo) => ({ ...previo, numero_cuenta: '', cci: '' })),
  })
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const verCuenta = permisos.ver_sueldos
  const editarCuenta = permisos.editar_sueldos
  const soloLectura = !permisos.editar

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || soloLectura) return
    const revision = revisar(f)
    setErrores(revision)
    setGeneral('')
    if (Object.keys(revision).length) return
    const cuerpo = {
      sexo: f.sexo,
      nacionalidad: f.nacionalidad.trim(),
      sistema_pension: f.sistema_pension,
      afp: f.sistema_pension === 'AFP' ? f.afp : '',
      tipo_comision: f.sistema_pension === 'AFP' ? f.tipo_comision : '',
      cuspp: f.sistema_pension === 'AFP' ? f.cuspp.trim().toUpperCase() : '',
      asignacion_familiar: f.asignacion_familiar,
      paga_renta_5ta: f.paga_renta_5ta,
      subsidio_descanso_medico: f.subsidio_descanso_medico,
      metodo_pago: f.metodo_pago,
    }
    // Banco y cuenta solo viajan si la persona puede cambiarlos.
    if (editarCuenta) {
      cuerpo.banco = f.banco
      if (f.numero_cuenta) cuerpo.numero_cuenta = f.numero_cuenta
      if (f.cci) cuerpo.cci = f.cci
    }
    guardar.mutate(cuerpo, {
      onError: (error) => {
        const delServidor = erroresDeCampo(error)
        setErrores(delServidor)
        setGeneral(Object.keys(delServidor).length > 0 && codigoDeError(error) === 'validacion' ? 'Revise los datos marcados.' : mensajeDeError(error))
      },
    })
  }

  return (
    <form onSubmit={enviar} noValidate className="rh-opciones">
      <fieldset disabled={guardar.isPending || soloLectura} className="rh-tarjeta">
        <header>
          <h3>Datos personales y pensión</h3>
        </header>
        <div className="rh-fila-campos">
          <Campo etiqueta="Sexo" tipo="select" error={errores.sexo}>
            {(p) => (
              <select {...p} value={f.sexo} onChange={(e) => poner('sexo', e.target.value)}>
                {SEXOS.map(([valor, texto]) => (
                  <option key={valor} value={valor}>
                    {texto}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Nacionalidad" requerido error={errores.nacionalidad}>
            {(p) => <input {...p} maxLength={40} value={f.nacionalidad} onChange={(e) => poner('nacionalidad', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Sistema de pensión" tipo="select" requerido error={errores.sistema_pension}>
            {(p) => (
              <select {...p} value={f.sistema_pension} onChange={(e) => poner('sistema_pension', e.target.value)}>
                {PENSIONES.map(([valor, texto]) => (
                  <option key={valor} value={valor}>
                    {texto}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        </div>
        {f.sistema_pension === 'AFP' && (
          <div className="rh-fila-campos">
            <Campo etiqueta="AFP" tipo="select" requerido error={errores.afp}>
              {(p) => (
                <select {...p} value={f.afp} onChange={(e) => poner('afp', e.target.value)}>
                  <option value="">Elegir AFP</option>
                  {AFPS.map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Tipo de comisión" tipo="select" requerido error={errores.tipo_comision}>
              {(p) => (
                <select {...p} value={f.tipo_comision} onChange={(e) => poner('tipo_comision', e.target.value)}>
                  {COMISIONES.map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="CUSPP" error={errores.cuspp} ayuda="12 letras y números. Sin él no se puede declarar en PLAME.">
              {(p) => <input {...p} maxLength={12} value={f.cuspp} onChange={(e) => poner('cuspp', e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))} />}
            </Campo>
          </div>
        )}
      </fieldset>

      <fieldset disabled={guardar.isPending || soloLectura} className="rh-tarjeta">
        <header>
          <h3>Opciones de este trabajador</h3>
        </header>
        <Interruptor activo={f.asignacion_familiar} onCambio={(v) => poner('asignacion_familiar', v)} texto="Cobra asignación familiar" descripcion="Tiene hijos que dan derecho a ella." />
        <Interruptor activo={f.paga_renta_5ta} onCambio={(v) => poner('paga_renta_5ta', v)} texto="Se le retiene renta de 5.ª categoría" descripcion="Su remuneración anual pasa de lo que se deduce de impuesto." />
        <Interruptor activo={f.subsidio_descanso_medico} onCambio={(v) => poner('subsidio_descanso_medico', v)} texto="Tiene subsidio por descanso médico" descripcion="EsSalud cubre sus descansos médicos largos: la planilla los trata aparte." />
      </fieldset>

      <fieldset disabled={guardar.isPending || soloLectura} className="rh-tarjeta">
        <header>
          <h3>Cómo se le paga</h3>
        </header>
        <Campo etiqueta="Medio de pago" tipo="select" error={errores.metodo_pago}>
          {(p) => (
            <select {...p} value={f.metodo_pago} onChange={(e) => poner('metodo_pago', e.target.value)}>
              {METODOS.map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
                </option>
              ))}
            </select>
          )}
        </Campo>
        {verCuenta && (
          <div className="rh-fila-campos">
            <Campo etiqueta="Banco" tipo="select" error={errores.banco}>
              {(p) => (
                <select {...p} disabled={!editarCuenta} value={f.banco} onChange={(e) => poner('banco', e.target.value)}>
                  <option value="">Elegir banco</option>
                  {BANCOS.map(([valor, texto]) => (
                    <option key={valor} value={valor}>
                      {texto}
                    </option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Número de cuenta" error={errores.numero_cuenta} ayuda={datos?.cuenta_puesta ? `Registrada, termina en ${datos.cuenta_final}. Escribe otra solo para cambiarla.` : 'Aún no tiene cuenta registrada.'}>
              {(p) => <input {...p} disabled={!editarCuenta} inputMode="numeric" autoComplete="off" maxLength={30} value={f.numero_cuenta} onChange={(e) => poner('numero_cuenta', e.target.value.replace(/[^0-9-]/g, ''))} />}
            </Campo>
            <Campo etiqueta="CCI" error={errores.cci} ayuda={datos?.cci_puesto ? `Registrado, termina en ${datos.cci_final}. Escribe otro solo para cambiarlo.` : '20 dígitos (opcional).'}>
              {(p) => <input {...p} disabled={!editarCuenta} inputMode="numeric" autoComplete="off" maxLength={20} value={f.cci} onChange={(e) => poner('cci', entero(e.target.value))} />}
            </Campo>
          </div>
        )}
        {!verCuenta && <p className="celda-suave">La cuenta bancaria solo la ven quienes tienen el permiso de sueldos.</p>}
      </fieldset>

      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      {!soloLectura && (
        <div className="rh-acciones">
          <button type="submit" className="boton-cabecera primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar datos laborales'}
          </button>
        </div>
      )}
    </form>
  )
}
