import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { hoyIso } from '../../almacen/inventario'
import { cuerpoGuia, MAX_VEHICULOS_SECUNDARIOS, sumaPesos, validarGuia } from '../ventas'

export const formularioInicial = (envio, hoy) => ({
  motivo: '01',
  modalidad: '02', // transporte privado: lo lleva la propia empresa
  m1l: false,
  fechaTraslado: hoy,
  partida: envio.punto_partida ?? '',
  ubigeoPartida: envio.ubigeo_partida?.codigo ?? '',
  llegada: envio.punto_llegada ?? '',
  ubigeoLlegada: envio.ubigeo_llegada?.codigo ?? '',
  transportista: '',
  conductor: '',
  vehiculo: '',
  secundarios: [],
  conductorEnPublico: false,
  bultos: '1',
  pesoEscrito: '',
  observacion: '',
})

/**
 * Todo lo que necesita la pantalla «Registrar guía de remisión» de un comprobante: lo que se elige, los
 * pesos, el transporte, el destinatario, las validaciones y la emisión. `envio` es lo que devuelve
 * `/ventas/comprobantes/{id}/envio/`.
 */
export function useGuiaRemision(envio) {
  const navegar = useNavigate()
  const hoy = hoyIso()
  const lineas = envio.lineas
  const [f, setF] = useState(() => formularioInicial(envio, hoy))
  const [cantidades, setCantidades] = useState(() => Object.fromEntries(lineas.filter((l) => Number(l.pendiente) > 0).map((l) => [l.id, String(Number(l.pendiente))])))
  const [pesos, setPesos] = useState({})
  const [destinatario, setDestinatario] = useState(null) // otro cliente; null = el de la venta
  const [serieElegida, setSerieElegida] = useState('')
  const [intento, setIntento] = useState(false)
  const [error, setError] = useState('')

  const serie = serieElegida || (envio.serie_sugerida ? String(envio.serie_sugerida) : '')
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const errores = validarGuia({ lineas, cantidades, pesos, f, hoy, series: envio.series, serie })
  const cuerpo = errores.length === 0 ? cuerpoGuia({ lineas, cantidades, pesos, f, destinatario, serie }) : null
  const clave = useClaveIdempotente(cuerpo)
  const emitir = useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`/ventas/comprobantes/${envio.comprobante}/guia-remision/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas']],
    exito: (g) => `Guía ${g.numero_completo} emitida.`,
    alExito: () => navegar('/ventas/guias-remision'),
    avisarError: false,
  })

  // Al cambiar de destinatario, la llegada se propone con la dirección y el distrito de ese cliente.
  const elegirDestinatario = (cliente) => {
    setDestinatario(cliente)
    setF((previo) => ({
      ...previo,
      llegada: cliente ? (cliente.direccion ?? '') : (envio.punto_llegada ?? ''),
      ubigeoLlegada: cliente ? (cliente.ubigeo ?? '') : (envio.ubigeo_llegada?.codigo ?? ''),
    }))
  }
  const agregarSecundario = (id) => setF((previo) => (previo.secundarios.includes(id) || previo.secundarios.length >= MAX_VEHICULOS_SECUNDARIOS ? previo : { ...previo, secundarios: [...previo.secundarios, id] }))
  const quitarSecundario = (id) => setF((previo) => ({ ...previo, secundarios: previo.secundarios.filter((x) => x !== id) }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (emitir.isPending) return
    setIntento(true)
    setError('')
    if (!cuerpo) return
    emitir.mutate({ datos: cuerpo, llave: clave }, { onError: (e) => setError(Object.keys(erroresDeCampo(e)).length ? 'Revisa los datos de la guía.' : mensajeDeError(e)) })
  }

  return {
    f,
    poner,
    cantidades,
    pesos,
    ponerCantidad: (id, valor) => setCantidades((previo) => ({ ...previo, [id]: valor.replace(',', '.') })),
    ponerPeso: (id, valor) => setPesos((previo) => ({ ...previo, [id]: valor.replace(',', '.') })),
    quitarLinea: (id) => setCantidades((previo) => ({ ...previo, [id]: '' })),
    pesoSugerido: sumaPesos(lineas, cantidades, pesos),
    destinatario,
    elegirDestinatario,
    serie,
    setSerieElegida,
    agregarSecundario,
    quitarSecundario,
    errores,
    intento,
    error,
    enviando: emitir.isPending,
    enviar,
  }
}
