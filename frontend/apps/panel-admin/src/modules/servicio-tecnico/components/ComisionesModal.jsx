import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const aNumero = (texto) => Number(String(texto).replace(',', '.'))
const valido = (n) => Number.isFinite(n) && n >= 0 && n <= 100

/** El porcentaje general: lo que gana todo técnico que no tiene uno propio. */
function General({ empresa, valorActual }) {
  const [valor, setValor] = useState(String(Number(valorActual)))
  const [error, setError] = useState('')
  const guardar = useMutacion({
    mutationFn: (porcentaje) => api.put('/servicio-tecnico/comisiones/por-defecto/', { porcentaje }, { params: { empresa } }).then((r) => r.data),
    invalidar: [['servicio']],
    exito: 'Porcentaje general guardado.',
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const numero = aNumero(valor)
    if (!valido(numero)) return setError('Use un porcentaje de 0 a 100.')
    setError('')
    guardar.mutate(numero.toFixed(2), { onError: (e) => setError(mensajeDeError(e)) })
  }
  return (
    <form onSubmit={enviar} noValidate className="servicio-comision">
      <strong>Porcentaje general</strong>
      <input inputMode="decimal" aria-label="Porcentaje general de los técnicos" value={valor} disabled={guardar.isPending} onChange={(e) => setValor(e.target.value)} />
      <span>%</span>
      <button type="submit" className="boton-cabecera" disabled={guardar.isPending}>
        {guardar.isPending ? 'Guardando…' : 'Guardar'}
      </button>
      {error && (
        <span role="alert" className="campo-error">
          {error}
        </span>
      )}
    </form>
  )
}

/** Una fila: el técnico y su porcentaje (el suyo o el general). */
function Fila({ empresa, tecnico }) {
  const [valor, setValor] = useState(String(Number(tecnico.porcentaje)))
  const [error, setError] = useState('')
  const guardar = useMutacion({
    mutationFn: (porcentaje) => api.put(`/servicio-tecnico/comisiones/${tecnico.id}/`, { porcentaje }, { params: { empresa } }).then((r) => r.data),
    invalidar: [['servicio']],
    exito: `Comisión de ${tecnico.nombre} guardada.`,
    avisarError: false,
  })
  const quitar = useMutacion({
    mutationFn: () => api.delete(`/servicio-tecnico/comisiones/${tecnico.id}/`, { params: { empresa } }).then((r) => r.data),
    invalidar: [['servicio']],
    exito: `${tecnico.nombre} vuelve a usar el porcentaje general.`,
    avisarError: false,
  })
  const ocupado = guardar.isPending || quitar.isPending
  const enviar = (evento) => {
    evento.preventDefault()
    if (ocupado) return
    const numero = aNumero(valor)
    if (!valido(numero)) return setError('Use un porcentaje de 0 a 100.')
    setError('')
    guardar.mutate(numero.toFixed(2), { onError: (e) => setError(mensajeDeError(e)) })
  }
  return (
    <li>
      <form onSubmit={enviar} noValidate className="servicio-comision">
        <strong>{tecnico.nombre}</strong>
        <input inputMode="decimal" aria-label={`Porcentaje de ${tecnico.nombre}`} value={valor} disabled={ocupado} onChange={(e) => setValor(e.target.value)} />
        <span>%</span>
        <button type="submit" className="boton-cabecera" disabled={ocupado}>
          {guardar.isPending ? 'Guardando…' : 'Guardar'}
        </button>
        {tecnico.propio ? (
          <button type="button" className="boton-cabecera" disabled={ocupado} onClick={() => quitar.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)) })}>
            Usar el general
          </button>
        ) : (
          <small className="celda-suave">usa el general</small>
        )}
        {error && (
          <span role="alert" className="campo-error">
            {error}
          </span>
        )}
      </form>
    </li>
  )
}

/** El porcentaje de comisión de cada técnico sobre la mano de obra cobrada. Vale para las entregas desde ahora. */
export default function ComisionesModal({ empresa, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['servicio', 'comisiones', empresa],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/comisiones/', { params: { empresa }, signal }).then((r) => r.data),
  })
  const tecnicos = consulta.data?.tecnicos ?? []
  return (
    <Modal titulo="Comisiones de los técnicos" subtitulo="Porcentaje sobre la mano de obra cobrada, sin IGV" onCerrar={onCerrar} ancho={620}>
      <p className="celda-suave">
        Cada técnico gana el porcentaje general, salvo que le pongas uno propio. El cambio se aplica a las órdenes que se entreguen desde ahora; las ya entregadas conservan el que tenían ese día. Los repuestos no comisionan.
      </p>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {consulta.data && <General key={consulta.data.por_defecto} empresa={empresa} valorActual={consulta.data.por_defecto} />}
        {tecnicos.length === 0 ? (
          <p className="estado-vacio">No hay personal del área técnica en esta empresa.</p>
        ) : (
          <ul className="servicio-comisiones">
            {tecnicos.map((t) => (
              <Fila key={`${t.id}-${t.porcentaje}-${t.propio}`} empresa={empresa} tecnico={t} />
            ))}
          </ul>
        )}
      </EstadoConsulta>
      <div className="modal-pie">
        <button type="button" className="primario" onClick={onCerrar}>
          Listo
        </button>
      </div>
    </Modal>
  )
}
