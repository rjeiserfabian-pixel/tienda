import { useState } from 'react'
import Can from '../../../shared/components/Can'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { hoyIso } from '../../almacen/inventario'
import { ATAJOS_RANGO } from '../../almacen/reportes'
import { dinero } from '../caja'

/** Botón que descarga un archivo del servidor y avisa si algo falla. */
export function BotonDescarga({ url, params, texto, deshabilitado, primario = false, onError }) {
  const notificar = useNotificar()
  const [descargando, setDescargando] = useState(false)
  const bajar = async () => {
    if (descargando) return
    onError('')
    setDescargando(true)
    try {
      const nombre = await descargarArchivo(url, params)
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (e) {
      onError(await mensajeDeErrorDescarga(e))
    } finally {
      setDescargando(false)
    }
  }
  return (
    <button type="button" className={`${primario ? 'primario ' : ''}boton-cabecera`} disabled={descargando || deshabilitado} onClick={bajar}>
      <Icono nombre="exportar" tam={18} /> {descargando ? 'Generando…' : texto}
    </button>
  )
}

export function Descargas({ children, error, permiso = 'CAJA.REPORTES.EXPORTAR' }) {
  return (
    <>
      <div className="acciones-reporte">
        <Can permiso={permiso}>{children}</Can>
      </div>
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
    </>
  )
}

export function Rango({ rango, setRango }) {
  return (
    <>
      <div className="fila-campos">
        <Campo etiqueta="Desde" icono="calendario">
          {(p) => <input {...p} type="date" max={hoyIso()} value={rango.desde} onChange={(e) => setRango((r) => ({ ...r, desde: e.target.value }))} />}
        </Campo>
        <Campo etiqueta="Hasta" icono="calendario">
          {(p) => <input {...p} type="date" max={hoyIso()} value={rango.hasta} onChange={(e) => setRango((r) => ({ ...r, hasta: e.target.value }))} />}
        </Campo>
      </div>
      <div className="atajos" aria-label="Atajos de periodo">
        {ATAJOS_RANGO.map((a) => {
          const activo = a.rango().desde === rango.desde && a.rango().hasta === rango.hasta
          return (
            <button key={a.id} type="button" className={`atajo${activo ? ' activo' : ''}`} aria-pressed={activo} onClick={() => setRango(a.rango())}>
              {a.texto}
            </button>
          )
        })}
      </div>
    </>
  )
}

export function Tarjetas({ titulo, filas, clave = 'saldo', etiqueta }) {
  if (!filas?.length) return null
  return (
    <dl className="cxp-tarjetas" aria-label={titulo}>
      {filas.map((t) => (
        <div key={`${t.moneda}-${t.tipo ?? ''}`} data-tono={Number(t[clave]) < 0 ? 'rojo' : undefined}>
          <dt>{etiqueta ? etiqueta(t) : titulo}</dt>
          <dd>{dinero(t[clave], t.moneda)}</dd>
          <small>{t.moneda === 'USD' ? 'Dólares' : 'Soles'}</small>
        </div>
      ))}
    </dl>
  )
}
