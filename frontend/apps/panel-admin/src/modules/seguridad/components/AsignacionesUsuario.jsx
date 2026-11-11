import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useRolesParaSelector } from '../hooks/useCatalogos'

const aIso = (fecha) => (fecha ? new Date(`${fecha}T23:59:59`).toISOString() : null)

export default function AsignacionesUsuario({ usuario, puedeEditar }) {
  const roles = useRolesParaSelector()
  const [f, setF] = useState({ rol: '', empresa: '', vigente_hasta: '' })
  const [errores, setErrores] = useState({})
  const [quitando, setQuitando] = useState(null)

  const nombreEmpresa = (id) => usuario.accesos.find((a) => a.empresa === id)?.empresa_nombre ?? `Empresa ${id}`

  const asignar = useMutacion({
    mutationFn: (datos) => api.post(`/seguridad/usuarios/${usuario.id}/roles/`, datos).then((r) => r.data),
    invalidar: [['usuarios'], ['roles']],
    exito: 'Rol asignado.',
    alExito: () => setF({ rol: '', empresa: '', vigente_hasta: '' }),
    avisarError: false,
  })
  const quitar = useMutacion({
    mutationFn: (id) => api.delete(`/seguridad/usuarios/${usuario.id}/roles/${id}/`),
    invalidar: [['usuarios'], ['roles']],
    exito: 'Rol quitado.',
    alExito: () => setQuitando(null),
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (asignar.isPending) return
    if (!f.rol) return setErrores({ rol: 'Elija un rol.' })
    if (f.vigente_hasta && new Date(`${f.vigente_hasta}T23:59:59`) <= new Date()) {
      return setErrores({ vigente_hasta: 'La fecha debe ser futura.' })
    }
    setErrores({})
    asignar.mutate(
      { rol: Number(f.rol), empresa: f.empresa ? Number(f.empresa) : null, vigente_hasta: aIso(f.vigente_hasta) },
      { onError: (error) => setErrores({ general: 'No se pudo asignar el rol.', ...erroresDeCampo(error) }) },
    )
  }

  return (
    <section className="bloque" aria-labelledby="roles-titulo">
      <h3 id="roles-titulo">Roles asignados</h3>
      {usuario.asignaciones.length === 0 ? (
        <p className="estado-vacio">Sin roles: el usuario no puede hacer nada todavía.</p>
      ) : (
        <table className="tabla">
          <thead>
            <tr><th>Rol</th><th>Empresa</th><th>Vence</th><th /></tr>
          </thead>
          <tbody>
            {usuario.asignaciones.map((a) => (
              <tr key={a.id}>
                <td>{a.rol.nombre} <span className="etiqueta">{a.rol.codigo}</span></td>
                <td>{a.empresa ? nombreEmpresa(a.empresa) : 'Todas sus empresas'}</td>
                <td>{a.vigente_hasta ? a.vigente_hasta.slice(0, 10) : '—'}</td>
                <td>
                  {puedeEditar && <button type="button" onClick={() => setQuitando(a)}>Quitar</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {puedeEditar && (
        <form onSubmit={enviar} noValidate className="barra" style={{ alignItems: 'flex-start' }}>
          <Campo etiqueta="Rol" error={errores.rol}>
            {(p) => (
              <select {...p} value={f.rol} onChange={(e) => setF({ ...f, rol: e.target.value })} disabled={roles.isLoading}>
                <option value="">{roles.isLoading ? 'Cargando…' : 'Elija un rol'}</option>
                {(roles.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>{r.nombre}</option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Empresa" error={errores.empresa}>
            {(p) => (
              <select {...p} value={f.empresa} onChange={(e) => setF({ ...f, empresa: e.target.value })}>
                <option value="">Todas sus empresas</option>
                {usuario.accesos.map((a) => (
                  <option key={a.empresa} value={a.empresa}>{a.empresa_nombre}</option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Vence (opcional)" error={errores.vigente_hasta}>
            {(p) => <input {...p} type="date" value={f.vigente_hasta} onChange={(e) => setF({ ...f, vigente_hasta: e.target.value })} />}
          </Campo>
          <div style={{ alignSelf: 'center', marginTop: 12 }}>
            <button type="submit" className="primario" disabled={asignar.isPending}>
              {asignar.isPending ? 'Asignando…' : 'Asignar rol'}
            </button>
          </div>
          {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        </form>
      )}

      {quitando && (
        <ConfirmarModal
          titulo="Quitar rol"
          mensaje={`¿Quitar el rol ${quitando.rol.nombre} a ${usuario.username}?`}
          textoConfirmar="Quitar rol"
          enviando={quitar.isPending}
          onConfirmar={() => quitar.mutate(quitando.id)}
          onCerrar={() => setQuitando(null)}
        />
      )}
    </section>
  )
}
