'use client'

import { useEffect, useState } from 'react'
import { llamar } from '@/lib/cliente'

/**
 * Reloj de la tienda para las cuentas regresivas.
 *
 * El reloj del celular o la laptop del cliente puede estar adelantado o atrasado; si se usara tal
 * cual, una oferta parecería terminar antes o después de lo real. Por eso se pide UNA vez la hora al
 * servidor (sin caché) y se guarda la diferencia con el reloj del equipo. Todas las cuentas
 * regresivas de la página comparten esa diferencia y un solo temporizador.
 */
let desfase = 0 // servidor − navegador, en milisegundos
let sincronizado = false
let pidiendo = null
const oyentes = new Set()
let intervalo = null

export const ahora = () => Date.now() + desfase

function sincronizar() {
  if (sincronizado || pidiendo) return
  const inicio = Date.now()
  pidiendo = llamar('hora')
    .then((datos) => {
      const servidor = Date.parse(datos?.ahora)
      if (Number.isFinite(servidor)) {
        // se descuenta la mitad de lo que tardó la respuesta
        desfase = servidor - (inicio + (Date.now() - inicio) / 2)
        sincronizado = true
        oyentes.forEach((f) => f(ahora()))
      }
    })
    .catch(() => {
      // sin conexión: se sigue con el reloj del equipo
    })
    .finally(() => {
      pidiendo = null
    })
}

function suscribir(f) {
  oyentes.add(f)
  if (!intervalo) intervalo = setInterval(() => oyentes.forEach((o) => o(ahora())), 1000)
  return () => {
    oyentes.delete(f)
    if (oyentes.size === 0 && intervalo) {
      clearInterval(intervalo)
      intervalo = null
    }
  }
}

/** La hora corregida, actualizada cada segundo. `null` hasta que la página está lista (evita saltos). */
export function useAhora() {
  const [valor, setValor] = useState(null)
  useEffect(() => {
    sincronizar()
    setValor(ahora())
    return suscribir(setValor)
  }, [])
  return valor
}

/** Desglosa los milisegundos que faltan en días, horas, minutos y segundos. */
export function desglosar(faltan) {
  const total = Math.max(0, Math.floor(faltan / 1000))
  return {
    dias: Math.floor(total / 86400),
    horas: Math.floor((total % 86400) / 3600),
    minutos: Math.floor((total % 3600) / 60),
    segundos: total % 60,
    total,
  }
}
