import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { hoyIso } from '../../almacen/inventario'
import { cuerpoGuiaTraslado, MAX_VEHICULOS_SECUNDARIOS, sumaPesosDe, validarGuiaTraslado } from '../ventas'
import { formularioInicial } from './useGuiaRemision'

/**
 * Todo lo que necesita la pantalla «Registrar guía de remisión» de un traspaso entre almacenes: el motivo, los
 * lugares, el transporte, los pesos, las validaciones y la emisión. `envio` es lo que devuelve
 * `/ventas/traspasos/{id}/envio/`. La guía lleva todo lo traspasado y no mueve stock.
 */
export function useGuiaTraslado(envio) {
  const navegar = useNavigate()
  const hoy = hoyIso()
  const lineas = envio.lineas
  const [f, setF] = useState(() => ({ ...formularioInicial(envio, hoy), motivo: envio.motivo }))
  const [pesos, setPesos] = useState({})
  const [serieElegida, setSerieElegida] = useState('')
  const [intento, setIntento] = useState(false)
  const [error, setError] = useState('')

  const serie = serieElegida || (envio.serie_sugerida ? String(envio.serie_sugerida) : '')
  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const errores = validarGuiaTraslado({ lineas, pesos, f, hoy, series: envio.series, serie })
  const cuerpo = errores.length === 0 ? cuerpoGuiaTraslado({ lineas, pesos, f, serie }) : null
  const clave = useClaveIdempotente(cuerpo)
  const emitir = useMutacion({
    mutationFn: ({ datos, llave }) => api.post(`/ventas/traspasos/${envio.movimiento}/guia-remision/`, datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas'], ['movimientos']],
    exito: (g) => `Guía ${g.numero_completo} emitida.`,
    alExito: () => navegar('/ventas/guias-remision'),
    avisarError: false,
  })

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
    pesos,
    ponerPeso: (id, valor) => setPesos((previo) => ({ ...previo, [id]: valor.replace(',', '.') })),
    pesoSugerido: sumaPesosDe(lineas, pesos),
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
