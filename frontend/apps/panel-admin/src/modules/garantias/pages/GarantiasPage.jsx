import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import { useImpresionDocumento } from '../../ventas/hooks/useImpresionDocumento'
import { especificacionCertificado } from '../components/CertificadoGarantia'
import ReclamarModal from '../components/ReclamarModal'
import ReclamoModal, { EstadoReclamo } from '../components/ReclamoModal'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../garantias.css'

const SITUACIONES = {
  VIGENTE: { texto: 'Vigente', tono: 'verde' },
  POR_VENCER: { texto: 'Por vencer', tono: 'ambar' },
  VENCIDA: { texto: 'Vencida', tono: 'rojo' },
  ANULADA: { texto: 'Anulada', tono: 'gris' },
  REEMPLAZADA: { texto: 'Reemplazada', tono: 'gris' },
}

function Situacion({ garantia }) {
  const s = SITUACIONES[garantia.situacion] ?? SITUACIONES.VIGENTE
  return (
    <span className="pildora" data-tono={s.tono}>
      {s.texto}
    </span>
  )
}

const detalleDeDias = (g) => {
  if (g.vigente) return `Quedan ${g.dias_restantes} ${g.dias_restantes === 1 ? 'día' : 'días'}`
  return g.estado === 'ANULADA' ? g.motivo_anulacion : 'Ya venció'
}

/** La garantía de una unidad y todo lo que le pasó: entró, salió, se vendió. */
/** Trae los datos del certificado al pedirlo y abre la vista previa para imprimirlo en A4 o ticket. */
function BotonCertificado({ id }) {
  const [pedido, setPedido] = useState(false)
  const consulta = useQuery({
    queryKey: ['garantias', 'certificado', id],
    queryFn: ({ signal }) => api.get(`/garantias/${id}/certificado/`, { signal }).then((r) => r.data),
    enabled: pedido,
  })
  const { imprimir, portal } = useImpresionDocumento(consulta.data ? especificacionCertificado(consulta.data) : null)
  useEffect(() => {
    if (pedido && consulta.data) {
      imprimir()
      setPedido(false)
    }
  }, [pedido, consulta.data, imprimir])
  return (
    <>
      <button type="button" disabled={pedido && consulta.isFetching} onClick={() => setPedido(true)}>
        {pedido && consulta.isFetching ? 'Preparando…' : 'Imprimir certificado'}
      </button>
      {consulta.isError && <span role="alert" className="campo-error">No se pudo preparar el certificado.</span>}
      {portal}
    </>
  )
}

function FichaGarantia({ id, onCerrar }) {
  const [reclamando, setReclamando] = useState(false)
  const [reclamo, setReclamo] = useState(null)
  const consulta = useQuery({
    queryKey: ['garantias', 'ficha', id],
    queryFn: ({ signal }) => api.get(`/garantias/${id}/`, { signal }).then((r) => r.data),
  })
  const g = consulta.data
  const tono = g ? SITUACIONES[g.situacion]?.tono : undefined
  return (
    <Modal titulo={g ? g.producto_nombre : 'Garantía'} subtitulo={g?.numero_serie ? `Serie / IMEI ${g.numero_serie}` : undefined} onCerrar={onCerrar} ancho={720}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(g)}>
        {g && (
          <>
            <dl className="cxp-tarjetas" aria-label="Resumen de la garantía">
              <div data-tono={tono === 'rojo' || tono === 'ambar' ? tono : undefined}>
                <dt>Situación</dt>
                <dd>{SITUACIONES[g.situacion]?.texto}</dd>
                <small>{detalleDeDias(g)}</small>
              </div>
              <div>
                <dt>Vence el</dt>
                <dd>{fechaCorta(g.vence_el)}</dd>
                <small>
                  {g.meses} {g.meses === 1 ? 'mes' : 'meses'} desde el {fechaCorta(g.fecha_inicio)}
                </small>
              </div>
              <div>
                <dt>Comprobante</dt>
                <dd>{g.comprobante_numero}</dd>
                <small>{g.empresa_nombre}</small>
              </div>
            </dl>
            <p>
              <strong>Cliente:</strong> {g.cliente_nombre || 'Sin cliente'}
              {g.cliente_documento ? ` · ${g.cliente_documento}` : ''}
              {!g.numero_serie && Number(g.cantidad) !== 1 ? ` · ${Number(g.cantidad)} unidades` : ''}
            </p>
            {g.reclamos.length > 0 && (
              <>
                <h3>Reclamos</h3>
                <ul className="lista-simple">
                  {g.reclamos.map((x) => (
                    <li key={x.id}>
                      <button type="button" onClick={() => setReclamo(x.id)}>
                        {x.numero_completo} · {fechaCorta(x.fecha)} · <EstadoReclamo reclamo={x} /> · {x.descripcion}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {g.vigente && !g.reclamos.some((x) => ['ABIERTO', 'EN_SERVICIO', 'EN_PROVEEDOR'].includes(x.estado)) && (
              <Can permiso="VENTAS.GARANTIA_RECLAMAR">
                <button type="button" className="primario" onClick={() => setReclamando(true)}>
                  Reclamar garantía
                </button>
              </Can>
            )}
            {g.estado === 'ACTIVA' && <BotonCertificado id={g.id} />}
            <h3>Historia de la unidad</h3>
            <ol className="linea-tiempo">
              {g.historial.map((e, i) => (
                <li key={`${e.fecha}-${i}`}>
                  <time dateTime={e.fecha}>{fechaCorta(e.fecha)}</time> {e.evento}
                </li>
              ))}
            </ol>
          </>
        )}
      </EstadoConsulta>
      {reclamando && g && (
        <ReclamarModal
          garantia={g}
          onCerrar={() => setReclamando(false)}
          onCreado={(nuevo) => {
            setReclamando(false)
            consulta.refetch()
            setReclamo(nuevo.id)
          }}
        />
      )}
      {reclamo && <ReclamoModal id={reclamo} onCerrar={() => { setReclamo(null); consulta.refetch() }} />}
    </Modal>
  )
}

/** Consulta de garantías: por serie o IMEI, comprobante, cliente o producto. */
export default function GarantiasPage() {
  const { empresaActivaId } = useEmpresas()
  const [busqueda, setBusqueda] = useState('')
  const [situacion, setSituacion] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [abierta, setAbierta] = useState(null)
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(['garantias', 'lista'], '/garantias/', { empresa: empresaActivaId, q, situacion, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="shield" titulo="Garantías" descripcion="Busca por serie o IMEI, comprobante, cliente o producto y mira si la garantía sigue vigente.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar garantías"
          placeholder="Serie, IMEI, comprobante, DNI o producto…"
        />
        <select
          aria-label="Situación"
          value={situacion}
          onChange={(e) => {
            setSituacion(e.target.value)
            setPagina(1)
          }}
        >
          <option value="">Todas</option>
          {Object.entries(SITUACIONES).map(([valor, s]) => (
            <option key={valor} value={valor}>
              {s.texto}
            </option>
          ))}
        </select>
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Producto</th>
                <th>Serie / IMEI</th>
                <th>Cliente</th>
                <th>Comprobante</th>
                <th>Vence</th>
                <th>Situación</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={6} icono="shield" titulo={q || situacion ? 'Ninguna garantía coincide' : 'Aún no hay garantías'} descripcion="Se crean solas al vender productos que tienen meses de garantía." />}
              {filas.map((g) => (
                <tr key={g.id} className="fila-clicable" onClick={() => setAbierta(g.id)}>
                  <td className="col-texto">
                    <strong>{g.producto_nombre}</strong>
                    {!g.numero_serie && Number(g.cantidad) !== 1 && <span className="sub-texto">{Number(g.cantidad)} unidades</span>}
                  </td>
                  <td>{g.numero_serie || '—'}</td>
                  <td className="col-texto">
                    {g.cliente_nombre || '—'}
                    {g.cliente_documento && <span className="sub-texto">{g.cliente_documento}</span>}
                  </td>
                  <td>{g.comprobante_numero}</td>
                  <td>
                    {fechaCorta(g.vence_el)}
                    <span className="sub-texto">{g.meses} meses</span>
                  </td>
                  <td>
                    <Situacion garantia={g} />
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
      {abierta && <FichaGarantia id={abierta} onCerrar={() => setAbierta(null)} />}
    </main>
  )
}
