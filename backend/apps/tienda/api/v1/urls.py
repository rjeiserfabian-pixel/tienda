from django.urls import path, re_path

from . import (
    admin,
    armador,
    compra,
    cuenta,
    envios,
    ofertas_admin,
    pagar,
    pagos,
    pedidos,
    pedidos_admin,
    publica,
)

app_name = "tienda"

# La parte pública acepta cada dirección CON o SIN barra final: el sitio en Next.js quita esa barra
# con un redirect, y así las fotos y las consultas no dan una vuelta de más.
urlpatterns = [
    # --- Pública (sin sesión, solo lectura) ---
    re_path(r"^menu/?$", publica.MenuView.as_view(), name="menu"),
    re_path(r"^inicio/?$", publica.InicioView.as_view(), name="inicio"),
    re_path(r"^productos/?$", publica.ProductosView.as_view(), name="productos"),
    re_path(r"^productos/(?P<slug>[-\w]+)/?$", publica.ProductoView.as_view(), name="producto"),
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
    re_path(r"^compra/cotizar/?$", compra.CotizarView.as_view(), name="compra-cotizar"),
    re_path(r"^pagos/configuracion/?$", pagos.PagosPublicaView.as_view(), name="pagos-publica"),
    re_path(
        r"^pedidos/(?P<numero>T-\d{1,9})/pagar/?$", pagar.PagarView.as_view(), name="pedido-pagar"
    ),
    re_path(r"^pagos/webhook/?$", pagar.WebhookView.as_view(), name="pagos-webhook"),
    re_path(r"^pedidos/?$", pedidos.PedidosView.as_view(), name="pedidos"),
    re_path(r"^pedidos/(?P<numero>T-\d{1,9})/?$", pedidos.PedidoView.as_view(), name="pedido"),
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
    path("admin/pagos/", pagos.PagosView.as_view(), name="pagos-admin"),
    path("admin/pagos/probar/", pagos.ProbarPagosView.as_view(), name="pagos-probar"),
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
