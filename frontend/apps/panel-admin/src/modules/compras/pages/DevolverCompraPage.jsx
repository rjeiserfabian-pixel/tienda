import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import { fechaCorta, hoyIso } from '../../almacen/inventario'
import DevolverLineas from '../components/DevolverLineas'
import ReembolsoDevolucion from '../components/ReembolsoDevolucion'
import ResumenDevolucion from '../components/ResumenDevolucion'
import { dinero, nuevoPago, numeroInterno, resolverPagos, totalPagado } from '../compras'
import { borradorDevolucion, cuerpoCalculo, cuerpoRegistro, lineasPedidas, validarDevolucion, validarReembolsos } from '../devoluciones'
import { useCalculoDevolucion, usePorDevolver } from '../hooks/useDevolucion'
import '../../almacen/inventario.css'
import '../compras.css'

const SIN_ERRORES = {}
/** Qué dice el servidor → en qué campo del formulario se muestra. */
const CAMPO_DEL_SERVIDOR = { comprobante_serie: 'serie', comprobante_numero: 'numero', fecha_emision: 'fecha', razon: 'razon', ajuste_redondeo: 'ajuste' }

function Formulario({ compra, porDevolver }) {
  const navegar = useNavigate()
  const { tiene } = usePermisos()
  const puedeVerCajas = tiene('CAJA.CUENTAS.VER')
  const moneda = compra.moneda
  const rutaCompra = `/compras/registro/${compra.id}`
  const [b, setB] = useState(borradorDevolucion)
  const [pagos, setPagos] = useState(() => [nuevoPago()])
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const [delServidor, setDelServidor] = useState(SIN_ERRORES)
  const [saliendo, setSaliendo] = useState(false)

  const medios = useOpciones('/mantenimiento/medios-pago/').data ?? []
  const cuentas = useOpciones('/mantenimiento/cuentas/', { empresa: compra.empresa }, { enabled: puedeVerCajas }).data ?? []

  const poner = useCallback((campo, valor) => setB((previo) => ({ ...previo, [campo]: valor })), [])
  const ponerFila = useCallback((linea, cambios) => setB((previo) => ({ ...previo, filas: { ...previo.filas, [linea]: { ...previo.filas[linea], ...cambios } } })), [])

  const pedidas = useMemo(() => lineasPedidas(b.filas, porDevolver.lineas), [b.filas, porDevolver.lineas])
  const unidades = pedidas.reduce((s, p) => s + p.cantidad, 0)
  const validacion = validarDevolucion(b, porDevolver.lineas, pedidas, compra)
  const calculable = pedidas.length > 0 && !validacion.campos.ajuste && !Object.keys(validacion.porLinea).length
  const calculo = useCalculoDevolucion(cuerpoCalculo({ empresa: compra.empresa, compra: compra.id, pedidas, ajuste: b.ajuste }), calculable)

  const porRecuperar = Number(calculo.datos?.por_recuperar ?? 0)
  const aDeuda = Number(calculo.datos?.aplicado_a_deuda ?? 0)
  const resueltos = resolverPagos(pagos, porRecuperar.toFixed(2), { medios, cuentas, moneda, tipoCambio: moneda === 'USD' ? compra.tipo_cambio : '' })
  const conReembolso = b.reembolsar && porRecuperar > 0
  const reembolsado = conReembolso ? totalPagado(resueltos) : 0
  const revisionReembolso = conReembolso ? validarReembolsos(resueltos, porRecuperar) : { porPago: SIN_ERRORES, general: '', valido: true }

  const faltan = [...validacion.faltan]
  if (conReembolso && !puedeVerCajas) faltan.push('Permiso para ver las cajas y cuentas (o dejar el dinero como saldo a favor)')
  else if (conReembolso && !revisionReembolso.valido) faltan.push('Corregir el reembolso')
  if (calculable && !calculo.datos && !calculo.calculando && !faltan.length) faltan.push('Esperar el cálculo de la devolución')

  const cuerpo = cuerpoRegistro({ empresa: compra.empresa, compra: compra.id, b, pedidas, reembolsos: conReembolso ? resueltos : [] })
  const clave = useClaveIdempotente(cuerpo)

  const registrar = useMutacion({
    mutationFn: ({ datos, llave }) => api.post('/compras/devoluciones/', datos, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['compras'], ['caja'], ['stock'], ['kardex'], ['movimientos']],
    exito: 'Devolución registrada. La mercadería salió del almacén.',
    alExito: (d) => navegar(`/compras/devoluciones/${d.id}`, { replace: true }),
    avisarError: false,
  })

  const enviar = () => {
    if (registrar.isPending) return
    setIntento(true)
    setDelServidor(SIN_ERRORES)
    setGeneral('')
    if (!validacion.valido || !revisionReembolso.valido || (conReembolso && !puedeVerCajas) || !calculo.datos || calculo.error) {
      setGeneral(calculo.error || revisionReembolso.general)
      return
    }
    registrar.mutate(
      { datos: cuerpo, llave: clave },
      {
        onError: (error) => {
          const campos = erroresDeCampo(error)
          const mapeados = {}
          const otros = []
          for (const [campo, mensaje] of Object.entries(campos)) {
            if (CAMPO_DEL_SERVIDOR[campo]) mapeados[CAMPO_DEL_SERVIDOR[campo]] = mensaje
            else otros.push(mensaje)
          }
          setDelServidor(mapeados)
          setGeneral(otros.length ? otros.join(' ') : Object.keys(campos).length ? '' : mensajeDeError(error))
        },
      },
    )
  }

  const hayCambios = pedidas.length > 0 || b.numero || b.razon
  const e = { ...(intento ? validacion.campos : SIN_ERRORES), ...delServidor }
  const enviando = registrar.isPending

  return (
    <main className="listado">
      <BotonVolver ruta={rutaCompra} texto="Volver a la compra" />
      <CabeceraListado icono="swap" titulo="Devolver mercadería" descripcion={`Compra N° ${numeroInterno(compra)} · ${compra.tipo_comprobante_nombre} ${compra.comprobante} · ${compra.proveedor_nombre} · ${fechaCorta(compra.fecha_emision)}`} />

      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="documento" titulo="Nota de crédito del proveedor" descripcion="Los datos de la nota de crédito que te entregó el proveedor por esta devolución.">
            <div className="fila-campos">
              <Campo etiqueta="Serie" error={e.serie}>
                {(p) => <input {...p} placeholder="FC01" maxLength={10} value={b.serie} disabled={enviando} onChange={(ev) => poner('serie', ev.target.value.toUpperCase())} />}
              </Campo>
              <Campo etiqueta="Número" requerido error={e.numero}>
                {(p) => <input {...p} placeholder="00000123" maxLength={20} value={b.numero} disabled={enviando} onChange={(ev) => poner('numero', ev.target.value.toUpperCase())} />}
              </Campo>
              <Campo etiqueta="Fecha de emisión" icono="calendario" requerido error={e.fecha}>
                {(p) => <input {...p} type="date" min={compra.fecha_emision} max={hoyIso()} value={b.fecha} disabled={enviando} onChange={(ev) => poner('fecha', ev.target.value)} />}
              </Campo>
            </div>
            <Campo etiqueta="Por qué se devuelve" requerido error={e.razon} contador={{ actual: b.razon.length, max: 250 }}>
              {(p) => <textarea {...p} rows={2} maxLength={250} placeholder="Ej. Mercadería dañada o distinta a la pedida" value={b.razon} disabled={enviando} onChange={(ev) => poner('razon', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Qué se devuelve" descripcion="Solo se puede devolver lo que sigue en el almacén. Sale al costo con que entró en esta compra.">
            <DevolverLineas compra={compra} lineas={porDevolver.lineas} filas={b.filas} errores={intento || Object.keys(validacion.porLinea).length ? validacion.porLinea : SIN_ERRORES} onFila={ponerFila} disabled={enviando} />
            <Campo etiqueta="Ajuste de redondeo (opcional)" error={e.ajuste} ayuda="Solo si la nota del proveedor difiere por céntimos (hasta 0.10, puede ser negativo).">
              {(p) => <input {...p} inputMode="decimal" placeholder="0.00" value={b.ajuste} disabled={enviando} onChange={(ev) => poner('ajuste', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>

          <PanelTarjeta icono="wallet" titulo="Dinero" descripcion="Primero baja lo que aún se debe de la compra; lo ya pagado se reembolsa o queda a tu favor.">
            <p className="celda-suave">
              Deuda actual de la compra: <strong>{dinero(porDevolver.deuda_pendiente, moneda)}</strong>
            </p>
            <ReembolsoDevolucion
              aDeuda={aDeuda}
              porRecuperar={porRecuperar}
              moneda={moneda}
              reembolsar={b.reembolsar}
              onReembolsar={(valor) => {
                poner('reembolsar', valor)
                setPagos([nuevoPago()])
              }}
              resueltos={resueltos}
              cuentas={cuentas}
              medios={medios}
              errores={intento ? revisionReembolso.porPago : SIN_ERRORES}
              sinPermisoCajas={!puedeVerCajas}
              onPagos={setPagos}
              disabled={enviando}
            />
          </PanelTarjeta>
        </div>

        <ResumenDevolucion
          calculo={calculo.datos}
          calculando={calculo.calculando}
          errorCalculo={calculo.error}
          moneda={moneda}
          reembolsado={reembolsado}
          faltan={intento || faltan.length ? faltan : []}
          general={general}
          enviando={enviando}
          unidades={unidades}
          onRegistrar={enviar}
          onCancelar={() => (hayCambios ? setSaliendo(true) : navegar(rutaCompra))}
        />
      </div>
      {saliendo && <ConfirmarModal titulo="Salir sin registrar" mensaje="Se perderá lo que escribiste en esta devolución. ¿Quieres salir?" textoConfirmar="Salir" onConfirmar={() => navegar(rutaCompra)} onCerrar={() => setSaliendo(false)} />}
    </main>
  )
}

/** Pantalla «Devolver mercadería»: se llega desde la ficha de una compra vigente. */
export default function DevolverCompraPage() {
  const { id } = useParams()
  const compra = useQuery({
    queryKey: ['compras', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/compras/${id}/`, { signal }).then((r) => r.data),
    staleTime: 0,
  })
  const porDevolver = usePorDevolver(id)
  const consulta = compra.isError ? compra : porDevolver
  const c = compra.data
  const p = porDevolver.data

  return (
    <EstadoConsulta consulta={consulta} hayDatos={Boolean(c && p)} vacio="La compra no existe.">
      {c && p && c.estado !== 'EMITIDO' && (
        <main className="listado">
          <BotonVolver ruta={`/compras/registro/${id}`} texto="Volver a la compra" />
          <p className="estado-vacio">Esta compra está anulada: no se puede devolver mercadería.</p>
        </main>
      )}
      {c && p && c.estado === 'EMITIDO' && p.lineas.every((l) => Number(l.pendiente) <= 0) && (
        <main className="listado">
          <BotonVolver ruta={`/compras/registro/${id}`} texto="Volver a la compra" />
          <p className="estado-vacio">Ya se devolvió todo lo comprado.</p>
        </main>
      )}
      {c && p && c.estado === 'EMITIDO' && p.lineas.some((l) => Number(l.pendiente) > 0) && <Formulario key={`${c.id}-${p.lineas.map((l) => l.devuelto).join()}`} compra={c} porDevolver={p} />}
    </EstadoConsulta>
  )
}
