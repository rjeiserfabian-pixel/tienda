import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { ALCANCES, useCatalogoPermisos } from '../hooks/useCatalogos'

const aIso = (fecha) => (fecha ? new Date(`${fecha}T23:59:59`).toISOString() : null)
const INICIAL = { codigo: '', tipo: 'DENY', empresa: '', alcance: 'EMPRESA', motivo: '', vigente_hasta: '' }

export default function ExcepcionesUsuario({ usuario, puedeEditar }) {
  const catalogo = useCatalogoPermisos()
  const [f, setF] = useState(INICIAL)
  const [errores, setErrores] = useState({})
  const [quitando, setQuitando] = useState(null)

  const nombreEmpresa = (id) => usuario.accesos.find((a) => a.empresa === id)?.empresa_nombre ?? `Empresa ${id}`

  const otorgar = useMutacion({
    mutationFn: (datos) => api.post(`/seguridad/usuarios/${usuario.id}/excepciones/`, datos).then((r) => r.data),
    invalidar: [['usuarios']],
    exito: 'Permiso individual guardado.',
    alExito: () => setF(INICIAL),
    avisarError: false,
  })
  const revocar = useMutacion({
    mutationFn: (id) => api.delete(`/seguridad/usuarios/${usuario.id}/excepciones/${id}/`),
    invalidar: [['usuarios']],
    exito: 'Permiso individual quitado.',
    alExito: () => setQuitando(null),
  })

  const cambiar = (e) => setF((p) => ({ ...p, [e.target.name]: e.target.value }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (otorgar.isPending) return
    const locales = {}
    if (!f.codigo) locales.codigo = 'Elija el permiso.'
    if (!f.motivo.trim()) locales.motivo = 'El motivo es obligatorio.'
    if (f.vigente_hasta && new Date(`${f.vigente_hasta}T23:59:59`) <= new Date()) {
      locales.vigente_hasta = 'La fecha debe ser futura.'
    }
    setErrores(locales)
    if (Object.keys(locales).length) return
    otorgar.mutate(
      { ...f, empresa: f.empresa ? Number(f.empresa) : null, vigente_hasta: aIso(f.vigente_hasta) },
      { onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }) },
    )
  }

  return (
    <section className="bloque" aria-labelledby="excepciones-titulo">
      <h3 id="excepciones-titulo">Permisos individuales</h3>
      <p className="campo-ayuda">
        Excepciones a los roles. «Denegar» siempre gana sobre cualquier rol. Todas requieren un motivo.
      </p>
      {usuario.excepciones.length === 0 ? (
        <p className="estado-vacio">Sin excepciones.</p>
      ) : (
        <table className="tabla">
          <thead>
            <tr><th>Permiso</th><th>Tipo</th><th>Empresa</th><th>Vence</th><th>Motivo</th><th /></tr>
          </thead>
          <tbody>
            {usuario.excepciones.map((x) => (
              <tr key={x.id}>
                <td>{x.codigo}</td>
                <td>
                  <span className={`etiqueta ${x.tipo === 'DENY' ? 'etiqueta-alerta' : 'etiqueta-ok'}`}>
                    {x.tipo === 'DENY' ? 'Denegar' : `Permitir (${x.alcance})`}
                  </span>
                </td>
                <td>{x.empresa ? nombreEmpresa(x.empresa) : 'Todas'}</td>
                <td>{x.vigente_hasta ? x.vigente_hasta.slice(0, 10) : '—'}</td>
                <td>{x.motivo}</td>
                <td>{puedeEditar && <button type="button" onClick={() => setQuitando(x)}>Quitar</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {puedeEditar && (
        <form onSubmit={enviar} noValidate style={{ maxWidth: 560, marginTop: 16 }}>
          <Campo etiqueta="Permiso" error={errores.codigo}>
            {(p) => (
              <select {...p} name="codigo" value={f.codigo} onChange={cambiar} disabled={catalogo.isLoading}>
                <option value="">{catalogo.isLoading ? 'Cargando…' : 'Elija un permiso'}</option>
                {(catalogo.data ?? []).map((c) => (
                  <option key={c.codigo} value={c.codigo}>{c.codigo} — {c.descripcion}</option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Tipo" error={errores.tipo}>
            {(p) => (
              <select {...p} name="tipo" value={f.tipo} onChange={cambiar}>
                <option value="DENY">Denegar</option>
                <option value="ALLOW">Permitir</option>
              </select>
            )}
          </Campo>
          {f.tipo === 'ALLOW' && (
            <Campo etiqueta="Alcance" error={errores.alcance}>
              {(p) => (
                <select {...p} name="alcance" value={f.alcance} onChange={cambiar}>
                  {ALCANCES.map(([valor, texto]) => <option key={valor} value={valor}>{texto}</option>)}
                </select>
              )}
            </Campo>
          )}
          <Campo etiqueta="Empresa" error={errores.empresa}>
            {(p) => (
              <select {...p} name="empresa" value={f.empresa} onChange={cambiar}>
                <option value="">Todas sus empresas</option>
                {usuario.accesos.map((a) => <option key={a.empresa} value={a.empresa}>{a.empresa_nombre}</option>)}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Vence (opcional)" error={errores.vigente_hasta}>
            {(p) => <input {...p} name="vigente_hasta" type="date" value={f.vigente_hasta} onChange={cambiar} />}
          </Campo>
          <Campo etiqueta="Motivo" error={errores.motivo}>
            {(p) => <input {...p} placeholder="Ej. Auditoría en curso o reemplazo temporal" name="motivo" maxLength={500} value={f.motivo} onChange={cambiar} />}
          </Campo>
          {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
          <button type="submit" className="primario" disabled={otorgar.isPending}>
            {otorgar.isPending ? 'Guardando…' : 'Guardar permiso individual'}
          </button>
        </form>
      )}

      {quitando && (
        <ConfirmarModal
          titulo="Quitar permiso individual"
          mensaje={`¿Quitar la excepción sobre ${quitando.codigo}? El usuario volverá a lo que digan sus roles.`}
          textoConfirmar="Quitar"
          enviando={revocar.isPending}
          onConfirmar={() => revocar.mutate(quitando.id)}
          onCerrar={() => setQuitando(null)}
        />
      )}
    </section>
  )
}
