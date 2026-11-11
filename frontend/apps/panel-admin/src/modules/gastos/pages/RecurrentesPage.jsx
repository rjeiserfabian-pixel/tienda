import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import RecurrenteModal from '../components/RecurrenteModal'
import { AVISOS_RECURRENTE, dinero, textoDeDias } from '../gastos'
import '../../almacen/inventario.css'
import '../gastos.css'

/** Gastos que se repiten (alquiler, luz, internet): cuándo le toca a cada uno y un botón para registrarlo. */
export default function RecurrentesPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [verInactivos, setVerInactivos] = useState(false)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'editar' | 'omitir' | 'quitar', registro? }
  const [error, setError] = useState('')

  const consulta = useListado(['gastos', 'recurrentes'], '/gastos/recurrentes/', { empresa: empresaActivaId, estado: verInactivos ? '' : 'ACTIVO', page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  const accion = useMutacion({
    mutationFn: ({ metodo, url, cuerpo }) => api.request({ method: metodo, url, data: cuerpo }).then((r) => r.data),
    invalidar: [['gastos'], ['caja']],
    avisarError: false,
  })
  const ejecutar = (datos, exito) => {
    setError('')
    accion.mutate(datos, { onSuccess: () => setDialogo(null), onError: (e) => setError(mensajeDeError(e)), meta: { exito } })
  }

  return (
    <main className="listado">
      <CabeceraListado icono="calendario" titulo="Gastos recurrentes" descripcion="Lo que pagas cada cierto tiempo: alquiler, luz, internet. El sistema te avisa cuándo toca y propone los datos; tú confirmas el importe y el comprobante.">
        <button type="button" className={`boton-cabecera${verInactivos ? ' activo' : ''}`} aria-pressed={verInactivos} onClick={() => setVerInactivos((v) => !v)}>
          Ver también los inactivos
        </button>
        <Can permiso="GASTOS.REGISTRAR">
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'editar', registro: null })}>
            <Icono nombre="agregar" tam={20} /> Nuevo gasto recurrente
          </button>
        </Can>
      </CabeceraListado>
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Gasto</th>
                <th>Se repite</th>
                <th>Le toca</th>
                <th className="num">Importe habitual</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={5} icono="calendario" titulo="Aún no tienes gastos recurrentes" descripcion="Crea el alquiler, la luz o el internet y el sistema te avisará cuándo toca pagarlos." />}
              {filas.map((r) => {
                const aviso = AVISOS_RECURRENTE[r.aviso]
                const activo = r.estado === 'ACTIVO'
                return (
                  <tr key={r.id} className={activo ? undefined : 'anulado'}>
                    <td className="col-texto">
                      <strong>{r.nombre}</strong>
                      <span className="sub-texto">
                        {r.categoria_nombre}
                        {r.proveedor_nombre ? ` · ${r.proveedor_nombre}` : ''}
                        {!r.con_comprobante ? ' · Sin comprobante' : ''}
                      </span>
                    </td>
                    <td>{r.periodicidad_descripcion || r.periodicidad_nombre}</td>
                    <td>
                      {fechaCorta(r.proxima_fecha)}
                      <span className="sub-texto">
                        <span className="pildora" data-tono={aviso.tono}>
                          {aviso.texto}
                        </span>{' '}
                        {activo ? textoDeDias(r.dias_para_toca) : ''}
                      </span>
                    </td>
                    <td className="num">{r.importe_estimado ? dinero(r.importe_estimado, r.moneda) : '—'}</td>
                    <td className="centrado">
                      <Can permiso="GASTOS.REGISTRAR">
                        {activo ? (
                          <>
                            <button type="button" className="primario boton-cabecera" onClick={() => navegar(`/gastos/registro/nuevo?recurrente=${r.id}`)}>
                              <Icono nombre="agregar" tam={17} /> Registrar
                            </button>
                            <button type="button" className="accion-icono" aria-label={`Omitir este ciclo de ${r.nombre}`} title="Omitir este ciclo (no hubo gasto)" onClick={() => setDialogo({ tipo: 'omitir', registro: r })}>
                              <Icono nombre="reactivar" tam={19} />
                            </button>
                          </>
                        ) : (
                          <button type="button" className="boton-cabecera" disabled={accion.isPending} onClick={() => ejecutar({ metodo: 'patch', url: `/gastos/recurrentes/${r.id}/`, cuerpo: { estado: 'ACTIVO' } })}>
                            Reactivar
                          </button>
                        )}
                        <button type="button" className="accion-icono" aria-label={`Editar ${r.nombre}`} title="Editar" onClick={() => setDialogo({ tipo: 'editar', registro: r })}>
                          <Icono nombre="lapiz" tam={19} />
                        </button>
                        <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${r.nombre}`} title="Quitar" onClick={() => setDialogo({ tipo: 'quitar', registro: r })}>
                          <Icono nombre="papelera" tam={19} />
                        </button>
                      </Can>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion
        pagina={pagina}
        tamano={tamano}
        total={consulta.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

      {dialogo?.tipo === 'editar' && <RecurrenteModal registro={dialogo.registro} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'omitir' && (
        <ConfirmarModal
          titulo="Omitir este ciclo"
          mensaje={`¿Este mes no hubo «${dialogo.registro.nombre}»? Se pasa al siguiente ciclo sin registrar ningún gasto.`}
          textoConfirmar="Omitir"
          onConfirmar={() => ejecutar({ metodo: 'post', url: `/gastos/recurrentes/${dialogo.registro.id}/omitir/` })}
          onCerrar={() => setDialogo(null)}
        />
      )}
      {dialogo?.tipo === 'quitar' && (
        <ConfirmarModal
          titulo="Quitar el gasto recurrente"
          mensaje={`«${dialogo.registro.nombre}» dejará de avisarte. Los gastos que ya registraste con él se quedan. Si solo quieres pausarlo, edítalo y desactívalo.`}
          textoConfirmar="Quitar"
          onConfirmar={() => ejecutar({ metodo: 'delete', url: `/gastos/recurrentes/${dialogo.registro.id}/` })}
          onCerrar={() => setDialogo(null)}
        />
      )}
    </main>
  )
}
