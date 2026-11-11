import { useState } from 'react'
import { Link } from 'react-router-dom'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useListado } from '../../../shared/hooks/useListado'
import { aNumero } from '../../almacen/utilidades'
import { fechaCorta } from '../../almacen/inventario'
import UsarSaldoModal from '../components/UsarSaldoModal'
import UsosSaldoModal from '../components/UsosSaldoModal'
import { dinero, MONEDAS, numeroInterno } from '../compras'
import '../../almacen/inventario.css'

/** Saldos a favor con proveedores: nacen de devoluciones ya pagadas o de anticipos y sirven para pagar compras a crédito. */
export default function SaldosAFavorPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeUsar = tiene('COMPRAS.CREDITO_USAR')
  const [soloDisponibles, setSoloDisponibles] = useState(true)
  const [moneda, setMoneda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'usar' | 'usos', credito }

  const consulta = useListado(['compras', 'creditos'], '/compras/creditos/', { empresa: empresaActivaId, moneda, disponibles: soloDisponibles ? '1' : '', page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="Saldos a favor" descripcion="Dinero que un proveedor te debe: por mercadería devuelta que ya habías pagado o por un anticipo que le diste. Sirve para pagar compras a crédito del mismo proveedor." />

      <div className="filtros-panel" role="search">
        <label>
          Moneda
          <select
            value={moneda}
            onChange={(e) => {
              setMoneda(e.target.value)
              setPagina(1)
            }}
          >
            <option value="">Todas</option>
            {Object.entries(MONEDAS).map(([valor, m]) => (
              <option key={valor} value={valor}>
                {m.nombre}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={soloDisponibles}
            onChange={(e) => {
              setSoloDisponibles(e.target.checked)
              setPagina(1)
            }}
          />{' '}
          Solo los que aún tienen saldo
        </label>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Proveedor</th>
                <th>Origen</th>
                <th>Fecha</th>
                <th className="num">Monto</th>
                <th className="num">Usado</th>
                <th className="num">Disponible</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={8} icono="coins" titulo="No hay saldos a favor" descripcion="Aparecen cuando devuelves mercadería ya pagada y dejas el dinero como saldo a favor." />}
              {filas.map((c) => {
                const conSaldo = !c.anulado && aNumero(c.disponible) > 0
                return (
                  <tr key={c.id} className={c.anulado ? 'anulado' : undefined}>
                    <td className="col-texto">{c.proveedor_nombre}</td>
                    <td className="col-texto">
                      {c.origen === 'ANTICIPO' ? (
                        <>
                          <Link to={`/compras/anticipos?q=${encodeURIComponent(c.anticipo_codigo)}`}>Anticipo {c.anticipo_codigo}</Link>
                          <span className="sub-texto">Dinero adelantado</span>
                        </>
                      ) : (
                        <>
                          <Link to={`/compras/devoluciones/${c.devolucion}`}>N° {numeroInterno({ numero: c.devolucion_numero })}</Link>
                          <span className="sub-texto">{c.devolucion_comprobante}</span>
                        </>
                      )}
                    </td>
                    <td>{fechaCorta(c.fecha)}</td>
                    <td className="num">{dinero(c.monto, c.moneda)}</td>
                    <td className="num">{dinero(c.usado, c.moneda)}</td>
                    <td className="num">
                      <strong>{dinero(c.disponible, c.moneda)}</strong>
                    </td>
                    <td>{c.anulado ? <span className="estado-pildora inactivo">Anulado</span> : conSaldo ? <span className="estado-pildora activo">Con saldo</span> : <span className="estado-pildora">Usado</span>}</td>
                    <td className="centrado">
                      <span className="acciones-fila">
                        {puedeUsar && conSaldo && (
                          <button type="button" className="primario" onClick={() => setDialogo({ tipo: 'usar', credito: c })}>
                            Usar
                          </button>
                        )}
                        {c.aplicaciones.length > 0 && (
                          <button type="button" onClick={() => setDialogo({ tipo: 'usos', credito: c })}>
                            Ver usos
                          </button>
                        )}
                      </span>
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

      {dialogo?.tipo === 'usar' && <UsarSaldoModal credito={dialogo.credito} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'usos' && <UsosSaldoModal credito={dialogo.credito} onCerrar={() => setDialogo(null)} />}
    </main>
  )
}
