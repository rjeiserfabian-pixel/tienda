import { useRef, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { fechaCorta } from '../../almacen/inventario'
import { MAX_BYTES_EXCEL, precioUnitario } from '../cotizaciones'

const ESTADO_FILA = {
  ok: { texto: 'Cotiza', tono: 'verde' },
  sin_precio: { texto: 'No cotiza', tono: 'gris' },
  error: { texto: 'Error', tono: 'rojo' },
}

/** Lo que traería el archivo, fila por fila, y las condiciones leídas de su encabezado. */
function Informe({ informe, moneda }) {
  const c = informe.condiciones ?? {}
  const condiciones = [
    c.forma_pago && ['Forma de pago', c.forma_pago === 'CREDITO' ? `Crédito${c.plazo_dias ? ` a ${c.plazo_dias} días` : ''}` : 'Contado'],
    c.plazo_entrega_dias !== undefined && ['Entrega', `${c.plazo_entrega_dias} días`],
    c.validez_hasta && ['Precios válidos hasta', fechaCorta(c.validez_hasta)],
    c.observacion && ['Observación', c.observacion],
  ].filter(Boolean)
  return (
    <>
      <p aria-live="polite">
        <strong>{informe.cotizados}</strong> con precio · <strong>{informe.sin_precio}</strong> sin precio · <strong>{informe.errores}</strong> con error
        {informe.filas_total > informe.filas.length ? ` (se muestran ${informe.filas.length} de ${informe.filas_total} filas)` : ''}
      </p>
      {condiciones.length > 0 && (
        <dl className="datos-lista">
          {condiciones.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {informe.problemas.length > 0 && (
        <ul className="compra-faltan" role="alert">
          {informe.problemas.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <div className="marco-tabla compra-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th className="centrado">Fila</th>
              <th className="centrado">N°</th>
              <th>Producto</th>
              <th className="num">Precio</th>
              <th className="num">Ofrece</th>
              <th>Resultado</th>
            </tr>
          </thead>
          <tbody>
            {informe.filas.map((f) => (
              <tr key={f.fila} className={f.estado === 'error' ? 'anulado' : undefined}>
                <td className="centrado celda-suave">{f.fila}</td>
                <td className="centrado">{f.posicion ?? '—'}</td>
                <td className="col-texto">{f.producto || '—'}</td>
                <td className="num">{f.precio === null ? '—' : precioUnitario(f.precio, moneda)}</td>
                <td className="num">{f.cantidad_ofrecida ?? '—'}</td>
                <td>
                  <span className="pildora" data-tono={ESTADO_FILA[f.estado]?.tono ?? 'gris'}>
                    {ESTADO_FILA[f.estado]?.texto ?? f.estado}
                  </span>
                  {f.mensaje && <span className="sub-texto">{f.mensaje}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

/**
 * Importar la respuesta de un proveedor desde el Excel de la plantilla, en dos pasos: «revisar»
 * informa fila por fila sin guardar nada y «aplicar» la guarda (todo o nada).
 */
export default function ImportarRespuestaModal({ cotizacion, respuesta, nombreProveedor, onCerrar }) {
  const notificar = useNotificar()
  const entrada = useRef(null)
  const [archivo, setArchivo] = useState(null)
  const [informe, setInforme] = useState(null)
  const [error, setError] = useState('')
  const [bajando, setBajando] = useState(false)

  const subir = (accion, adjunto) => {
    const cuerpo = new FormData()
    cuerpo.append('respuesta', respuesta)
    cuerpo.append('accion', accion)
    cuerpo.append('archivo', adjunto)
    return api.post(`/compras/cotizaciones/${cotizacion.id}/importar/`, cuerpo, { timeout: 60_000 }).then((r) => r.data)
  }
  // Revisar no guarda nada (no invalida consultas); aplicar sí.
  const revisar = useMutacion({ mutationFn: (adjunto) => subir('revisar', adjunto), alExito: (d) => setInforme(d.informe), avisarError: false })
  const enviar = useMutacion({ mutationFn: () => subir('aplicar', archivo), invalidar: [['compras']], avisarError: false })
  const ocupado = enviar.isPending || revisar.isPending

  const elegir = (evento) => {
    const elegido = evento.target.files?.[0]
    evento.target.value = '' // permite elegir otra vez el mismo archivo
    setError('')
    setInforme(null)
    if (!elegido || ocupado) return
    if (!/\.xlsx$/i.test(elegido.name)) return setError('Elige el Excel de la plantilla (termina en .xlsx).')
    if (elegido.size > MAX_BYTES_EXCEL) return setError('El archivo pesa más de 2 MB.')
    setArchivo(elegido)
    // En cuanto se elige, se revisa: así se ven los errores antes de guardar nada.
    revisar.mutate(elegido, { onError: (e) => setError(erroresDeCampo(e).archivo || mensajeDeError(e)) })
  }

  const aplicar = () => {
    if (ocupado || !archivo) return
    setError('')
    enviar.mutate(undefined, {
        onSuccess: () => {
          notificar('exito', `Respuesta de ${nombreProveedor} importada.`)
          onCerrar()
        },
        onError: (e) => setError(erroresDeCampo(e).archivo || mensajeDeError(e)),
    })
  }

  const plantilla = async () => {
    if (bajando) return
    setBajando(true)
    setError('')
    try {
      const nombre = await descargarArchivo(`/compras/cotizaciones/${cotizacion.id}/plantilla/`, { respuesta })
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (e) {
      setError(await mensajeDeErrorDescarga(e))
    } finally {
      setBajando(false)
    }
  }

  return (
    <Modal titulo="Importar respuesta desde Excel" subtitulo={`${cotizacion.codigo} · ${nombreProveedor}`} onCerrar={onCerrar} ancho={980}>
      <p>Descarga la plantilla (ya trae los productos y cantidades), pásala al proveedor o llénala con su respuesta y súbela aquí. Primero se revisa; no se guarda nada hasta que pulses «Aplicar».</p>
      <div className="acciones-reporte">
        <button type="button" className="boton-cabecera" disabled={bajando} onClick={plantilla}>
          <Icono nombre="exportar" tam={18} /> {bajando ? 'Generando…' : 'Descargar plantilla'}
        </button>
        <input ref={entrada} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden onChange={elegir} />
        <button type="button" className="boton-cabecera" disabled={ocupado} onClick={() => entrada.current?.click()}>
          <Icono nombre="importar" tam={18} /> {archivo ? 'Elegir otro archivo' : 'Elegir el Excel'}
        </button>
        {archivo && <span className="celda-suave">{archivo.name}</span>}
      </div>
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
      {revisar.isPending && <p aria-live="polite">Revisando el archivo…</p>}
      {informe && <Informe informe={informe} moneda={cotizacion.moneda} />}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={ocupado}>
          Cancelar
        </button>
        <button type="button" className="primario" disabled={ocupado || !informe?.se_puede_aplicar} onClick={aplicar}>
          {ocupado ? 'Guardando…' : 'Aplicar respuesta'}
        </button>
      </div>
    </Modal>
  )
}
