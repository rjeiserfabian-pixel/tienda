import { useState } from 'react'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import AdelantoDetalleModal from '../components/AdelantoDetalleModal'
import AdelantoNuevoModal from '../components/AdelantoNuevoModal'
import { fechaCorta, soles } from '../rrhh'
import '../rrhh.css'

const FILTROS = [
  ['', 'Todos'],
  ['saldo', 'Con saldo por descontar'],
  ['ANULADO', 'Anulados'],
]

/** Adelantos de sueldo y préstamos de la empresa, con lo que falta descontar de cada uno. */
export default function AdelantosPage() {
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [tipo, setTipo] = useState('')
  const [filtro, setFiltro] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [nuevo, setNuevo] = useState(false)
  const [abierto, setAbierto] = useState(null)
  const q = useDebounce(busqueda.trim(), 400)

  const consulta = useListado(
    ['adelantos'],
    '/rrhh/adelantos/',
    { empresa: empresaActivaId, q, tipo, con_saldo: filtro === 'saldo' ? '1' : '', estado: filtro === 'ANULADO' ? 'ANULADO' : '', page: pagina, page_size: tamano },
    { enabled: Boolean(empresaActivaId) },
  )
  const filas = consulta.data?.results ?? []

  const cambiar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="wallet" titulo="Adelantos y préstamos" descripcion="Dinero que la empresa entrega a un trabajador. Sale de una caja y se descuenta en su planilla, de una vez (adelanto) o en cuotas (préstamo).">
        <Buscador valor={busqueda} onCambio={cambiar(setBusqueda)} etiqueta="Buscar trabajador" placeholder="Buscar por trabajador o N°" />
        <select className="boton-cabecera" aria-label="Tipo" value={tipo} onChange={(e) => cambiar(setTipo)(e.target.value)}>
          <option value="">Adelantos y préstamos</option>
          <option value="ADELANTO">Solo adelantos</option>
          <option value="PRESTAMO">Solo préstamos</option>
        </select>
        <select className="boton-cabecera" aria-label="Estado" value={filtro} onChange={(e) => cambiar(setFiltro)(e.target.value)}>
          {FILTROS.map(([valor, texto]) => (
            <option key={valor} value={valor}>
              {texto}
            </option>
          ))}
        </select>
        <Can permiso="RRHH.ADELANTOS.REGISTRAR">
          <button type="button" className="boton-cabecera primario" onClick={() => setNuevo(true)}>
            <Icono nombre="agregar" tam={19} /> Nuevo
          </button>
        </Can>
      </CabeceraListado>

      {consulta.data && (
        <p className="rh-aviso" role="status">
          Falta descontar en total: <strong>{soles(consulta.data.pendiente_total)}</strong>
          {(q || tipo || filtro) && ' (con los filtros elegidos)'}
        </p>
      )}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>N°</th>
                <th>Trabajador</th>
                <th>Tipo</th>
                <th>Fecha</th>
                <th className="derecha">Monto</th>
                <th className="derecha">Falta descontar</th>
                <th>Estado</th>
                <th className="centrado">Ver</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={8} icono="wallet" titulo="No hay adelantos ni préstamos" descripcion="Cuando entregue uno aparecerá aquí con lo que falta descontar." />}
              {filas.map((a) => (
                <tr key={a.id} className="rh-fila-clicable" onClick={() => setAbierto(a.id)}>
                  <td>{String(a.numero).padStart(6, '0')}</td>
                  <td>
                    <strong>{a.personal_nombre}</strong>
                    <span className="rh-sub">Sale de {a.cuenta_nombre}</span>
                  </td>
                  <td>
                    {a.tipo_nombre}
                    {a.num_cuotas > 1 && <span className="rh-sub">{a.num_cuotas} cuotas</span>}
                  </td>
                  <td>{fechaCorta(a.fecha)}</td>
                  <td className="derecha">{soles(a.monto)}</td>
                  <td className="derecha">{a.estado === 'ANULADO' ? '—' : soles(a.saldo_pendiente)}</td>
                  <td>
                    <span className="pildora mas" data-tono={a.estado === 'ANULADO' ? 'gris' : Number(a.saldo_pendiente) > 0 ? 'ambar' : 'verde'}>
                      {a.estado === 'ANULADO' ? 'Anulado' : Number(a.saldo_pendiente) > 0 ? 'Por descontar' : 'Descontado'}
                    </span>
                  </td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button
                        type="button"
                        className="accion-icono ver"
                        aria-label={`Ver el adelanto ${a.numero}`}
                        title="Ver el detalle"
                        onClick={(evento) => {
                          evento.stopPropagation()
                          setAbierto(a.id)
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
      {nuevo && <AdelantoNuevoModal onCerrar={() => setNuevo(false)} onCreado={(a) => { setNuevo(false); setAbierto(a.id) }} />}
      {abierto && <AdelantoDetalleModal id={abierto} onCerrar={() => setAbierto(null)} />}
    </main>
  )
}
