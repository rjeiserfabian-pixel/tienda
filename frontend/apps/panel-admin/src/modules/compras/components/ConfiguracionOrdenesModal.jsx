import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'

function Formulario({ empresaId, actual, onCerrar }) {
  const [monto, setMonto] = useState(actual.monto_aprobacion ?? '')
  const [tolerancia, setTolerancia] = useState(String(Number(actual.tolerancia)))
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const guardar = useMutacion({
    mutationFn: (datos) => api.patch('/compras/ordenes/configuracion/', datos).then((r) => r.data),
    invalidar: [['compras', 'ordenes']],
    exito: 'Configuración guardada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const e = {}
    const m = aNumero(monto)
    if (String(monto).trim() !== '' && (m === null || m < 0 || !/^\d+([.,]\d{1,2})?$/.test(String(monto).trim()))) e.monto = 'Un monto en soles, con hasta 2 decimales (o déjalo vacío).'
    const t = aNumero(tolerancia)
    if (t === null || t < 0 || t > 100 || !/^\d+([.,]\d{1,2})?$/.test(String(tolerancia).trim())) e.tolerancia = 'De 0 a 100, con hasta 2 decimales.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    guardar.mutate(
      { empresa: empresaId, monto_aprobacion: String(monto).trim() === '' ? null : paraServidor(monto), tolerancia: paraServidor(tolerancia) },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores({ monto: delServidor.monto_aprobacion, tolerancia: delServidor.tolerancia })
          setGeneral(Object.keys(delServidor).length ? '' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <form onSubmit={enviar} noValidate>
      <Campo etiqueta="Pedir aprobación desde (S/)" error={errores.monto} ayuda="Una orden que pase de este monto, en soles, la aprueba un administrador antes de emitirse. Vacío = nunca pide aprobación.">
        {(p) => <input {...p} inputMode="decimal" placeholder="Sin límite" value={monto} disabled={guardar.isPending} onChange={(e) => setMonto(e.target.value)} />}
      </Campo>
      <Campo etiqueta="Tolerancia al recibir (%)" error={errores.tolerancia} ayuda="Cuánto más de lo pedido se puede recibir. 0 = nada más que lo pedido.">
        {(p) => <input {...p} inputMode="decimal" value={tolerancia} disabled={guardar.isPending} onChange={(e) => setTolerancia(e.target.value)} />}
      </Campo>
      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
          Cancelar
        </button>
        <button type="submit" className="primario" disabled={guardar.isPending}>
          {guardar.isPending ? 'Guardando…' : 'Guardar'}
        </button>
      </div>
    </form>
  )
}

/** Desde qué monto una orden pide aprobación y cuánto más se puede recibir de lo pedido (por empresa). */
export default function ConfiguracionOrdenesModal({ empresaId, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['compras', 'ordenes', 'configuracion', empresaId],
    queryFn: ({ signal }) => api.get('/compras/ordenes/configuracion/', { params: { empresa: empresaId }, signal }).then((r) => r.data),
    staleTime: 0,
  })
  return (
    <Modal titulo="Configuración de órdenes de compra" subtitulo="Vale para la empresa activa" onCerrar={onCerrar} ancho={560}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {consulta.data && <Formulario empresaId={empresaId} actual={consulta.data} onCerrar={onCerrar} />}
      </EstadoConsulta>
    </Modal>
  )
}
