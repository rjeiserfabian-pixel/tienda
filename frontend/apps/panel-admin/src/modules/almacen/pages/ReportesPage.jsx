import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import FiltrosAntiguedad from '../components/FiltrosAntiguedad'
import SelectorProducto from '../components/SelectorProducto'
import VistaReporte from '../components/VistaReporte'
import { useOpciones } from '../hooks/useOpciones'
import { hoyIso } from '../inventario'
import { ATAJOS_FECHA, ATAJOS_RANGO, guardarPreferencias, leerPreferencias, REPORTES } from '../reportes'
import '../inventario.css'

/** Libros y reportes de inventario: se ven en pantalla y se descargan en Excel o PDF. */
export default function ReportesPage() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const notificar = useNotificar()
  const [tipo, setTipo] = useState(() => leerPreferencias(empresaActivaId).tipo)
  const [almacen, setAlmacen] = useState(() => leerPreferencias(empresaActivaId).almacen)
  const [producto, setProducto] = useState(null)
  const [rango, setRango] = useState(() => ATAJOS_RANGO[0].rango())
  const [fecha, setFecha] = useState(hoyIso())
  const [descargando, setDescargando] = useState(null) // 'xlsx' | 'pdf' mientras se genera
  const [errorDescarga, setErrorDescarga] = useState('')
  const [antiguedad, setAntiguedad] = useState({ categoria: '', marca: '', soloAntiguo: false })

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const reporte = REPORTES[tipo]
  const lista = almacenes.data ?? []
  // Un almacén recordado que ya no existe se descarta; el Kardex siempre necesita uno.
  const almacenValido = lista.some((a) => String(a.id) === almacen) ? almacen : ''
  const almacenElegido = almacenValido || (reporte.almacen === 'obligatorio' ? String(lista[0]?.id ?? '') : '')

  useEffect(() => {
    if (empresaActivaId && almacenes.isSuccess) guardarPreferencias(empresaActivaId, { tipo, almacen: almacenValido })
  }, [empresaActivaId, almacenes.isSuccess, tipo, almacenValido])

  // Lo que falta o está mal; vacío si ya se puede consultar.
  const pendiente = (() => {
    if (!empresaActivaId) return 'Elija una empresa.'
    if (reporte.producto && !producto?.id) return 'Elija un producto para ver el reporte.'
    if (reporte.almacen === 'obligatorio' && !almacenElegido) return 'Esta empresa aún no tiene almacenes.'
    if (reporte.periodo === 'rango') {
      if (!rango.desde || !rango.hasta) return 'Indique desde y hasta.'
      if (rango.desde > rango.hasta) return '«Desde» no puede ser posterior a «Hasta».'
      if (rango.hasta > hoyIso()) return '«Hasta» no puede ser una fecha futura.'
    } else if (reporte.periodo === 'fecha' && (!fecha || fecha > hoyIso())) return 'Elija una fecha que no sea futura.'
    return ''
  })()

  const params = {
    empresa: empresaActivaId,
    almacen: reporte.almacen ? almacenElegido : undefined,
    producto: reporte.producto ? producto?.id : undefined,
    ...(reporte.periodo === 'rango' ? rango : reporte.periodo === 'fecha' ? { fecha } : {}),
    ...(reporte.filtrosAntiguedad ? { categoria: antiguedad.categoria, marca: antiguedad.marca, solo_antiguo: antiguedad.soloAntiguo ? 'true' : undefined } : {}),
  }
  const limpios = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== undefined))

  const vista = useQuery({
    queryKey: ['reporte-vista', tipo, limpios],
    queryFn: ({ signal }) => api.get(`/inventario/reportes/${tipo}/vista/`, { params: limpios, signal }).then((r) => r.data),
    enabled: !pendiente,
    staleTime: 30_000,
    retry: false,
  })

  const descargar = async (formato) => {
    if (descargando || pendiente) return
    setErrorDescarga('')
    setDescargando(formato)
    try {
      const nombre = await descargarArchivo(`/inventario/reportes/${tipo}/`, { ...limpios, formato })
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (e) {
      setErrorDescarga(await mensajeDeErrorDescarga(e))
    } finally {
      setDescargando(null)
    }
  }

  const elegir = (nuevo) => {
    setTipo(nuevo)
    setErrorDescarga('')
  }
  const ocupado = Boolean(pendiente) || Boolean(descargando)

  return (
    <main className="listado">
      <CabeceraListado
        icono="exportar"
        titulo="Reportes de inventario"
        descripcion={`Libros y reportes de ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. Revísalos aquí y descárgalos para el contador. El costo es al promedio ponderado.`}
      />

      <div className="reportes-tarjetas" role="radiogroup" aria-label="Reporte">
        {Object.entries(REPORTES).map(([valor, r]) => (
          <button key={valor} type="button" role="radio" aria-checked={tipo === valor} className={`reporte-tarjeta${tipo === valor ? ' activa' : ''}`} onClick={() => elegir(valor)}>
            <Icono nombre={r.icono} tam={22} />
            <strong>{r.nombre}</strong>
            <span className="sub-texto">{r.formato}</span>
            <span className="reporte-ayuda">{r.ayuda}</span>
          </button>
        ))}
      </div>

      <div className="panel-reportes">
        <div className="fila-campos">
          {reporte.almacen && (
            <Campo etiqueta="Almacén" tipo="select">
              {(p) => (
                <select {...p} value={almacenElegido} onChange={(e) => setAlmacen(e.target.value)}>
                  {reporte.almacen === 'opcional' && <option value="">Todos los almacenes</option>}
                  {lista.map((a) => (
                    <option key={a.id} value={a.id}>{a.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
          )}
          {reporte.periodo === 'ninguno' ? null : reporte.periodo === 'rango' ? (
            <>
              <Campo etiqueta="Desde" icono="calendario">
                {(p) => <input {...p} type="date" max={hoyIso()} value={rango.desde} onChange={(e) => setRango((r) => ({ ...r, desde: e.target.value }))} />}
              </Campo>
              <Campo etiqueta="Hasta" icono="calendario">
                {(p) => <input {...p} type="date" max={hoyIso()} value={rango.hasta} onChange={(e) => setRango((r) => ({ ...r, hasta: e.target.value }))} />}
              </Campo>
            </>
          ) : (
            <Campo etiqueta="Al día" icono="calendario">
              {(p) => <input {...p} type="date" max={hoyIso()} value={fecha} onChange={(e) => setFecha(e.target.value)} />}
            </Campo>
          )}
        </div>
        {reporte.filtrosAntiguedad && (
          <FiltrosAntiguedad empresaId={empresaActivaId} filtros={antiguedad} alCambiar={(cambio) => setAntiguedad((a) => ({ ...a, ...cambio }))} />
        )}
        <div className="atajos" aria-label="Atajos de periodo" hidden={reporte.periodo === 'ninguno'}>
          {reporte.periodo === 'rango'
            ? ATAJOS_RANGO.map((a) => {
                const activo = a.rango().desde === rango.desde && a.rango().hasta === rango.hasta
                return (
                  <button key={a.id} type="button" className={`atajo${activo ? ' activo' : ''}`} aria-pressed={activo} onClick={() => setRango(a.rango())}>{a.texto}</button>
                )
              })
            : ATAJOS_FECHA.map((a) => {
                const activo = a.fecha() === fecha
                return (
                  <button key={a.id} type="button" className={`atajo${activo ? ' activo' : ''}`} aria-pressed={activo} onClick={() => setFecha(a.fecha())}>{a.texto}</button>
                )
              })}
        </div>
        {reporte.producto && <SelectorProducto valor={producto} onElegir={setProducto} />}

        <div className="acciones-reporte">
          <span className="celda-suave">{pendiente || 'El archivo trae el reporte completo, con todas las filas.'}</span>
          <button type="button" className="primario" disabled={ocupado} onClick={() => descargar('xlsx')}>
            <Icono nombre="exportar" tam={19} /> {descargando === 'xlsx' ? 'Generando…' : 'Excel'}
          </button>
          <button type="button" disabled={ocupado || reporte.soloExcel} title={reporte.soloExcel ? 'Este reporte solo existe en Excel' : undefined} onClick={() => descargar('pdf')}>
            <Icono nombre="documento" tam={19} /> {descargando === 'pdf' ? 'Generando…' : 'PDF'}
          </button>
        </div>
        {errorDescarga && <p role="alert" className="campo-error">{errorDescarga}</p>}
      </div>

      {pendiente ? <p className="estado-vacio">{pendiente}</p> : <VistaReporte consulta={vista} />}
    </main>
  )
}
