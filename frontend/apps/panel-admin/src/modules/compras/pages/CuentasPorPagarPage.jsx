import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import DeudasProveedorModal from '../components/DeudasProveedorModal'
import PagarCompraModal from '../components/PagarCompraModal'
import PorFactura from '../components/PorFactura'
import PorProveedor from '../components/PorProveedor'
import ResumenDeudas from '../components/ResumenDeudas'
import '../../almacen/inventario.css'
import '../compras.css'

const FILTROS_VACIOS = { vencimiento: '', vence_hasta: '' }
const VISTAS = { PROVEEDOR: 'Por proveedor', FACTURA: 'Por factura' }

/** Cuentas por pagar: lo que se debe a los proveedores por compras a crédito, por proveedor o por factura. */
export default function CuentasPorPagarPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [vista, setVista] = useState('PROVEEDOR')
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(FILTROS_VACIOS)
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(false)
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'pagar', id } o { tipo: 'proveedor', proveedor }
  const q = useDebounce(busqueda, 400)

  const hayFiltros = Object.values(filtros).some(Boolean)
  const parametros = { empresa: empresaActivaId, q, ...filtros }
  const cerrar = () => setDialogo(null)
  const filtrar = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }))
    setPagina(1)
  }
  const cambiarTamano = (t) => {
    setTamano(t)
    setPagina(1)
  }
  const elegirVista = (v) => {
    setVista(v)
    setPagina(1)
  }
  const comun = { parametros, pagina, tamano, onPagina: setPagina, onTamano: cambiarTamano, hayFiltros }

  return (
    <main className="listado">
      <CabeceraListado icono="wallet" titulo="Cuentas por pagar" descripcion="Lo que debes a tus proveedores por compras a crédito. Lo más urgente aparece primero.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar deudas"
          placeholder={vista === 'PROVEEDOR' ? 'Proveedor o RUC…' : 'Proveedor o comprobante…'}
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
      </CabeceraListado>

      <ResumenDeudas empresaId={empresaActivaId} />

      <div className="segmentos" role="radiogroup" aria-label="Cómo ver las deudas">
        {Object.entries(VISTAS).map(([valor, texto]) => (
          <button key={valor} type="button" role="radio" aria-checked={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => elegirVista(valor)}>
            {texto}
          </button>
        ))}
      </div>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Vencimiento
            <select value={filtros.vencimiento} onChange={filtrar('vencimiento')}>
              <option value="">Todas</option>
              <option value="vencidas">Solo con cuotas vencidas</option>
              <option value="por_vencer">Solo al día</option>
            </select>
          </label>
          <label>
            Vencen hasta
            <input type="date" value={filtros.vence_hasta} onChange={filtrar('vence_hasta')} />
          </label>
          {hayFiltros && (
            <button
              type="button"
              onClick={() => {
                setFiltros(FILTROS_VACIOS)
                setPagina(1)
              }}
            >
              Limpiar filtros
            </button>
          )}
        </div>
      )}

      {vista === 'PROVEEDOR' ? (
        <PorProveedor {...comun} onAbrir={(proveedor) => setDialogo({ tipo: 'proveedor', proveedor })} />
      ) : (
        <PorFactura {...comun} onVer={(id) => navegar(`/compras/registro/${id}`)} onPagar={(id) => setDialogo({ tipo: 'pagar', id })} />
      )}

      {dialogo?.tipo === 'proveedor' && <DeudasProveedorModal proveedor={dialogo.proveedor} onCerrar={cerrar} />}
      {dialogo?.tipo === 'pagar' && <PagarCompraModal compraId={dialogo.id} onCerrar={cerrar} />}
    </main>
  )
}
