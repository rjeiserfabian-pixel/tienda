import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { agruparEventos, cambiosDeWhatsApp, desdeServidor, MAX_TOKEN, MODOS, revisarWhatsApp } from '../whatsapp'
import '../../tienda/pagos.css'
import '../whatsapp.css'

const CLAVE = ['organizacion', 'whatsapp']

/** Copia un texto al portapapeles (si el navegador no deja, no pasa nada). */
async function copiar(texto) {
  try {
    await navigator.clipboard.writeText(texto)
    return true
  } catch {
    return false
  }
}

/** WhatsApp Business: la cuenta de Meta del negocio, compartida por la tienda y el servicio técnico. */
export default function WhatsAppPage() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/organizacion/whatsapp/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  const datos = consulta.data

  const [form, setForm] = useState(null)
  const [errores, setErrores] = useState({})
  const [cambiandoToken, setCambiandoToken] = useState(false)
  const [confirmarActivo, setConfirmarActivo] = useState(false)
  const [telefonoPrueba, setTelefonoPrueba] = useState('')
  const [resultado, setResultado] = useState(null) // { ok, mensaje } del mensaje de prueba
  const [copiado, setCopiado] = useState('')

  // El formulario se reinicia solo cuando cambian los datos guardados (el token nunca vuelve).
  const clave = useMemo(() => (datos ? JSON.stringify(desdeServidor(datos)) : null), [datos])
  useEffect(() => {
    if (clave) {
      setForm(JSON.parse(clave))
      setCambiandoToken(false)
    }
  }, [clave])

  const cambios = useMemo(() => (datos && form ? cambiosDeWhatsApp(datos, form) : {}), [datos, form])
  const hayCambios = Object.keys(cambios).length > 0

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/organizacion/whatsapp/', cuerpo).then((r) => r.data),
    invalidar: [CLAVE],
    exito: 'Configuración de WhatsApp guardada.',
    avisarError: false,
    alExito: () => {
      setForm((f) => (f ? { ...f, token: '', quitar_token: false } : f))
      setCambiandoToken(false)
      setResultado(null)
    },
  })

  const probar = useMutacion({
    mutationFn: (telefono) => api.post('/organizacion/whatsapp/probar/', { telefono }).then((r) => r.data),
    avisarError: false,
    alExito: (r) => setResultado(r),
  })

  const poner = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined, _general: undefined }))
    setResultado(null)
  }
  const ponerPlantilla = (clavePlantilla, valor) => {
    setForm((f) => ({ ...f, plantillas: { ...f.plantillas, [clavePlantilla]: valor } }))
    setErrores((e) => ({ ...e, [`plantilla_${clavePlantilla}`]: undefined, _general: undefined }))
  }

  const enviar = () => {
    setConfirmarActivo(false)
    guardar.mutate(cambios, {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }

  const alEnviar = (evento) => {
    evento.preventDefault()
    const locales = revisarWhatsApp(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    // Activar manda mensajes reales a clientes reales: se pide confirmación explícita.
    if (cambios.modo === 'ACTIVO') setConfirmarActivo(true)
    else enviar()
  }

  const probarEnvio = () => {
    setResultado(null)
    probar.mutate(telefonoPrueba, { onError: (error) => setResultado({ ok: false, mensaje: mensajeDeError(error) }) })
  }

  const copiarTexto = async (claveEvento, texto) => {
    const ok = await copiar(texto)
    setCopiado(ok ? claveEvento : '')
    if (ok) setTimeout(() => setCopiado(''), 1800)
  }

  const grupos = useMemo(() => agruparEventos(datos?.eventos), [datos])
  const hayTokenGuardado = Boolean(datos?.tiene_token)
  const quitandoToken = Boolean(form?.quitar_token)
  const tokenPendiente = Boolean(form && (form.token.trim() || quitandoToken))
  const faltan = datos?.faltan_para_activar ?? []
  const hayErrorDeCampo = Object.entries(errores).some(([k, v]) => k !== '_general' && v)

  return (
    <main className="listado tienda-pagina pagos-pagina whatsapp-pagina">
      <CabeceraListado
        icono="chat"
        titulo="WhatsApp Business"
        descripcion="Conecta la cuenta de WhatsApp de tu negocio para avisar a tus clientes de sus pedidos (tienda) y de sus equipos (servicio técnico). Mientras esté apagado, todo sigue funcionando por correo."
      />

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && form && (
          <>
            <ol className="pagos-pasos" aria-label="Cómo conectar WhatsApp Business">
              <li>
                Entra a <strong>business.facebook.com</strong>, crea tu cuenta de empresa y agrega <em>WhatsApp → API de WhatsApp Business</em> con tu número.
              </li>
              <li>
                Copia el <strong>ID del número de teléfono</strong> y crea un <strong>token permanente</strong> (usuario del sistema). Pégalos abajo.
              </li>
              <li>
                Crea las <strong>plantillas</strong> en Meta con los textos sugeridos de abajo y espera a que las aprueben (suele tardar minutos u horas).
              </li>
              <li>
                Escribe aquí el nombre de cada plantilla, prueba con tu celular y activa.
              </li>
            </ol>

            <form onSubmit={alEnviar} noValidate className="pagos-form" aria-label="Configuración de WhatsApp Business">
              <PanelTarjeta id="wa-modo" icono="chat" titulo="Estado" descripcion="Empieza en «Prueba» para ver que todo funciona sin enviar nada real.">
                <div className="pagos-modos" role="group" aria-label="Modo de WhatsApp">
                  {Object.entries(MODOS).map(([valor, m]) => (
                    <button key={valor} type="button" className="pagos-modo" aria-pressed={form.modo === valor} onClick={() => poner('modo', valor)}>
                      <strong>{m.texto}</strong>
                      <small>{m.detalle}</small>
                    </button>
                  ))}
                </div>
                {form.modo === 'ACTIVO' && faltan.length > 0 && (
                  <div className="pagos-alerta" role="status">
                    <Icono nombre="bell" tam={18} />
                    <span>Para activar falta: {faltan.join(' ')}</span>
                  </div>
                )}
                {errores.modo && (
                  <p role="alert" className="campo-error">
                    {errores.modo}
                  </p>
                )}
              </PanelTarjeta>

              <PanelTarjeta id="wa-cuenta" icono="key" titulo="Cuenta de WhatsApp Business" descripcion="El token se guarda cifrado y nadie, ni tú, puede volver a verlo.">
                <div className="pagos-rejilla">
                  <Campo etiqueta="Número de WhatsApp Business" error={errores.numero} ayuda="Solo para que lo recuerdes (el que ven tus clientes).">
                    {(p) => <input {...p} name="numero" inputMode="tel" autoComplete="off" maxLength={20} value={form.numero} onChange={(e) => poner('numero', e.target.value)} />}
                  </Campo>
                  <Campo etiqueta="ID del número de teléfono" error={errores.telefono_id} ayuda="Está en Meta, en WhatsApp → API. Es un número largo (no es tu teléfono).">
                    {(p) => <input {...p} name="telefono_id" inputMode="numeric" autoComplete="off" spellCheck={false} maxLength={40} value={form.telefono_id} onChange={(e) => poner('telefono_id', e.target.value)} />}
                  </Campo>
                  <Campo etiqueta="Token de acceso" error={errores.token} ayuda="Token permanente del usuario del sistema. Se guarda cifrado.">
                    {(p) => (
                      <div className="pagos-secreta">
                        <input
                          {...p}
                          name="token"
                          type="password"
                          autoComplete="new-password"
                          spellCheck={false}
                          maxLength={MAX_TOKEN}
                          disabled={(hayTokenGuardado && !cambiandoToken) || quitandoToken}
                          placeholder={quitandoToken ? 'Se quitará al guardar' : hayTokenGuardado ? `••••••••${datos.token_final} (guardado)` : 'Pega aquí tu token'}
                          value={form.token}
                          onChange={(e) => poner('token', e.target.value)}
                        />
                        {hayTokenGuardado && !cambiandoToken && !quitandoToken && (
                          <>
                            <button type="button" onClick={() => setCambiandoToken(true)}>
                              Cambiar
                            </button>
                            <button type="button" className="peligro" onClick={() => poner('quitar_token', true)}>
                              Quitar
                            </button>
                          </>
                        )}
                        {cambiandoToken && (
                          <button
                            type="button"
                            onClick={() => {
                              setCambiandoToken(false)
                              poner('token', '')
                            }}
                          >
                            Cancelar
                          </button>
                        )}
                        {quitandoToken && (
                          <button type="button" onClick={() => poner('quitar_token', false)}>
                            Deshacer
                          </button>
                        )}
                      </div>
                    )}
                  </Campo>
                  <Campo etiqueta="Versión de la API" error={errores.version_api} ayuda="Déjala como está salvo que Meta pida otra.">
                    {(p) => <input {...p} name="version_api" autoComplete="off" spellCheck={false} maxLength={10} value={form.version_api} onChange={(e) => poner('version_api', e.target.value)} />}
                  </Campo>
                  <Campo etiqueta="Idioma de las plantillas" error={errores.idioma} ayuda="Normalmente «es». Debe coincidir con el idioma con que creaste las plantillas.">
                    {(p) => <input {...p} name="idioma" autoComplete="off" spellCheck={false} maxLength={10} value={form.idioma} onChange={(e) => poner('idioma', e.target.value)} />}
                  </Campo>
                </div>
              </PanelTarjeta>

              <PanelTarjeta
                id="wa-plantillas"
                icono="checklist"
                titulo="Plantillas de los avisos"
                descripcion="WhatsApp solo deja que un negocio escriba primero con plantillas aprobadas por Meta. Copia el texto, créala en Meta y escribe aquí su nombre."
              >
                {grupos.map((g) => (
                  <section key={g.modulo} className="wa-grupo" aria-label={g.modulo}>
                    <h3>{g.modulo}</h3>
                    <ul className="wa-lista">
                      {g.eventos.map((ev) => (
                        <li key={ev.clave} className="wa-aviso">
                          <div className="wa-aviso-cab">
                            <strong>{ev.nombre}</strong>
                            <button type="button" className="wa-copiar" onClick={() => copiarTexto(ev.clave, ev.texto_sugerido)}>
                              {copiado === ev.clave ? '¡Copiado!' : 'Copiar texto sugerido'}
                            </button>
                          </div>
                          <p className="wa-texto">{ev.texto_sugerido}</p>
                          <Campo etiqueta="Nombre de la plantilla en Meta" error={errores[`plantilla_${ev.clave}`]}>
                            {(p) => (
                              <input
                                {...p}
                                name={`plantilla_${ev.clave}`}
                                autoComplete="off"
                                spellCheck={false}
                                maxLength={80}
                                placeholder="ej. pedido_pagado"
                                value={form.plantillas[ev.clave] ?? ''}
                                onChange={(e) => ponerPlantilla(ev.clave, e.target.value)}
                              />
                            )}
                          </Campo>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
                <p className="celda-suave">
                  En cada plantilla las variables van en este orden: <strong>{'{{1}}'}</strong> nombre del cliente, <strong>{'{{2}}'}</strong> número de pedido u orden, <strong>{'{{3}}'}</strong> enlace.
                </p>
              </PanelTarjeta>

              {errores._general && !hayErrorDeCampo && (
                <p role="alert" className="campo-error">
                  {errores._general}
                </p>
              )}

              <div className="pagos-pie">
                <button type="submit" className="primario" disabled={!hayCambios || guardar.isPending}>
                  {guardar.isPending ? 'Guardando…' : 'Guardar'}
                </button>
                {!hayCambios && !hayTokenGuardado && <small className="celda-suave">Aún no hay cuenta conectada.</small>}
              </div>
            </form>

            <PanelTarjeta id="wa-prueba" icono="bell" titulo="Mensaje de prueba" descripcion="Comprueba que la cuenta funciona enviando un mensaje a tu propio celular. Guarda antes los cambios.">
              <div className="wa-prueba">
                <Campo etiqueta="Tu celular">
                  {(p) => <input {...p} name="telefono_prueba" inputMode="tel" autoComplete="off" maxLength={30} placeholder="987 654 321" value={telefonoPrueba} onChange={(e) => setTelefonoPrueba(e.target.value)} />}
                </Campo>
                <button type="button" onClick={probarEnvio} disabled={!telefonoPrueba.trim() || hayCambios || tokenPendiente || probar.isPending}>
                  {probar.isPending ? 'Enviando…' : 'Enviar mensaje de prueba'}
                </button>
              </div>
              {hayCambios && <small className="celda-suave">Guarda primero los cambios para probar con ellos.</small>}
              {resultado && (
                <p role="status" className={`pagos-alerta pagos-resultado ${resultado.ok ? 'ok' : 'peligro'}`}>
                  <Icono nombre={resultado.ok ? 'checklist' : 'bell'} tam={18} />
                  <span>{resultado.mensaje}</span>
                </p>
              )}
            </PanelTarjeta>
          </>
        )}
      </EstadoConsulta>

      {confirmarActivo && (
        <ConfirmarModal
          titulo="¿Activar WhatsApp?"
          mensaje="Desde este momento se enviarán mensajes reales de WhatsApp a tus clientes (pedidos de la tienda y equipos de servicio técnico). ¿Ya probaste con tu propio celular?"
          textoConfirmar="Sí, activar"
          enviando={guardar.isPending}
          onConfirmar={enviar}
          onCerrar={() => setConfirmarActivo(false)}
        />
      )}
    </main>
  )
}
