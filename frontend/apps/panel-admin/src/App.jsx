import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './core/auth/AuthContext'
import RedirigirFicha from './core/router/RedirigirFicha'
import RequireAuth from './core/router/RequireAuth'
import RequirePermiso from './core/router/RequirePermiso'
import LoginPage from './modules/seguridad/pages/LoginPage'
import ErrorBoundary from './shared/components/ErrorBoundary'
import { NotificacionesProvider } from './shared/contexts/NotificacionesContext'
import { EmpresasProvider } from './shared/contexts/EmpresasContext'
import { PermisosProvider } from './shared/contexts/PermisosContext'
import DashboardLayout from './shared/layouts/DashboardLayout'
import InicioPage from './modules/inicio/pages/InicioPage'
import NoEncontradaPage from './modules/inicio/pages/NoEncontradaPage'
import { ALMACENES, CENTROS_COSTO, CATEGORIAS_GASTO, CLIENTES, CONCEPTOS_CAJA, CONDUCTORES, CUENTAS_FINANCIERAS, EMPRESAS_TRANSPORTE, LISTAS_PRECIO, MARCAS, MEDIOS_PAGO, PERIODICIDADES, PERSONAL, PROVEEDORES, SERIES_COMPROBANTE, TIPOS_COMPROBANTE, UBICACIONES, UNIDADES, VEHICULOS } from './modules/mantenimiento/maestros'

import { CATALOGOS_SERVICIO } from './modules/servicio-tecnico/catalogos'
import { CATALOGOS_RRHH } from './modules/rrhh/maestros'

const MaestroListado = lazy(() => import('./modules/mantenimiento/components/MaestroListado'))
const TipoCambioPage = lazy(() => import('./modules/mantenimiento/pages/TipoCambioPage'))
const ClasificacionPage = lazy(() => import('./modules/mantenimiento/pages/ClasificacionPage'))
const ProductosTiendaPage = lazy(() => import('./modules/tienda/pages/ProductosTiendaPage'))
const EspecificacionesTiendaPage = lazy(() => import('./modules/tienda/pages/EspecificacionesTiendaPage'))
const ConfiguracionTiendaPage = lazy(() => import('./modules/tienda/pages/ConfiguracionTiendaPage'))
const EnviosTiendaPage = lazy(() => import('./modules/tienda/pages/EnviosTiendaPage'))
const ArmadorTiendaPage = lazy(() => import('./modules/tienda/pages/ArmadorTiendaPage'))
const PagosTiendaPage = lazy(() => import('./modules/tienda/pages/PagosTiendaPage'))
const PedidosTiendaPage = lazy(() => import('./modules/tienda/pages/PedidosTiendaPage'))
const OfertasTiendaPage = lazy(() => import('./modules/tienda/pages/OfertasTiendaPage'))
const ProductosPage = lazy(() => import('./modules/almacen/pages/ProductosPage'))
const PuntoVentaPage = lazy(() => import('./modules/ventas/pages/PuntoVentaPage'))
const VentasPage = lazy(() => import('./modules/ventas/pages/VentasPage'))
const VentaFichaPage = lazy(() => import('./modules/ventas/pages/VentaFichaPage'))
const CuentasDeCobroPage = lazy(() => import('./modules/ventas/pages/CuentasDeCobroPage'))
const LiquidacionTarjetasPage = lazy(() => import('./modules/ventas/pages/LiquidacionTarjetasPage'))
const LiquidacionInternaPage = lazy(() => import('./modules/ventas/pages/LiquidacionInternaPage'))
const ProformasPage = lazy(() => import('./modules/ventas/pages/ProformasPage'))
const ProformaFichaPage = lazy(() => import('./modules/ventas/pages/ProformaFichaPage'))
const NuevaProformaPage = lazy(() => import('./modules/ventas/pages/NuevaProformaPage'))
const NotasCreditoPage = lazy(() => import('./modules/ventas/pages/NotasCreditoPage'))
const NuevaNotaCreditoPage = lazy(() => import('./modules/ventas/pages/NuevaNotaCreditoPage'))
const CentroReportesPage = lazy(() => import('./modules/reportes/pages/CentroReportesPage'))
const ReportesVentasPage = lazy(() => import('./modules/ventas/pages/ReportesVentasPage'))
const GuiasRemisionPage =lazy(() => import('./modules/ventas/pages/GuiasRemisionPage'))
const NuevaGuiaPage = lazy(() => import('./modules/ventas/pages/NuevaGuiaPage'))
const VentasPorCobrarPage = lazy(() => import('./modules/ventas/pages/VentasPorCobrarPage'))
const ConsultaPreciosPage = lazy(() => import('./modules/ventas/pages/ConsultaPreciosPage'))
const OrdenesPage = lazy(() => import('./modules/servicio-tecnico/pages/OrdenesPage'))
const EstadoPublicoPage = lazy(() => import('./modules/servicio-tecnico/pages/EstadoPublicoPage'))
const AvisosWhatsappPage = lazy(() => import('./modules/servicio-tecnico/pages/AvisosWhatsappPage'))
const TableroPage = lazy(() => import('./modules/servicio-tecnico/pages/TableroPage'))
const ReportesServicioPage = lazy(() => import('./modules/servicio-tecnico/pages/ReportesServicioPage'))
const MisOrdenesPage = lazy(() => import('./modules/servicio-tecnico/pages/MisOrdenesPage'))
const OrdenFichaPage = lazy(() => import('./modules/servicio-tecnico/pages/OrdenFichaPage'))
const RegistrarIngresoPage = lazy(() => import('./modules/servicio-tecnico/pages/RegistrarIngresoPage'))
const IgvPage = lazy(() => import('./modules/mantenimiento/pages/IgvPage'))
const ProductoFichaPage = lazy(() => import('./modules/almacen/pages/ProductoFichaPage'))
const ComprasPage = lazy(() => import('./modules/compras/pages/ComprasPage'))
const CuentasPorPagarPage = lazy(() => import('./modules/compras/pages/CuentasPorPagarPage'))
const CompraFichaPage = lazy(() => import('./modules/compras/pages/CompraFichaPage'))
const SaldosPage = lazy(() => import('./modules/caja/pages/SaldosPage'))
const MovimientosCajaPage = lazy(() => import('./modules/caja/pages/MovimientosCajaPage'))
const TransferenciasPage = lazy(() => import('./modules/caja/pages/TransferenciasPage'))
const SesionesCajaPage = lazy(() => import('./modules/caja/pages/SesionesCajaPage'))
const ReportesGastosPage = lazy(() => import('./modules/gastos/pages/ReportesGastosPage'))
const RecurrentesPage = lazy(() => import('./modules/gastos/pages/RecurrentesPage'))
const GastosPage = lazy(() => import('./modules/gastos/pages/GastosPage'))
const RegistrarGastoPage = lazy(() => import('./modules/gastos/pages/RegistrarGastoPage'))
const GastoFichaPage = lazy(() => import('./modules/gastos/pages/GastoFichaPage'))
const CajaChicaPage = lazy(() => import('./modules/caja/pages/CajaChicaPage'))
const ReportesCajaPage = lazy(() => import('./modules/caja/pages/ReportesCajaPage'))
const ConciliacionPage = lazy(() => import('./modules/caja/pages/ConciliacionPage'))
const ChequesPage = lazy(() => import('./modules/caja/pages/ChequesPage'))
const ConciliacionDetallePage = lazy(() => import('./modules/caja/pages/ConciliacionDetallePage'))
const RegistroComprasPage = lazy(() => import('./modules/compras/pages/RegistroComprasPage'))
const RegistrarCompraPage = lazy(() => import('./modules/compras/pages/RegistrarCompraPage'))
const DevolucionesPage = lazy(() => import('./modules/compras/pages/DevolucionesPage'))
const OrdenesCompraPage = lazy(() => import('./modules/compras/pages/OrdenesCompraPage'))
const ReposicionPage = lazy(() => import('./modules/compras/pages/ReposicionPage'))
const ReporteOrdenesPage = lazy(() => import('./modules/compras/pages/ReporteOrdenesPage'))
const OrdenCompraFichaPage = lazy(() => import('./modules/compras/pages/OrdenCompraFichaPage'))
const OrdenCompraFormPage = lazy(() => import('./modules/compras/pages/OrdenCompraFormPage'))
const CotizacionesPage = lazy(() => import('./modules/compras/pages/CotizacionesPage'))
const CotizacionFichaPage = lazy(() => import('./modules/compras/pages/CotizacionFichaPage'))
const CotizacionFormPage = lazy(() => import('./modules/compras/pages/CotizacionFormPage'))
const ReporteDevolucionesPage = lazy(() => import('./modules/compras/pages/ReporteDevolucionesPage'))
const DevolucionFichaPage = lazy(() => import('./modules/compras/pages/DevolucionFichaPage'))
const DevolverCompraPage = lazy(() => import('./modules/compras/pages/DevolverCompraPage'))
const AnticiposPage = lazy(() => import('./modules/compras/pages/AnticiposPage'))
const SaldosAFavorPage = lazy(() => import('./modules/compras/pages/SaldosAFavorPage'))
const StockPage = lazy(() => import('./modules/almacen/pages/StockPage'))
const MovimientosPage = lazy(() => import('./modules/almacen/pages/MovimientosPage'))
const KardexPage = lazy(() => import('./modules/almacen/pages/KardexPage'))
const TrasladoEmpresasPage = lazy(() => import('./modules/almacen/pages/TrasladoEmpresasPage'))
const ReportesPage = lazy(() => import('./modules/almacen/pages/ReportesPage'))
const SeriesPage = lazy(() => import('./modules/almacen/pages/SeriesPage'))
const FacturacionPage = lazy(() => import('./modules/facturacion/pages/FacturacionPage'))
const TomasPage = lazy(() => import('./modules/almacen/pages/TomasPage'))
const TomaFichaPage = lazy(() => import('./modules/almacen/pages/TomaFichaPage'))
const TrabajadoresPage = lazy(() => import('./modules/rrhh/pages/TrabajadoresPage'))
const TrabajadorFichaPage = lazy(() => import('./modules/rrhh/pages/TrabajadorFichaPage'))
const AsistenciaPage = lazy(() => import('./modules/rrhh/pages/AsistenciaPage'))
const AdelantosPage = lazy(() => import('./modules/rrhh/pages/AdelantosPage'))
const PlanillasPage = lazy(() => import('./modules/rrhh/pages/PlanillasPage'))
const PlanillaPage = lazy(() => import('./modules/rrhh/pages/PlanillaPage'))
const VacacionesPage = lazy(() => import('./modules/rrhh/pages/VacacionesPage'))
const CtsPage = lazy(() => import('./modules/rrhh/pages/CtsPage'))
const ReportesRrhhPage = lazy(() => import('./modules/rrhh/pages/ReportesPage'))
const MiPortalPage = lazy(() => import('./modules/rrhh/pages/MiPortalPage'))
const CtsDetallePage = lazy(() => import('./modules/rrhh/pages/CtsDetallePage'))
const MaestroFicha = lazy(() => import('./modules/mantenimiento/components/MaestroFicha'))
const UsuariosPage = lazy(() => import('./modules/seguridad/pages/UsuariosPage'))
const UsuarioDetallePage = lazy(() => import('./modules/seguridad/pages/UsuarioDetallePage'))
const RolesPage = lazy(() => import('./modules/seguridad/pages/RolesPage'))
const RolDetallePage = lazy(() => import('./modules/seguridad/pages/RolDetallePage'))
const SesionesPage = lazy(() => import('./modules/seguridad/pages/SesionesPage'))
const CambiarPasswordPage = lazy(() => import('./modules/seguridad/pages/CambiarPasswordPage'))
const EmpresasPage = lazy(() => import('./modules/organizacion/pages/EmpresasPage'))
const EmpresaDetallePage = lazy(() => import('./modules/organizacion/pages/EmpresaDetallePage'))
const SucursalesPage = lazy(() => import('./modules/organizacion/pages/SucursalesPage'))

const CuentaSeguridadPage = lazy(() => import('./modules/seguridad/pages/CuentaSeguridadPage'))
const AuditoriaPage = lazy(() => import('./modules/seguridad/pages/AuditoriaPage'))
const RecuperarPage = lazy(() => import('./modules/seguridad/pages/RecuperarPage'))
const RecuperarConfirmarPage = lazy(() => import('./modules/seguridad/pages/RecuperarConfirmarPage'))
const OrganizacionPage = lazy(() => import('./modules/organizacion/pages/OrganizacionPage'))

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
})

// Los contextos que dependen de un usuario autenticado viven DENTRO de RequireAuth.
function PanelProviders({ children }) {
  return (
    <EmpresasProvider>
      <PermisosProvider>{children}</PermisosProvider>
    </EmpresasProvider>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <NotificacionesProvider>
        <AuthProvider>
          <BrowserRouter>
            <Suspense fallback={<p style={{ padding: 24 }}>Cargando…</p>}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/estado/:token" element={<EstadoPublicoPage />} />
              <Route path="/recuperar" element={<RecuperarPage />} />
              <Route path="/recuperar/confirmar" element={<RecuperarConfirmarPage />} />
              <Route element={<RequireAuth />}>
                <Route
                  element={
                    <PanelProviders>
                      <DashboardLayout />
                    </PanelProviders>
                  }
                >
                  <Route path="/" element={<InicioPage />} />
                  <Route path="/reportes" element={<CentroReportesPage />} />
                  <Route path="/reportes/:area" element={<CentroReportesPage />} />
                  <Route path="/cuenta/password" element={<CambiarPasswordPage />} />
                  <Route path="/cuenta/seguridad" element={<CuentaSeguridadPage />} />
                  <Route path="/seguridad/sesiones" element={<SesionesPage />} />
                  <Route element={<RequirePermiso permiso="SEGURIDAD.AUDITORIA.VER" organizacion />}>
                    <Route path="/seguridad/auditoria" element={<AuditoriaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SEGURIDAD.ORGANIZACION.GESTIONAR" organizacion />}>
                    <Route path="/seguridad/organizacion" element={<OrganizacionPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SEGURIDAD.USUARIOS.VER" organizacion />}>
                    <Route path="/seguridad/usuarios" element={<UsuariosPage />} />
                    <Route path="/seguridad/usuarios/:id" element={<UsuarioDetallePage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SEGURIDAD.ROLES.VER" organizacion />}>
                    <Route path="/seguridad/roles" element={<RolesPage />} />
                    <Route path="/seguridad/roles/:id" element={<RolDetallePage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SEGURIDAD.EMPRESAS.VER" organizacion />}>
                    <Route path="/seguridad/empresas" element={<EmpresasPage />} />
                    <Route path="/seguridad/empresas/:id" element={<EmpresaDetallePage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SEGURIDAD.SUCURSALES.GESTIONAR" organizacion />}>
                    <Route path="/seguridad/sucursales" element={<SucursalesPage />} />
                  </Route>
                  {[PERSONAL, CLIENTES, PROVEEDORES, MARCAS, ALMACENES, UBICACIONES, TIPOS_COMPROBANTE, SERIES_COMPROBANTE, MEDIOS_PAGO, PERIODICIDADES, CUENTAS_FINANCIERAS, CONCEPTOS_CAJA, CATEGORIAS_GASTO, CENTROS_COSTO, UNIDADES, LISTAS_PRECIO, EMPRESAS_TRANSPORTE, CONDUCTORES, VEHICULOS, ...CATALOGOS_SERVICIO, ...CATALOGOS_RRHH].map((config) => (
                    <Route key={config.clave} element={<RequirePermiso permiso={`${config.permiso}.VER`} organizacion={config.deOrganizacion} />}>
                      <Route path={config.ruta} element={<MaestroListado config={config} />} />
                      <Route path={`${config.ruta}/:id`} element={<MaestroFicha config={config} />} />
                    </Route>
                  ))}
                  <Route element={<RequirePermiso permiso="MANTENIMIENTO.IGV.VER" organizacion />}>
                    <Route path="/mantenimiento/igv" element={<IgvPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="MANTENIMIENTO.PRODUCTOS.VER" organizacion />}>
                    <Route path="/ventas/consulta-precios" element={<ConsultaPreciosPage />} />
                    <Route path="/almacen/productos" element={<ProductosPage />} />
                    <Route path="/almacen/productos/:id" element={<ProductoFichaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="MANTENIMIENTO.PRODUCTOS.CREAR" organizacion />}>
                    <Route path="/almacen/productos/nuevo" element={<ProductoFichaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="INVENTARIO.VER" />}>
                    <Route path="/almacen/stock" element={<StockPage />} />
                    <Route path="/almacen/movimientos" element={<MovimientosPage />} />
                    <Route path="/almacen/kardex" element={<KardexPage />} />
                    <Route path="/almacen/traslado-empresas" element={<TrasladoEmpresasPage />} />
                    <Route path="/almacen/series" element={<SeriesPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="INVENTARIO.TOMAS.VER" />}>
                    <Route path="/almacen/tomas" element={<TomasPage />} />
                    <Route path="/almacen/tomas/:id" element={<TomaFichaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.TRABAJADORES.VER" />}>
                    <Route path="/rrhh/trabajadores" element={<TrabajadoresPage />} />
                    <Route path="/rrhh/trabajadores/:id" element={<TrabajadorFichaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.ASISTENCIA.VER" />}>
                    <Route path="/rrhh/asistencia" element={<AsistenciaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.ADELANTOS.VER" />}>
                    <Route path="/rrhh/adelantos" element={<AdelantosPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.VACACIONES.VER" />}>
                    <Route path="/rrhh/vacaciones" element={<VacacionesPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.REPORTES.VER" />}>
                    <Route path="/rrhh/reportes" element={<ReportesRrhhPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.AUTOSERVICIO.VER" />}>
                    <Route path="/rrhh/mi-portal" element={<MiPortalPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.CTS.VER" />}>
                    <Route path="/rrhh/cts" element={<CtsPage />} />
                    <Route path="/rrhh/cts/:id" element={<CtsDetallePage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="RRHH.PLANILLA.VER" />}>
                    <Route path="/rrhh/planillas" element={<PlanillasPage />} />
                    <Route path="/rrhh/planillas/:id" element={<PlanillaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="FACTURACION.VER" />}>
                    <Route path="/facturacion" element={<FacturacionPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="VENTAS.VENDER" />}>
                    <Route path="/ventas/pos" element={<PuntoVentaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="VENTAS.GUIA_REMISION" />}>
                    <Route path="/ventas/guias-remision/nueva" element={<NuevaGuiaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="VENTAS.NOTA_CREDITO" />}>
                    <Route path="/ventas/notas-credito/nueva" element={<NuevaNotaCreditoPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="VENTAS.LIQUIDAR_TARJETA" />}>
                    <Route path="/ventas/liquidacion-tarjetas" element={<LiquidacionTarjetasPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="VENTAS.LIQUIDAR_INTERNA" />}>
                    <Route path="/ventas/liquidacion-interna" element={<LiquidacionInternaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="VENTAS.CUENTAS_COBRO" />}>
                    <Route path="/ventas/cuentas-de-cobro" element={<CuentasDeCobroPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="VENTAS.VER" />}>
                    <Route path="/ventas/proformas" element={<ProformasPage />} />
                    <Route path="/ventas/proformas/nueva" element={<NuevaProformaPage />} />
                    <Route path="/ventas/proformas/:id" element={<ProformaFichaPage />} />
                    <Route path="/ventas/notas-credito" element={<NotasCreditoPage />} />
                    <Route path="/ventas/guias-remision" element={<GuiasRemisionPage />} />
                    <Route path="/ventas/reportes" element={<ReportesVentasPage />} />
                    <Route path="/ventas/historial" element={<VentasPage />} />
                    <Route path="/ventas/historial/:id" element={<VentaFichaPage />} />
                    <Route path="/ventas/por-cobrar" element={<VentasPorCobrarPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="COMPRAS.VER" />}>
                    <Route path="/compras/registro" element={<ComprasPage />} />
                    <Route path="/compras/registro/:id" element={<CompraFichaPage />} />
                    <Route path="/compras/por-pagar" element={<CuentasPorPagarPage />} />
                    <Route path="/compras/ordenes" element={<OrdenesCompraPage />} />
                    <Route path="/compras/ordenes/:id" element={<OrdenCompraFichaPage />} />
                    <Route path="/compras/devoluciones" element={<DevolucionesPage />} />
                    <Route path="/compras/devoluciones/:id" element={<DevolucionFichaPage />} />
                    <Route path="/compras/saldos-a-favor" element={<SaldosAFavorPage />} />
                    <Route path="/compras/anticipos" element={<AnticiposPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="CAJA.MOVIMIENTOS.VER" />}>
                    <Route path="/caja/saldos" element={<SaldosPage />} />
                    <Route path="/caja/movimientos" element={<MovimientosCajaPage />} />
                    <Route path="/caja/transferencias" element={<TransferenciasPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="CAJA.SESIONES.VER" />}>
                    <Route path="/caja/sesiones" element={<SesionesCajaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="GASTOS.VER" />}>
                    <Route path="/gastos/registro" element={<GastosPage />} />
                    <Route path="/gastos/reportes" element={<ReportesGastosPage />} />
                    <Route path="/gastos/recurrentes" element={<RecurrentesPage />} />
                    <Route path="/gastos/registro/:id" element={<GastoFichaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="GASTOS.REGISTRAR" />}>
                    <Route path="/gastos/registro/nuevo" element={<RegistrarGastoPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SERVICIOS.VER" />}>
                    <Route path="/servicio-tecnico/ordenes" element={<OrdenesPage />} />
                    <Route path="/servicio-tecnico/tablero" element={<TableroPage />} />
                    <Route path="/servicio-tecnico/ordenes/:id" element={<OrdenFichaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SERVICIOS.AVISOS.GESTIONAR" />}>
                    <Route path="/servicio-tecnico/avisos" element={<AvisosWhatsappPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SERVICIOS.REPORTES.VER" />}>
                    <Route path="/servicio-tecnico/reportes" element={<ReportesServicioPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SERVICIOS.EJECUTAR" />}>
                    <Route path="/servicio-tecnico/mis-ordenes" element={<MisOrdenesPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="SERVICIOS.RECEPCIONAR" />}>
                    <Route path="/servicio-tecnico/ingreso" element={<RegistrarIngresoPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="CAJA.CAJA_CHICA.VER" />}>
                    <Route path="/caja/caja-chica" element={<CajaChicaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="CAJA.REPORTES.VER" />}>
                    <Route path="/caja/reportes" element={<ReportesCajaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="CAJA.CHEQUES.VER" />}>
                    <Route path="/caja/cheques" element={<ChequesPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="CAJA.CONCILIACION.VER" />}>
                    <Route path="/caja/conciliacion" element={<ConciliacionPage />} />
                    <Route path="/caja/conciliacion/:id" element={<ConciliacionDetallePage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="COMPRAS.EXPORTAR" />}>
                    <Route path="/compras/registro-compras" element={<RegistroComprasPage />} />
                    <Route path="/compras/reporte-devoluciones" element={<ReporteDevolucionesPage />} />
                    <Route path="/compras/reporte-ordenes" element={<ReporteOrdenesPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="COMPRAS.CREAR" />}>
                    <Route path="/compras/registro/nueva" element={<RegistrarCompraPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="ORDENES_COMPRA.CREAR" />}>
                    <Route path="/compras/ordenes/nueva" element={<OrdenCompraFormPage />} />
                    <Route path="/compras/ordenes/reposicion" element={<ReposicionPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="ORDENES_COMPRA.EDITAR" />}>
                    <Route path="/compras/ordenes/:id/editar" element={<OrdenCompraFormPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="COTIZACIONES_COMPRA.VER" />}>
                    <Route path="/compras/cotizaciones" element={<CotizacionesPage />} />
                    <Route path="/compras/cotizaciones/:id" element={<CotizacionFichaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="COTIZACIONES_COMPRA.CREAR" />}>
                    <Route path="/compras/cotizaciones/nueva" element={<CotizacionFormPage />} />
                    <Route path="/compras/cotizaciones/:id/editar" element={<CotizacionFormPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="COMPRAS.DEVOLVER" />}>
                    <Route path="/compras/registro/:id/devolver" element={<DevolverCompraPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="INVENTARIO.EXPORTAR" />}>
                    <Route path="/almacen/reportes" element={<ReportesPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="MANTENIMIENTO.PRODUCTOS.VER" organizacion />}>
                    <Route path="/tienda/productos" element={<ProductosTiendaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="TIENDA.CONFIGURAR" organizacion />}>
                    <Route path="/tienda/configuracion" element={<ConfiguracionTiendaPage />} />
                    <Route path="/tienda/envios" element={<EnviosTiendaPage />} />
                    <Route path="/tienda/arma-tu-pc" element={<ArmadorTiendaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="TIENDA.PEDIDOS.VER" organizacion />}>
                    <Route path="/tienda/pedidos" element={<PedidosTiendaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="TIENDA.OFERTAS.GESTIONAR" organizacion />}>
                    <Route path="/tienda/ofertas" element={<OfertasTiendaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="TIENDA.PAGOS.CONFIGURAR" organizacion />}>
                    <Route path="/tienda/pagos" element={<PagosTiendaPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="MANTENIMIENTO.CLASIFICACION.VER" organizacion />}>
                    <Route path="/tienda/especificaciones" element={<EspecificacionesTiendaPage />} />
                    <Route path="/mantenimiento/clasificacion" element={<ClasificacionPage />} />
                  </Route>
                  <Route element={<RequirePermiso permiso="MANTENIMIENTO.TIPO_CAMBIO.VER" organizacion />}>
                    <Route path="/mantenimiento/tipo-cambio" element={<TipoCambioPage />} />
                  </Route>
                  {/* Clientes y proveedores se mudaron a Ventas y Compras: las direcciones viejas siguen sirviendo. */}
                  <Route path="/mantenimiento/clientes" element={<Navigate to={CLIENTES.ruta} replace />} />
                  <Route path="/mantenimiento/clientes/:id" element={<RedirigirFicha base={CLIENTES.ruta} />} />
                  <Route path="/mantenimiento/proveedores" element={<Navigate to={PROVEEDORES.ruta} replace />} />
                  <Route path="/mantenimiento/proveedores/:id" element={<RedirigirFicha base={PROVEEDORES.ruta} />} />
                  <Route path="*" element={<NoEncontradaPage />} />
                </Route>
              </Route>
            </Routes>
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
        </NotificacionesProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
