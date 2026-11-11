import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useListado } from '../../../shared/hooks/useListado'
import AccionConNotaModal from '../../caja/components/AccionConNotaModal'
import { dinero } from '../../compras/compras'
import TrasladoEmpresasModal from '../components/TrasladoEmpresasModal'
import { fechaCorta } from '../inventario'
import '../inventario.css'

const VACIO = []
const numero = (n) => String(n).padStart(6, '0')

/**
 * Traslado entre empresas: mercadería que pasa de una empresa a la otra sin vender a nadie. Sale al
 * costo, la que recibe queda debiéndolo (se liquida con las ventas internas) y, si viaja a otro
 * local, se le crea su guía de remisión.
 */
export default function TrasladoEmpresasPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const navegar = useNavigate()
  const puedeTrasladar = tiene('INVENTARIO.TRASLADO_EMPRESAS.REGISTRAR')
  const puedeGuia = tiene('VENTAS.GUIA_REMISION')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'nuevo' } o { tipo: 'anular', fila }

  const listado = useListado(['almacen', 'traslados-empresas'], '/ventas/traslados-empresas/', { empresa: empresaActivaId, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = listado.data?.results ?? VACIO

  return (
    <main className="listado">
      <CabeceraListado
        icono="swap"
        titulo="Traslado entre empresas"
        descripcion="Pasa mercadería de una empresa a la otra sin venderla. Sale al costo y la empresa que recibe queda debiéndolo; se liquida junto con las ventas internas."
      >
        {puedeTrasladar && (
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'nuevo' })}>
            <Icono nombre="swap" tam={18} /> Nuevo traslado
          </button>
        )}
      </CabeceraListado>

      <EstadoConsulta consulta={listado} hayDatos={Boolean(listado.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>N°</th>
                <th>Fecha</th>
                <th>Entrega</th>
                <th>Recibe</th>
                <th>De → a</th>
                <th className="num">Productos</th>
                <th className="num">Costo</th>
                <th>Estado</th>
                <th>Guía</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="swap" titulo="Todavía no hay traslados" descripcion="Cuando pases mercadería de una empresa a la otra, aparecerá aquí." />}
              {filas.map((t) => {
                const anulado = t.estado === 'ANULADO'
                return (
                  <tr key={t.id} className={anulado ? 'anulado' : undefined}>
                    <td className="celda-suave">{numero(t.numero)}</td>
                    <td>{fechaCorta(t.fecha)}</td>
                    <td>{t.entrega}</td>
                    <td>{t.recibe}</td>
                    <td className="celda-suave">{t.almacen_origen} → {t.almacen_destino}</td>
                    <td className="num">{t.cantidad_lineas}</td>
                    <td className="num">{dinero(t.total_costo, 'PEN')}</td>
                    <td>
                      <span className="pildora" data-tono={anulado ? 'rojo' : t.liquidado ? 'verde' : 'ambar'}>
                        {anulado ? 'Anulado' : t.liquidado ? 'Liquidado' : 'Por liquidar'}
                      </span>
                    </td>
                    <td className="celda-suave">{t.guia ? t.guia.numero_completo : '—'}</td>
                    <td className="centrado">
                      <span className="acciones-fila">
                        {!anulado && puedeGuia && !t.guia && t.movimiento && (
                          <button type="button" className="accion-icono" aria-label={`Crear la guía de remisión del traslado ${t.numero}`} title="Crear guía de remisión (si la mercadería viaja)" onClick={() => navegar(`/ventas/guias-remision/nueva?traspaso=${t.movimiento}`)}>
                            <Icono nombre="truck" tam={19} />
                          </button>
                        )}
                        {!anulado && puedeTrasladar && (
                          <button type="button" className="accion-icono peligro-suave" aria-label={`Anular el traslado ${t.numero}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', fila: t })}>
                            <Icono nombre="papelera" tam={18} />
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
        total={listado.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

      {dialogo?.tipo === 'nuevo' && <TrasladoEmpresasModal onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'anular' && (
        <AccionConNotaModal
          url={`/ventas/traslados-empresas/${dialogo.fila.id}/anular/`}
          invalidar={[['almacen'], ['movimientos'], ['stock'], ['kardex'], ['ventas']]}
          titulo="Anular el traslado"
          subtitulo={`N° ${numero(dialogo.fila.numero)} · ${dialogo.fila.entrega} → ${dialogo.fila.recibe} · ${dinero(dialogo.fila.total_costo, 'PEN')}`}
          descripcion="La mercadería vuelve a la empresa que la entregó y la deuda entre las empresas se compensa. Si la mercadería ya salió de la empresa que la recibió, no se podrá anular."
          campo="motivo"
          etiqueta="Motivo"
          requerido
          placeholder="Ej. Se cargó por error"
          boton="Anular traslado"
          exito="Traslado anulado."
          peligro
          onCerrar={() => setDialogo(null)}
        />
      )}
    </main>
  )
}
