import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import {
  agruparAlmacenes,
  cambiosDeConfiguracion,
  desdeServidor,
  revisarConfiguracion,
  MAX_NOMBRE,
} from '../configuracion'
import ContenidoTienda from '../components/ContenidoTienda'
import '../tienda.css'

const CLAVE = ['tienda', 'configuracion']

/** Configuración de la tienda: si está abierta, qué precios y qué almacenes muestra. */
export default function ConfiguracionTiendaPage() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/tienda/admin/configuracion/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false, // no pisar lo que se está escribiendo
  })
  const datos = consulta.data

  const [form, setForm] = useState(null)
  const [errores, setErrores] = useState({})
  const [confirmarApertura, setConfirmarApertura] = useState(false)
  const [mensajeEstado, setMensajeEstado] = useState('')

  // Al llegar (o volver a llegar) los datos del servidor, el formulario parte de ellos.
  // (La clave evita pisar lo que se escribe cuando solo cambió el logo, que se guarda aparte.)
  const claveForm = useMemo(() => (datos ? JSON.stringify(desdeServidor(datos)) : null), [datos])
  useEffect(() => {
    if (claveForm) setForm(JSON.parse(claveForm))
  }, [claveForm])

  const cambiar = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined }))
  }

  const alternarAlmacen = (id) =>
    cambiar('almacenes', form.almacenes.includes(id) ? form.almacenes.filter((x) => x !== id) : [...form.almacenes, id])

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/tienda/admin/configuracion/', cuerpo).then((r) => r.data),
    invalidar: [CLAVE],
    avisarError: false,
  })

  const cambios = useMemo(() => (datos && form ? cambiosDeConfiguracion(datos, form) : {}), [datos, form])
  const hayCambios = Object.keys(cambios).length > 0

  const alGuardar = (evento) => {
    evento.preventDefault()
    const locales = revisarConfiguracion(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    guardar.mutate(cambios, {
      onSuccess: () => setErrores({}),
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }

  const cambiarApertura = (abrir) => {
    setMensajeEstado('')
    guardar.mutate(
      { activa: abrir },
      {
        onSuccess: () => {
          setConfirmarApertura(false)
          setErrores((e) => ({ ...e, activa: undefined }))
        },
        onError: (error) => {
          setConfirmarApertura(false)
          const porCampo = erroresDeCampo(error)
          setErrores((e) => ({ ...e, activa: porCampo.activa }))
          setMensajeEstado(porCampo.activa ? '' : mensajeDeError(error))
        },
      },
    )
  }

  const grupos = useMemo(() => agruparAlmacenes(datos?.opciones?.almacenes ?? []), [datos])
  const listaEfectiva = datos?.opciones?.listas?.find((l) => l.id === datos.lista_precio_efectiva)
  const abierta = Boolean(datos?.activa)
  const enviando = guardar.isPending

  return (
    <main className="listado tienda-pagina tienda-config">
      <CabeceraListado
        icono="settings"
        titulo="Configuración de la tienda"
        descripcion="Decide si la tienda está abierta, cómo se ve (logo, contacto, textos) y qué precios y almacenes muestra."
      />

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos && form)}>
        {datos && form && (
          <>
            <section className="tienda-estado-grande" data-abierta={abierta || undefined} aria-label="Estado de la tienda">
              <span className="tienda-estado-icono" aria-hidden="true">
                <Icono nombre="store" tam={30} />
              </span>
              <div className="tienda-estado-texto">
                <h2>{abierta ? 'Tienda abierta' : 'Tienda cerrada'}</h2>
                <p>
                  {abierta
                    ? 'El público ya puede ver los productos publicados y sus precios.'
                    : 'Nadie puede ver la tienda todavía. Ábrela cuando tengas productos publicados.'}
                </p>
                {errores.activa && (
                  <p role="alert" className="campo-error">
                    {errores.activa}
                  </p>
                )}
                {mensajeEstado && (
                  <p role="alert" className="campo-error">
                    {mensajeEstado}
                  </p>
                )}
              </div>
              <Interruptor
                activo={abierta}
                disabled={enviando}
                onCambio={(v) => (v ? setConfirmarApertura(true) : cambiarApertura(false))}
                texto={abierta ? 'Abierta' : 'Cerrada'}
                descripcion={abierta ? 'Pulsa para cerrarla' : 'Pulsa para abrirla'}
              />
            </section>

            <section className="tienda-resumen-config" aria-label="Resumen de productos">
              <strong>
                {datos.resumen.publicados} {datos.resumen.publicados === 1 ? 'producto publicado' : 'productos publicados'}
              </strong>
              <Link to="/tienda/productos" className="boton-cabecera">
                <Icono nombre="package" tam={18} /> Ver productos en tienda
              </Link>
              {datos.resumen.publicados_sin_precio > 0 && (
                <p className="tienda-aviso" role="status">
                  <Icono nombre="bell" tam={18} />
                  <span>
                    <strong>{datos.resumen.publicados_sin_precio}</strong>{' '}
                    {datos.resumen.publicados_sin_precio === 1 ? 'producto publicado no tiene' : 'productos publicados no tienen'} precio
                    en la lista elegida{listaEfectiva ? ` («${listaEfectiva.nombre}»)` : ''}: mostrarán «Consultar precio» hasta que se
                    les cargue uno. <Link to="/tienda/productos">Revisar productos</Link>.
                  </span>
                </p>
              )}
            </section>

            <form onSubmit={alGuardar} noValidate className="tienda-config-form">
              <PanelTarjeta id="config-datos" icono="settings" titulo="Datos de la tienda" descripcion="Cómo se presenta y a qué precio se vende.">
                <div className="maestro-campos">
                  <Campo
                    etiqueta="Nombre de la tienda"
                    requerido
                    error={errores.nombre}
                    contador={{ actual: form.nombre.length, max: MAX_NOMBRE }}
                    ayuda="Aparece en el encabezado y en el título de cada página."
                  >
                    {(p) => <input {...p} name="nombre" value={form.nombre} maxLength={MAX_NOMBRE} onChange={(e) => cambiar('nombre', e.target.value)} />}
                  </Campo>

                  <Campo
                    etiqueta="Lista de precios que ve el público"
                    tipo="select"
                    error={errores.lista_precio}
                    ayuda={
                      listaEfectiva
                        ? `Ahora se usa «${listaEfectiva.nombre}»${datos.lista_precio === null ? ' (la principal)' : ''}.`
                        : 'No hay una lista de precios disponible.'
                    }
                  >
                    {(p) => (
                      <select {...p} name="lista_precio" value={form.lista_precio} onChange={(e) => cambiar('lista_precio', e.target.value)}>
                        <option value="">La principal (por defecto)</option>
                        {datos.opciones.listas.map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.nombre}
                            {l.es_principal ? ' · principal' : ''}
                          </option>
                        ))}
                      </select>
                    )}
                  </Campo>

                  <Campo
                    etiqueta="Avisar «pocas unidades» desde"
                    error={errores.pocas_unidades}
                    ayuda="Si quedan estas unidades o menos, la tienda dice «pocas unidades» (sin mostrar el stock exacto). Con 0 nunca avisa."
                  >
                    {(p) => (
                      <input
                        {...p}
                        name="pocas_unidades"
                        inputMode="numeric"
                        value={form.pocas_unidades}
                        maxLength={3}
                        onChange={(e) => cambiar('pocas_unidades', e.target.value.replace(/\D/g, ''))}
                      />
                    )}
                  </Campo>
                </div>

                <div className="tienda-config-interruptor">
                  <Interruptor
                    activo={form.precios_con_igv}
                    onCambio={(v) => cambiar('precios_con_igv', v)}
                    texto="Mostrar precios con IGV incluido"
                    descripcion={
                      form.precios_con_igv
                        ? 'El cliente ve el precio final con IGV. El monto exacto se confirma al pagar, según su zona de entrega.'
                        : 'El cliente ve el precio sin IGV.'
                    }
                  />
                  {errores.precios_con_igv && (
                    <p role="alert" className="campo-error">
                      {errores.precios_con_igv}
                    </p>
                  )}
                </div>
              </PanelTarjeta>

              <PanelTarjeta
                id="config-almacenes"
                icono="boxes"
                titulo="Almacenes que abastecen la tienda"
                descripcion="El stock que ve el cliente es la suma de los almacenes marcados. La tienda es una sola para las dos empresas."
              >
                {grupos.length === 0 ? (
                  <p className="celda-suave">No hay almacenes activos. Créalos en Mantenimiento › Almacenes.</p>
                ) : (
                  <div className="tienda-almacenes">
                    {grupos.map((g) => (
                      <fieldset key={g.empresa} className="tienda-almacenes-grupo">
                        <legend>{g.empresa}</legend>
                        <ul>
                          {g.almacenes.map((a) => (
                            <li key={a.id}>
                              <label className="tienda-casilla">
                                <input type="checkbox" checked={form.almacenes.includes(a.id)} onChange={() => alternarAlmacen(a.id)} />
                                {a.nombre}
                              </label>
                            </li>
                          ))}
                        </ul>
                      </fieldset>
                    ))}
                  </div>
                )}
                <p className="celda-suave tienda-almacenes-conteo" aria-live="polite">
                  {form.almacenes.length === 0 ? 'Ninguno marcado: la tienda no puede abrirse sin almacenes.' : `${form.almacenes.length} marcado${form.almacenes.length === 1 ? '' : 's'}.`}
                </p>
                {errores.almacenes && (
                  <p role="alert" className="campo-error">
                    {errores.almacenes}
                  </p>
                )}
              </PanelTarjeta>

              <ContenidoTienda datos={datos} form={form} errores={errores} cambiar={cambiar} clave={CLAVE} />

              {errores._general && !Object.keys(errores).some((k) => k !== '_general' && errores[k]) && (
                <p role="alert" className="campo-error">
                  {errores._general}
                </p>
              )}

              <div className="tienda-config-pie">
                <button type="submit" className="primario" disabled={!hayCambios || enviando}>
                  {enviando ? 'Guardando…' : 'Guardar cambios'}
                </button>
                {!hayCambios && !enviando && <small className="celda-suave">No hay cambios por guardar.</small>}
                {guardar.isSuccess && !hayCambios && (
                  <small className="tienda-guardado" role="status">
                    <Icono nombre="checklist" tam={16} /> Cambios guardados.
                  </small>
                )}
              </div>
            </form>

            <section className="tienda-ayuda" aria-label="Cómo se verá">
              <Icono nombre="ojo" tam={22} />
              <div>
                <strong>Cómo se verá</strong>
                <p>
                  La tienda pública se alimenta de esta configuración y de los productos que tengan activado <strong>«Mostrar en la tienda»</strong>.
                  Los cambios se ven de inmediato. Los productos sin foto, inactivos o sin publicar no aparecen.
                </p>
              </div>
            </section>
          </>
        )}
      </EstadoConsulta>

      {confirmarApertura && (
        <ConfirmarModal
          titulo="¿Abrir la tienda?"
          mensaje="El público podrá ver todos los productos publicados con sus precios y su disponibilidad. Puedes cerrarla cuando quieras."
          textoConfirmar="Abrir la tienda"
          enviando={enviando}
          onConfirmar={() => cambiarApertura(true)}
          onCerrar={() => setConfirmarApertura(false)}
        />
      )}
    </main>
  )
}
