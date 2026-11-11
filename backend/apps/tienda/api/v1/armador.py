"""API de «Arma tu PC»: configuración (panel) y armado (público)."""

import logging

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle, TiendaThrottle
from apps.mantenimiento.models import CampoEspecificacion, Categoria, EstadoRegistro
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import armador, catalogo
from apps.tienda.exceptions import DatosInvalidos
from apps.tienda.models import ConfiguracionArmador

from .cuenta import TAG, _Base
from .publica import _Publica

logger = logging.getLogger(__name__)

CONFIGURAR = "TIENDA.CONFIGURAR"
TAM_PAGINA = 24
MAX_PAGINA = 48


# ---------------------------------------------------------------------------
# Público
# ---------------------------------------------------------------------------
class ArmadorView(_Publica):
    """Los espacios activos del armador con sus categorías (o ``{activo: false}``)."""

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        ctx = self.contexto()
        return self.responder(
            request,
            lambda: armador.publica(armador.configuracion_vigente(ctx.organizacion_id), ctx),
        )


def _lineas_de_texto(texto: str) -> list[dict]:
    """«12:1,15,20:2» → [{producto: 12, cantidad: 1}, …] (para el enlace compartible)."""
    filas = []
    for trozo in (texto or "").split(",")[: armador.MAX_LINEAS + 1]:
        if not trozo.strip():
            continue
        producto, _, cantidad = trozo.partition(":")
        filas.append({"producto": producto.strip(), "cantidad": cantidad.strip() or 1})
    return filas


def _entero(valor, defecto: int, minimo: int, maximo: int) -> int:
    try:
        return min(max(int(valor), minimo), maximo)
    except (TypeError, ValueError):
        return defecto


class OpcionesView(_Publica):
    """Productos de un espacio con su compatibilidad frente a lo ya elegido (``p=12:1,15``)."""

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        ctx = self.contexto()
        espacio = request.query_params.get("espacio", "")
        entradas = _lineas_de_texto(request.query_params.get("p", ""))
        todas = request.query_params.get("todas") == "1"
        pagina = _entero(request.query_params.get("page"), 1, 1, 10_000)
        tam = _entero(request.query_params.get("page_size"), TAM_PAGINA, 1, MAX_PAGINA)

        def construir():
            config = armador.configuracion_vigente(ctx.organizacion_id)
            if not armador.esta_listo(config):
                raise DatosInvalidos("El armador no está disponible por ahora.")
            return armador.opciones(
                ctx, config, espacio, entradas, todas=todas, pagina=pagina, tam=tam
            )

        return self.responder(request, construir)


class LineaEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=1, max_value=99, required=False, default=1)


class ValidarEntrada(serializers.Serializer):
    lineas = LineaEntrada(many=True, allow_empty=True, max_length=armador.MAX_LINEAS)


class ValidarView(_Base):
    """Compatibilidad, faltantes y total de un armado. No guarda nada."""

    throttle_classes = [TiendaThrottle]

    @extend_schema(tags=TAG, request=ValidarEntrada, responses={200: dict})
    def post(self, request):
        entrada = ValidarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        self.organizacion_id()  # 503 si la tienda está cerrada
        ctx = catalogo.contexto()
        config = armador.configuracion_vigente(ctx.organizacion_id)
        if not armador.esta_listo(config):
            raise DatosInvalidos("El armador no está disponible por ahora.")
        return Response(armador.validar(ctx, config, entrada.validated_data["lineas"]))


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = {"get": CONFIGURAR, "patch": CONFIGURAR}

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización, no de una empresa

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


def _config_de(organizacion_id: int) -> ConfiguracionArmador:
    existente = ConfiguracionArmador.objects.filter(organizacion_id=organizacion_id).first()
    return existente or ConfiguracionArmador.objects.create(organizacion_id=organizacion_id)


def _salida(config: ConfiguracionArmador) -> dict:
    org = config.organizacion_id
    espacios = armador._espacios_guardados(config)
    categorias = list(
        Categoria.objects.sin_ambito()
        .filter(organizacion_id=org, estado=EstadoRegistro.ACTIVO)
        .select_related("familia")
        .order_by("familia__nombre", "nombre")
    )
    # Campos de especificación de las categorías de cada espacio: para elegir con qué dato compara
    # cada regla y avisar si la categoría no tiene el campo.
    por_categoria: dict[int, list] = {}
    for c in CampoEspecificacion.objects.sin_ambito().filter(
        organizacion_id=org, estado=EstadoRegistro.ACTIVO
    ):
        por_categoria.setdefault(c.categoria_id, []).append(c)
    campos_de_espacio = {}
    for clave, e in espacios.items():
        vistos: dict[str, str] = {}
        for cat in e["categorias"]:
            for campo in por_categoria.get(cat, []):
                vistos.setdefault(campo.clave, campo.nombre)
        campos_de_espacio[clave] = [
            {"clave": k, "nombre": n} for k, n in sorted(vistos.items(), key=lambda t: t[1])
        ]
    efectivas = armador.claves_efectivas(config)
    ajustes = config.reglas or {}
    reglas = []
    for regla in armador.REGLAS:
        claves = {}
        for alias, (espacio, defecto) in regla.claves.items():
            actual = efectivas[regla.id][alias]
            existentes = {c["clave"] for c in campos_de_espacio.get(espacio, [])}
            claves[alias] = {
                "espacio": espacio,
                "espacio_nombre": armador.ESPACIO_POR_CLAVE[espacio].nombre,
                "clave": actual,
                "defecto": defecto,
                "existe": actual in existentes,
                "espacio_configurado": bool(espacios[espacio]["categorias"]),
            }
        reglas.append(
            {
                "id": regla.id,
                "nombre": regla.nombre,
                "descripcion": regla.descripcion,
                "activa": (ajustes.get(regla.id) or {}).get("activa", True),
                "claves": claves,
            }
        )
    return {
        "activo": config.activo,
        "listo": armador.esta_listo(config),
        "espacios": list(espacios.values()),
        "reglas": reglas,
        "opciones": {
            "categorias": [
                {"id": c.pk, "nombre": c.nombre, "familia": c.familia.nombre} for c in categorias
            ],
            "campos": campos_de_espacio,
        },
    }


class EspacioEntrada(serializers.Serializer):
    clave = serializers.CharField(max_length=30)
    categorias = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=50
    )
    obligatorio = serializers.BooleanField(required=False)
    max_unidades = serializers.IntegerField(min_value=1, max_value=10, required=False)


class ReglaEntrada(serializers.Serializer):
    activa = serializers.BooleanField(required=False)
    claves = serializers.DictField(child=serializers.CharField(max_length=50), required=False)


class ArmadorEntrada(serializers.Serializer):
    activo = serializers.BooleanField(required=False)
    espacios = EspacioEntrada(many=True, required=False, max_length=len(armador.ESPACIOS))
    reglas = serializers.DictField(child=ReglaEntrada(), required=False)


class ArmadorAdminView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(_salida(_config_de(request.user.organizacion_id)))

    @extend_schema(tags=TAG, request=ArmadorEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request):
        entrada = ArmadorEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        config = _config_de(request.user.organizacion_id)
        cambios: dict = {}
        if "espacios" in datos or "reglas" in datos:
            propuesta = {
                "espacios": datos.get("espacios", config.espacios),
                "reglas": datos.get("reglas", config.reglas),
            }
            valido = armador.validar_configuracion(config.organizacion_id, propuesta)
            if "espacios" in datos:
                config.espacios = valido["espacios"]
                cambios["espacios"] = [
                    {"clave": e["clave"], "categorias": e["categorias"]} for e in valido["espacios"]
                ]
            if "reglas" in datos:
                config.reglas = valido["reglas"]
                cambios["reglas"] = sorted(valido["reglas"])
        if "activo" in datos:
            if datos["activo"] and not armador.espacios_con_categorias(config):
                raise DatosInvalidos(
                    "Elige las categorías de al menos un espacio antes de activarlo."
                )
            config.activo = datos["activo"]
            cambios["activo"] = datos["activo"]
        config.save()
        if cambios:
            registrar(
                "tienda.armador_configurado",
                recurso_tipo="configuracion_armador",
                recurso_id=config.pk,
                resumen="Configuración de «Arma tu PC» actualizada",
                detalle=cambios,
            )
        transaction.on_commit(catalogo.invalidar)
        return Response(_salida(config))
