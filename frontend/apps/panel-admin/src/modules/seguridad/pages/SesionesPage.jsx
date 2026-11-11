import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora } from '../../../shared/utils/fechas'

const TAMANOS = [10, 20, 50, 100]

/** Sesiones abiertas del propio usuario, con opción de cerrar las de otros dispositivos. */
export default function SesionesPage() {
  const [aCerrar, setACerrar] = useState(null)
  const [cerrandoOtras, setCerrandoOtras] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(20)
  const consulta = useListado(['sesiones'], '/seguridad/sesiones/', { page: pagina, page_size: tamano })
  const filas = consulta.data?.results ?? []

  const cerrar = useMutacion({
    mutationFn: (id) => api.delete(`/seguridad/sesiones/${id}/`),
    invalidar: [['sesiones']],
    exito: 'Sesión cerrada.',
    alExito: () => setACerrar(null),
  })

  const cerrarOtras = useMutacion({
    mutationFn: () => api.delete('/seguridad/sesiones/otras/'),
    invalidar: [['sesiones']],
    exito: 'Se cerraron las demás sesiones.',
    alExito: () => setCerrandoOtras(false),
  })
  const hayOtras = filas.some((s) => !s.actual) || (consulta.data?.count ?? 0) > filas.length

  return (
    <main className="listado">
      <CabeceraListado
        icono="devices"
        titulo="Mis sesiones"
        descripcion="Dispositivos donde tienes la sesión abierta. Cierra los que no reconozcas."
      >
        {hayOtras && (
          <button type="button" className="boton-cabecera primario" onClick={() => setCerrandoOtras(true)}>
            <Icono nombre="salir" tam={19} />
            Cerrar las demás sesiones
          </button>
        )}
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Dispositivo</th>
                <th>Plataforma</th>
                <th>IP</th>
                <th>Inicio</th>
                <th>Último uso</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={7} icono="devices" titulo="No hay sesiones abiertas" descripcion="Aquí aparecerán los dispositivos donde inicies sesión." />
              )}
              {filas.map((s, i) => (
                <tr key={s.id}>
                  <td className="centrado celda-suave">{(pagina - 1) * tamano + i + 1}</td>
                  <td>
                    <span className="texto-pildora-fila">
                      {s.dispositivo || <span className="celda-suave">Sin nombre</span>}
                      {s.actual && <span className="estado-pildora activo">Esta sesión</span>}
                    </span>
                  </td>
                  <td>
                    <span className="pildora" data-tono={s.plataforma === 'WEB' ? 'azul' : 'morado'}>
                      {s.plataforma === 'WEB' ? 'Panel web' : 'App móvil'}
                    </span>
                  </td>
                  <td className="celda-suave">{s.ip || '—'}</td>
                  <td className="celda-suave">{fechaHora(s.creado_en)}</td>
                  <td className="celda-suave">{fechaHora(s.ultimo_uso)}</td>
                  <td className="centrado">
                    {!s.actual && (
                      <button
                        type="button"
                        className="accion-icono peligro-suave"
                        title="Cerrar esta sesión"
                        aria-label="Cerrar esta sesión"
                        disabled={cerrar.isPending}
                        onClick={() => setACerrar(s)}
                      >
                        <Icono nombre="salir" tam={19} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion
        pagina={pagina}
        tamano={tamano}
        total={consulta.data?.count ?? 0}
        tamanos={TAMANOS}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

      {aCerrar && (
        <ConfirmarModal
          titulo="Cerrar sesión"
          mensaje={`Se cerrará la sesión abierta el ${fechaHora(aCerrar.creado_en)} desde ${aCerrar.ip || 'una dirección desconocida'}. Quien la use tendrá que iniciar sesión de nuevo.`}
          textoConfirmar="Cerrar sesión"
          enviando={cerrar.isPending}
          onConfirmar={() => cerrar.mutate(aCerrar.id)}
          onCerrar={() => setACerrar(null)}
        />
      )}
      {cerrandoOtras && (
        <ConfirmarModal
          titulo="Cerrar las demás sesiones"
          mensaje="Se cerrarán todas las sesiones abiertas en otros dispositivos. Esta sesión se mantiene. Quien las use tendrá que iniciar sesión de nuevo."
          textoConfirmar="Cerrar las demás"
          enviando={cerrarOtras.isPending}
          onConfirmar={() => cerrarOtras.mutate()}
          onCerrar={() => setCerrandoOtras(false)}
        />
      )}
    </main>
  )
}
