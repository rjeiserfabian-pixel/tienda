// Formato de fecha y hora uniforme en todo el panel: 27/10/2026 03:59 p. m.
const FECHA_HORA = new Intl.DateTimeFormat('es-PE', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
})

export function fechaHora(iso, vacio = '—') {
  if (!iso) return vacio
  const fecha = new Date(iso)
  return Number.isNaN(fecha.getTime()) ? vacio : FECHA_HORA.format(fecha).replace(',', '')
}
