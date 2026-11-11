import { useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../hooks/useClaveIdempotente'
import { useOpciones } from '../hooks/useOpciones'
import {
  CON_CLIENTE,
  CON_COMPROBANTE,
  CON_PROVEEDOR,
  hoyIso,
  nuevaLinea,
  ORIGENES,
  ORIGENES_MANUALES,
  numerosDe,
  paraServidor,
  serieValida,
  TIPOS_MOVIMIENTO,
} from '../inventario'
import { aNumero, soles } from '../utilidades'
import '../inventario.css'
import LineasMovimiento from './LineasMovimiento'

const inicial = () => ({
  tipo: 'ENTRADA',
  origen: 'COMPRA',
  fecha: hoyIso(),
  almacen: '',
  proveedor: '',
  cliente: '',
  comprobante_tipo: '',
  comprobante_serie: '',
  comprobante_numero: '',
  comprobante_fecha: '',
  moneda: 'PEN',
  tipo_cambio: '',
  precios_incluyen_igv: false,
  observacion: '',
})

/** Cuerpo que recibe el servidor. Se arma igual para enviar y para calcular la clave de idempotencia. */
function armarCuerpo(f, lineas, empresa, ubicacionesValidas) {
  const conComprobante = CON_COMPROBANTE.includes(f.origen)
  const cuerpo = {
    empresa,
    almacen: Number(f.almacen) || null,
    tipo: f.tipo,
    origen: f.origen,
    fecha: f.fecha,
    observacion: f.observacion.trim(),
    lineas: lineas.map((l) => {
      const conSerie = Boolean(l.producto?.lleva_serie)
      const series = conSerie ? l.series : []
      // En una entrada cada serie viaja con su dato opcional; en una salida solo cuáles salen.
      const enviadas = f.tipo === 'ENTRADA' ? series.map((s) => (s.otros_datos ? { numero: s.numero, otros_datos: s.otros_datos } : s.numero)) : numerosDe(series)
      return {
        producto: l.producto?.id ?? null,
        cantidad: conSerie ? String(series.length) : paraServidor(l.cantidad),
        ...(conSerie ? { series: enviadas } : {}),
        ...(f.tipo === 'ENTRADA' ? { precio_unitario: paraServidor(l.precio) } : {}),
        // Solo si la ubicación elegida sigue siendo del almacén (al cambiar de almacén deja de valer).
        ...(f.tipo === 'ENTRADA' && l.ubicacion && ubicacionesValidas.has(Number(l.ubicacion)) ? { ubicacion: Number(l.ubicacion) } : {}),
      }
    }),
  }
  if (CON_PROVEEDOR.includes(f.origen) && f.proveedor) cuerpo.proveedor = Number(f.proveedor)
  if (CON_CLIENTE.includes(f.origen) && f.cliente) cuerpo.cliente = Number(f.cliente)
  if (conComprobante) {
    Object.assign(cuerpo, {
      comprobante_tipo: f.comprobante_tipo,
      comprobante_serie: f.comprobante_serie.trim(),
      comprobante_numero: f.comprobante_numero.trim(),
      moneda: f.moneda,
      precios_incluyen_igv: f.precios_incluyen_igv,
    })
    if (f.comprobante_fecha) cuerpo.comprobante_fecha = f.comprobante_fecha
    if (f.moneda === 'USD' && f.tipo_cambio) cuerpo.tipo_cambio = paraServidor(f.tipo_cambio)
  }
  return cuerpo
}

/** Revisa lo que se puede revisar en el navegador; el servidor vuelve a validar todo. */
function validar(f, lineas) {
  const campos = {}
  const porLinea = {}
  if (!f.almacen) campos.almacen = 'Elija el almacén.'
  if (!f.fecha) campos.fecha = 'Indique la fecha.'
  else if (f.fecha > hoyIso()) campos.fecha = 'La fecha no puede ser futura.'
  if ((f.comprobante_serie || f.comprobante_numero) && !f.comprobante_tipo) campos.comprobante_tipo = 'Elija el tipo de comprobante.'
  for (const l of lineas) {
    const e = {}
    if (!l.producto) e.producto = 'Elija el producto.'
    if (l.producto?.lleva_serie) {
      const series = numerosDe(l.series)
      const mala = series.find((s) => !serieValida(s))
      if (!series.length) e.series = 'Escriba al menos una serie o IMEI.'
      else if (mala) e.series = `«${mala}» no es válida: use de 3 a 40 letras, números, guiones o puntos.`
      else if (new Set(series).size !== series.length) e.series = 'Hay series repetidas.'
    } else {
      const cantidad = aNumero(l.cantidad)
      if (cantidad === null || cantidad <= 0) e.cantidad = 'Mayor que cero.'
      else if (!/^\d+([.,]\d{1,3})?$/.test(String(l.cantidad).trim())) e.cantidad = 'Hasta 3 decimales.'
    }
    if (f.tipo === 'ENTRADA') {
      const precio = aNumero(l.precio)
      if (precio === null || precio < 0) e.precio = 'Indique el precio.'
    }
    if (Object.keys(e).length) porLinea[l.id] = e
  }
  return { campos, porLinea, valido: !Object.keys(campos).length && !Object.keys(porLinea).length }
}

export default function MovimientoFormModal({ onCerrar }) {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [f, setF] = useState(inicial)
  const [lineas, setLineas] = useState(() => [nuevaLinea()])
  const [errores, setErrores] = useState({ campos: {}, porLinea: {} })
  const [general, setGeneral] = useState('')

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId })
  const proveedores = useOpciones('/mantenimiento/proveedores/', {}, { enabled: CON_PROVEEDOR.includes(f.origen) })
  const clientes = useOpciones('/mantenimiento/clientes/', {}, { enabled: CON_CLIENTE.includes(f.origen) })
  const almacen = f.almacen || String(almacenes.data?.[0]?.id ?? '')
  // Los tipos de comprobante son un catálogo editable: se piden los de compras o los de ventas.
  const comprobantes = useOpciones('/mantenimiento/tipos-comprobante/', { [CON_CLIENTE.includes(f.origen) ? 'aplica_ventas' : 'aplica_compras']: '1' }, { enabled: CON_COMPROBANTE.includes(f.origen) })
  const { tiene } = usePermisos()
  const puedeUbicar = tiene('INVENTARIO.UBICACIONES.ASIGNAR')
  const ubicaciones = useOpciones('/mantenimiento/ubicaciones/', { empresa: empresaActivaId, almacen }, { enabled: Boolean(almacen) && f.tipo === 'ENTRADA' && puedeUbicar })
  const ubicacionesDelAlmacen = useMemo(() => (puedeUbicar && f.tipo === 'ENTRADA' ? (ubicaciones.data ?? []) : []), [puedeUbicar, f.tipo, ubicaciones.data])
  const ubicacionesValidas = useMemo(() => new Set(ubicacionesDelAlmacen.map((u) => u.id)), [ubicacionesDelAlmacen])

  const formulario = useMemo(() => ({ ...f, almacen }), [f, almacen])
  const cuerpo = useMemo(() => armarCuerpo(formulario, lineas, empresaActivaId, ubicacionesValidas), [formulario, lineas, empresaActivaId, ubicacionesValidas])
  const clave = useClaveIdempotente(cuerpo)

  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) =>
      api.post('/inventario/movimientos/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['movimientos'], ['stock'], ['kardex'], ['periodos']],
    exito: (m) => `Movimiento N° ${String(m.numero).padStart(6, '0')} registrado.`,
    alExito: onCerrar,
    avisarError: false,
  })

  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const cambiarTipo = (tipo) => setF((previo) => ({ ...previo, tipo, origen: ORIGENES_MANUALES[tipo][0] }))
  const conComprobante = CON_COMPROBANTE.includes(f.origen)
  const cantidadDe = (l) => (l.producto?.lleva_serie ? l.series.length : (aNumero(l.cantidad) ?? 0))
  const total = f.tipo === 'ENTRADA' ? lineas.reduce((s, l) => s + cantidadDe(l) * (aNumero(l.precio) ?? 0), 0) : null

  const enviar = (evento) => {
    evento.preventDefault()
    if (registrar.isPending) return
    const revision = validar(formulario, lineas)
    setErrores(revision)
    setGeneral('')
    if (!revision.valido) return
    registrar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores({ campos: delServidor, porLinea: {} })
          setGeneral(Object.keys(delServidor).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  const e = errores.campos
  return (
    <Modal titulo="Registrar movimiento" subtitulo={`En ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'}. El costo se calcula solo, al promedio.`} onCerrar={onCerrar} ancho={940}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={registrar.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <div className="fila-campos">
            <Campo etiqueta="Movimiento" tipo="select" requerido>
              {(p) => (
                <select {...p} value={f.tipo} onChange={(ev) => cambiarTipo(ev.target.value)}>
                  {Object.entries(TIPOS_MOVIMIENTO).map(([valor, { texto }]) => (
                    <option key={valor} value={valor}>{texto}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Motivo" tipo="select" requerido error={e.origen}>
              {(p) => (
                <select {...p} value={f.origen} onChange={(ev) => poner('origen', ev.target.value)}>
                  {ORIGENES_MANUALES[f.tipo].map((o) => (
                    <option key={o} value={o}>{ORIGENES[o]}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Fecha" icono="calendario" requerido error={e.fecha}>
              {(p) => <input {...p} type="date" max={hoyIso()} value={f.fecha} onChange={(ev) => poner('fecha', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Almacén" tipo="select" requerido error={e.almacen}>
              {(p) => (
                <select {...p} value={almacen} onChange={(ev) => poner('almacen', ev.target.value)}>
                  {almacenes.isLoading && <option value="">Cargando…</option>}
                  {(almacenes.data ?? []).map((a) => (
                    <option key={a.id} value={a.id}>{a.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
          </div>

          {conComprobante && (
            <>
              <div className="fila-campos">
                {CON_PROVEEDOR.includes(f.origen) && (
                  <Campo etiqueta="Proveedor" tipo="select" error={e.proveedor}>
                    {(p) => (
                      <select {...p} value={f.proveedor} onChange={(ev) => poner('proveedor', ev.target.value)}>
                        <option value="">Sin indicar</option>
                        {(proveedores.data ?? []).map((x) => (
                          <option key={x.id} value={x.id}>{x.nombre}</option>
                        ))}
                      </select>
                    )}
                  </Campo>
                )}
                {CON_CLIENTE.includes(f.origen) && (
                  <Campo etiqueta="Cliente" tipo="select" error={e.cliente}>
                    {(p) => (
                      <select {...p} value={f.cliente} onChange={(ev) => poner('cliente', ev.target.value)}>
                        <option value="">Sin indicar</option>
                        {(clientes.data ?? []).map((x) => (
                          <option key={x.id} value={x.id}>{x.nombre}</option>
                        ))}
                      </select>
                    )}
                  </Campo>
                )}
                <Campo etiqueta="Comprobante" tipo="select" error={e.comprobante_tipo} ayuda={comprobantes.isError ? 'No se pudieron cargar los tipos de comprobante. Pide acceso a Tipos de comprobante.' : undefined}>
                  {(p) => (
                    <select {...p} value={f.comprobante_tipo} onChange={(ev) => poner('comprobante_tipo', ev.target.value)}>
                      <option value="">Sin comprobante</option>
                      {(comprobantes.data ?? []).map((t) => (
                        <option key={t.codigo} value={t.codigo}>{t.nombre}</option>
                      ))}
                    </select>
                  )}
                </Campo>
                <Campo etiqueta="Serie" error={e.comprobante_serie}>
                  {(p) => <input {...p} placeholder="F001" maxLength={10} value={f.comprobante_serie} onChange={(ev) => poner('comprobante_serie', ev.target.value.toUpperCase())} />}
                </Campo>
                <Campo etiqueta="Número" error={e.comprobante_numero || e.comprobante_duplicado}>
                  {(p) => <input {...p} placeholder="1245" maxLength={20} value={f.comprobante_numero} onChange={(ev) => poner('comprobante_numero', ev.target.value.toUpperCase())} />}
                </Campo>
                <Campo etiqueta="Fecha del comprobante" icono="calendario" error={e.comprobante_fecha}>
                  {(p) => <input {...p} type="date" max={hoyIso()} value={f.comprobante_fecha} onChange={(ev) => poner('comprobante_fecha', ev.target.value)} />}
                </Campo>
              </div>
              <div className="fila-campos">
                <Campo etiqueta="Moneda" tipo="select">
                  {(p) => (
                    <select {...p} value={f.moneda} onChange={(ev) => poner('moneda', ev.target.value)}>
                      <option value="PEN">Soles</option>
                      <option value="USD">Dólares</option>
                    </select>
                  )}
                </Campo>
                {f.moneda === 'USD' && (
                  <Campo etiqueta="Tipo de cambio" error={e.tipo_cambio} ayuda="Déjelo vacío para usar el oficial del día.">
                    {(p) => <input {...p} inputMode="decimal" placeholder="Ej. 3.75" value={f.tipo_cambio} onChange={(ev) => poner('tipo_cambio', ev.target.value)} />}
                  </Campo>
                )}
                {f.tipo === 'ENTRADA' && (
                  <label className="casilla">
                    <input type="checkbox" checked={f.precios_incluyen_igv} onChange={(ev) => poner('precios_incluyen_igv', ev.target.checked)} />
                    <span>Los precios incluyen IGV</span>
                  </label>
                )}
              </div>
            </>
          )}

          <LineasMovimiento lineas={lineas} onCambiar={setLineas} tipo={f.tipo} ubicaciones={ubicacionesDelAlmacen} errores={errores.porLinea} disabled={registrar.isPending} />
          {e.lineas && <p role="alert" className="campo-error">{e.lineas}</p>}

          <Campo etiqueta="Observación" error={e.observacion}>
            {(p) => <input {...p} maxLength={250} placeholder="Opcional" value={f.observacion} onChange={(ev) => poner('observacion', ev.target.value)} />}
          </Campo>

          <div className="resumen-movimiento" aria-live="polite">
            <span>
              Productos: <strong>{lineas.length}</strong>
            </span>
            {total !== null && (
              <span>
                Importe aproximado: <strong>{soles(total)}</strong>
              </span>
            )}
          </div>
        </fieldset>

        {general && <p role="alert" className="campo-error">{general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={registrar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={registrar.isPending}>
            {registrar.isPending ? 'Registrando…' : 'Registrar movimiento'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
