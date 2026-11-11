import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import AccionConNotaModal from '../../caja/components/AccionConNotaModal'
import { BotonDescarga } from '../../caja/components/ReporteComun'
import { dinero } from '../../compras/compras'
import LiquidarInternaModal from '../components/LiquidarInternaModal'
import '../../almacen/inventario.css'
import '../ventas.css'

const VACIO = []
const numero = (n) => String(n).padStart(6, '0')

/**
 * Liquidación entre empresas: lo que se deben por las ventas internas (la mercadería de una que
 * vendió la otra) y el historial de lo ya liquidado. Se suele liquidar al cerrar la caja del día.
 */
export default function LiquidacionInternaPage() {
  const { empresaActivaId } = useEmpresas()
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [errorInforme, setErrorInforme] = useState('')
  const [dialogo, setDialogo] = useState(null) // { tipo: 'liquidar', pendiente } o { tipo: 'anular', fila }

  const pendientes = useQuery({
    queryKey: ['ventas', 'liquidaciones-internas-pendientes', empresaActivaId],
    queryFn: ({ signal }) => api.get('/ventas/liquidaciones-internas/pendientes/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const historial = useListado(['ventas', 'liquidaciones-internas'], '/ventas/liquidaciones-internas/', { empresa: empresaActivaId, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = historial.data?.results ?? VACIO
  const grupos = pendientes.data ?? VACIO

  return (
    <main className="listado">
      <CabeceraListado icono="swap" titulo="Liquidación entre empresas" descripcion="Cuando una empresa vende mercadería de la otra, le debe lo que costó; y cuando una cobra con Culqi un pedido de la tienda que incluye productos de la otra, le debe ese dinero. Aquí se compensa lo que se deben y se salda." />

      <EstadoConsulta consulta={pendientes} hayDatos={Boolean(pendientes.data)}>
        {grupos.length === 0 ? (
          <p className="estado-vacio">No hay nada por liquidar entre las empresas.</p>
        ) : (
          <div className="cxp-resumen">
            {grupos.map((g) => (
              <dl className="cxp-tarjetas" key={`${g.local}-${g.pagadora}-${g.receptora}`} aria-label={`${g.pagadora_nombre} y ${g.receptora_nombre}`}>
                <div data-tono={Number(g.monto) > 0 ? 'ambar' : undefined}>
                  <dt>
                    {Number(g.monto) > 0 ? `${g.pagadora_nombre} debe a ${g.receptora_nombre}` : `${g.pagadora_nombre} y ${g.receptora_nombre}`}
                  </dt>
                  <dd>{dinero(g.monto, 'PEN')}</dd>
                  <small>
                    {g.origen === 'COBRO_TIENDA' ? 'Cobros de la tienda virtual · ' : ''}
                    {g.partidas.length} {g.partidas.length === 1 ? 'partida' : 'partidas'}
                    {Number(g.monto) === 0 ? ' · se compensan' : ''}
                  </small>
                </div>
                <div className="liquidar-accion">
                  <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'liquidar', pendiente: g })}>
                    <Icono nombre="swap" tam={18} /> {Number(g.monto) > 0 ? 'Liquidar' : 'Cerrar cuentas'}
                  </button>
                </div>
              </dl>
            ))}
          </div>
        )}
      </EstadoConsulta>

      <h3>Liquidaciones hechas</h3>
      {errorInforme && (
        <p role="alert" className="campo-error">
          {errorInforme}
        </p>
      )}
      <EstadoConsulta consulta={historial} hayDatos={Boolean(historial.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>N°</th>
                <th>Fecha</th>
                <th>Paga</th>
                <th>Recibe</th>
                <th>De → a</th>
                <th className="num">Monto</th>
                <th className="num">Partidas</th>
                <th>Estado</th>
                <th>Informe</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={10} icono="swap" titulo="Todavía no hay liquidaciones" descripcion="Cuando liquides lo que se deben las empresas, aparecerá aquí." />}
              {filas.map((l) => (
                <tr key={l.id} className={l.estado === 'ANULADO' ? 'anulado' : undefined}>
                  <td className="celda-suave">{numero(l.numero)}</td>
                  <td>{fechaCorta(l.fecha)}</td>
                  <td>{l.paga}</td>
                  <td>{l.recibe}</td>
                  <td className="celda-suave">{l.desde ? `${l.desde} → ${l.hacia}` : 'Se compensaron'}{l.local === 'TIENDA_WEB' ? ' · tienda virtual' : ''}</td>
                  <td className="num">{dinero(l.monto, 'PEN')}</td>
                  <td className="num">{l.cantidad_partidas}</td>
                  <td>
                    <span className="pildora" data-tono={l.estado === 'ANULADO' ? 'rojo' : 'verde'}>
                      {l.estado === 'ANULADO' ? 'Anulada' : 'Vigente'}
                    </span>
                  </td>
                  <td>
                    <BotonDescarga url={`/ventas/liquidaciones-internas/${l.id}/excel/`} params={{ empresa: empresaActivaId }} texto="Excel" onError={setErrorInforme} />
                  </td>
                  <td className="centrado">
                    {l.estado !== 'ANULADO' && (
                      <button type="button" className="accion-icono peligro-suave" aria-label={`Anular la liquidación ${l.numero}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', fila: l })}>
                        <Icono nombre="papelera" tam={18} />
                      </button>
                    )}
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
        total={historial.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

      {dialogo?.tipo === 'liquidar' && <LiquidarInternaModal pendiente={dialogo.pendiente} empresaId={empresaActivaId} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'anular' && (
        <AccionConNotaModal
          url={`/ventas/liquidaciones-internas/${dialogo.fila.id}/anular/`}
          invalidar={[['ventas'], ['caja']]}
          titulo="Anular la liquidación"
          subtitulo={`N° ${numero(dialogo.fila.numero)} · ${dinero(dialogo.fila.monto, 'PEN')}`}
          descripcion="Se anula el asiento entre las cajas y lo que se deben vuelve a quedar pendiente."
          campo="motivo"
          etiqueta="Motivo"
          requerido
          placeholder="Ej. Se liquidó por error"
          boton="Anular liquidación"
          exito="Liquidación anulada."
          peligro
          onCerrar={() => setDialogo(null)}
        />
      )}
    </main>
  )
}
