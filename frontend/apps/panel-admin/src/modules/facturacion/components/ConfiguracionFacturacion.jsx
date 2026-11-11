import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Interruptor from '../../../shared/components/Interruptor'
import SelectorUbigeo from '../../../shared/components/SelectorUbigeo'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { MODOS } from '../facturacion'
import { useConfiguracionFe } from '../hooks/useFacturacion'
import '../facturacion.css'

const VACIO_SECRETOS = { usuario_sol: '', clave_sol: '', gre_client_id: '', gre_client_secret: '' }

/** Formulario ya con los datos de la empresa. Las claves solo se escriben: nunca se muestran. */
function Formulario({ config, empresaId, puedeEditar }) {
  const [f, setF] = useState({
    activo: config.activo,
    modo: config.modo,
    ubigeo_fiscal: config.ubigeo_fiscal,
    urbanizacion: config.urbanizacion,
    codigo_sunat_defecto: config.codigo_sunat_defecto,
    ...VACIO_SECRETOS,
  })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')
  const [prueba, setPrueba] = useState(null)

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.patch('/facturacion/configuracion/', cuerpo).then((r) => r.data),
    invalidar: [['facturacion', 'configuracion']],
    exito: 'Configuración guardada.',
    alExito: () => setF((previo) => ({ ...previo, ...VACIO_SECRETOS })),
    avisarError: false,
  })
  const probar = useMutacion({
    mutationFn: () => api.post('/facturacion/configuracion/probar/', { empresa: empresaId }, { timeout: 20_000 }).then((r) => r.data),
    avisarError: false,
  })

  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || !puedeEditar) return
    const e = {}
    if (f.ubigeo_fiscal && !/^\d{6}$/.test(f.ubigeo_fiscal)) e.ubigeo_fiscal = 'Elija el distrito de la lista.'
    if (f.codigo_sunat_defecto && !/^\d{8}$/.test(f.codigo_sunat_defecto)) e.codigo_sunat_defecto = 'Son 8 dígitos.'
    setErrores(e)
    setGeneral('')
    if (Object.keys(e).length) return
    // Solo se envían las claves que se escribieron: vacío = se conserva la que ya está guardada.
    const secretos = Object.fromEntries(Object.entries({ usuario_sol: f.usuario_sol, clave_sol: f.clave_sol, gre_client_id: f.gre_client_id, gre_client_secret: f.gre_client_secret }).filter(([, v]) => v !== ''))
    guardar.mutate(
      { empresa: empresaId, activo: f.activo, modo: f.modo, ubigeo_fiscal: f.ubigeo_fiscal, urbanizacion: f.urbanizacion.trim(), codigo_sunat_defecto: f.codigo_sunat_defecto, ...secretos },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores(delServidor)
          setGeneral(mensajeDeError(error))
        },
      },
    )
  }

  const hacerPrueba = () => {
    if (probar.isPending) return
    setPrueba(null)
    probar.mutate(undefined, { onSuccess: setPrueba, onError: (error) => setPrueba({ error: mensajeDeError(error) }) })
  }

  const puesta = (hay) => (hay ? 'Ya está guardada. Escribe solo si quieres cambiarla.' : 'Todavía no está guardada.')

  return (
    <form onSubmit={enviar} noValidate className="fe-config">
      <fieldset className="toma-fieldset" disabled={!puedeEditar || guardar.isPending}>
        {config.faltantes.length > 0 && (
          <div role="status" className="modal-aviso">
            Para poder facturar falta: {config.faltantes.join('; ')}.
          </div>
        )}
        <Interruptor activo={f.activo} onCambio={(v) => poner('activo', v)} texto="Facturación electrónica activa" descripcion="Apagada, nada se envía a SUNAT. Solo se puede activar con la configuración completa." />

        <Campo etiqueta="Modo" tipo="select" error={errores.modo} ayuda={f.modo === 'PRODUCCION' ? 'Cuidado: en producción los comprobantes son oficiales y llegan a SUNAT de verdad.' : 'En beta se envía al servidor de pruebas de SUNAT: no tiene efectos reales.'}>
          {(p) => (
            <select {...p} value={f.modo} onChange={(e) => poner('modo', e.target.value)}>
              {Object.entries(MODOS).map(([valor, texto]) => (
                <option key={valor} value={valor}>
                  {texto}
                </option>
              ))}
            </select>
          )}
        </Campo>

        <h4 className="fe-titulo">Clave SOL (usuario secundario)</h4>
        <div className="fila-campos">
          <Campo etiqueta="Usuario secundario SOL" error={errores.usuario_sol} ayuda={config.usuario_sol ? `Guardado: ${config.usuario_sol}. Escribe solo para cambiarlo.` : 'Todavía no está guardado.'}>
            {(p) => <input {...p} name="usuario_sol" autoComplete="off" maxLength={40} value={f.usuario_sol} onChange={(e) => poner('usuario_sol', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Clave del usuario secundario" error={errores.clave_sol} ayuda={puesta(config.clave_sol_puesta)}>
            {(p) => <input {...p} name="clave_sol" type="password" autoComplete="new-password" maxLength={80} value={f.clave_sol} onChange={(e) => poner('clave_sol', e.target.value)} />}
          </Campo>
        </div>

        <h4 className="fe-titulo">Guía de remisión electrónica</h4>
        <div className="fila-campos">
          <Campo etiqueta="Client ID" error={errores.gre_client_id} ayuda={puesta(config.gre_client_id_puesto)}>
            {(p) => <input {...p} name="gre_client_id" type="password" autoComplete="new-password" maxLength={80} value={f.gre_client_id} onChange={(e) => poner('gre_client_id', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Client secret" error={errores.gre_client_secret} ayuda={puesta(config.gre_client_secret_puesto)}>
            {(p) => <input {...p} name="gre_client_secret" type="password" autoComplete="new-password" maxLength={120} value={f.gre_client_secret} onChange={(e) => poner('gre_client_secret', e.target.value)} />}
          </Campo>
        </div>

        <h4 className="fe-titulo">Datos que pide la factura</h4>
        <p className="campo-ayuda">
          Dirección fiscal: <strong>{config.direccion_fiscal || 'sin registrar'}</strong>. Se toma de la ficha de la empresa (Seguridad › Empresas).
        </p>
        <Campo etiqueta="Distrito del domicilio fiscal" icono="ubicacion" error={errores.ubigeo_fiscal}>
          {(p) => <SelectorUbigeo {...p} valor={f.ubigeo_fiscal} onCambio={(v) => poner('ubigeo_fiscal', v)} disabled={!puedeEditar} />}
        </Campo>
        <div className="fila-campos">
          <Campo etiqueta="Urbanización" error={errores.urbanizacion}>
            {(p) => <input {...p} name="urbanizacion" maxLength={100} value={f.urbanizacion} onChange={(e) => poner('urbanizacion', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Código SUNAT por defecto de los productos" error={errores.codigo_sunat_defecto} ayuda="8 dígitos. Lo usan los productos que no tienen un código propio.">
            {(p) => <input {...p} name="codigo_sunat_defecto" inputMode="numeric" maxLength={8} placeholder="Ej. 43211503" value={f.codigo_sunat_defecto} onChange={(e) => poner('codigo_sunat_defecto', e.target.value.replace(/\D/g, ''))} />}
          </Campo>
        </div>
      </fieldset>

      {general && (
        <p role="alert" className="campo-error">
          {general}
        </p>
      )}
      {prueba && (
        <div role="status" className="modal-aviso">
          {prueba.error ? (
            prueba.error
          ) : (
            <>
              <strong>{prueba.api_alcanzable ? 'La API de facturación responde.' : 'No se pudo conectar con la API de facturación.'}</strong>
              {prueba.faltantes.length > 0 ? ` Falta configurar: ${prueba.faltantes.join('; ')}.` : ' La configuración está completa.'}
              {prueba.faltantes_guia.length > prueba.faltantes.length ? ` Para guías falta además: ${prueba.faltantes_guia.filter((x) => !prueba.faltantes.includes(x)).join('; ')}.` : ''}
            </>
          )}
        </div>
      )}
      <div className="fe-pie">
        <button type="button" onClick={hacerPrueba} disabled={probar.isPending || !puedeEditar}>
          {probar.isPending ? 'Probando…' : 'Probar conexión'}
        </button>
        {puedeEditar && (
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar configuración'}
          </button>
        )}
      </div>
      {!puedeEditar && <p className="campo-ayuda">No tienes permiso para cambiar esta configuración.</p>}
    </form>
  )
}

/** Configuración de la facturación electrónica de la empresa activa. */
export default function ConfiguracionFacturacion() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const consulta = useConfiguracionFe(empresaActivaId)
  return (
    <section aria-label="Configuración de la facturación electrónica">
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {consulta.data && <Formulario key={`${empresaActivaId}-${consulta.dataUpdatedAt}`} config={consulta.data} empresaId={empresaActivaId} puedeEditar={tiene('FACTURACION.CONFIGURAR')} />}
      </EstadoConsulta>
    </section>
  )
}
