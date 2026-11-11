import { Link } from 'react-router-dom'
import Avatar from '../../../shared/components/Avatar'
import { Icono } from '../../../shared/components/IconosPanel'
import { MODO_LECTURA } from '../../../shared/hooks/useModoLectura'
import { fechaHora } from '../../../shared/utils/fechas'
import { etiquetaRol } from './etiquetasRol'

const nombreCompleto = (u) => [u.nombres, u.apellidos].filter(Boolean).join(' ')

/** Encabezado ordenable: al pulsarlo alterna ascendente / descendente (el servidor ordena). */
function Th({ campo, orden, alOrdenar, children }) {
  const activa = orden === campo || orden === `-${campo}`
  const ascendente = orden === campo
  return (
    <th aria-sort={activa ? (ascendente ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className={`orden-boton${activa ? ' activa' : ''}`} onClick={() => alOrdenar(campo)}>
        {children}
        <Icono nombre={activa ? (ascendente ? 'ordenarAsc' : 'ordenarDesc') : 'ordenar'} tam={17} />
      </button>
    </th>
  )
}

function Roles({ codigos }) {
  if (codigos.length === 0) return <span className="celda-suave">—</span>
  const visibles = codigos.slice(0, 2)
  return (
    <>
      {visibles.map((codigo) => {
        const { texto, tono } = etiquetaRol(codigo)
        return (
          <span key={codigo} className="pildora" data-tono={tono} title={codigo}>
            {texto}
          </span>
        )
      })}
      {codigos.length > 2 && (
        <span className="pildora mas" data-tono="gris" title={codigos.slice(2).join(', ')}>
          +{codigos.length - 2}
        </span>
      )}
    </>
  )
}

/**
 * Tabla de usuarios. Las acciones reales por fila: ver, editar (ambas abren la ficha) y
 * desactivar / reactivar. Un usuario no puede desactivarse a sí mismo.
 */
export default function TablaUsuarios({
  filas,
  desde,
  orden,
  alOrdenar,
  yoId,
  puedeDesactivar,
  alDesactivar,
  alReactivar,
  pendienteId,
  filaVacia,
}) {
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th className="centrado">#</th>
            <th className="centrado">Foto</th>
            <Th campo="username" orden={orden} alOrdenar={alOrdenar}>Usuario</Th>
            <Th campo="nombre" orden={orden} alOrdenar={alOrdenar}>Nombre completo</Th>
            <th>Rol</th>
            <th>Empresas</th>
            <Th campo="estado" orden={orden} alOrdenar={alOrdenar}>Estado</Th>
            <Th campo="ultimo_acceso" orden={orden} alOrdenar={alOrdenar}>Último acceso</Th>
            <th className="centrado">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {filas.length === 0 && filaVacia}
          {filas.map((u, i) => {
            const nombre = nombreCompleto(u) || u.username
            const esUnoMismo = u.id === yoId
            return (
              <tr key={u.id}>
                <td className="centrado celda-suave">{desde + i}</td>
                <td className="centrado">
                  <Avatar nombre={nombre} />
                </td>
                <td className="celda-usuario">
                  <Link to={`/seguridad/usuarios/${u.id}`}>{u.username}</Link>
                  {u.mfa_activo && (
                    <span title="Verificación en dos pasos activa" style={{ marginLeft: 6, color: '#6fe3a5' }}>
                      <Icono nombre="shield" tam={15} />
                    </span>
                  )}
                </td>
                <td>{nombreCompleto(u) || <span className="celda-suave">—</span>}<br /><small className="celda-suave">{u.email}</small></td>
                <td><Roles codigos={u.roles} /></td>
                <td className="celda-suave">{u.empresas.map((e) => e.nombre).join(', ') || '—'}</td>
                <td>
                  <span className={`estado-pildora ${u.activo ? 'activo' : 'inactivo'}`}>{u.activo ? 'Activo' : 'Inactivo'}</span>
                </td>
                <td className="celda-suave">
                  {fechaHora(u.ultimo_acceso, 'Nunca')}
                </td>
                <td className="centrado">
                  <span className="acciones-fila">
                    <Link to={`/seguridad/usuarios/${u.id}${MODO_LECTURA}`} className="accion-icono ver" aria-label={`Ver a ${u.username}`} title="Ver (solo consulta)">
                      <Icono nombre="ojo" tam={19} />
                    </Link>
                    <Link to={`/seguridad/usuarios/${u.id}#datos`} className="accion-icono editar" aria-label={`Editar a ${u.username}`} title="Editar">
                      <Icono nombre="lapiz" tam={19} />
                    </Link>
                    {puedeDesactivar && !esUnoMismo && (u.activo ? (
                      <button type="button" className="accion-icono peligro-suave" disabled={pendienteId === u.id} aria-label={`Desactivar a ${u.username}`} title="Desactivar" onClick={() => alDesactivar(u)}>
                        <Icono nombre="apagar" tam={19} />
                      </button>
                    ) : (
                      <button type="button" className="accion-icono reactivar" disabled={pendienteId === u.id} aria-label={`Reactivar a ${u.username}`} title="Reactivar" onClick={() => alReactivar(u)}>
                        <Icono nombre="reactivar" tam={19} />
                      </button>
                    ))}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
