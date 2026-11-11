import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useClaveIdempotente } from '../../almacen/hooks/useClaveIdempotente'
import { hoyIso } from '../../almacen/inventario'
import AccesoriosIngreso from '../components/AccesoriosIngreso'
import ClienteIngreso from '../components/ClienteIngreso'
import EquipoIngreso from '../components/EquipoIngreso'
import RevisionesIngreso from '../components/RevisionesIngreso'
import { useConfiguracionServicio } from '../hooks/useConfiguracionServicio'
import { armarCuerpo, borradorInicial, CAMPO_DEL_SERVIDOR, equipoVacio, PRIORIDADES, validarIngreso } from '../servicio'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../servicio-tecnico.css'

const RUTA = '/servicio-tecnico/ordenes'
const VACIO = []

function Formulario() {
  const navegar = useNavigate()
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const hoy = hoyIso()
  const [b, setB] = useState(borradorInicial)
  const [intento, setIntento] = useState(false)
  const [general, setGeneral] = useState('')
  const [delServidor, setDelServidor] = useState({})
  const [registrado, setRegistrado] = useState(false)
  const [saliendo, setSaliendo] = useState(false)
  const poner = (campo, valor) => setB((previo) => ({ ...previo, [campo]: typeof valor === 'function' ? valor(previo[campo]) : valor }))

  const configuracion = useConfiguracionServicio(empresaActivaId)
  const datos = configuracion.data
  const tipos = datos?.tipos_equipo ?? VACIO
  const sucursales = datos?.sucursales ?? VACIO
  const tecnicos = datos?.tecnicos ?? VACIO

  const tipoEquipo = b.equipoExistente ? b.equipoExistente.tipo : b.equipo.tipo
  const validacion = validarIngreso(b, { hoy })
  const e = { ...(intento ? validacion.errores : {}), ...delServidor }

  // Las revisiones de un tipo de equipo que se dejó de usar no se envían.
  const cuerpo = useMemo(() => {
    if (!validacion.valido) return null
    const aplicables = new Set((datos?.revisiones ?? VACIO).filter((r) => !r.tipo_equipo || String(r.tipo_equipo) === String(tipoEquipo)).map((r) => String(r.id)))
    const revisiones = Object.fromEntries(Object.entries(b.revisiones).filter(([id]) => aplicables.has(id)))
    return armarCuerpo({ ...b, revisiones }, empresaActivaId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(b), validacion.valido, empresaActivaId, tipoEquipo, datos])
  const clave = useClaveIdempotente(cuerpo)

  const registrar = useMutacion({
    mutationFn: ({ cuerpo: contenido, llave }) => api.post('/servicio-tecnico/ordenes/', contenido, { headers: { 'Idempotency-Key': llave }, timeout: 30_000 }).then((r) => r.data),
    invalidar: [['servicio']],
    exito: (o) => `Equipo recibido: orden ${o.codigo}.`,
    alExito: (o) => {
      setRegistrado(true)
      navegar(`${RUTA}/${o.id}`, { replace: true, state: { imprimir: true } })
    },
    avisarError: false,
  })
  const enviando = registrar.isPending

  const sinGuardar = !registrado && (Boolean(b.cliente) || b.falla.trim() !== '' || b.equipo.marca !== '' || b.equipo.modelo !== '')
  useEffect(() => {
    if (!sinGuardar) return undefined
    const avisar = (ev) => ev.preventDefault()
    window.addEventListener('beforeunload', avisar)
    return () => window.removeEventListener('beforeunload', avisar)
  }, [sinGuardar])

  const enviar = () => {
    if (enviando) return
    setIntento(true)
    setGeneral('')
    setDelServidor({})
    if (!validacion.valido || !cuerpo) {
      setTimeout(() => {
        const primero = document.querySelector('.compra-principal [aria-invalid="true"]')
        primero?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        primero?.focus({ preventScroll: true })
      }, 0)
      return
    }
    registrar.mutate(
      { cuerpo, llave: clave },
      {
        onError: (error) => {
          const campos = erroresDeCampo(error)
          const mapeados = Object.fromEntries(Object.entries(campos).flatMap(([k, v]) => (CAMPO_DEL_SERVIDOR[k] ? [[CAMPO_DEL_SERVIDOR[k], v]] : [])))
          setDelServidor(mapeados)
          setGeneral(Object.keys(campos).length && Object.keys(mapeados).length === Object.keys(campos).length ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  const elegirCliente = (cliente) => setB((previo) => ({ ...previo, cliente, equipoExistente: null, equipo: equipoVacio() }))
  const cancelar = () => (sinGuardar ? setSaliendo(true) : navegar(RUTA))
  const nombreEmpresa = empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'

  return (
    <main className="listado compra-pagina">
      <BotonVolver ruta={RUTA} texto="Volver a las órdenes" />
      <CabeceraListado icono="wrench" titulo="Registrar ingreso de un equipo" descripcion={`En ${nombreEmpresa}. Al guardar se crea la orden de servicio y se imprime la hoja de ingreso.`} />
      {configuracion.isError && (
        <p role="alert" className="campo-error">
          {mensajeDeError(configuracion.error)}
        </p>
      )}
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="user" titulo="Cliente" descripcion="Quién deja el equipo.">
            <ClienteIngreso cliente={b.cliente} onElegir={elegirCliente} error={e.cliente} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="boxes" titulo="Equipo" descripcion="Qué equipo es. Si ya vino antes, elígelo para ver su historial.">
            <EquipoIngreso b={b} poner={poner} errores={e} tipos={tipos} empresaId={empresaActivaId} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Falla y estado" descripcion="Lo que cuenta el cliente y cómo llega el equipo. Protege al taller ante reclamos.">
            <Campo etiqueta="Falla que reporta el cliente" requerido error={e.falla} contador={{ actual: b.falla.length, max: 1000 }}>
              {(p) => <textarea {...p} rows={3} maxLength={1000} placeholder="Ej. No enciende desde ayer; antes hacía un pitido." value={b.falla} disabled={enviando} onChange={(ev) => poner('falla', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Estado físico al recibirlo" error={e.estadoFisico} contador={{ actual: b.estadoFisico.length, max: 1000 }} ayuda="Rayones, golpes, piezas faltantes… tal como llega.">
              {(p) => <textarea {...p} rows={2} maxLength={1000} placeholder="Ej. Rayón en la tapa, falta una tecla." value={b.estadoFisico} disabled={enviando} onChange={(ev) => poner('estadoFisico', ev.target.value)} />}
            </Campo>
            <Campo etiqueta="Clave o patrón del equipo" icono="key" error={e.clave} ayuda="Opcional. Se guarda cifrada y no se imprime: solo la ve quien trabaja el equipo.">
              {(p) => <input {...p} type="text" autoComplete="off" maxLength={100} placeholder="Ej. 1234" value={b.clave} disabled={enviando} onChange={(ev) => poner('clave', ev.target.value)} />}
            </Campo>
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Accesorios que deja" descripcion="Lo que el cliente entrega junto con el equipo.">
            <AccesoriosIngreso catalogo={datos?.accesorios ?? VACIO} accesorios={b.accesorios} onCambio={(lista) => poner('accesorios', lista)} error={e.accesorios} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="scan" titulo="Revisión al recibirlo" descripcion="Cómo está el equipo antes de tocarlo. Marca solo lo que pudiste comprobar.">
            <RevisionesIngreso catalogo={datos?.revisiones ?? VACIO} tipoEquipo={tipoEquipo} revisiones={b.revisiones} onCambio={(r) => poner('revisiones', r)} disabled={enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="chat" titulo="Avisos al cliente" descripcion="Opcional: avisarle por WhatsApp cuando su equipo avance.">
            <label>
              <input type="checkbox" checked={b.aceptaWhatsapp} disabled={enviando} onChange={(ev) => poner('aceptaWhatsapp', ev.target.checked)} /> El cliente acepta recibir avisos de su orden por WhatsApp
            </label>
            {b.aceptaWhatsapp && b.cliente && !b.cliente.telefono && <p className="celda-suave">Este cliente no tiene teléfono registrado: agrégalo en su ficha para que le lleguen los avisos.</p>}
          </PanelTarjeta>

          <PanelTarjeta icono="settings" titulo="Asignación" descripcion="Opcional: puedes asignar el técnico y el tipo de servicio después.">
            <div className="fila-campos">
              <Campo etiqueta="Técnico" tipo="select" error={e.tecnico} ayuda={tecnicos.length === 0 ? 'No hay personal del área técnica en esta empresa.' : undefined}>
                {(p) => (
                  <select {...p} value={b.tecnico} disabled={enviando} onChange={(ev) => poner('tecnico', ev.target.value)}>
                    <option value="">Sin asignar</option>
                    {tecnicos.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Tipo de servicio" tipo="select" error={e.tipoServicio}>
                {(p) => (
                  <select {...p} value={b.tipoServicio} disabled={enviando} onChange={(ev) => poner('tipoServicio', ev.target.value)}>
                    <option value="">Aún no se sabe</option>
                    {(datos?.tipos_servicio ?? VACIO).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.nombre}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
              <Campo etiqueta="Prioridad" tipo="select">
                {(p) => (
                  <select {...p} value={b.prioridad} disabled={enviando} onChange={(ev) => poner('prioridad', ev.target.value)}>
                    {PRIORIDADES.map(([valor, texto]) => (
                      <option key={valor} value={valor}>
                        {texto}
                      </option>
                    ))}
                  </select>
                )}
              </Campo>
            </div>
            <div className="fila-campos">
              <Campo etiqueta="Fecha prometida" icono="calendario" error={e.fechaPromesa} ayuda="Opcional: cuándo se le dijo al cliente que estaría listo.">
                {(p) => <input {...p} type="date" min={hoy} value={b.fechaPromesa} disabled={enviando} onChange={(ev) => poner('fechaPromesa', ev.target.value)} />}
              </Campo>
              {sucursales.length > 1 && (
                <Campo etiqueta="Tienda" tipo="select" error={e.sucursal}>
                  {(p) => (
                    <select {...p} value={b.sucursal} disabled={enviando} onChange={(ev) => poner('sucursal', ev.target.value)}>
                      <option value="">Toda la empresa</option>
                      {sucursales.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.nombre}
                        </option>
                      ))}
                    </select>
                  )}
                </Campo>
              )}
            </div>
          </PanelTarjeta>
        </div>

        <aside className="compra-resumen" aria-label="Resumen del ingreso">
          <h3>Resumen</h3>
          <dl className="compra-totales">
            <div>
              <dt>Cliente</dt>
              <dd>{b.cliente ? b.cliente.nombre : '—'}</dd>
            </div>
            <div>
              <dt>Equipo</dt>
              <dd>{b.equipoExistente ? [b.equipoExistente.tipo_nombre, b.equipoExistente.marca, b.equipoExistente.modelo].filter(Boolean).join(' ') : [tipos.find((t) => String(t.id) === String(b.equipo.tipo))?.nombre, b.equipo.marca, b.equipo.modelo].filter(Boolean).join(' ') || '—'}</dd>
            </div>
            <div>
              <dt>Accesorios</dt>
              <dd>{b.accesorios.length || 'Ninguno'}</dd>
            </div>
            <div>
              <dt>Revisiones marcadas</dt>
              <dd>{Object.values(b.revisiones).filter((r) => r.resultado).length}</dd>
            </div>
          </dl>
          {validacion.faltan.length > 0 && (
            <div className="compra-faltan">
              <strong>Para registrar falta:</strong>
              <ul>
                {validacion.faltan.map((texto) => (
                  <li key={texto}>{texto}</li>
                ))}
              </ul>
            </div>
          )}
          {general && (
            <p role="alert" className="campo-error">
              {general}
            </p>
          )}
          <button type="button" className="primario compra-registrar" disabled={enviando || configuracion.isLoading} onClick={enviar}>
            <Icono nombre="wrench" tam={20} /> {enviando ? 'Registrando…' : 'Registrar ingreso'}
          </button>
          <button type="button" disabled={enviando} onClick={cancelar}>
            Cancelar
          </button>
        </aside>
      </div>
      {saliendo && <ConfirmarModal titulo="Salir sin registrar" mensaje="Se perderá lo que escribiste en este ingreso. ¿Quieres salir?" textoConfirmar="Salir" onConfirmar={() => navegar(RUTA)} onCerrar={() => setSaliendo(false)} />}
    </main>
  )
}

/** Pantalla «Registrar ingreso». Se reinicia sola si se cambia de empresa (la orden es de una sola empresa). */
export default function RegistrarIngresoPage() {
  const { empresaActivaId } = useEmpresas()
  if (!empresaActivaId) return <p style={{ padding: 24 }}>Elige una empresa para registrar el ingreso.</p>
  return <Formulario key={empresaActivaId} />
}
