"""API interna (con sesión) para configurar la tienda: qué precios y qué almacenes muestra."""

import logging
from decimal import Decimal

from django.db import transaction
from django.http import FileResponse, Http404
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import Almacen, EstadoRegistro, ListaPrecio, PrecioProducto, Producto
from apps.organizacion.exceptions import LogoInvalido
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import catalogo, servicios
from apps.tienda.models import ConfiguracionTienda

logger = logging.getLogger(__name__)

TAG = ["tienda"]
CONFIGURAR = "TIENDA.CONFIGURAR"


class ConfiguracionEntrada(serializers.Serializer):
    activa = serializers.BooleanField(required=False)
    nombre = serializers.CharField(max_length=80, required=False)
    lista_precio = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    almacenes = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=100
    )
    precios_con_igv = serializers.BooleanField(required=False)
    pocas_unidades = serializers.IntegerField(min_value=0, max_value=500, required=False)
    permite_envio = serializers.BooleanField(required=False)
    permite_recojo = serializers.BooleanField(required=False)
    peso_por_defecto_kg = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=Decimal("0.01"), required=False
    )


CAMPOS_CONTENIDO = [
    "descripcion", "nombre_junto_al_logo", "color_principal", "whatsapp", "telefono", "correo",
    "direccion", "horario",
    "mapa_url", "facebook", "instagram", "tiktok", "youtube", "avisos", "portada_etiqueta",
    "portada_titulo", "portada_subtitulo", "servicio_visible", "servicio_titulo", "servicio_texto",
    "servicio_puntos", "garantia_texto", "entrega_texto", "libro_reclamaciones_url",
    "terminos_url", "privacidad_url",
]  # fmt: skip


def _luminancia(hexa: str) -> float:
    def canal(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hexa[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


class ContenidoEntrada(serializers.ModelSerializer):
    """Marca, contacto y textos. Cada campo se valida con las reglas del modelo (URL, correo…)."""

    avisos = serializers.ListField(
        child=serializers.CharField(max_length=90, allow_blank=True), required=False, max_length=3
    )
    servicio_puntos = serializers.ListField(
        child=serializers.CharField(max_length=60, allow_blank=True), required=False, max_length=4
    )

    class Meta:
        model = ConfiguracionTienda
        fields = CAMPOS_CONTENIDO
        extra_kwargs = {
            c: (
                {"required": False}
                if c in ("servicio_visible", "nombre_junto_al_logo")
                else {"required": False, "allow_blank": True}
            )
            for c in CAMPOS_CONTENIDO
            if c not in ("avisos", "servicio_puntos")
        }

    def validate_color_principal(self, valor):
        if not valor:
            return ""
        valor = valor.upper()
        # Texto blanco sobre el botón: el color debe ser lo bastante oscuro para leerse (WCAG 3:1).
        if 1.05 / (_luminancia(valor) + 0.05) < 3:
            raise serializers.ValidationError(
                "Ese color es muy claro: el texto blanco de los botones no se leería bien."
            )
        return valor

    def validate_whatsapp(self, valor):
        digitos = "".join(c for c in valor if c.isdigit())
        if not digitos:
            return ""
        if len(digitos) == 9 and digitos.startswith("9"):
            digitos = "51" + digitos  # número peruano escrito sin el código de país
        if not 10 <= len(digitos) <= 15:
            raise serializers.ValidationError(
                "Escriba el número con código de país, ej. 51987654321."
            )
        return digitos

    def validate_avisos(self, lista):
        return [" ".join(x.split()) for x in lista if x.strip()]

    def validate_servicio_puntos(self, lista):
        return [" ".join(x.split()) for x in lista if x.strip()]

    def validate(self, datos):
        for campo, valor in list(datos.items()):
            if isinstance(valor, str):
                datos[campo] = " ".join(valor.split())
        return datos


def _almacenes_de_la_organizacion(organizacion_id: int):
    """Todos los almacenes activos de la organización (de cualquier empresa).

    La tienda es de la organización: quien la configura no debe quitar sin querer los almacenes
    de una empresa que no ve.
    """
    return Almacen.objects.sin_ambito().filter(
        empresa__organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO
    )


def _fijar_almacenes(config: ConfiguracionTienda, ids) -> None:
    """Deja EXACTAMENTE esos almacenes (sin depender de lo que ve el usuario)."""
    ids = set(ids)
    enlace = ConfiguracionTienda.almacenes.through
    filas = enlace.objects.filter(configuraciontienda_id=config.pk)
    filas.exclude(almacen_id__in=ids).delete()
    existentes = set(filas.values_list("almacen_id", flat=True))
    enlace.objects.bulk_create(
        [enlace(configuraciontienda_id=config.pk, almacen_id=i) for i in ids - existentes]
    )


def _config_de(organizacion_id: int) -> ConfiguracionTienda:
    """La configuración de la organización; la primera vez se crea con valores razonables."""
    existente = ConfiguracionTienda.objects.filter(organizacion_id=organizacion_id).first()
    if existente is not None:
        return existente
    config = ConfiguracionTienda.objects.create(organizacion_id=organizacion_id, nombre="Tienda")
    _fijar_almacenes(
        config, _almacenes_de_la_organizacion(organizacion_id).values_list("pk", flat=True)
    )
    return config


def _lista_efectiva(config: ConfiguracionTienda) -> ListaPrecio | None:
    if config.lista_precio_id:
        return config.lista_precio
    return ListaPrecio.objects.filter(es_principal=True, estado=EstadoRegistro.ACTIVO).first()


def _datos_empresa(organizacion_id: int) -> dict | None:
    """Lo que la tienda toma de la ficha de la empresa principal (solo lectura, para mostrarlo)."""
    empresa = servicios.empresa_principal(organizacion_id)
    if empresa is None:
        return None
    return {
        "razon_social": empresa.razon_social,
        "ruc": empresa.ruc,
        "telefono": empresa.telefono,
        "correo": empresa.correo,
        "direccion": empresa.direccion_fiscal,
    }


def _salida(config: ConfiguracionTienda) -> dict:
    lista = _lista_efectiva(config)
    publicados = Producto.objects.filter(publicado_web=True, estado=EstadoRegistro.ACTIVO)
    sin_precio = (
        publicados.exclude(
            pk__in=PrecioProducto.objects.filter(lista=lista).values("producto_id")
        ).count()
        if lista
        else publicados.count()
    )
    return {
        "activa": config.activa,
        "nombre": config.nombre,
        "lista_precio": config.lista_precio_id,
        "lista_precio_efectiva": lista.pk if lista else None,
        "almacenes": sorted(
            ConfiguracionTienda.almacenes.through.objects.filter(
                configuraciontienda_id=config.pk
            ).values_list("almacen_id", flat=True)
        ),
        "precios_con_igv": config.precios_con_igv,
        "pocas_unidades": config.pocas_unidades,
        "permite_envio": config.permite_envio,
        "permite_recojo": config.permite_recojo,
        "peso_por_defecto_kg": format(config.peso_por_defecto_kg, "f"),
        "tiene_logo": bool(config.logo),
        "logo_version": config.logo_version,
        **{c: getattr(config, c) for c in CAMPOS_CONTENIDO},
        "empresa_principal": _datos_empresa(config.organizacion_id),
        "opciones": {
            "listas": [
                {"id": ls.pk, "nombre": ls.nombre, "es_principal": ls.es_principal}
                for ls in ListaPrecio.objects.filter(estado=EstadoRegistro.ACTIVO).order_by(
                    "orden", "id"
                )
            ],
            "almacenes": [
                {"id": a.pk, "nombre": a.nombre, "empresa": a.empresa.razon_social}
                for a in _almacenes_de_la_organizacion(config.organizacion_id)
                .select_related("empresa")
                .order_by("empresa__razon_social", "nombre")
            ],
        },
        "resumen": {"publicados": publicados.count(), "publicados_sin_precio": sin_precio},
    }


class ConfiguracionTiendaView(APIView):
    """Ver y cambiar la configuración de la tienda de la organización."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = {"get": CONFIGURAR, "patch": CONFIGURAR}

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización, no de una empresa

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        respuesta = Response(_salida(_config_de(request.user.organizacion_id)))
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    @extend_schema(tags=TAG, request=ConfiguracionEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request):
        entrada = ConfiguracionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        config = _config_de(request.user.organizacion_id)
        cambios: dict = {}

        if "lista_precio" in datos:
            lista_id = datos["lista_precio"]
            if (
                lista_id is not None
                and not ListaPrecio.objects.filter(
                    pk=lista_id, estado=EstadoRegistro.ACTIVO
                ).exists()
            ):
                raise ValidationError({"lista_precio": "Elija una lista de precios activa."})
            config.lista_precio_id = lista_id
            cambios["lista_precio"] = lista_id
        if "almacenes" in datos:
            ids = set(datos["almacenes"])
            elegidos = list(
                _almacenes_de_la_organizacion(config.organizacion_id).filter(pk__in=ids)
            )
            if len(elegidos) != len(ids):
                raise ValidationError(
                    {"almacenes": "Hay almacenes que no existen o están inactivos."}
                )
            _fijar_almacenes(config, [a.pk for a in elegidos])
            cambios["almacenes"] = sorted(ids)
        contenido = ContenidoEntrada(data=request.data, partial=True)
        contenido.is_valid(raise_exception=True)
        for campo, valor in contenido.validated_data.items():
            setattr(config, campo, valor)
            cambios[campo] = valor
        for campo in (
            "nombre", "precios_con_igv", "pocas_unidades", "permite_envio", "permite_recojo",
            "peso_por_defecto_kg",
        ):  # fmt: skip
            if campo in datos:
                valor = " ".join(datos[campo].split()) if campo == "nombre" else datos[campo]
                if campo == "nombre" and not valor:
                    raise ValidationError({"nombre": "Escriba el nombre de la tienda."})
                setattr(config, campo, valor)
                cambios[campo] = valor
        if "activa" in datos:
            if datos["activa"]:
                if not ConfiguracionTienda.almacenes.through.objects.filter(
                    configuraciontienda_id=config.pk
                ).exists():
                    raise ValidationError(
                        {"activa": "Elija al menos un almacén cuyo stock abastezca la tienda."}
                    )
                if _lista_efectiva(config) is None:
                    raise ValidationError({"activa": "No hay una lista de precios para mostrar."})
            config.activa = datos["activa"]
            cambios["activa"] = datos["activa"]
        config.save()
        if cambios:
            registrar(
                "tienda.configuracion_editada",
                recurso_tipo="configuracion_tienda",
                recurso_id=config.pk,
                resumen="Configuración de la tienda actualizada",
                detalle=cambios,
            )
        transaction.on_commit(catalogo.invalidar)
        return Response(_salida(config))


class LogoTiendaView(APIView):
    """El logo de la tienda (propio de la tienda, no el de las empresas)."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permisos_por_accion = {"get": CONFIGURAR, "post": CONFIGURAR, "delete": CONFIGURAR}

    def empresas_de_la_operacion(self, request):
        return [None]

    @extend_schema(tags=TAG, responses={(200, "image/png"): bytes})
    def get(self, request):
        config = _config_de(request.user.organizacion_id)
        try:
            archivo = config.logo.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404 from None
        respuesta = FileResponse(archivo, content_type=servicios.tipo_de_logo(config))
        respuesta["Cache-Control"] = "private, no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta

    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request):
        archivo = request.FILES.get("logo")
        if archivo is None:
            raise LogoInvalido("Elige un logo para subir.")
        config = servicios.guardar_logo(_config_de(request.user.organizacion_id), archivo)
        transaction.on_commit(catalogo.invalidar)
        return Response(_salida(config))

    @extend_schema(tags=TAG, responses={200: dict})
    def delete(self, request):
        config = servicios.quitar_logo(_config_de(request.user.organizacion_id))
        transaction.on_commit(catalogo.invalidar)
        return Response(_salida(config))
