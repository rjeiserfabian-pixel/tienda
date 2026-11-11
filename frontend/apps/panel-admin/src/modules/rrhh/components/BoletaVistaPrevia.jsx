import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import VistaPreviaImpresion from '../../ventas/components/VistaPreviaImpresion'
import { mesAnio } from '../rrhh'
import BoletaA4 from './BoletaA4'

/** Trae la boleta (de la planilla, o la propia con `url`) y la muestra para imprimirla o guardarla como PDF. */
export default function BoletaVistaPrevia({ planilla, detalle, url, onCerrar }) {
  const direccion = url ?? `/rrhh/planillas/${planilla}/trabajadores/${detalle}/boleta/`
  const notificar = useNotificar()
  const consulta = useQuery({
    queryKey: ['planillas', 'boleta', direccion],
    queryFn: ({ signal }) => api.get(direccion, { signal }).then((r) => r.data),
    staleTime: 0,
    retry: 0,
  })
  useEffect(() => {
    if (!consulta.isError) return
    notificar('error', mensajeDeError(consulta.error))
    onCerrar()
  }, [consulta.isError, consulta.error, notificar, onCerrar])

  const b = consulta.data
  if (!b) return null
  return <VistaPreviaImpresion tipo="boleta" titulo={`Boleta de pago · ${mesAnio(b.periodo)}`} subtitulo={b.trabajador.nombre} formatos={{ A4: <BoletaA4 datos={b} /> }} onCerrar={onCerrar} />
}
