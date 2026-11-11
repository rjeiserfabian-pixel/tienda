import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { cambiosDelArmador, desdeServidor, espacioDeCategoria, MAX_UNIDADES, revisarArmador } from '../armador'
import '../tienda.css'
import '../armador.css'

const CLAVE = ['tienda', 'armador']

/** Arma tu PC: qué categorías llenan cada espacio y qué reglas de compatibilidad se usan. */
export default function ArmadorTiendaPage() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/tienda/admin/armador/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const datos = consulta.data

  const [form, setForm] = useState(null)
  const [errores, setErrores] = useState({})

  // El formulario se reinicia solo cuando cambian los datos guardados.
  const clave = useMemo(() => (datos ? JSON.stringify(desdeServidor(datos)) : null), [datos])
  useEffect(() => {
    if (clave) setForm(JSON.parse(clave))
  }, [clave])

  const cambios = useMemo(() => (datos && form ? cambiosDelArmador(datos, form) : {}), [datos, form])
  const hayCambios = Object.keys(cambios).length > 0

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/tienda/admin/armador/', cuerpo).then((r) => r.data),
    invalidar: [CLAVE],
    exito: 'Configuración de «Arma tu PC» guardada.',
    avisarError: false,
    alExito: () => setErrores({}),
  })

  const categorias = useMemo(() => datos?.opciones?.categorias ?? [], [datos])
  const nombreCategoria = useMemo(() => new Map(categorias.map((c) => [c.id, `${c.familia} › ${c.nombre}`])), [categorias])
  const ocupadas = useMemo(() => (form ? espacioDeCategoria(form) : new Map()), [form])

  const cambiarEspacio = (claveEspacio, parche) => {
    setForm((f) => ({ ...f, espacios: f.espacios.map((e) => (e.clave === claveEspacio ? { ...e, ...parche } : e)) }))
    setErrores({})
  }
  const cambiarRegla = (id, parche) => {
    setForm((f) => ({ ...f, reglas: { ...f.reglas, [id]: { ...f.reglas[id], ...parche } } }))
    setErrores({})
  }

  const alEnviar = (evento) => {
    evento.preventDefault()
    const locales = revisarArmador(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    guardar.mutate(cambios, {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }

  const hayEspacioConCategorias = form?.espacios.some((e) => e.categorias.length > 0)

  return (
    <main className="listado tienda-pagina armador-pagina">
      <CabeceraListado
        icono="devices"
        titulo="Arma tu PC"
        descripcion="Un armador guiado para que tus clientes elijan piezas compatibles entre sí. Tú decides qué categorías llenan cada espacio; la compatibilidad se verifica con las especificaciones de tus productos."
      />

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && form && (
          <form onSubmit={alEnviar} noValidate className="armador-form" aria-label="Configuración de Arma tu PC">
            <PanelTarjeta id="armador-estado" icono="devices" titulo="Estado" descripcion="Mientras esté apagado, la tienda muestra «Arma tu PC» como próximamente.">
              <Interruptor
                activo={form.activo}
                onCambio={(v) => {
                  setForm((f) => ({ ...f, activo: v }))
                  setErrores({})
                }}
                texto={form.activo ? 'Armador activado' : 'Armador desactivado'}
                descripcion={
                  form.activo ? 'Los clientes ven «Arma tu PC» en la tienda.' : 'Actívalo cuando hayas elegido las categorías de cada espacio.'
                }
              />
              {!hayEspacioConCategorias && (
                <p className="armador-aviso" role="status">
                  <Icono nombre="bell" tam={18} /> Elige las categorías de al menos un espacio para poder activarlo.
                </p>
              )}
              {errores.activo && (
                <p role="alert" className="campo-error">
                  {errores.activo}
                </p>
              )}
            </PanelTarjeta>

            <PanelTarjeta
              id="armador-espacios"
              icono="boxes"
              titulo="Espacios y categorías"
              descripcion="Cada espacio es una pieza de la PC. Elige qué categorías de tu catálogo la llenan. Una categoría solo puede estar en un espacio. Los espacios sin categorías no se muestran."
            >
              <ul className="armador-espacios">
                {form.espacios.map((e) => {
                  const def = datos.espacios.find((x) => x.clave === e.clave)
                  const libres = categorias.filter((c) => !ocupadas.has(c.id))
                  return (
                    <li key={e.clave} className="armador-espacio">
                      <div className="armador-espacio-cab">
                        <strong>{def.nombre}</strong>
                        <small className="celda-suave">{def.ayuda}</small>
                      </div>
                      {e.categorias.length > 0 ? (
                        <ul className="armador-chips" aria-label={`Categorías de ${def.nombre}`}>
                          {e.categorias.map((id) => (
                            <li key={id}>
                              <span>{nombreCategoria.get(id) ?? `Categoría ${id}`}</span>
                              <button
                                type="button"
                                aria-label={`Quitar ${nombreCategoria.get(id) ?? id} de ${def.nombre}`}
                                onClick={() => cambiarEspacio(e.clave, { categorias: e.categorias.filter((c) => c !== id) })}
                              >
                                ×
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="celda-suave armador-vacio">Sin categorías: no se mostrará.</p>
                      )}
                      <div className="armador-espacio-controles">
                        <label className="armador-agregar">
                          <span className="sr-only">Agregar una categoría a {def.nombre}</span>
                          <select
                            value=""
                            onChange={(ev) => {
                              const id = Number(ev.target.value)
                              if (id) cambiarEspacio(e.clave, { categorias: [...e.categorias, id] })
                            }}
                            disabled={libres.length === 0}
                          >
                            <option value="">{libres.length ? '+ Agregar categoría…' : 'No quedan categorías libres'}</option>
                            {libres.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.familia} › {c.nombre}
                              </option>
                            ))}
                          </select>
                        </label>
                        <Interruptor
                          activo={e.obligatorio}
                          onCambio={(v) => cambiarEspacio(e.clave, { obligatorio: v })}
                          texto={e.obligatorio ? 'Obligatorio' : 'Opcional'}
                          descripcion=""
                        />
                        <label className="armador-max">
                          <span>Unidades máx.</span>
                          <input
                            type="number"
                            min={1}
                            max={MAX_UNIDADES}
                            inputMode="numeric"
                            value={e.max_unidades}
                            onChange={(ev) => cambiarEspacio(e.clave, { max_unidades: ev.target.value })}
                            aria-invalid={errores[`max_${e.clave}`] ? 'true' : undefined}
                          />
                        </label>
                      </div>
                      {errores[`max_${e.clave}`] && (
                        <p role="alert" className="campo-error">
                          {errores[`max_${e.clave}`]}
                        </p>
                      )}
                    </li>
                  )
                })}
              </ul>
              {errores.espacios && (
                <p role="alert" className="campo-error">
                  {errores.espacios}
                </p>
              )}
            </PanelTarjeta>

            <PanelTarjeta
              id="armador-reglas"
              icono="checklist"
              titulo="Reglas de compatibilidad"
              descripcion="Comparan datos de las especificaciones de los productos. Si a un producto le falta el dato, el cliente ve «no pudimos verificarlo» (nunca se afirma compatibilidad sin dato). Solo lo incompatible bloquea el «agregar todo al carrito»."
            >
              <ul className="armador-reglas">
                {datos.reglas.map((r) => {
                  const estado = form.reglas[r.id]
                  // Falta un dato si el espacio tiene categorías pero ninguna trae el campo elegido.
                  const faltan = Object.entries(r.claves).filter(
                    ([alias, c]) => c.espacio_configurado && !(datos.opciones.campos[c.espacio] ?? []).some((o) => o.clave === estado.claves[alias]),
                  )
                  return (
                    <li key={r.id} className="armador-regla">
                      <details>
                        <summary>
                          <span className="armador-regla-nombre">
                            <strong>{r.nombre}</strong>
                            <small className="celda-suave">{r.descripcion}</small>
                          </span>
                          {estado.activa && faltan.length > 0 && <span className="armador-etiqueta">Falta un campo</span>}
                          {!estado.activa && <span className="armador-etiqueta apagada">Apagada</span>}
                        </summary>
                        <div className="armador-regla-cuerpo">
                          <Interruptor
                            activo={estado.activa}
                            onCambio={(v) => cambiarRegla(r.id, { activa: v })}
                            texto={estado.activa ? 'Regla activa' : 'Regla apagada'}
                            descripcion=""
                          />
                          <div className="armador-claves">
                            {Object.entries(r.claves).map(([alias, c]) => {
                              const opciones = datos.opciones.campos[c.espacio] ?? []
                              const actual = estado.claves[alias]
                              const existe = opciones.some((o) => o.clave === actual)
                              return (
                                <label key={alias} className="armador-clave">
                                  <span>Dato de «{c.espacio_nombre}»</span>
                                  <select value={actual} onChange={(ev) => cambiarRegla(r.id, { claves: { ...estado.claves, [alias]: ev.target.value } })}>
                                    {!existe && <option value={actual}>{actual} (no existe en sus categorías)</option>}
                                    {opciones.map((o) => (
                                      <option key={o.clave} value={o.clave}>
                                        {o.nombre}
                                        {o.clave === c.defecto ? ' (recomendado)' : ''}
                                      </option>
                                    ))}
                                  </select>
                                  {!c.espacio_configurado ? (
                                    <small className="celda-suave">Este espacio aún no tiene categorías.</small>
                                  ) : !existe ? (
                                    <small className="armador-falta">
                                      Las categorías de este espacio no tienen el campo «{c.defecto}». Cárgales la plantilla en Especificaciones.
                                    </small>
                                  ) : null}
                                </label>
                              )
                            })}
                          </div>
                        </div>
                      </details>
                    </li>
                  )
                })}
              </ul>
              {errores.reglas && (
                <p role="alert" className="campo-error">
                  {errores.reglas}
                </p>
              )}
            </PanelTarjeta>

            {errores._general && !errores.activo && !errores.espacios && !errores.reglas && (
              <p role="alert" className="campo-error">
                {errores._general}
              </p>
            )}
            <div className="armador-pie">
              <button type="submit" className="primario" disabled={!hayCambios || guardar.isPending}>
                {guardar.isPending ? 'Guardando…' : 'Guardar'}
              </button>
              {datos.activo && datos.listo && <small className="celda-suave">El armador está visible en la tienda: /arma-tu-pc</small>}
            </div>
          </form>
        )}
      </EstadoConsulta>
    </main>
  )
}
