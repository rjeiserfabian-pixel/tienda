import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import EstadoVacio, { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import AccionConNotaModal from '../components/AccionConNotaModal'
import RendirCajaChicaModal from '../components/RendirCajaChicaModal'
import { dinero } from '../caja'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../caja.css'

/** Cajas chicas: un fondo fijo para gastos menores. Se gasta con comprobantes, se rinde y se repone. */
export default function CajaChicaPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(10)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'rendir', caja } o { tipo: 'anular', rendicion }
  const puedeAnular = tiene('CAJA.MOVIMIENTOS.ANULAR')

  const cajas = useQuery({
    queryKey: ['caja', 'caja-chica', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/caja-chica/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const saldos = useQuery({
    queryKey: ['caja', 'saldos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data.cuentas),
    enabled: Boolean(empresaActivaId),
  })
  const rendiciones = useListado(['caja', 'rendiciones'], '/caja/rendiciones/', { empresa: empresaActivaId, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = rendiciones.data?.results ?? []
  const lista = cajas.data ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="package" titulo="Caja chica" descripcion="Un fondo fijo para gastos menores. Cuando baja, se rinden los gastos con sus comprobantes y otra caja repone lo gastado." />

      <EstadoConsulta consulta={cajas} hayDatos={Boolean(cajas.data)}>
        {lista.length === 0 ? (
          <EstadoVacio icono="package" titulo="Aún no tienes una caja chica" descripcion="En «Cajas y cuentas», crea una caja de efectivo y márcala como «Caja chica»; su fondo inicial sugerido será el fondo fijo." />
        ) : (
          <div className="caja-tarjetas">
            {lista.map((c) => (
              <article key={c.cuenta} className="caja-tarjeta">
                <header>
                  <strong>{c.nombre}</strong>
                  <span className="sub-texto">Fondo fijo {dinero(c.fondo, c.moneda)}{c.sucursal_nombre ? ` · ${c.sucursal_nombre}` : ''}</span>
                </header>
                <p className="caja-saldo" data-negativo={Number(c.saldo) < 0 || undefined}>
                  {dinero(c.saldo, c.moneda)}
                </p>
                <dl className="caja-detalle">
                  <div>
                    <dt>Gastado sin rendir</dt>
                    <dd>{dinero(c.por_rendir_total, c.moneda)}</dd>
                  </div>
                  <div>
                    <dt>Gastos</dt>
                    <dd>{c.por_rendir_cantidad}</dd>
                  </div>
                  <div>
                    <dt>Falta para el fondo</dt>
                    <dd>{dinero(c.faltante, c.moneda)}</dd>
                  </div>
                </dl>
                <footer>
                  <Can permiso="CAJA.CAJA_CHICA.RENDIR">
                    <button type="button" className="primario boton-cabecera" disabled={c.por_rendir_cantidad === 0} onClick={() => setDialogo({ tipo: 'rendir', caja: c })}>
                      <Icono nombre="reactivar" tam={18} /> Rendir y reponer
                    </button>
                  </Can>
                </footer>
              </article>
            ))}
          </div>
        )}
      </EstadoConsulta>

      <section className="caja-grupo" aria-label="Rendiciones hechas">
        <h3>Rendiciones</h3>
        <EstadoConsulta consulta={rendiciones} hayDatos={Boolean(rendiciones.data)}>
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>N°</th>
                  <th>Caja chica</th>
                  <th>Gastos de</th>
                  <th>Repuso desde</th>
                  <th className="num">Gastos</th>
                  <th className="num">Total</th>
                  <th>Estado</th>
                  <th className="centrado">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {filas.length === 0 && <FilaVacia columnas={8} icono="package" titulo="Todavía no hay rendiciones" descripcion="Cuando rindas los gastos de una caja chica, aparecerán aquí." />}
                {filas.map((r) => (
                  <tr key={r.id} className={r.estado === 'ANULADO' ? 'anulado' : undefined}>
                    <td className="celda-suave">{String(r.numero).padStart(6, '0')}</td>
                    <td className="col-texto">
                      {r.cuenta_nombre}
                      {r.glosa && <span className="sub-texto">{r.glosa}</span>}
                      {r.estado === 'ANULADO' && r.motivo_anulacion && <span className="sub-texto">Anulada: {r.motivo_anulacion}</span>}
                    </td>
                    <td>
                      {fechaCorta(r.desde)} – {fechaCorta(r.hasta)}
                    </td>
                    <td>{r.origen_nombre}</td>
                    <td className="num">{r.cantidad}</td>
                    <td className="num">{dinero(r.total, r.moneda)}</td>
                    <td>{r.estado === 'ANULADO' ? <span className="estado-pildora inactivo">Anulada</span> : <span className="estado-pildora activo">Vigente</span>}</td>
                    <td className="centrado">
                      {puedeAnular && r.estado !== 'ANULADO' && (
                        <button type="button" className="accion-icono peligro-suave" aria-label={`Anular la rendición ${r.numero}`} title="Anular" onClick={() => setDialogo({ tipo: 'anular', rendicion: r })}>
                          <Icono nombre="apagar" tam={19} />
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
          total={rendiciones.data?.count ?? 0}
          onPagina={setPagina}
          onTamano={(t) => {
            setTamano(t)
            setPagina(1)
          }}
        />
      </section>

      {dialogo?.tipo === 'rendir' && <RendirCajaChicaModal caja={dialogo.caja} cuentas={saldos.data ?? []} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'anular' && (
        <AccionConNotaModal
          url={`/caja/rendiciones/${dialogo.rendicion.id}/anular/`}
          titulo="Anular la rendición"
          subtitulo={`N° ${String(dialogo.rendicion.numero).padStart(6, '0')} · ${dinero(dialogo.rendicion.total, dialogo.rendicion.moneda)}`}
          descripcion="Se anula también la reposición: el dinero vuelve a la caja de origen y los gastos quedan otra vez por rendir."
          campo="motivo"
          etiqueta="Motivo"
          requerido
          placeholder="Ej. Faltó el comprobante de un gasto"
          boton="Anular"
          ocupado="Anulando…"
          exito="Rendición anulada."
          peligro
          onCerrar={() => setDialogo(null)}
        />
      )}
    </main>
  )
}
