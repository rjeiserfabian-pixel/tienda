import { useState } from 'react'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import EditarDatosSerieModal from '../components/EditarDatosSerieModal'
import MovimientoDetalleModal from '../components/MovimientoDetalleModal'
import { useOpciones } from '../hooks/useOpciones'
import { fechaCorta } from '../inventario'
import '../inventario.css'

/** Busca una serie o IMEI y muestra dónde está y por qué movimientos pasó (entrada y salida). */
export default function SeriesPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeCorregir = tiene('INVENTARIO.SERIES.EDITAR')
  const [corrigiendo, setCorrigiendo] = useState(null)
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [almacen, setAlmacen] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [verMovimiento, setVerMovimiento] = useState(null)
  const q = useDebounce(busqueda, 400)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const consulta = useListado(['series'], '/inventario/series/', { empresa: empresaActivaId, q, estado, almacen, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const desde = (pagina - 1) * tamano + 1

  const cambiar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  return (
    <main className="listado">
      <CabeceraListado icono="scan" titulo="Series e IMEI" descripcion="Cada unidad con número de serie: dónde está, cuándo entró y cuándo salió. Escribe parte del número, o de sus otros datos, para buscarla.">
        <Buscador valor={busqueda} onCambio={cambiar(setBusqueda)} etiqueta="Buscar una serie" placeholder="Serie, IMEI u otros datos…" />
        <select className="boton-cabecera" aria-label="Estado" value={estado} onChange={(e) => cambiar(setEstado)(e.target.value)}>
          <option value="">En stock y vendidas</option>
          <option value="EN_STOCK">Solo en stock</option>
          <option value="SALIDO">Solo las que ya salieron</option>
        </select>
        {(almacenes.data ?? []).length > 1 && (
          <select className="boton-cabecera" aria-label="Almacén" value={almacen} onChange={(e) => cambiar(setAlmacen)(e.target.value)}>
            <option value="">Todos los almacenes</option>
            {almacenes.data.map((a) => (
              <option key={a.id} value={a.id}>{a.nombre}</option>
            ))}
          </select>
        )}
      </CabeceraListado>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Serie o IMEI</th>
                <th>Producto</th>
                <th>Otros datos</th>
                <th>Almacén</th>
                <th>Estado</th>
                <th>Entró</th>
                <th>Salió</th>
                <th className="centrado">Movimientos</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={9} icono="scan" titulo="No hay series con esos filtros" descripcion="Las series aparecen al registrar compras o traspasos de productos que llevan serie o IMEI." />
              )}
              {filas.map((s, i) => (
                <tr key={s.id}>
                  <td className="centrado celda-suave">{desde + i}</td>
                  <td><strong>{s.numero}</strong></td>
                  <td>
                    {s.producto_nombre}
                    <span className="sub-texto">{s.producto_codigo}</span>
                  </td>
                  <td className="celda-suave">{s.otros_datos || '—'}</td>
                  <td>{s.almacen_nombre}</td>
                  <td>{s.estado === 'EN_STOCK' ? <span className="estado-pildora activo">En stock</span> : <span className="pildora" data-tono="gris">Ya salió</span>}</td>
                  <td>{fechaCorta(s.entrada_fecha)}<span className="sub-texto">Mov. {String(s.entrada_numero).padStart(6, '0')}</span></td>
                  <td>{s.salida_fecha ? <>{fechaCorta(s.salida_fecha)}<span className="sub-texto">Mov. {String(s.salida_numero).padStart(6, '0')}</span></> : '—'}</td>
                  <td className="centrado">
                    <span className="acciones-fila">
                      <button type="button" className="accion-icono ver" aria-label={`Ver el movimiento de entrada de ${s.numero}`} title="Ver la entrada" onClick={() => setVerMovimiento(s.entrada_movimiento)}>
                        <Icono nombre="ojo" tam={19} />
                      </button>
                      {puedeCorregir && (
                        <button type="button" className="accion-icono editar" aria-label={`Corregir los otros datos de ${s.numero}`} title="Corregir los otros datos" onClick={() => setCorrigiendo(s)}>
                          <Icono nombre="lapiz" tam={19} />
                        </button>
                      )}
                      {s.salida_movimiento && (
                        <button type="button" className="accion-icono peligro-suave" aria-label={`Ver el movimiento de salida de ${s.numero}`} title="Ver la salida" onClick={() => setVerMovimiento(s.salida_movimiento)}>
                          <Icono nombre="salir" tam={19} />
                        </button>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={(t) => cambiar(setTamano)(t)} />
      {corrigiendo && <EditarDatosSerieModal serie={corrigiendo} onCerrar={() => setCorrigiendo(null)} />}
      {verMovimiento && <MovimientoDetalleModal id={verMovimiento} onCerrar={() => setVerMovimiento(null)} />}
    </main>
  )
}
