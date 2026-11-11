from django.urls import path
from rest_framework.routers import SimpleRouter

from . import (
    categorias_gasto,
    conceptos_caja,
    cuentas,
    fiscal,
    pagos,
    presentaciones,
    series,
    transporte,
    views,
)

app_name = "mantenimiento"

router = SimpleRouter()
router.register("personal", views.PersonalViewSet, basename="personal")
router.register("clientes", views.ClienteViewSet, basename="cliente")
router.register("proveedores", views.ProveedorViewSet, basename="proveedor")
router.register("familias", views.FamiliaViewSet, basename="familia")
router.register("categorias", views.CategoriaViewSet, basename="categoria")
router.register("marcas", views.MarcaViewSet, basename="marca")
router.register("unidades", views.UnidadMedidaViewSet, basename="unidad-medida")
router.register("listas-precio", views.ListaPrecioViewSet, basename="lista-precio")
router.register("productos", views.ProductoViewSet, basename="producto")
router.register("almacenes", views.AlmacenViewSet, basename="almacen")
router.register("ubicaciones", views.UbicacionViewSet, basename="ubicacion")
router.register(
    "presentaciones", presentaciones.PresentacionProductoViewSet, basename="presentacion"
)
router.register("cuentas", cuentas.CuentaFinancieraViewSet, basename="cuenta-financiera")
router.register("medios-pago", pagos.MedioPagoViewSet, basename="medio-pago")
router.register("conceptos-caja", conceptos_caja.ConceptoCajaViewSet, basename="concepto-caja")
router.register(
    "categorias-gasto", categorias_gasto.CategoriaGastoViewSet, basename="categoria-gasto"
)
router.register("periodicidades", pagos.PeriodicidadViewSet, basename="periodicidad")
router.register("series-comprobante", series.SerieComprobanteViewSet, basename="serie-comprobante")
router.register("tipos-comprobante", fiscal.TipoComprobanteViewSet, basename="tipo-comprobante")
router.register("afectaciones-igv", fiscal.AfectacionIGVViewSet, basename="afectacion-igv")
router.register("tasas-impuesto", fiscal.TasaImpuestoViewSet, basename="tasa-impuesto")
router.register("tipo-cambio", views.TipoCambioViewSet, basename="tipo-cambio")
router.register("centros-costo", views.CentroCostoViewSet, basename="centro-costo")
router.register(
    "empresas-transporte", transporte.EmpresaTransporteViewSet, basename="empresa-transporte"
)
router.register("conductores", transporte.ConductorViewSet, basename="conductor")
router.register("vehiculos", transporte.VehiculoViewSet, basename="vehiculo")

urlpatterns = [
    path("ubigeos/", transporte.UbigeoListView.as_view(), name="ubigeos"),
    path("igv/configuracion/", fiscal.ConfiguracionIgvView.as_view(), name="igv-configuracion"),
    path("igv/sugerencia/", fiscal.SugerenciaIgvView.as_view(), name="igv-sugerencia"),
    path("consultas/uso/", views.UsoConsultasView.as_view(), name="consultas-uso"),
    path(
        "consultas/<str:tipo>/<str:numero>/", views.ConsultaDocumentoView.as_view(), name="consulta"
    ),
    *router.urls,
]
