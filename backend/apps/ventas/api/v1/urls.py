from django.urls import path
from rest_framework.routers import SimpleRouter

from . import (
    cuentas_de_cobro,
    guias,
    guias_traslado,
    liquidaciones,
    liquidaciones_internas,
    notas_credito,
    por_cobrar,
    proformas,
    reportes,
    traslados_empresas,
    views,
)

app_name = "ventas"

router = SimpleRouter()
router.register("guias-remision", guias.GuiaViewSet, basename="guia-remision")
router.register("notas-credito", notas_credito.NotaCreditoViewSet, basename="nota-credito")
router.register("proformas", proformas.ProformaViewSet, basename="proforma")
router.register("liquidaciones", liquidaciones.LiquidacionViewSet, basename="liquidacion")
router.register(
    "liquidaciones-internas",
    liquidaciones_internas.LiquidacionInternaViewSet,
    basename="liquidacion-interna",
)
router.register(
    "traslados-empresas",
    traslados_empresas.TrasladoEmpresasViewSet,
    basename="traslado-empresas",
)
router.register(
    "cuentas-de-cobro", cuentas_de_cobro.CuentaDeCobroViewSet, basename="cuenta-de-cobro"
)
router.register("", views.VentaViewSet, basename="venta")

urlpatterns = [
    path("configuracion/", views.ConfiguracionView.as_view(), name="configuracion"),
    path("catalogo/", views.CatalogoView.as_view(), name="catalogo"),
    path("series-sugeridas/", views.SeriesSugeridasView.as_view(), name="series-sugeridas"),
    path("previsualizar/", views.PrevisualizarView.as_view(), name="previsualizar"),
    path("por-cobrar/resumen/", por_cobrar.ResumenView.as_view(), name="por-cobrar-resumen"),
    path("por-cobrar/clientes/", por_cobrar.ClientesView.as_view(), name="por-cobrar-clientes"),
    path(
        "por-cobrar/comprobantes/",
        por_cobrar.ComprobantesView.as_view(),
        name="por-cobrar-comprobantes",
    ),
    path("recibos/<int:recibo_id>/", por_cobrar.ReciboView.as_view(), name="recibo"),
    path(
        "por-cobrar/clientes/<int:cliente_id>/",
        por_cobrar.DeudaDeClienteView.as_view(),
        name="por-cobrar-cliente",
    ),
    path(
        "clientes/<int:cliente_id>/credito/",
        por_cobrar.CreditoDeClienteView.as_view(),
        name="credito-cliente",
    ),
    path(
        "notas-credito/excel/", notas_credito.NotasExcelView.as_view(), name="notas-credito-excel"
    ),
    path("guias-remision/excel/", guias.GuiasExcelView.as_view(), name="guias-remision-excel"),
    path(
        "comprobantes/enviables/",
        guias.EnviablesView.as_view(),
        name="comprobantes-enviables",
    ),
    path(
        "comprobantes/devolvibles/",
        notas_credito.DevolviblesView.as_view(),
        name="comprobantes-devolvibles",
    ),
    path(
        "comprobantes/<int:comprobante_id>/devolucion/",
        notas_credito.PendienteView.as_view(),
        name="devolucion",
    ),
    path(
        "comprobantes/<int:comprobante_id>/nota-credito/previsualizar/",
        notas_credito.PrevisualizarView.as_view(),
        name="nota-credito-previsualizar",
    ),
    path(
        "comprobantes/<int:comprobante_id>/nota-credito/",
        notas_credito.EmitirView.as_view(),
        name="nota-credito-emitir",
    ),
    path(
        "comprobantes/<int:comprobante_id>/envio/",
        guias.PendienteView.as_view(),
        name="envio",
    ),
    path(
        "comprobantes/<int:comprobante_id>/guia-remision/",
        guias.EmitirView.as_view(),
        name="guia-emitir",
    ),
    path(
        "traspasos/<int:movimiento_id>/envio/",
        guias_traslado.PendienteView.as_view(),
        name="traspaso-envio",
    ),
    path(
        "traspasos/<int:movimiento_id>/guia-remision/",
        guias_traslado.EmitirView.as_view(),
        name="traspaso-guia-emitir",
    ),
    path(
        "comprobantes/<int:comprobante_id>/abonar/",
        por_cobrar.AbonarView.as_view(),
        name="abonar",
    ),
    path(
        "abonos/<int:abono_id>/anular/", por_cobrar.AnularAbonoView.as_view(), name="anular-abono"
    ),
    *[
        path(f"reportes/{ruta}/", vista.as_view(), name=f"reporte-{ruta}")
        for ruta, vista in (
            ("resumen", reportes.ResumenView),
            ("vendedores", reportes.VendedoresView),
            ("productos", reportes.ProductosView),
            ("clientes", reportes.ClientesView),
            ("metodos", reportes.MetodosView),
            ("registro", reportes.RegistroView),
            ("ventas-internas", reportes.VentasInternasView),
            ("consolidado", reportes.ConsolidadoView),
        )
    ],
    *[
        path(f"reportes/{ruta}/excel/", vista.as_view(), name=f"reporte-{ruta}-excel")
        for ruta, vista in (
            ("resumen", reportes.ResumenExcelView),
            ("vendedores", reportes.VendedoresExcelView),
            ("productos", reportes.ProductosExcelView),
            ("clientes", reportes.ClientesExcelView),
            ("metodos", reportes.MetodosExcelView),
            ("registro", reportes.RegistroExcelView),
            ("ventas-internas", reportes.VentasInternasExcelView),
            ("consolidado", reportes.ConsolidadoExcelView),
        )
    ],
    *router.urls,
]
