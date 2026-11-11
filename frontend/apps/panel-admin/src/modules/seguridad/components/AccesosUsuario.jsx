import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const aFechaLocal = (iso) => (iso ? iso.slice(0, 10) : '')
// El vencimiento es "hasta el fin de ese día" (hora local), nunca a medianoche.
const aIso = (fecha) => (fecha ? new Date(`${fecha}T23:59:59`).toISOString() : null)

function AccesoModal({ usuario, acceso, empresa, onCerrar }) {
  const [f, setF] = useState({
    cargo: acceso?.cargo ?? '',
    estado: acceso?.estado ?? 'ACTIVO',
    vigente_hasta: aFechaLocal(acceso?.vigente_hasta),
    sucursales: acceso?.sucursales ?? [],
  })
  const [errores, setErrores] = useState({})

  const sucursales = useQuery({
    queryKey: ['sucursales', 'de-empresa', empresa.id],
    queryFn: ({ signal }) =>
      api
        .get('/organizacion/sucursales/', { params: { empresa: empresa.id, page_size: 100 }, signal })
        .then((r) => r.data.results),
  })

  const guardar = useMutacion({
    mutationFn: (datos) =>
      api.put(`/seguridad/usuarios/${usuario.id}/accesos/${empresa.id}/`, datos).then((r) => r.data),
    invalidar: [['usuarios']],
    exito: 'Acceso guardado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const alternar = (id) =>
    setF((p) => ({
      ...p,
      sucursales: p.sucursales.includes(id) ? p.sucursales.filter((x) => x !== id) : [...p.sucursales, id],
    }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    if (f.vigente_hasta && new Date(`${f.vigente_hasta}T23:59:59`) <= new Date()) {
      return setErrores({ vigente_hasta: 'La fecha debe ser futura.' })
    }
    setErrores({})
    guardar.mutate(
      { ...f, vigente_hasta: aIso(f.vigente_hasta) },
      { onError: (error) => setErrores({ general: 'No se pudo guardar el acceso.', ...erroresDeCampo(error) }) },
    )
  }

  return (
    <Modal
      titulo={`Acceso a ${empresa.razon_social ?? empresa.empresa_nombre}`}
      subtitulo="Define el cargo, la vigencia y las sucursales del usuario en esta empresa."
      onCerrar={onCerrar}
    >
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Cargo" icono="user" error={errores.cargo}>
          {(p) => <input {...p} placeholder="Ej. Vendedor" value={f.cargo} onChange={(e) => setF({ ...f, cargo: e.target.value })} />}
        </Campo>
        <Campo etiqueta="Estado" icono="settings" tipo="select" error={errores.estado}>
          {(p) => (
            <select {...p} value={f.estado} onChange={(e) => setF({ ...f, estado: e.target.value })}>
              <option value="ACTIVO">Activo</option>
              <option value="INACTIVO">Inactivo</option>
              <option value="SUSPENDIDO">Suspendido</option>
            </select>
          )}
        </Campo>
        <Campo etiqueta="Vence (opcional)" icono="calendario" error={errores.vigente_hasta}>
          {(p) => (
            <input {...p} type="date" value={f.vigente_hasta} onChange={(e) => setF({ ...f, vigente_hasta: e.target.value })} />
          )}
        </Campo>
        <fieldset className="grupo">
          <legend>Sucursales habilitadas</legend>
          {sucursales.isLoading && <p aria-busy="true">Cargando sucursales…</p>}
          {sucursales.isError && <p role="alert" className="campo-error">No se pudieron cargar las sucursales.</p>}
          {(sucursales.data ?? []).map((s) => (
            <label key={s.id} style={{ display: 'block' }}>
              <input type="checkbox" checked={f.sucursales.includes(s.id)} onChange={() => alternar(s.id)} /> {s.nombre} [{s.codigo}]
            </label>
          ))}
          <small className="campo-ayuda">
            Solo afectan a los permisos con alcance «Sus sucursales». Los permisos de alcance empresa
            no dependen de esta lista.
          </small>
          {errores.sucursales && <small role="alert" className="campo-error">{errores.sucursales}</small>}
        </fieldset>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending || sucursales.isLoading}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function AccesosUsuario({ usuario, puedeEditar }) {
  const { empresas } = useEmpresas()
  const [editando, setEditando] = useState(null) // { empresa, acceso|null }
  const [quitando, setQuitando] = useState(null)

  const quitar = useMutacion({
    mutationFn: (empresaId) => api.delete(`/seguridad/usuarios/${usuario.id}/accesos/${empresaId}/`),
    invalidar: [['usuarios']],
    exito: 'Acceso quitado.',
    alExito: () => setQuitando(null),
  })

  const conAcceso = new Set(usuario.accesos.map((a) => a.empresa))
  const disponibles = empresas.filter((e) => !conAcceso.has(e.id))

  return (
    <section className="bloque" aria-labelledby="accesos-titulo">
      <div className="cabecera-pagina">
        <h3 id="accesos-titulo">Accesos a empresas</h3>
        {puedeEditar && disponibles.length > 0 && (
          <select
            aria-label="Dar acceso a una empresa"
            value=""
            onChange={(e) => {
              const empresa = empresas.find((x) => x.id === Number(e.target.value))
              if (empresa) setEditando({ empresa, acceso: null })
            }}
          >
            <option value="">+ Dar acceso a empresa…</option>
            {disponibles.map((e) => (
              <option key={e.id} value={e.id}>{e.razon_social}</option>
            ))}
          </select>
        )}
      </div>
      {usuario.accesos.length === 0 ? (
        <p className="estado-vacio">El usuario no tiene acceso a ninguna empresa.</p>
      ) : (
        <table className="tabla">
          <thead>
            <tr><th>Empresa</th><th>Cargo</th><th>Estado</th><th>Vence</th><th>Sucursales</th><th /></tr>
          </thead>
          <tbody>
            {usuario.accesos.map((a) => (
              <tr key={a.empresa}>
                <td>{a.empresa_nombre}</td>
                <td>{a.cargo || '—'}</td>
                <td><span className={`etiqueta ${a.estado === 'ACTIVO' ? 'etiqueta-ok' : 'etiqueta-aviso'}`}>{a.estado}</span></td>
                <td>{aFechaLocal(a.vigente_hasta) || '—'}</td>
                <td>{a.sucursales.length || '—'}</td>
                <td>
                  {puedeEditar && (
                    <>
                      <button type="button" onClick={() => setEditando({ empresa: { id: a.empresa, razon_social: a.empresa_nombre }, acceso: a })}>
                        Editar
                      </button>{' '}
                      <button type="button" onClick={() => setQuitando(a)}>Quitar</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editando && (
        <AccesoModal usuario={usuario} acceso={editando.acceso} empresa={editando.empresa} onCerrar={() => setEditando(null)} />
      )}
      {quitando && (
        <ConfirmarModal
          titulo="Quitar acceso"
          mensaje={`¿Quitar el acceso de ${usuario.username} a ${quitando.empresa_nombre}? Perderá de inmediato los permisos en esa empresa.`}
          textoConfirmar="Quitar acceso"
          enviando={quitar.isPending}
          onConfirmar={() => quitar.mutate(quitando.empresa)}
          onCerrar={() => setQuitando(null)}
        />
      )}
    </section>
  )
}
