import { useState } from 'react'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../../compras/compras'
import '../../almacen/inventario.css'
import '../ventas.css'

/**
 * Busca el comprobante de una operación (una nota de crédito, una guía de remisión). Solo trae los
 * vigentes de la empresa que todavía tienen algo por devolver o por enviar. Se busca por cliente,
 * RUC/DNI o número («F001-1724»), con un retraso de 400 ms para no consultar en cada tecla.
 * `url` es el buscador del servidor y `texto` lo que se explica debajo del título.
 */
export default function BuscarComprobanteModal({ empresaId, onElegir, onCerrar, url = '/ventas/comprobantes/devolvibles/', texto = 'Solo aparecen los vigentes con algo por devolver.' }) {
  const [busqueda, setBusqueda] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(10)
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(['ventas', 'buscar-comprobante', url], url, { empresa: empresaId, q, desde, hasta, page: pagina, page_size: tamano }, { enabled: Boolean(empresaId) })
  const filas = consulta.data?.results ?? []
  const filtrar = (poner) => (e) => {
    poner(e.target.value)
    setPagina(1)
  }

  return (
    <Modal titulo="Buscar venta" subtitulo={`Elige el comprobante. ${texto}`} onCerrar={onCerrar} ancho={900}>
      <div className="fila-campos">
        <Campo etiqueta="Cliente, RUC/DNI o número" icono="buscar">
          {(p) => <input {...p} type="search" autoFocus maxLength={60} placeholder="Ej. F001-1724 o Distritec" value={busqueda} onChange={filtrar(setBusqueda)} />}
        </Campo>
        <Campo etiqueta="Desde" icono="calendario">
          {(p) => <input {...p} type="date" value={desde} max={hasta || undefined} onChange={filtrar(setDesde)} />}
        </Campo>
        <Campo etiqueta="Hasta" icono="calendario">
          {(p) => <input {...p} type="date" value={hasta} min={desde || undefined} onChange={filtrar(setHasta)} />}
        </Campo>
      </div>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Comprobante</th>
                <th>Cliente</th>
                <th className="num">Total</th>
                <th className="centrado">
                  <span className="sr-only">Elegir</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={5} icono="documento" titulo="No hay comprobantes para elegir" descripcion="Prueba con otro nombre, número o rango de fechas." />}
              {filas.map((c) => (
                <tr key={c.id} className="fila-clicable" onClick={() => onElegir(c.id)}>
                  <td>{fechaCorta(c.fecha)}</td>
                  <td>
                    <strong>{c.numero_completo}</strong>
                    <span className="sub-texto">{c.tipo_nombre}</span>
                  </td>
                  <td>
                    {c.cliente_nombre || 'Clientes varios'}
                    {c.cliente_documento && <span className="sub-texto">{c.cliente_tipo_documento} {c.cliente_documento}</span>}
                  </td>
                  <td className="num">{dinero(c.total, c.moneda)}</td>
                  <td className="centrado">
                    <button
                      type="button"
                      className="primario"
                      onClick={(ev) => {
                        ev.stopPropagation()
                        onElegir(c.id)
                      }}
                    >
                      Elegir
                    </button>
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
    </Modal>
  )
}
