from django.urls import path, re_path

from apps.garantias.api.v1 import avisos as garantias_avisos
from apps.garantias.api.v1 import views as garantias_publico

from . import (
    admin,
    armador,
    compra,
    cuenta,
    cupones_admin,
    envios,
    favoritos,
    legal,
    ofertas_admin,
    pagar,
    pagos,
    pedidos,
    pedidos_admin,
    publica,
    resenas,
)

app_name = "tienda"

# La parte pública acepta cada dirección CON o SIN barra final: el sitio en Next.js quita esa barra
# con un redirect, y así las fotos y las consultas no dan una vuelta de más.
urlpatterns = [
    # Consulta de garantía por serie y documento (la usa la página «Consulta tu garantía»).
    re_path(
        r"^garantia/buscar/?$",
        garantias_publico.BuscarPublicaView.as_view(),
        name="garantia-buscar",
    ),
    re_path(r"^garantia/baja/?$", garantias_avisos.BajaPublicaView.as_view(), name="garantia-baja"),
    # --- Pública (sin sesión, solo lectura) ---
    re_path(r"^menu/?$", publica.MenuView.as_view(), name="menu"),
    re_path(r"^inicio/?$", publica.InicioView.as_view(), name="inicio"),
    re_path(r"^productos/?$", publica.ProductosView.as_view(), name="productos"),
    re_path(r"^productos/(?P<slug>[-\w]+)/?$", publica.ProductoView.as_view(), name="producto"),
    re_path(
        r"^productos/(?P<slug>[-\w]+)/resenas/?$",
        resenas.ResenasPublicasView.as_view(),
        name="producto-resenas",
    ),
    re_path(
        r"^productos/(?P<slug>[-\w]+)/mi-resena/?$",
        resenas.MiResenaView.as_view(),
        name="producto-mi-resena",
    ),
    re_path(r"^comparar/?$", publica.CompararView.as_view(), name="comparar"),
    re_path(r"^sugerencias/?$", publica.SugerenciasView.as_view(), name="sugerencias"),
    re_path(r"^armador/?$", armador.ArmadorView.as_view(), name="armador"),
    re_path(r"^armador/opciones/?$", armador.OpcionesView.as_view(), name="armador-opciones"),
    re_path(r"^armador/validar/?$", armador.ValidarView.as_view(), name="armador-validar"),
    re_path(r"^ubigeos/?$", publica.UbigeosView.as_view(), name="ubigeos"),
    re_path(r"^ofertas/?$", publica.OfertasView.as_view(), name="ofertas"),
    re_path(r"^banners/?$", publica.BannersView.as_view(), name="banners"),
    re_path(
        r"^banners/(?P<banner_id>\d+)/(?P<tam>[a-z]+)/(?P<version>[0-9a-f]{12})/?$",
        publica.BannerImagenView.as_view(),
        name="banner-imagen",
    ),
    re_path(r"^hora/?$", publica.HoraView.as_view(), name="hora"),
    re_path(r"^feed/google\.xml$", publica.FeedGoogleView.as_view(), name="feed-google"),
    re_path(r"^sitemap/?$", publica.MapaDelSitioView.as_view(), name="sitemap"),
    re_path(r"^fotos/(?P<foto_id>\d+)/(?P<tam>[a-z]+)/?$", publica.FotoView.as_view(), name="foto"),
    re_path(r"^configuracion/?$", publica.ConfiguracionPublicaView.as_view(), name="publica"),
    re_path(r"^logo/(?P<version>[0-9a-f]{12})/?$", publica.LogoView.as_view(), name="logo"),
    # --- Cuenta del cliente (cookie de sesión; ver cuenta.py) ---
    re_path(r"^cuenta/registro/?$", cuenta.RegistroView.as_view(), name="cuenta-registro"),
    re_path(r"^cuenta/verificar/?$", cuenta.VerificarView.as_view(), name="cuenta-verificar"),
    re_path(
        r"^cuenta/reenviar-verificacion/?$",
        cuenta.ReenviarVerificacionView.as_view(),
        name="cuenta-reenviar",
    ),
    re_path(r"^cuenta/ingresar/?$", cuenta.IngresarView.as_view(), name="cuenta-ingresar"),
    re_path(r"^cuenta/salir/?$", cuenta.SalirView.as_view(), name="cuenta-salir"),
    re_path(r"^cuenta/recuperar/?$", cuenta.RecuperarView.as_view(), name="cuenta-recuperar"),
    re_path(
        r"^cuenta/recuperar/confirmar/?$",
        cuenta.RecuperarConfirmarView.as_view(),
        name="cuenta-recuperar-confirmar",
    ),
    re_path(r"^cuenta/sesion/?$", cuenta.SesionView.as_view(), name="cuenta-sesion"),
    re_path(r"^cuenta/perfil/?$", cuenta.PerfilView.as_view(), name="cuenta-perfil"),
    re_path(
        r"^cuenta/cambiar-password/?$",
        cuenta.CambiarPasswordView.as_view(),
        name="cuenta-cambiar-password",
    ),
    re_path(r"^cuenta/direcciones/?$", cuenta.DireccionesView.as_view(), name="cuenta-direcciones"),
    re_path(
        r"^cuenta/direcciones/(?P<pk>\d+)/?$",
        cuenta.DireccionView.as_view(),
        name="cuenta-direccion",
    ),
    # --- Carrito y resumen de la compra ---
    re_path(r"^carrito/calcular/?$", compra.CalcularView.as_view(), name="carrito-calcular"),
    re_path(r"^cuenta/carrito/?$", compra.CarritoGuardadoView.as_view(), name="cuenta-carrito"),
    re_path(
        r"^cuenta/baja-promociones/?$",
        cuenta.BajaPromocionesView.as_view(),
        name="cuenta-baja-promociones",
    ),
    re_path(r"^cuenta/favoritos/?$", favoritos.FavoritosView.as_view(), name="favoritos"),
    re_path(
        r"^cuenta/favoritos/(?P<producto_id>\d+)/?$",
        favoritos.FavoritoView.as_view(),
        name="favorito",
    ),
    re_path(
        r"^cuenta/avisos-stock/(?P<producto_id>\d+)/?$",
        favoritos.AvisoStockView.as_view(),
        name="aviso-stock",
    ),
    re_path(r"^libro-de-reclamaciones/?$", legal.LibroView.as_view(), name="libro"),
    re_path(r"^reclamos/?$", legal.RegistrarReclamoView.as_view(), name="reclamo"),
    re_path(r"^paginas/(?P<slug>[-\w]+)/?$", legal.PaginaView.as_view(), name="pagina-legal"),
    re_path(r"^compra/cotizar/?$", compra.CotizarView.as_view(), name="compra-cotizar"),
    re_path(r"^pagos/configuracion/?$", pagos.PagosPublicaView.as_view(), name="pagos-publica"),
    re_path(
        r"^pedidos/(?P<numero>T-\d{1,9})/pagar/?$", pagar.PagarView.as_view(), name="pedido-pagar"
    ),
    re_path(r"^pagos/webhook/?$", pagar.WebhookView.as_view(), name="pagos-webhook"),
    re_path(r"^cuenta/garantias/?$", pedidos.GarantiasView.as_view(), name="mis-garantias"),
    re_path(r"^pedidos/?$", pedidos.PedidosView.as_view(), name="pedidos"),
    re_path(r"^pedidos/(?P<numero>T-\d{1,9})/?$", pedidos.PedidoView.as_view(), name="pedido"),
    re_path(
        r"^pedidos/(?P<numero>T-\d{1,9})/voucher/?$",
        pedidos.VoucherView.as_view(),
        name="pedido-voucher",
    ),
    re_path(
        r"^pedidos/(?P<numero>T-\d{1,9})/cancelar/?$",
        pedidos.CancelarPedidoView.as_view(),
        name="pedido-cancelar",
    ),
    # --- Interna (con sesión y permiso) ---
    path("admin/configuracion/", admin.ConfiguracionTiendaView.as_view(), name="configuracion"),
    path("admin/logo/", admin.LogoTiendaView.as_view(), name="logo-admin"),
    path("admin/pedidos/", pedidos_admin.PedidosView.as_view(), name="pedidos-admin"),
    path("admin/pedidos/resumen/", pedidos_admin.ResumenView.as_view(), name="pedidos-resumen"),
    path("admin/pedidos/<str:numero>/", pedidos_admin.PedidoView.as_view(), name="pedido-admin"),
    path(
        "admin/pedidos/<str:numero>/estado/",
        pedidos_admin.EstadoView.as_view(),
        name="pedido-estado",
    ),
    path("admin/pedidos/<str:numero>/nota/", pedidos_admin.NotaView.as_view(), name="pedido-nota"),
    path(
        "admin/pedidos/<str:numero>/saldo/",
        pedidos_admin.SaldoView.as_view(),
        name="pedido-saldo",
    ),
    path(
        "admin/pedidos/<str:numero>/voucher/",
        pedidos_admin.VoucherVerView.as_view(),
        name="pedido-voucher-admin",
    ),
    path(
        "admin/pedidos/<str:numero>/transferencia/confirmar/",
        pedidos_admin.ConfirmarTransferenciaView.as_view(),
        name="pedido-transferencia-confirmar",
    ),
    path(
        "admin/pedidos/<str:numero>/transferencia/rechazar/",
        pedidos_admin.RechazarTransferenciaView.as_view(),
        name="pedido-transferencia-rechazar",
    ),
    path(
        "admin/pedidos/<str:numero>/serie/",
        pedidos_admin.CambiarSerieView.as_view(),
        name="pedido-serie",
    ),
    path(
        "admin/pedidos/<str:numero>/reembolso/",
        pedidos_admin.ReembolsoView.as_view(),
        name="pedido-reembolso",
    ),
    path(
        "admin/pedidos/<str:numero>/reembolso/plan/",
        pedidos_admin.ReembolsoPlanView.as_view(),
        name="pedido-reembolso-plan",
    ),
    path(
        "admin/pedidos/<str:numero>/reembolso/reintentar/",
        pedidos_admin.ReembolsoReintentarView.as_view(),
        name="pedido-reembolso-reintentar",
    ),
    path(
        "admin/pedidos/<str:numero>/reintentar-comprobante/",
        pedidos_admin.ReintentarComprobanteView.as_view(),
        name="pedido-reintentar",
    ),
    path("admin/armador/", armador.ArmadorAdminView.as_view(), name="armador-admin"),
    path("admin/armador/datos/", armador.DatosArmadorView.as_view(), name="armador-datos"),
    path(
        "admin/armador/datos/plantilla/",
        armador.PlantillaDatosView.as_view(),
        name="armador-datos-plantilla",
    ),
    path(
        "admin/armador/datos/importar/",
        armador.ImportarDatosView.as_view(),
        name="armador-datos-importar",
    ),
    path("admin/pagos/", pagos.PagosView.as_view(), name="pagos-admin"),
    path("admin/pagos/probar/", pagos.ProbarPagosView.as_view(), name="pagos-probar"),
    path(
        "admin/carrito-abandonado/",
        cupones_admin.CarritoAbandonadoView.as_view(),
        name="carrito-abandonado",
    ),
    path("admin/cupones/", cupones_admin.CuponesView.as_view(), name="cupones-admin"),
    path(
        "admin/cupones/opciones/",
        cupones_admin.OpcionesCuponView.as_view(),
        name="cupones-opciones",
    ),
    path("admin/cupones/<int:pk>/", cupones_admin.CuponView.as_view(), name="cupon-admin"),
    path(
        "admin/cupones/<int:pk>/usos/",
        cupones_admin.UsosCuponView.as_view(),
        name="cupon-usos",
    ),
    path("admin/reclamos/", legal.ReclamosAdminView.as_view(), name="reclamos-admin"),
    path("admin/reclamos/<int:pk>/", legal.ReclamoAdminView.as_view(), name="reclamo-admin"),
    path(
        "admin/reclamos/<int:pk>/responder/",
        legal.ResponderReclamoView.as_view(),
        name="reclamo-responder",
    ),
    path(
        "admin/reclamos/<int:pk>/reenviar/",
        legal.ReenviarRespuestaView.as_view(),
        name="reclamo-reenviar",
    ),
    path("admin/paginas/", legal.PaginasAdminView.as_view(), name="paginas-admin"),
    path("admin/paginas/<slug:slug>/", legal.PaginaAdminView.as_view(), name="pagina-admin"),
    path("admin/metricas/", legal.MetricasView.as_view(), name="metricas-admin"),
    path("admin/resenas/", resenas.ResenasAdminView.as_view(), name="resenas-admin"),
    path(
        "admin/resenas/configuracion/",
        resenas.ConfiguracionResenasView.as_view(),
        name="resenas-configuracion",
    ),
    path(
        "admin/resenas/<int:pk>/ocultar/",
        resenas.OcultarResenaView.as_view(),
        name="resena-ocultar",
    ),
    path(
        "admin/resenas/<int:pk>/mostrar/",
        resenas.MostrarResenaView.as_view(),
        name="resena-mostrar",
    ),
    path(
        "admin/resenas/<int:pk>/responder/",
        resenas.ResponderResenaView.as_view(),
        name="resena-responder",
    ),
    path("admin/ofertas/", ofertas_admin.OfertasView.as_view(), name="ofertas-admin"),
    path(
        "admin/ofertas/productos/",
        ofertas_admin.ProductosParaOfertaView.as_view(),
        name="ofertas-productos",
    ),
    path("admin/ofertas/<int:pk>/", ofertas_admin.OfertaView.as_view(), name="oferta-admin"),
    path("admin/banners/", ofertas_admin.BannersView.as_view(), name="banners-admin"),
    path("admin/banners/<int:pk>/", ofertas_admin.BannerView.as_view(), name="banner-admin"),
    path(
        "admin/banners/<int:pk>/imagen/<str:tam>/",
        ofertas_admin.BannerVistaPreviaView.as_view(),
        name="banner-vista",
    ),
    path("admin/envios/", envios.EnviosView.as_view(), name="envios-admin"),
    path("admin/envios/zonas/", envios.ZonasView.as_view(), name="zonas-admin"),
    path("admin/envios/zonas/<int:pk>/", envios.ZonaView.as_view(), name="zona-admin"),
    path("admin/envios/puntos/", envios.PuntosView.as_view(), name="puntos-admin"),
    path("admin/envios/puntos/<int:pk>/", envios.PuntoView.as_view(), name="punto-admin"),
    path("admin/envios/ubigeos/", envios.UbigeosView.as_view(), name="ubigeos-admin"),
]
