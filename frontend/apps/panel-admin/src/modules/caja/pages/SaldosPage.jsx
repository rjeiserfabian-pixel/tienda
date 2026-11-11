import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import EstadoVacio from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { fechaCorta } from '../../almacen/inventario'
import AbrirSesionModal from '../components/AbrirSesionModal'
import AlertasCaja from '../components/AlertasCaja'
import ContarSesionModal from '../components/ContarSesionModal'
import MovimientoModal from '../components/MovimientoModal'
import TransferenciaModal from '../components/TransferenciaModal'
import { dinero, GRUPOS_DE_CUENTA, ROLES_CAJA } from '../caja'
import '../../almacen/inventario.css'
import '../../compras/compras.css'
import '../caja.css'

/** Cuánto dinero hay en cada caja y cuenta de la empresa, y el total por moneda. */
export default function SaldosPage() {
  const navegar = useNavigate()
  const { empresaActivaId } = useEmpresas()
  const [dialogo, setDialogo] = useState(null) // { tipo, cuenta? }
  const consulta = useQuery({
    queryKey: ['caja', 'saldos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const datos = consulta.data
  const cuentas = datos?.cuentas ?? []

  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="Saldos" descripcion="El dinero que hay en cada caja, cuenta de banco y billetera de la empresa. Cada saldo sale del libro de movimientos.">
        <Can permiso="CAJA.TRANSFERIR">
          <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'MOVER' })}>
            <Icono nombre="swap" tam={19} /> Mover dinero
          </button>
        </Can>
        <Can permiso="CAJA.MOVIMIENTOS.CREAR">
          <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'EGRESO' })}>
            <Icono nombre="agregar" tam={19} /> Egreso
          </button>
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'INGRESO' })}>
            <Icono nombre="agregar" tam={20} /> Ingreso
          </button>
        </Can>
      </CabeceraListado>

      <AlertasCaja />

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && cuentas.length === 0 ? (
          <EstadoVacio icono="wallet" titulo="Aún no hay cajas ni cuentas" descripcion="Registra las de tu empresa para empezar a llevar su dinero.">
            <button type="button" className="primario" onClick={() => navegar('/caja/cuentas')}>
              Registrar una caja o cuenta
            </button>
          </EstadoVacio>
        ) : (
          datos && (
            <>
              <dl className="cxp-tarjetas" aria-label="Total por moneda">
                {datos.totales.map((t) => (
                  <div key={t.moneda} data-tono={Number(t.saldo) < 0 ? 'rojo' : undefined}>
                    <dt>Total en {t.moneda === 'USD' ? 'dólares' : 'soles'}</dt>
                    <dd>{dinero(t.saldo, t.moneda)}</dd>
                    <small>Suma de las cuentas activas</small>
                  </div>
                ))}
              </dl>
              {GRUPOS_DE_CUENTA.map(([tipo, titulo]) => {
                const delGrupo = cuentas.filter((c) => c.tipo === tipo)
                if (delGrupo.length === 0) return null
                return (
                  <section key={tipo} aria-label={titulo} className="caja-grupo">
                    <h3>{titulo}</h3>
                    <div className="caja-tarjetas">
                      {delGrupo.map((c) => (
                        <article key={c.cuenta} className={`caja-tarjeta${c.estado !== 'ACTIVO' ? ' inactiva' : ''}`}>
                          <header>
                            <strong>{c.nombre}</strong>
                            <span className="sub-texto">
                              {c.moneda === 'USD' ? 'Dólares' : 'Soles'}
                              {c.sucursal_nombre ? ` · ${c.sucursal_nombre}` : ''}
                              {c.estado !== 'ACTIVO' ? ' · Inactiva' : ''}
                            </span>
                            {c.rol_caja && <span className="pildora caja-rol" data-tono={c.rol_caja === 'PRINCIPAL' ? 'morado' : 'gris'}>{ROLES_CAJA[c.rol_caja]}</span>}
                          </header>
                          <p className="caja-saldo" data-negativo={Number(c.saldo) < 0 || undefined}>
                            {dinero(c.saldo, c.moneda)}
                          </p>
                          {c.saldo_minimo !== null && Number(c.saldo) >= 0 && Number(c.saldo) < Number(c.saldo_minimo) && <p className="caja-bajo">Bajo su mínimo de {dinero(c.saldo_minimo, c.moneda)}: conviene reponer.</p>}
                          {Number(c.saldo) < 0 && <p className="compra-aviso">Ya salió más dinero del que se registró que entró. Registra con cuánto empezó (saldo inicial en «Cajas y cuentas») o el ingreso que falta.</p>}
                          <dl className="caja-detalle">
                            <div>
                              <dt>Entró</dt>
                              <dd>{dinero(c.ingresos, c.moneda)}</dd>
                            </div>
                            <div>
                              <dt>Salió</dt>
                              <dd>{dinero(c.egresos, c.moneda)}</dd>
                            </div>
                          </dl>
                          <p className="celda-suave">
                            Saldo inicial {dinero(c.saldo_inicial, c.moneda)}
                            {c.ultimo_movimiento ? ` · último movimiento ${fechaCorta(c.ultimo_movimiento)}` : ' · sin movimientos'}
                          </p>
                          {c.tipo === 'CAJA' && c.estado === 'ACTIVO' && (c.sesion || c.exige_sesion) && (
                            <p className="caja-sesion" data-abierta={c.sesion ? true : undefined}>
                              {c.sesion ? `Abierta por ${c.sesion.responsable_nombre} desde ${new Date(c.sesion.abierta_en).toLocaleString('es-PE', { dateStyle: 'short', timeStyle: 'short' })}` : 'Cerrada: abre la sesión para mover su efectivo.'}
                            </p>
                          )}
                          {c.tipo === 'CAJA' && c.estado === 'ACTIVO' && !c.exige_sesion && <p className="compra-aviso">No exige abrir turno: su efectivo se mueve aunque nadie la abra. Actívalo en «Cajas y cuentas» para controlar cada día.</p>}
                          {c.tipo === 'CAJA' && c.estado === 'ACTIVO' && !c.sucursal_nombre && <p className="compra-aviso">Sin sucursal: no comparte mostrador con otra empresa. Asígnale su sucursal en «Cajas y cuentas».</p>}
                          <footer>
                            {c.tipo === 'CAJA' && c.estado === 'ACTIVO' && (
                              <Can permiso="CAJA.SESIONES.ABRIR">
                                {c.sesion ? (
                                  <>
                                    <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'CONTAR', sesion: c.sesion.id })}>
                                      <Icono nombre="calculator" tam={18} /> Contar
                                    </button>
                                    <button type="button" className="boton-cabecera" onClick={() => setDialogo({ tipo: 'CERRAR_CAJA', sesion: c.sesion.id })}>
                                      <Icono nombre="lock" tam={18} /> Cerrar caja
                                    </button>
                                  </>
                                ) : (
                                  <button type="button" className="primario boton-cabecera" title={c.exige_sesion ? 'Esta caja exige abrirse antes de mover su efectivo' : 'Opcional: abre tu turno para contar el efectivo al cerrar'} onClick={() => setDialogo({ tipo: 'ABRIR', cuenta: c })}>
                                    <Icono nombre="reactivar" tam={18} /> Abrir caja
                                  </button>
                                )}
                              </Can>
                            )}
                            <button type="button" className="boton-cabecera" onClick={() => navegar(`/caja/movimientos?cuenta=${c.cuenta}`)}>
                              <Icono nombre="tabla" tam={18} /> Ver movimientos
                            </button>
                          </footer>
                        </article>
                      ))}
                    </div>
                  </section>
                )
              })}
            </>
          )
        )}
      </EstadoConsulta>

      {dialogo?.tipo === 'MOVER' && <TransferenciaModal cuentas={cuentas} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'ABRIR' && <AbrirSesionModal cuenta={dialogo.cuenta} cuentas={cuentas} onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'CONTAR' && <ContarSesionModal sesionId={dialogo.sesion} modo="arquear" onCerrar={() => setDialogo(null)} />}
      {dialogo?.tipo === 'CERRAR_CAJA' && <ContarSesionModal sesionId={dialogo.sesion} modo="cerrar" onCerrar={() => setDialogo(null)} />}
      {dialogo && ['EGRESO', 'INGRESO'].includes(dialogo.tipo) && <MovimientoModal tipoInicial={dialogo.tipo} umbral={datos?.umbral_bancarizacion} cuentas={cuentas} cuentaInicial={dialogo.cuenta} onCerrar={() => setDialogo(null)} />}
    </main>
  )
}
