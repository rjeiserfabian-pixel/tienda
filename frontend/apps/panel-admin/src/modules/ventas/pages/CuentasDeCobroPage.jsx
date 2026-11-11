import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../../almacen/hooks/useOpciones'
import '../../almacen/inventario.css'
import '../ventas.css'

const VACIO = []

/** Una cuenta de cobro nueva: qué método entra a qué caja o cuenta, en toda la empresa o en una tienda. */
function NuevaCuentaModal({ empresaId, onCerrar }) {
  const medios = useOpciones('/mantenimiento/medios-pago/').data ?? VACIO
  const tiendas = useOpciones('/organizacion/sucursales/', { empresa: empresaId }).data ?? VACIO
  const cuentas = useOpciones('/mantenimiento/cuentas/', { empresa: empresaId }).data ?? VACIO
  const [medio, setMedio] = useState('')
  const [tienda, setTienda] = useState('')
  const [cuenta, setCuenta] = useState('')
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const elegido = medios.find((m) => String(m.id) === medio)
  // El efectivo entra a una caja; los demás métodos, a una cuenta de banco o billetera.
  const opciones = cuentas.filter((c) => (elegido?.tipo === 'EFECTIVO' ? c.tipo === 'CAJA' : c.tipo !== 'CAJA'))

  const crear = useMutacion({
    mutationFn: (datos) => api.post('/ventas/cuentas-de-cobro/', datos).then((r) => r.data),
    invalidar: [['ventas']],
    exito: 'Cuenta de cobro guardada.',
    alExito: onCerrar,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const e = {}
    if (!medio) e.medio_pago = 'Elige el método de pago.'
    if (!cuenta) e.cuenta = 'Elige la caja o cuenta donde entra.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    crear.mutate(
      { empresa: empresaId, medio_pago: Number(medio), cuenta: Number(cuenta), ...(tienda ? { sucursal: Number(tienda) } : {}) },
      {
        onError: (error) => {
          const campos = erroresDeCampo(error)
          setErrores({ medio_pago: campos.medio_pago, cuenta: campos.cuenta, sucursal: campos.sucursal })
          setGeneral(Object.keys(campos).length ? 'Revisa los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo="Nueva cuenta de cobro" subtitulo="Dónde entra lo que se cobra con un método de pago" onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={crear.isPending} style={{ border: 0, padding: 0, margin: 0 }}>
          <Campo etiqueta="Método de pago" tipo="select" requerido error={errores.medio_pago}>
            {(p) => (
              <select {...p} value={medio} onChange={(e) => { setMedio(e.target.value); setCuenta('') }}>
                <option value="">Elige el método</option>
                {medios.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Tienda" tipo="select" error={errores.sucursal} ayuda="«Toda la empresa» sirve para las tiendas que no tengan una cuenta propia.">
            {(p) => (
              <select {...p} value={tienda} onChange={(e) => setTienda(e.target.value)}>
                <option value="">Toda la empresa</option>
                {tiendas.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Entra a" tipo="select" requerido error={errores.cuenta} ayuda={elegido ? (elegido.tipo === 'EFECTIVO' ? 'El efectivo entra a una caja.' : 'Este método entra a una cuenta de banco o billetera.') : undefined}>
            {(p) => (
              <select {...p} value={cuenta} disabled={!medio} onChange={(e) => setCuenta(e.target.value)}>
                <option value="">{medio ? 'Elige dónde entra' : 'Primero elige el método'}</option>
                {opciones.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre} · {c.moneda === 'USD' ? 'US$' : 'S/'}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        </fieldset>
        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={crear.isPending}>
            {crear.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Cuentas de cobro: a qué caja o cuenta entra cada método de pago, por empresa y por tienda. */
export default function CuentasDeCobroPage() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const [creando, setCreando] = useState(false)
  const [quitando, setQuitando] = useState(null)
  const consulta = useQuery({
    queryKey: ['ventas', 'cuentas-de-cobro', empresaActivaId],
    queryFn: ({ signal }) => api.get('/ventas/cuentas-de-cobro/', { params: { empresa: empresaActivaId, page_size: 100 }, signal }).then((r) => r.data.results),
    enabled: Boolean(empresaActivaId),
  })
  const filas = consulta.data ?? VACIO
  const quitar = useMutacion({
    mutationFn: (id) => api.delete(`/ventas/cuentas-de-cobro/${id}/`),
    invalidar: [['ventas']],
    exito: 'Cuenta de cobro quitada.',
    alExito: () => setQuitando(null),
  })

  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="Cuentas de cobro" descripcion={`A qué caja o cuenta entra lo que ${empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa'} cobra con cada método. Puedes elegir una cuenta distinta por tienda (por ejemplo, un Yape por tienda).`}>
        <Can permiso="VENTAS.CUENTAS_COBRO">
          <button type="button" className="primario boton-cabecera" onClick={() => setCreando(true)}>
            <Icono nombre="agregar" tam={20} /> Nueva cuenta de cobro
          </button>
        </Can>
      </CabeceraListado>
      <p className="celda-suave">El efectivo, si no indicas otra cosa, entra a la caja de mostrador de la tienda. Un método sin cuenta no se puede cobrar.</p>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Método de pago</th>
                <th>Tienda</th>
                <th>Entra a</th>
                <th>Moneda</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={5} icono="coins" titulo="Todavía no hay cuentas de cobro" descripcion="Indica a qué cuenta entra cada método de pago (Yape, tarjeta, transferencia)." />}
              {filas.map((f) => (
                <tr key={f.id}>
                  <td>
                    <strong>{f.medio_pago_nombre}</strong>
                  </td>
                  <td>{f.sucursal_nombre || <span className="celda-suave">Toda la empresa</span>}</td>
                  <td>{f.cuenta_nombre}</td>
                  <td>{f.moneda === 'USD' ? 'Dólares' : 'Soles'}</td>
                  <td className="centrado">
                    <Can permiso="VENTAS.CUENTAS_COBRO">
                      <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${f.medio_pago_nombre} → ${f.cuenta_nombre}`} title="Quitar" onClick={() => setQuitando(f)}>
                        <Icono nombre="papelera" tam={18} />
                      </button>
                    </Can>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      {creando && <NuevaCuentaModal empresaId={empresaActivaId} onCerrar={() => setCreando(false)} />}
      {quitando && (
        <ConfirmarModal
          titulo="Quitar la cuenta de cobro"
          mensaje={`«${quitando.medio_pago_nombre}» dejará de entrar a «${quitando.cuenta_nombre}»${quitando.sucursal_nombre ? ` en ${quitando.sucursal_nombre}` : ''}. Las ventas ya hechas no cambian.`}
          textoConfirmar="Quitar"
          enviando={quitar.isPending}
          onConfirmar={() => quitar.mutate(quitando.id)}
          onCerrar={() => setQuitando(null)}
        />
      )}
    </main>
  )
}
