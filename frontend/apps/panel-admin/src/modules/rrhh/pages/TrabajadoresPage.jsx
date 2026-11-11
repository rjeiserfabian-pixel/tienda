import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../rrhh'
import '../rrhh.css'

const FILTROS_CONTRATO = [
  ['', 'Todos'],
  ['vigente', 'Con contrato vigente'],
  ['sin_contrato', 'Sin contrato'],
  ['por_vencer', 'Por vencer'],
  ['vencido', 'Vencidos'],
]

/** Texto y tono del vencimiento de un contrato a plazo fijo (nada si no vence). */
function Vencimiento({ contrato }) {
  if (!contrato?.fecha_fin) return <span className="celda-suave">No vence</span>
  const dias = contrato.dias_para_vencer
  const tono = dias < 0 ? 'rojo' : dias <= 30 ? 'ambar' : 'gris'
  const texto = dias < 0 ? `Venció hace ${-dias} día(s)` : dias === 0 ? 'Vence hoy' : `Vence en ${dias} día(s)`
  return (
    <>
      {fechaCorta(contrato.fecha_fin)}
      <span className="pildora mas" data-tono={tono}>
        {texto}
      </span>
    </>
  )
}

/** Los trabajadores de la empresa con su contrato y lo que falta para poder calcularles la planilla. */
export default function TrabajadoresPage() {
  const { empresaActivaId } = useEmpresas()
  const navegar = useNavigate()
  const [busqueda, setBusqueda] = useState('')
  const [contrato, setContrato] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const q = useDebounce(busqueda.trim(), 400)

  const consulta = useListado(
    ['trabajadores'],
    '/rrhh/trabajadores/',
    { empresa: empresaActivaId, q, contrato, estado: 'ACTIVO', page: pagina, page_size: tamano },
    { enabled: Boolean(empresaActivaId) },
  )
  const filas = consulta.data?.results ?? []

  const cambiar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="users" titulo="Trabajadores" descripcion="La ficha laboral de cada trabajador: pensión, forma de pago y contratos. Los trabajadores se registran en Mantenimiento › Personal.">
        <Buscador valor={busqueda} onCambio={cambiar(setBusqueda)} etiqueta="Buscar trabajador" placeholder="Buscar por nombre o documento" />
        <select className="boton-cabecera" aria-label="Contrato" value={contrato} onChange={(e) => cambiar(setContrato)(e.target.value)}>
          {FILTROS_CONTRATO.map(([valor, texto]) => (
            <option key={valor} value={valor}>
              {texto}
            </option>
          ))}
        </select>
        <Link className="boton-cabecera" to="/mantenimiento/personal">
          <Icono nombre="agregar" tam={19} /> Registrar trabajador
        </Link>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Trabajador</th>
                <th>Cargo</th>
                <th>Contrato</th>
                <th>Vencimiento</th>
                <th>Ficha</th>
                <th className="centrado">Ver</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={6} icono="users" titulo="No hay trabajadores para mostrar" descripcion="Registra al personal en Mantenimiento › Personal; luego completa aquí su ficha laboral y su contrato." />}
              {filas.map((t) => (
                <tr key={t.id} className="rh-fila-clicable" onClick={() => navegar(`/rrhh/trabajadores/${t.id}`)}>
                  <td>
                    <strong>{t.nombre_completo}</strong>
                    <span className="rh-sub">
                      {t.tipo_documento} {t.numero_documento}
                    </span>
                  </td>
                  <td>{t.contrato?.cargo || t.cargo || '—'}</td>
                  <td>
                    {t.contrato ? (
                      <>
                        {t.contrato.tipo_nombre}
                        <span className="rh-sub">
                          {t.contrato.regimen_nombre} · desde {fechaCorta(t.contrato.fecha_inicio)}
                        </span>
                      </>
                    ) : (
                      <span className="pildora mas" data-tono="rojo">
                        Sin contrato
                      </span>
                    )}
                  </td>
                  <td>{t.contrato ? <Vencimiento contrato={t.contrato} /> : '—'}</td>
                  <td>
                    {t.faltantes.length === 0 ? (
                      <span className="pildora mas" data-tono="verde">
                        Completa
                      </span>
                    ) : (
                      <span className="pildora mas" data-tono="ambar" title={t.faltantes.join(', ')}>
                        Falta {t.faltantes.length}
                      </span>
                    )}
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button
                        type="button"
                        className="accion-icono ver"
                        aria-label={`Abrir la ficha de ${t.nombre_completo}`}
                        title="Ver la ficha"
                        onClick={(evento) => {
                          evento.stopPropagation()
                          navegar(`/rrhh/trabajadores/${t.id}`)
                        }}
                      >
                        <Icono nombre="ojo" tam={19} />
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={cambiar(setTamano)} />
    </main>
  )
}
