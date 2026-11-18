import { useState } from 'react'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import ReclamoModal, { EstadoReclamo } from '../components/ReclamoModal'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../garantias.css'

const ESTADOS = {
  ABIERTOS: 'Abiertos',
  EN_SERVICIO: 'En servicio técnico',
  EN_PROVEEDOR: 'Con el proveedor',
  RESUELTO: 'Resueltos',
  RECHAZADO: 'Rechazados',
  '': 'Todos',
}

/** Reclamos de garantía: los que están abiertos primero, con su seguimiento. */
export default function ReclamosGarantiaPage() {
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('ABIERTOS')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [abierto, setAbierto] = useState(null)
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(['garantias', 'reclamos'], '/garantias/reclamos/', { empresa: empresaActivaId, q, estado, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="shield" titulo="Reclamos de garantía" descripcion="Los reclamos de los clientes, con lo que se hizo: servicio técnico, proveedor y cómo se resolvieron.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar reclamos"
          placeholder="Serie, cliente, producto o RMA…"
        />
        <select
          aria-label="Estado"
          value={estado}
          onChange={(e) => {
            setEstado(e.target.value)
            setPagina(1)
          }}
        >
          {Object.entries(ESTADOS).map(([valor, texto]) => (
            <option key={valor} value={valor}>
              {texto}
            </option>
          ))}
        </select>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Reclamo</th>
                <th>Producto</th>
                <th>Cliente</th>
                <th>Falla</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={5} icono="shield" titulo={q || estado !== 'ABIERTOS' ? 'Ningún reclamo coincide' : 'No hay reclamos abiertos'} descripcion="Los reclamos se abren desde la ficha de una garantía vigente." />}
              {filas.map((r) => (
                <tr key={r.id} className="fila-clicable" onClick={() => setAbierto(r.id)}>
                  <td>
                    <strong>{r.numero_completo}</strong>
                    <span className="sub-texto">{fechaCorta(r.fecha)}</span>
                  </td>
                  <td className="col-texto">
                    {r.producto_nombre}
                    {r.numero_serie && <span className="sub-texto">{r.numero_serie}</span>}
                  </td>
                  <td className="col-texto">
                    {r.cliente_nombre || '—'}
                    {r.cliente_documento && <span className="sub-texto">{r.cliente_documento}</span>}
                  </td>
                  <td className="col-texto">{r.descripcion}</td>
                  <td>
                    <EstadoReclamo reclamo={r} />
                    {r.rma_numero && <span className="sub-texto">RMA {r.rma_numero}</span>}
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
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />
      {abierto && <ReclamoModal id={abierto} onCerrar={() => { setAbierto(null); consulta.refetch() }} />}
    </main>
  )
}
