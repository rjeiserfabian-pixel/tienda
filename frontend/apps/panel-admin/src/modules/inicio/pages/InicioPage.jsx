import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import { MARCA } from '../../../core/marca'
import { LogoMarca } from '../../seguridad/components/Iconos'
import { Icono } from '../../../shared/components/IconosPanel'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { dinero } from '../../compras/compras'
import { Dona, Montos, NoDisponible } from '../components/Graficos'
import './inicio.css'

// Accesos a pantallas que ya existen, visibles solo con el permiso correspondiente.
// ``organizacion`` = el permiso es de toda la organización; sin eso se mira en la empresa activa.
const ACCESOS = [
  { texto: 'Punto de venta', ruta: '/ventas/pos', icono: 'cart', permiso: 'VENTAS.VENDER' },
  { texto: 'Registrar compra', ruta: '/compras/registro/nueva', icono: 'truck', permiso: 'COMPRAS.CREAR' },
  { texto: 'Registrar gasto', ruta: '/gastos/registro/nuevo', icono: 'coins', permiso: 'GASTOS.REGISTRAR' },
  { texto: 'Recibir un equipo', ruta: '/servicio-tecnico/ingreso', icono: 'wrench', permiso: 'SERVICIOS.RECEPCIONAR' },
  { texto: 'Todos los reportes', ruta: '/reportes', icono: 'chart' },
  { texto: 'Usuarios', ruta: '/seguridad/usuarios', icono: 'users', permiso: 'SEGURIDAD.USUARIOS.VER', organizacion: true },
  { texto: 'Roles y permisos', ruta: '/seguridad/roles', icono: 'key', permiso: 'SEGURIDAD.ROLES.VER', organizacion: true },
  { texto: 'Empresas', ruta: '/seguridad/empresas', icono: 'building', permiso: 'SEGURIDAD.EMPRESAS.VER', organizacion: true },
  { texto: 'Sucursales', ruta: '/seguridad/sucursales', icono: 'store', permiso: 'SEGURIDAD.SUCURSALES.GESTIONAR', organizacion: true },
  { texto: 'Auditoría', ruta: '/seguridad/auditoria', icono: 'history', permiso: 'SEGURIDAD.AUDITORIA.VER', organizacion: true },
  { texto: 'Organización', ruta: '/seguridad/organizacion', icono: 'settings', permiso: 'SEGURIDAD.ORGANIZACION.GESTIONAR', organizacion: true },
  { texto: 'Mi seguridad', ruta: '/cuenta/seguridad', icono: 'lock' },
  { texto: 'Mis sesiones', ruta: '/seguridad/sesiones', icono: 'devices' },
]

function Panel({ titulo, icono, children, pie }) {
  return (
    <section className="inicio-panel">
      <header>
        <Icono nombre={icono} tam={22} />
        <h3>{titulo}</h3>
        {pie}
      </header>
      {children}
    </section>
  )
}

const num = (v) => Number(v ?? 0).toLocaleString('es-PE', { maximumFractionDigits: 2 })

/** Un indicador del día: ícono, título, montos por moneda y una nota. */
function Indicador({ icono, texto, nota, children, enlace }) {
  const cuerpo = (
    <>
      <span className="indicador-icono"><Icono nombre={icono} tam={26} /></span>
      <div>
        <p>{texto}</p>
        <strong>{children}</strong>
        {nota && <small>{nota}</small>}
      </div>
    </>
  )
  return enlace ? (
    <Link to={enlace} className="indicador indicador-enlace">{cuerpo}</Link>
  ) : (
    <article className="indicador">{cuerpo}</article>
  )
}

const hay = (bloque) => Boolean(bloque) && !bloque.error

export default function InicioPage() {
  const { usuario } = useAuth()
  const { tiene } = usePermisos()
  const { empresaActivaId } = useEmpresas()
  const accesos = ACCESOS.filter((a) => !a.permiso || tiene(a.permiso, { organizacion: Boolean(a.organizacion) }))
  const [monedaElegida, setMonedaElegida] = useState(null)

  const consulta = useQuery({
    queryKey: ['panel', 'inicio', empresaActivaId],
    queryFn: ({ signal }) =>
      api.get('/panel/inicio/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
    staleTime: 60_000,
    refetchInterval: 120_000,
  })
  const bloques = consulta.data?.bloques ?? {}
  const { ventas, por_cobrar: cobrar, compras, gastos, inventario: inv, caja, servicio } = bloques

  const categorias = hay(ventas) ? ventas.por_categoria : []
  const monedas = categorias.map((c) => c.moneda)
  const moneda = monedas.includes(monedaElegida) ? monedaElegida : monedas[0]
  const categoriaActual = categorias.find((c) => c.moneda === moneda)
  const masVendidos = hay(ventas) ? ventas.mas_vendidos : []
  const productos = masVendidos.find((c) => c.moneda === moneda) ?? masVendidos[0]

  return (
    <main className="inicio">
      <header className="inicio-saludo">
        <h2>¡Hola, {usuario.nombres || usuario.username}!</h2>
        <p>Bienvenido al sistema {MARCA.nombre}</p>
      </header>

      <section className="inicio-banner" aria-label="Presentación">
        <div className="banner-marca">
          <LogoMarca tam={74} />
          <div>
            <p className="banner-wordmark" role="img" aria-label={MARCA.nombre}>
              <span aria-hidden="true">{MARCA.nombrePrincipal}</span>
              <span className="acento" aria-hidden="true">{MARCA.nombreAcento}</span>
            </p>
            <p className="banner-lema">Tu tecnología, nuestro compromiso</p>
          </div>
        </div>
        <img className="banner-imagen" src="/banner-productos.jpg" alt="" aria-hidden="true" decoding="async" />
        <div className="banner-mensaje">
          <p className="banner-titulo">
            Potencia
            <span>tu negocio</span>
          </p>
          <p>Ventas • Inventario • Servicios en un solo sistema</p>
        </div>
      </section>

      {consulta.isError && (
        <p className="inicio-pendiente" role="alert">
          No se pudo cargar el resumen.{' '}
          <button type="button" className="enlace-boton" onClick={() => consulta.refetch()}>
            Reintentar
          </button>
        </p>
      )}
      {consulta.isLoading && <p className="inicio-pendiente" aria-live="polite">Cargando el resumen…</p>}

      <section className="inicio-indicadores" aria-label="Indicadores del día">
        {hay(ventas) && (
          <Indicador icono="cart" texto="Ventas de hoy" nota="Neto, con IGV" enlace="/ventas/historial">
            <Montos filas={ventas.hoy} campo="neto" />
          </Indicador>
        )}
        {hay(ventas) && (
          <Indicador icono="tablero" texto="Ventas del mes" nota="Neto, con IGV" enlace="/ventas/reportes">
            <Montos filas={ventas.mes} campo="neto" />
          </Indicador>
        )}
        {hay(cobrar) && (
          <Indicador
            icono="wallet"
            texto="Por cobrar"
            nota={cobrar.totales.some((t) => Number(t.vencido) > 0) ? 'Hay deudas vencidas' : 'Nada vencido'}
            enlace="/ventas/por-cobrar"
          >
            <Montos filas={cobrar.totales} campo="saldo" />
          </Indicador>
        )}
        {hay(compras) && (
          <Indicador
            icono="truck"
            texto="Por pagar"
            nota={compras.por_pagar.some((t) => Number(t.vencido) > 0) ? 'Hay deudas vencidas' : 'Nada vencido'}
            enlace="/compras/por-pagar"
          >
            <Montos filas={compras.por_pagar} campo="saldo" />
          </Indicador>
        )}
        {hay(caja) && (
          <Indicador icono="coins" texto="Caja y bancos" nota={`${caja.cuentas} cuentas activas`} enlace="/caja/saldos">
            <Montos filas={caja.saldos} campo="monto" />
          </Indicador>
        )}
        {hay(servicio) && (
          <Indicador
            icono="wrench"
            texto="Servicio técnico"
            nota={`${servicio.listas_para_entrega} listas para entregar`}
            enlace="/servicio-tecnico/tablero"
          >
            {servicio.abiertas} abiertas
          </Indicador>
        )}
      </section>

      <div className="inicio-paneles">
        {ventas && (
          <Panel titulo="Ventas por categoría (mes)" icono="chart">
            {ventas.error ? (
              <NoDisponible />
            ) : (
              <>
                {monedas.length > 1 && (
                  <div className="pildoras" role="group" aria-label="Moneda">
                    {monedas.map((m) => (
                      <button key={m} type="button" aria-pressed={m === moneda} onClick={() => setMonedaElegida(m)}>
                        {m === 'USD' ? 'Dólares' : 'Soles'}
                      </button>
                    ))}
                  </div>
                )}
                <Dona filas={categoriaActual?.filas ?? []} moneda={moneda} />
              </>
            )}
          </Panel>
        )}

        {ventas && (
          <Panel titulo="Productos más vendidos (mes)" icono="package">
            {ventas.error ? (
              <NoDisponible />
            ) : (
              <table className="tabla inicio-tabla">
                <thead>
                  <tr><th>#</th><th>Producto</th><th>Cant.</th><th>Total</th></tr>
                </thead>
                <tbody>
                  {(productos?.filas ?? []).filter((f) => f.nombre !== 'Otros').map((f, i) => (
                    <tr key={f.nombre}>
                      <td>{i + 1}</td>
                      <td>{f.nombre}</td>
                      <td>{num(f.unidades)}</td>
                      <td>{dinero(f.valor, productos.moneda)}</td>
                    </tr>
                  ))}
                  {!productos?.filas?.length && (
                    <tr><td colSpan={4} className="estado-vacio">Aún no hay ventas este mes.</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </Panel>
        )}

        {inv && (
          <Panel titulo="Estado del inventario" icono="boxes">
            {inv.error ? (
              <NoDisponible />
            ) : (
              <dl className="inicio-lista">
                <div><dt>Unidades en stock</dt><dd>{num(inv.unidades)}</dd></div>
                <div><dt>Productos con stock</dt><dd>{inv.productos_con_stock}</dd></div>
                <div>
                  <dt><Link to="/almacen/stock">Productos en bajo stock</Link></dt>
                  <dd data-tono={inv.productos_bajo_minimo ? 'alerta' : undefined}>{inv.productos_bajo_minimo}</dd>
                </div>
                <div>
                  <dt>Productos agotados</dt>
                  <dd data-tono={inv.productos_agotados ? 'alerta' : undefined}>{inv.productos_agotados}</dd>
                </div>
                <div><dt>Valor al costo</dt><dd>{dinero(inv.valor_costo_soles, 'PEN')}</dd></div>
                {inv.stock_antiguo && (
                  <div>
                    <dt>
                      <Link to="/almacen/reportes" title={`Stock que lleva más de ${inv.stock_antiguo.umbral_dias} días en el almacén`}>Productos con stock antiguo</Link>
                    </dt>
                    <dd data-tono={inv.stock_antiguo.productos ? 'alerta' : undefined}>
                      {inv.stock_antiguo.productos}
                      {inv.stock_antiguo.productos > 0 && <small> · {dinero(inv.stock_antiguo.valor_costo_soles, 'PEN')}</small>}
                    </dd>
                  </div>
                )}
              </dl>
            )}
          </Panel>
        )}
      </div>

      <div className="inicio-paneles dos">
        <Panel titulo="Accesos rápidos" icono="tendencia">
          <div className="inicio-accesos">
            {accesos.map((a) => (
              <Link key={a.ruta} to={a.ruta} className="acceso">
                <Icono nombre={a.icono} tam={28} />
                <span>{a.texto}</span>
              </Link>
            ))}
          </div>
        </Panel>

        <div className="inicio-columna">
          {(hay(ventas) || hay(compras) || hay(gastos)) && (
            <Panel titulo="Resumen del mes" icono="tablero">
              <dl className="inicio-lista">
                {hay(ventas) && (
                  <div><dt>Ventas netas</dt><dd><Montos filas={ventas.mes} campo="neto" /></dd></div>
                )}
                {hay(compras) && (
                  <div><dt>Compras</dt><dd><Montos filas={compras.mes} campo="total" /></dd></div>
                )}
                {hay(gastos) && (
                  <div><dt>Gastos</dt><dd><Montos filas={gastos.mes} campo="total" /></dd></div>
                )}
                {hay(ventas) && ventas.con_utilidad && (
                  <div>
                    <dt>Utilidad bruta (ventas)</dt>
                    <dd><Montos filas={ventas.mes} campo="utilidad" tono="bueno" /></dd>
                  </div>
                )}
              </dl>
              <p className="inicio-pendiente">
                Importes con IGV. Soles y dólares se muestran por separado.
              </p>
            </Panel>
          )}

          {hay(caja) && caja.avisos.length > 0 && (
            <Panel titulo="Para revisar hoy" icono="bell">
              <ul className="inicio-avisos">
                {caja.avisos.map((a) => (
                  <li key={a.codigo} data-nivel={a.nivel}>
                    <Link to={a.enlace}>
                      <strong>{a.titulo}</strong>
                      <span>{a.detalle}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </main>
  )
}
