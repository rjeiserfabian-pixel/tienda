import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { cantidad as formatoCantidad, fechaCorta, hoyIso, paraServidor } from '../../almacen/inventario'
import { aNumero } from '../../almacen/utilidades'
import { dinero } from '../compras'
import '../../almacen/inventario.css'
import '../compras.css'

const RUTA = '/compras/ordenes'

/** Un proveedor con lo que hay que pedirle: cantidades editables y botón para dejar la orden en borrador. */
function GrupoReposicion({ grupo, almacenId, empresaId }) {
  const navegar = useNavigate()
  const [cantidades, setCantidades] = useState({}) // por producto; vacío = lo sugerido
  const [error, setError] = useState('')
  const valor = (p) => cantidades[p.producto] ?? String(Number(p.sugerido))
  const lineas = grupo.productos.filter((p) => aNumero(valor(p)) > 0)
  const malas = grupo.productos.some((p) => valor(p) !== '' && (aNumero(valor(p)) === null || aNumero(valor(p)) < 0 || !/^\d+([.,]\d{1,3})?$/.test(String(valor(p)).trim())))
  const sinCosto = lineas.filter((p) => !(aNumero(p.precio_estimado) > 0)).length

  const crear = useMutacion({
    mutationFn: (llave) =>
      api
        .post(
          '/compras/ordenes/',
          {
            empresa: empresaId,
            proveedor: grupo.proveedor.id,
            almacen: Number(almacenId),
            fecha_emision: hoyIso(),
            observacion: 'Reposición sugerida: productos bajo el stock mínimo.',
            lineas: lineas.map((p) => ({ producto: p.producto, cantidad: paraServidor(valor(p)), precio_unitario: paraServidor(p.precio_estimado) })),
          },
          { headers: { 'Idempotency-Key': llave }, timeout: 30_000 },
        )
        .then((r) => r.data),
    invalidar: [['compras']],
    exito: (o) => `Orden ${o.codigo} creada en borrador. Revísala y emítela.`,
    alExito: (o) => navegar(`${RUTA}/${o.id}`),
    avisarError: false,
  })

  const enviar = () => {
    if (crear.isPending || malas || lineas.length === 0) return
    setError('')
    crear.mutate(globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`, {
      onError: (e) => {
        const campos = erroresDeCampo(e)
        setError(Object.keys(campos).length ? Object.values(campos).join(' ') : mensajeDeError(e))
      },
    })
  }

  const p = grupo.proveedor
  return (
    <PanelTarjeta
      icono="handshake"
      titulo={p ? p.nombre : 'Sin proveedor habitual'}
      descripcion={p ? `${p.tipo_documento} ${p.numero_documento} · proveedor de su compra más reciente` : 'Productos que nunca se compraron: elige a quién pedírselos creando la orden a mano.'}
      acciones={
        p && (
          <button type="button" className="primario boton-cabecera" disabled={crear.isPending || malas || lineas.length === 0} onClick={enviar}>
            {crear.isPending ? 'Creando…' : `Crear orden (${lineas.length})`}
          </button>
        )
      }
    >
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Producto</th>
              <th className="num">Stock</th>
              <th className="num">Mínimo</th>
              <th className="num">En camino</th>
              <th className="num">Pedir</th>
              <th className="num">Precio estimado</th>
              <th>Última compra</th>
            </tr>
          </thead>
          <tbody>
            {grupo.productos.map((prod) => (
              <tr key={prod.producto}>
                <td className="col-texto">
                  {prod.nombre}
                  <span className="sub-texto">
                    {prod.codigo} · {prod.unidad}
                  </span>
                </td>
                <td className="num">{formatoCantidad(prod.stock)}</td>
                <td className="num">{formatoCantidad(prod.minimo)}</td>
                <td className="num">{formatoCantidad(prod.en_camino)}</td>
                <td className="num">
                  {p ? (
                    <input aria-label={`Cantidad a pedir de ${prod.nombre}`} className="compra-numero" inputMode="decimal" value={valor(prod)} disabled={crear.isPending} aria-invalid={aNumero(valor(prod)) === null || aNumero(valor(prod)) < 0} onChange={(e) => setCantidades((previas) => ({ ...previas, [prod.producto]: e.target.value }))} />
                  ) : (
                    <strong>{formatoCantidad(prod.sugerido)}</strong>
                  )}
                </td>
                <td className="num">{aNumero(prod.precio_estimado) > 0 ? dinero(prod.precio_estimado) : <span className="celda-suave">Sin costo</span>}</td>
                <td className="celda-suave">{prod.ultima_compra ? fechaCorta(prod.ultima_compra) : 'Nunca'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {p && sinCosto > 0 && <p className="celda-suave">{sinCosto === 1 ? 'Un producto no tiene' : `${sinCosto} productos no tienen`} costo en el catálogo: la orden se crea con precio 0 y lo corriges al editarla.</p>}
      {p && <p className="celda-suave">Se crea como borrador, en soles y con el costo del catálogo como precio; puedes cambiar todo antes de emitirla.</p>}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
    </PanelTarjeta>
  )
}

/** Reposición sugerida: lo que conviene pedir según el stock mínimo, agrupado por proveedor. */
export default function ReposicionPage() {
  const { empresaActivaId } = useEmpresas()
  const [almacen, setAlmacen] = useState('')
  const [hasta, setHasta] = useState('2')
  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const almacenId = almacen || String(almacenes.data?.[0]?.id ?? '')
  const veces = aNumero(hasta)
  const hastaValido = veces !== null && veces >= 1 && veces <= 10

  const consulta = useQuery({
    queryKey: ['compras', 'ordenes', 'reposicion', empresaActivaId, almacenId, hasta],
    queryFn: ({ signal }) => api.get('/compras/ordenes/reposicion/', { params: { empresa: empresaActivaId, almacen: almacenId, hasta: paraServidor(hasta) }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId && almacenId && hastaValido),
    staleTime: 0,
  })
  const datos = consulta.data

  return (
    <main className="listado">
      <BotonVolver ruta={RUTA} texto="Volver a Órdenes de compra" />
      <CabeceraListado icono="boxes" titulo="Reposición sugerida" descripcion="Los productos que están en su stock mínimo (o por debajo), descontando lo que ya viene en órdenes emitidas. Es solo una sugerencia: nada se crea hasta que lo pidas." />
      <div className="panel-reportes">
        <div className="fila-campos">
          <Campo etiqueta="Almacén" tipo="select">
            {(p) => (
              <select {...p} value={almacenId} onChange={(e) => setAlmacen(e.target.value)}>
                {(almacenes.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Reponer hasta (veces el mínimo)" error={hastaValido ? undefined : 'De 1 a 10.'} ayuda="2 = pedir lo necesario para tener el doble del mínimo.">
            {(p) => <input {...p} inputMode="decimal" value={hasta} onChange={(e) => setHasta(e.target.value)} />}
          </Campo>
        </div>
      </div>

      {!almacenId ? (
        <p className="estado-vacio">Esta empresa no tiene almacenes.</p>
      ) : !hastaValido ? null : (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
          {datos && datos.total_productos === 0 && <p className="estado-vacio">Nada que reponer en {datos.almacen_nombre}: ningún producto está en su mínimo.</p>}
          {datos?.grupos.map((g) => (
            <GrupoReposicion key={`${almacenId}-${hasta}-${g.proveedor?.id ?? 'sin'}`} grupo={g} almacenId={almacenId} empresaId={empresaActivaId} />
          ))}
        </EstadoConsulta>
      )}
    </main>
  )
}
