import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import PuntoModal from '../components/PuntoModal'
import ZonaModal from '../components/ZonaModal'
import { ajustesDesdeServidor, cambiosDeAjustes, MODALIDADES, resumenTarifas, revisarAjustes, soles } from '../envios'
import '../tienda.css'
import '../envios.css'

const CLAVE = ['tienda', 'envios']
const CLAVE_CONFIG = ['tienda', 'configuracion']
const PESTANAS = [
  ['envio', 'Envío a domicilio'],
  ['recojo', 'Recojo en tienda'],
]

/** Envíos y recojo: a dónde llega la tienda, cuánto cuesta y dónde se recoge. */
export default function EnviosTiendaPage() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/tienda/admin/envios/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const config = useQuery({
    queryKey: CLAVE_CONFIG,
    queryFn: ({ signal }) => api.get('/tienda/admin/configuracion/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const datos = consulta.data

  const [pestana, setPestana] = useState('envio')
  const [zonaAbierta, setZonaAbierta] = useState(null) // null = cerrada, {} = nueva, zona = editar
  const [puntoAbierto, setPuntoAbierto] = useState(null)
  const [aEliminar, setAEliminar] = useState(null) // { tipo: 'zona' | 'punto', item }

  // Ajustes generales (interruptores y peso por defecto): van a la configuración de la tienda.
  const [ajustes, setAjustes] = useState(null)
  const [erroresAjustes, setErroresAjustes] = useState({})
  const claveAjustes = useMemo(() => (config.data ? JSON.stringify(ajustesDesdeServidor(config.data)) : null), [config.data])
  useEffect(() => {
    if (claveAjustes) setAjustes(JSON.parse(claveAjustes))
  }, [claveAjustes])
  const cambiosAjustes = useMemo(() => (config.data && ajustes ? cambiosDeAjustes(config.data, ajustes) : {}), [config.data, ajustes])
  const hayAjustes = Object.keys(cambiosAjustes).length > 0

  const guardarAjustes = useMutacion({
    mutationFn: (cuerpo) => api.patch('/tienda/admin/configuracion/', cuerpo).then((r) => r.data),
    invalidar: [CLAVE_CONFIG],
    exito: 'Ajustes de entrega guardados.',
    avisarError: false,
  })
  const alGuardarAjustes = (evento) => {
    evento.preventDefault()
    const locales = revisarAjustes(ajustes)
    setErroresAjustes(locales)
    if (Object.keys(locales).length > 0) return
    guardarAjustes.mutate(cambiosAjustes, {
      onError: (error) => setErroresAjustes({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }
  const cambiarAjuste = (campo, valor) => {
    setAjustes((a) => ({ ...a, [campo]: valor }))
    setErroresAjustes((e) => ({ ...e, [campo]: undefined }))
  }

  const eliminar = useMutacion({
    mutationFn: ({ tipo, item }) => api.delete(`/tienda/admin/envios/${tipo === 'zona' ? 'zonas' : 'puntos'}/${item.id}/`).then((r) => r.data),
    invalidar: [CLAVE],
    exito: 'Eliminado.',
    alExito: () => setAEliminar(null),
  })

  // Encender o apagar una zona o un punto sin abrir el formulario.
  const alternar = useMutacion({
    mutationFn: ({ tipo, item }) =>
      api.patch(`/tienda/admin/envios/${tipo === 'zona' ? 'zonas' : 'puntos'}/${item.id}/`, tipo === 'zona' ? { activa: !item.activa } : { activo: !item.activo }).then((r) => r.data),
    invalidar: [CLAVE],
  })

  const zonas = datos?.zonas ?? []
  const puntos = datos?.puntos ?? []
  const almacenes = useMemo(() => datos?.opciones?.almacenes ?? [], [datos])
  const nombreAlmacen = useMemo(() => new Map(almacenes.map((a) => [a.id, a.nombre])), [almacenes])
  const sinZonas = zonas.filter((z) => z.activa).length === 0
  const sinPuntos = puntos.filter((p) => p.activo).length === 0

  return (
    <main className="listado tienda-pagina envios-pagina">
      <CabeceraListado
        icono="truck"
        titulo="Envíos y recojo"
        descripcion="A dónde llega la tienda, cuánto cuesta el envío según el peso y en qué locales el cliente puede recoger su pedido."
      />

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && (
          <>
            {ajustes && (
              <form onSubmit={alGuardarAjustes} noValidate className="envios-ajustes" aria-label="Ajustes de entrega">
                <Interruptor
                  activo={ajustes.permite_envio}
                  onCambio={(v) => cambiarAjuste('permite_envio', v)}
                  texto="Ofrecer envío a domicilio"
                  descripcion={ajustes.permite_envio ? 'El cliente puede pedir que se lo lleven.' : 'La tienda no ofrece envío por ahora.'}
                />
                <Interruptor
                  activo={ajustes.permite_recojo}
                  onCambio={(v) => cambiarAjuste('permite_recojo', v)}
                  texto="Ofrecer recojo en tienda"
                  descripcion={ajustes.permite_recojo ? 'El cliente puede recoger en un punto con stock.' : 'La tienda no ofrece recojo por ahora.'}
                />
                <Campo
                  etiqueta="Peso por defecto (kg)"
                  error={erroresAjustes.peso_por_defecto_kg}
                  ayuda="Se usa para calcular el envío de los productos que no tienen peso cargado en su ficha."
                >
                  {(p) => (
                    <input
                      {...p}
                      name="peso_por_defecto_kg"
                      inputMode="decimal"
                      value={ajustes.peso_por_defecto_kg}
                      maxLength={7}
                      onChange={(e) => cambiarAjuste('peso_por_defecto_kg', e.target.value)}
                    />
                  )}
                </Campo>
                <div className="envios-ajustes-pie">
                  <button type="submit" className="primario" disabled={!hayAjustes || guardarAjustes.isPending}>
                    {guardarAjustes.isPending ? 'Guardando…' : 'Guardar ajustes'}
                  </button>
                  {erroresAjustes._general && !erroresAjustes.peso_por_defecto_kg && (
                    <p role="alert" className="campo-error">
                      {erroresAjustes._general}
                    </p>
                  )}
                </div>
              </form>
            )}

            <div className="tienda-segmentos envios-pestanas" role="group" aria-label="Tipo de entrega">
              {PESTANAS.map(([valor, texto]) => (
                <button key={valor} type="button" aria-pressed={pestana === valor} onClick={() => setPestana(valor)}>
                  {texto}
                </button>
              ))}
            </div>

            {pestana === 'envio' && (
              <PanelTarjeta
                id="envios-zonas"
                icono="truck"
                titulo="Zonas de envío"
                descripcion="Cada zona dice qué lugares cubre y cuánto cuesta. Lima suele ser reparto propio por peso; provincias, una agencia con pago en destino."
                acciones={
                  <button type="button" className="primario" onClick={() => setZonaAbierta({})}>
                    <Icono nombre="agregar" tam={18} /> Nueva zona
                  </button>
                }
              >
                {sinZonas && (
                  <p className="tienda-aviso" role="status">
                    <Icono nombre="bell" tam={18} />
                    <span>
                      {zonas.length === 0 ? 'Todavía no hay zonas.' : 'No hay zonas activas.'} Sin zonas, los clientes solo podrán recoger en tienda.
                    </span>
                  </p>
                )}
                <ul className="envios-lista">
                  {zonas.map((z) => (
                    <li key={z.id} className="envios-tarjeta" data-apagada={!z.activa || undefined}>
                      <header>
                        <div>
                          <h4>{z.nombre}</h4>
                          <span className="envios-etiqueta">{MODALIDADES[z.modalidad]?.texto ?? z.modalidad}</span>
                          {!z.activa && <span className="envios-etiqueta apagada">Apagada</span>}
                        </div>
                        <div className="envios-acciones">
                          <button type="button" className="icono-boton" aria-label={`${z.activa ? 'Apagar' : 'Encender'} la zona ${z.nombre}`} disabled={alternar.isPending} onClick={() => alternar.mutate({ tipo: 'zona', item: z })}>
                            <Icono nombre={z.activa ? 'apagar' : 'reactivar'} tam={18} />
                          </button>
                          <button type="button" className="icono-boton" aria-label={`Editar la zona ${z.nombre}`} onClick={() => setZonaAbierta(z)}>
                            <Icono nombre="lapiz" tam={18} />
                          </button>
                          <button type="button" className="icono-boton" aria-label={`Eliminar la zona ${z.nombre}`} onClick={() => setAEliminar({ tipo: 'zona', item: z })}>
                            <Icono nombre="papelera" tam={18} />
                          </button>
                        </div>
                      </header>
                      <p className="envios-tarifas-resumen">{resumenTarifas(z)}</p>
                      {z.modalidad === 'TIENDA' && z.envio_gratis_desde && <p className="celda-suave">Envío gratis desde {soles(z.envio_gratis_desde)}.</p>}
                      {(z.plazo || z.detalle) && <p className="celda-suave">{[z.plazo, z.detalle].filter(Boolean).join(' · ')}</p>}
                      <ul className="envios-chips solo-lectura" aria-label={`Lugares de la zona ${z.nombre}`}>
                        {z.coberturas.map((c) => (
                          <li key={c.prefijo}>
                            <span>{c.nombre}</span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </PanelTarjeta>
            )}

            {pestana === 'recojo' && (
              <PanelTarjeta
                id="envios-puntos"
                icono="store"
                titulo="Puntos de recojo"
                descripcion="El cliente solo ve un punto si TODO su pedido está en los almacenes de ese local."
                acciones={
                  <button type="button" className="primario" onClick={() => setPuntoAbierto({})}>
                    <Icono nombre="agregar" tam={18} /> Nuevo punto
                  </button>
                }
              >
                {sinPuntos && (
                  <p className="tienda-aviso" role="status">
                    <Icono nombre="bell" tam={18} />
                    <span>{puntos.length === 0 ? 'Todavía no hay puntos de recojo.' : 'No hay puntos activos.'} Sin ellos, los clientes solo podrán pedir envío.</span>
                  </p>
                )}
                <ul className="envios-lista">
                  {puntos.map((p) => (
                    <li key={p.id} className="envios-tarjeta" data-apagada={!p.activo || undefined}>
                      <header>
                        <div>
                          <h4>{p.nombre}</h4>
                          {!p.activo && <span className="envios-etiqueta apagada">Apagado</span>}
                        </div>
                        <div className="envios-acciones">
                          <button type="button" className="icono-boton" aria-label={`${p.activo ? 'Apagar' : 'Encender'} el punto ${p.nombre}`} disabled={alternar.isPending} onClick={() => alternar.mutate({ tipo: 'punto', item: p })}>
                            <Icono nombre={p.activo ? 'apagar' : 'reactivar'} tam={18} />
                          </button>
                          <button type="button" className="icono-boton" aria-label={`Editar el punto ${p.nombre}`} onClick={() => setPuntoAbierto(p)}>
                            <Icono nombre="lapiz" tam={18} />
                          </button>
                          <button type="button" className="icono-boton" aria-label={`Eliminar el punto ${p.nombre}`} onClick={() => setAEliminar({ tipo: 'punto', item: p })}>
                            <Icono nombre="papelera" tam={18} />
                          </button>
                        </div>
                      </header>
                      <p>{p.direccion}</p>
                      <p className="celda-suave">{[p.horario, p.listo_en, p.telefono].filter(Boolean).join(' · ')}</p>
                      <p className="celda-suave">
                        {p.almacenes.length === 0
                          ? 'Sin almacenes: nunca tendrá stock.'
                          : `Almacenes: ${p.almacenes.map((id) => nombreAlmacen.get(id) ?? `#${id}`).join(', ')}`}
                      </p>
                    </li>
                  ))}
                </ul>
              </PanelTarjeta>
            )}
          </>
        )}
      </EstadoConsulta>

      {zonaAbierta && <ZonaModal zona={zonaAbierta.id ? zonaAbierta : null} onCerrar={() => setZonaAbierta(null)} />}
      {puntoAbierto && <PuntoModal punto={puntoAbierto.id ? puntoAbierto : null} almacenes={almacenes} onCerrar={() => setPuntoAbierto(null)} />}
      {aEliminar && (
        <ConfirmarModal
          titulo={aEliminar.tipo === 'zona' ? '¿Eliminar la zona?' : '¿Eliminar el punto de recojo?'}
          mensaje={
            aEliminar.tipo === 'zona'
              ? `Se borra «${aEliminar.item.nombre}» con sus tarifas y sus lugares quedan libres. Los clientes de esos lugares dejarán de ver envío.`
              : `Se borra «${aEliminar.item.nombre}». Los clientes ya no podrán recoger ahí.`
          }
          textoConfirmar="Eliminar"
          enviando={eliminar.isPending}
          onConfirmar={() => eliminar.mutate(aEliminar)}
          onCerrar={() => setAEliminar(null)}
        />
      )}
    </main>
  )
}
