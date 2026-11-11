import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { conteoParaEnviar, dinero, resultadoDeConteo, totalContado, validarConteo } from '../caja'
import ConteoEfectivo from './ConteoEfectivo'

const TEXTOS = {
  arquear: { titulo: 'Contar el efectivo', boton: 'Guardar el conteo', ocupado: 'Guardando…', ayuda: 'Cuenta lo que hay en la caja. No se cierra: sirve para revisar en mitad del turno.' },
  cerrar: { titulo: 'Cerrar la caja', boton: 'Cerrar la sesión', ocupado: 'Cerrando…', ayuda: 'Cuenta todo el efectivo. Lo que sobre o falte queda registrado y la caja se cierra: no admite más movimientos hasta abrir otra sesión.' },
}

/** Cuenta el efectivo de una sesión abierta (por billetes y monedas) para arquear o para cerrar la caja. */
export default function ContarSesionModal({ sesionId, modo, onCerrar }) {
  const textos = TEXTOS[modo]
  const [conteo, setConteo] = useState({})
  const [observacion, setObservacion] = useState('')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const [juntas, setJuntas] = useState(true)
  // Al cerrar, si las empresas se deben algo por ventas internas, se liquida primero (lo confirma quien cierra).
  const [porLiquidar, setPorLiquidar] = useState('')

  const detalle = useQuery({
    queryKey: ['caja', 'sesion', sesionId],
    queryFn: ({ signal }) => api.get(`/caja/sesiones/${sesionId}/`, { signal }).then((r) => r.data),
    staleTime: 0,
  })
  const sesion = detalle.data
  // Si otra empresa usa el mismo cajón, se cuenta una sola vez contra la suma de todas sus cajas.
  const compartido = sesion?.mostrador && juntas ? sesion.mostrador : null
  const esperado = compartido ? compartido.esperado_total : sesion?.esperado_actual

  const contar = useMutacion({
    mutationFn: (datos) => api.post(`/caja/sesiones/${sesionId}/${modo === 'cerrar' ? 'cerrar' : 'arquear'}/`, datos, { timeout: 30_000 }).then((r) => r.data),
    invalidar: [['caja']],
    exito: (r) => {
      // Con el cajón compartido la respuesta trae la parte de esta caja: el resultado es el del total.
      const diferencia = compartido ? Number(resultadoDeConteo(totalContado(conteo), esperado).diferencia) : Number(r.diferencia)
      const detalleDiferencia = diferencia === 0 ? 'cuadra' : diferencia > 0 ? `sobra ${dinero(diferencia, sesion.moneda)}` : `falta ${dinero(-diferencia, sesion.moneda)}`
      return modo === 'cerrar' ? `Caja cerrada: ${detalleDiferencia}.` : `Conteo guardado: ${detalleDiferencia}.`
    },
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (contar.isPending || !sesion) return
    const malo = validarConteo(conteo)
    const e = {}
    if (malo) e.conteo = malo
    const resultado = resultadoDeConteo(totalContado(conteo), esperado)
    if (modo === 'cerrar' && resultado.tipo !== 'cuadra' && !observacion.trim()) e.observacion = 'Explique la diferencia.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    contar.mutate(
      { conteo: conteoParaEnviar(conteo), ...(compartido ? { mostrador: true } : {}), ...(porLiquidar ? { liquidar_interna: true } : {}), ...(observacion.trim() ? { observacion: observacion.trim() } : {}) },
      {
        onError: (error) => {
          if (codigoDeError(error) === 'liquidacion_interna_pendiente' && !porLiquidar) {
            setPorLiquidar(mensajeDeError(error))
            setGeneral('')
            return
          }
          const campos = erroresDeCampo(error)
          setErrores({ conteo: campos.conteo, observacion: campos.observacion })
          setGeneral(Object.keys(campos).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  const hayDiferencia = sesion && resultadoDeConteo(totalContado(conteo), esperado).tipo !== 'cuadra'
  return (
    <Modal titulo={textos.titulo} subtitulo={sesion ? `${sesion.cuenta_nombre} · sesión ${String(sesion.numero).padStart(6, '0')} de ${sesion.responsable_nombre}` : undefined} onCerrar={onCerrar} ancho={760}>
      <EstadoConsulta consulta={detalle} hayDatos={Boolean(sesion)}>
        {sesion && (
          <form onSubmit={enviar} noValidate>
            <fieldset disabled={contar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
              <p className="celda-suave">{textos.ayuda}</p>
              {sesion.mostrador && (
                <div className="caja-compartida">
                  <label>
                    <input type="checkbox" checked={juntas} onChange={(e) => setJuntas(e.target.checked)} />
                    <span>
                      <strong>Este mostrador lo comparten varias empresas.</strong> Contar el cajón una sola vez y {modo === 'cerrar' ? 'cerrar todas las cajas juntas' : 'revisar todas las cajas juntas'}.
                    </span>
                  </label>
                  {juntas && (
                    <ul>
                      <li>
                        {sesion.cuenta_nombre}: espera {dinero(sesion.esperado_actual, sesion.moneda)}
                      </li>
                      {sesion.mostrador.hermanas.map((h) => (
                        <li key={h.sesion}>
                          {h.cuenta_nombre} ({h.empresa_nombre}): espera {dinero(h.esperado, sesion.moneda)}
                        </li>
                      ))}
                      <li>
                        <strong>En el cajón debe haber {dinero(sesion.mostrador.esperado_total, sesion.moneda)}.</strong> Si sobra o falta, se reparte entre las cajas según lo que esperaba cada una.
                      </li>
                    </ul>
                  )}
                </div>
              )}
              <ConteoEfectivo moneda={sesion.moneda} conteo={conteo} onCambio={setConteo} esperado={esperado} error={errores.conteo} />
              <Campo etiqueta={modo === 'cerrar' && hayDiferencia ? 'Explique la diferencia' : 'Observación'} requerido={modo === 'cerrar' && hayDiferencia} error={errores.observacion} contador={{ actual: observacion.length, max: 250 }}>
                {(p) => <input {...p} maxLength={250} placeholder={hayDiferencia ? 'Ej. Vuelto mal dado a un cliente' : 'Opcional'} value={observacion} onChange={(e) => setObservacion(e.target.value)} />}
              </Campo>
            </fieldset>
            {porLiquidar && (
              <p className="compra-aviso" role="status">
                {porLiquidar} Al confirmar, primero se liquida lo que se deben las empresas (al costo, con un asiento entre sus cajas) y enseguida se cierra la caja; si algo falla, no queda nada a medias.
              </p>
            )}
            {general && (
              <p role="alert" className="campo-error">
                {general}
              </p>
            )}
            <div className="modal-pie">
              <button type="button" onClick={onCerrar} disabled={contar.isPending}>
                Cancelar
              </button>
              <button type="submit" className="primario" disabled={contar.isPending}>
                {contar.isPending ? textos.ocupado : porLiquidar ? 'Liquidar y cerrar' : textos.boton}
              </button>
            </div>
          </form>
        )}
      </EstadoConsulta>
    </Modal>
  )
}
