import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { cantidadesDeMotivo, cobrosSugeridos, cuerpoNota, lineasDevueltas, MOTIVOS_TOTALES, seriesDeMotivo, validarNota } from '../ventas'

const VACIO = []

/** ¿Cada línea elegida lleva todas las series que vuelven? (sin eso el servidor no puede calcular la nota) */
const seriesCompletas = (lineas, cantidades, series) => lineas.every((l) => !l.lleva_serie || !(Number(cantidades[l.id]) > 0) || (series[l.id] ?? []).length === Number(cantidades[l.id]))

/**
 * Todo lo que necesita la pantalla «Emitir nota de crédito» de un comprobante: lo que se elige, el
 * cálculo del servidor (importes, a deudas, a reembolsar), el reembolso prellenado por los métodos con
 * que pagó el cliente, las validaciones y la emisión. `pendiente` es lo que devuelve
 * `/ventas/comprobantes/{id}/devolucion/`.
 */
export function useNotaCredito(pendiente, medios) {
  const navegar = useNavigate()
  const lineas = pendiente.lineas ?? VACIO
  const moneda = pendiente.moneda
  const anulacionLibre = pendiente.motivos.some((m) => m.codigo === '01' && m.disponible)
  const [motivo, setMotivo] = useState(anulacionLibre ? '01' : '06')
  const [escritas, setEscritas] = useState({})
  const [elegidas, setElegidas] = useState({})
  const [serieElegida, setSerieElegida] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [reingresa, setReingresa] = useState(true)
  const [editados, setEditados] = useState(null) // el reembolso, una vez que la persona lo cambia
  const [intento, setIntento] = useState(false)
  const [error, setError] = useState('')

  const cantidades = cantidadesDeMotivo(motivo, lineas, escritas)
  const series = seriesDeMotivo(motivo, lineas, elegidas)
  const serie = serieElegida || (pendiente.serie_sugerida ? String(pendiente.serie_sugerida) : '')

  // --- El cálculo del servidor, sin guardar nada ---
  const listo = lineasDevueltas(lineas, cantidades, series).length > 0 && seriesCompletas(lineas, cantidades, series)
  const cuerpoCalculo = listo ? cuerpoNota({ lineas, cantidades, series, cobros: [], reingresa, descripcion: '', motivo }) : null
  const demorado = useDebounce(cuerpoCalculo, 300)
  const calculo = useQuery({
    queryKey: ['ventas', 'nota-previa', pendiente.comprobante, demorado],
    queryFn: ({ signal }) => api.post(`/ventas/comprobantes/${pendiente.comprobante}/nota-credito/previsualizar/`, demorado, { signal }).then((r) => r.data),
    enabled: Boolean(demorado),
    retry: false,
    staleTime: 0,
    placeholderData: (previo) => previo,
  })
  const calculando = listo && (JSON.stringify(demorado) !== JSON.stringify(cuerpoCalculo) || calculo.isFetching)
  const errorDeCalculo = listo && calculo.isError ? mensajeDeError(calculo.error) : ''
  const datos = listo && !errorDeCalculo && !calculando ? calculo.data : undefined
  const totalCts = datos ? Math.round(Number(datos.total) * 100) : 0
  const aReembolsarCts = datos ? Math.round(Number(datos.a_reembolsar) * 100) : 0
  const aCuotas = datos ? Number(datos.a_cuotas) : 0
  const importes = useMemo(() => new Map((datos?.lineas ?? VACIO).map((l) => [l.linea, Number(l.total)])), [datos])

  // --- El reembolso: lo que propone el servidor, hasta que la persona lo cambia ---
  const medioPorOmision = medios.find((m) => m.tipo === 'EFECTIVO') ?? medios[0]
  const sugeridos = useMemo(() => (datos ? cobrosSugeridos(datos.reembolso_sugerido, datos.reembolso_sin_asignar, medioPorOmision?.id) : VACIO), [datos, medioPorOmision])
  const cobros = editados ?? sugeridos

  const errores = validarNota({ lineas, cantidades, series, cobros, medios, aReembolsarCts })
  if (!pendiente.se_puede_devolver) errores.unshift('Este comprobante ya no admite notas de crédito.')
  if (pendiente.series.length === 0) errores.push('No hay una serie de nota de crédito para este comprobante: créala en Mantenimiento → Series de comprobantes.')
  else if (!serie) errores.push('Elige la serie de la nota.')
  if (!descripcion.trim()) errores.push('Escribe el sustento de la nota.')
  const cuerpo = errores.length === 0 && datos ? cuerpoNota({ lineas, cantidades, series, cobros, reingresa, descripcion, motivo, serie }) : null
  const clave = useClaveIdempotente(cuerpo)
  const emitir = useMutacion({
    mutationFn: ({ datos: d, llave }) => api.post(`/ventas/comprobantes/${pendiente.comprobante}/nota-credito/`, d, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['ventas'], ['caja'], ['almacen'], ['inventario'], ['stock']],
    exito: (n) => `Nota de crédito ${n.numero_completo} emitida.`,
    alExito: () => navegar('/ventas/notas-credito'),
    avisarError: false,
  })

  // Cambiar lo que se devuelve cambia el dinero: el reembolso vuelve a proponerse.
  const cambiarMotivo = (nuevo) => {
    setMotivo(nuevo)
    setEditados(null)
  }
  const escribirCantidad = (id, valor) => {
    setEscritas((previo) => ({ ...previo, [id]: valor }))
    setEditados(null)
  }
  const elegirSeries = (id, valor) => {
    setElegidas((previo) => ({ ...previo, [id]: valor }))
    setEditados(null)
  }
  const enviar = (evento) => {
    evento.preventDefault()
    if (emitir.isPending) return
    setIntento(true)
    setError('')
    if (!cuerpo) return
    emitir.mutate({ datos: cuerpo, llave: clave }, { onError: (e) => setError(Object.keys(erroresDeCampo(e)).length ? 'Revisa los datos de la nota.' : mensajeDeError(e)) })
  }

  return {
    moneda,
    motivo,
    esTotal: MOTIVOS_TOTALES.includes(motivo),
    cantidades,
    series,
    serie,
    descripcion,
    reingresa,
    cobros,
    datos,
    importes,
    totalCts,
    aReembolsarCts,
    aCuotas,
    calculando,
    errorDeCalculo,
    errores,
    intento,
    error,
    enviando: emitir.isPending,
    puedeEnviar: !emitir.isPending && !calculando && totalCts > 0,
    cambiarMotivo,
    escribirCantidad,
    elegirSeries,
    setSerieElegida,
    setDescripcion,
    setReingresa,
    setCobros: setEditados,
    enviar,
  }
}
