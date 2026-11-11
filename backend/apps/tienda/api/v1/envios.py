"""Panel: zonas de envío (con tarifas por peso y lugares que cubren) y puntos de recojo."""

import logging
from decimal import Decimal

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import Ubigeo
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import catalogo, envios
from apps.tienda.models import CoberturaZona, PuntoRecojo, TarifaZona, ZonaEnvio

logger = logging.getLogger(__name__)

TAG = ["tienda"]
CONFIGURAR = "TIENDA.CONFIGURAR"
MAX_TRAMOS = 20
MAX_COBERTURAS = 400


class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = dict.fromkeys(("get", "post", "patch", "delete"), CONFIGURAR)

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización, no de una empresa

    def respuesta(self, request, estado=200):
        respuesta = Response(_salida(request.user.organizacion_id), status=estado)
        respuesta["Cache-Control"] = "no-store"
        return respuesta


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
def _etiquetas_de_cobertura(prefijos: set[str]) -> dict[str, str]:
    """«15» → LIMA (departamento), «1501» → LIMA - LIMA (provincia), «150101» → … (distrito)."""
    etiquetas: dict[str, str] = {}
    if not prefijos:
        return etiquetas
    largos = {p for p in prefijos if len(p) == 6}
    for u in Ubigeo.objects.filter(codigo__in=largos):
        etiquetas[u.codigo] = u.nombre_completo
    for p in prefijos - largos:
        u = Ubigeo.objects.filter(codigo__startswith=p).order_by("codigo").first()
        if u is None:
            continue
        etiquetas[p] = (
            f"{u.departamento} (todo el departamento)".upper()
            if len(p) == 2
            else f"{u.departamento} - {u.provincia} (toda la provincia)".upper()
        )
    return etiquetas


def _zona_salida(zona: ZonaEnvio, etiquetas: dict[str, str]) -> dict:
    return {
        "id": zona.pk,
        "nombre": zona.nombre,
        "modalidad": zona.modalidad,
        "plazo": zona.plazo,
        "detalle": zona.detalle,
        "activa": zona.activa,
        "orden": zona.orden,
        "envio_gratis_desde": None
        if zona.envio_gratis_desde is None
        else format(zona.envio_gratis_desde, "f"),
        "kg_adicional": None if zona.kg_adicional is None else format(zona.kg_adicional, "f"),
        "tarifas": [
            {"hasta_kg": format(t.hasta_kg, "f"), "costo": format(t.costo, "f")}
            for t in sorted(zona.tarifas.all(), key=lambda t: t.hasta_kg)
            if t.eliminado_en is None
        ],
        "coberturas": [
            {"prefijo": c.prefijo, "nombre": etiquetas.get(c.prefijo, c.prefijo)}
            for c in sorted(zona.coberturas.all(), key=lambda c: c.prefijo)
            if c.eliminado_en is None
        ],
    }


def _punto_salida(punto: PuntoRecojo) -> dict:
    return {
        "id": punto.pk,
        "nombre": punto.nombre,
        "direccion": punto.direccion,
        "ubigeo": punto.ubigeo,
        "horario": punto.horario,
        "indicaciones": punto.indicaciones,
        "listo_en": punto.listo_en,
        "telefono": punto.telefono,
        "activo": punto.activo,
        "orden": punto.orden,
        "almacenes": sorted(a.pk for a in punto.almacenes.all()),
    }


def _salida(organizacion_id: int) -> dict:
    zonas = list(
        ZonaEnvio.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id)
        .prefetch_related("tarifas", "coberturas")
        .order_by("orden", "id")
    )
    etiquetas = _etiquetas_de_cobertura(
        {c.prefijo for z in zonas for c in z.coberturas.all() if c.eliminado_en is None}
    )
    puntos = list(
        PuntoRecojo.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id)
        .prefetch_related("almacenes")
        .order_by("orden", "id")
    )
    return {
        "zonas": [_zona_salida(z, etiquetas) for z in zonas],
        "puntos": [_punto_salida(p) for p in puntos],
        "opciones": {
            "almacenes": [
                {"id": a.pk, "nombre": a.nombre, "empresa": a.empresa.razon_social}
                for a in envios.almacenes_de_la_organizacion(organizacion_id)
                .select_related("empresa")
                .order_by("empresa__razon_social", "nombre")
            ],
        },
    }


# ---------------------------------------------------------------------------
# Zonas
# ---------------------------------------------------------------------------
class TarifaEntrada(serializers.Serializer):
    hasta_kg = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=Decimal("0.01"))
    costo = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0"))


class ZonaEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=80)
    modalidad = serializers.ChoiceField(choices=ZonaEnvio.Modalidad.choices)
    plazo = serializers.CharField(max_length=100, required=False, allow_blank=True)
    detalle = serializers.CharField(max_length=250, required=False, allow_blank=True)
    activa = serializers.BooleanField(required=False)
    orden = serializers.IntegerField(min_value=0, max_value=1000, required=False)
    envio_gratis_desde = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True
    )
    kg_adicional = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True
    )
    tarifas = TarifaEntrada(many=True, required=False, max_length=MAX_TRAMOS)
    coberturas = serializers.ListField(
        child=serializers.RegexField(r"^(\d{2}|\d{4}|\d{6})$"),
        required=False,
        max_length=MAX_COBERTURAS,
    )

    def validate_nombre(self, valor):
        valor = " ".join(valor.split())
        if not valor:
            raise serializers.ValidationError("Escribe el nombre de la zona.")
        return valor

    def validate_tarifas(self, tramos):
        limites = [t["hasta_kg"] for t in tramos]
        if len(set(limites)) != len(limites):
            raise serializers.ValidationError("Hay dos tramos con el mismo peso.")
        return tramos


def _validar_coberturas(organizacion_id: int, prefijos: list[str], zona_id: int | None):
    prefijos = list(dict.fromkeys(prefijos))
    for p in prefijos:
        if not Ubigeo.objects.filter(codigo__startswith=p).exists():
            raise ValidationError({"coberturas": f"El lugar {p} no existe."})
    ocupados = CoberturaZona.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, prefijo__in=prefijos
    )
    if zona_id:
        ocupados = ocupados.exclude(zona_id=zona_id)
    primero = ocupados.select_related("zona").first()
    if primero is not None:
        raise ValidationError(
            {
                "coberturas": (
                    f"El lugar {primero.prefijo} ya está en la zona «{primero.zona.nombre}»."
                )
            }
        )
    return prefijos


def _guardar_zona(zona: ZonaEnvio, datos: dict) -> None:
    organizacion_id = zona.organizacion_id
    campos = ("nombre", "modalidad", "plazo", "detalle", "activa", "orden")
    for campo in campos + ("envio_gratis_desde", "kg_adicional"):
        if campo in datos:
            valor = datos[campo]
            if isinstance(valor, str):
                valor = " ".join(valor.split())
            setattr(zona, campo, valor)
    if zona.modalidad == ZonaEnvio.Modalidad.DESTINO:
        zona.envio_gratis_desde = None
        zona.kg_adicional = None
    zona.save()
    if "tarifas" in datos:
        if zona.modalidad == ZonaEnvio.Modalidad.TIENDA and not datos["tarifas"]:
            raise ValidationError({"tarifas": "Pon al menos un tramo de peso con su costo."})
        zona.tarifas.filter(eliminado_en__isnull=True).delete()  # borrado lógico
        for t in datos["tarifas"] if zona.modalidad == ZonaEnvio.Modalidad.TIENDA else []:
            TarifaZona.objects.sin_ambito().create(organizacion_id=organizacion_id, zona=zona, **t)
    if "coberturas" in datos:
        prefijos = _validar_coberturas(organizacion_id, datos["coberturas"], zona.pk)
        zona.coberturas.filter(eliminado_en__isnull=True).delete()
        for p in prefijos:
            CoberturaZona.objects.sin_ambito().create(
                organizacion_id=organizacion_id, zona=zona, prefijo=p
            )


class EnviosView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return self.respuesta(request)


class ZonasView(_Admin):
    @extend_schema(tags=TAG, request=ZonaEntrada, responses={201: dict})
    @transaction.atomic
    def post(self, request):
        entrada = ZonaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        if datos["modalidad"] == ZonaEnvio.Modalidad.TIENDA and not datos.get("tarifas"):
            raise ValidationError({"tarifas": "Pon al menos un tramo de peso con su costo."})
        zona = ZonaEnvio(organizacion_id=request.user.organizacion_id)
        _guardar_zona(zona, {"tarifas": [], "coberturas": [], **datos})
        registrar(
            "tienda.zona_creada", recurso_tipo="zona_envio", recurso_id=zona.pk,
            resumen=f"Zona de envío «{zona.nombre}» creada",
        )  # fmt: skip
        transaction.on_commit(catalogo.invalidar)
        return self.respuesta(request, 201)


class ZonaView(_Admin):
    def _zona(self, request, pk: int) -> ZonaEnvio:
        zona = ZonaEnvio.objects.filter(pk=pk, organizacion_id=request.user.organizacion_id).first()
        if zona is None:
            raise NotFound("No existe esa zona.")
        return zona

    @extend_schema(tags=TAG, request=ZonaEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request, pk: int):
        zona = self._zona(request, pk)
        entrada = ZonaEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        _guardar_zona(zona, entrada.validated_data)
        registrar(
            "tienda.zona_editada", recurso_tipo="zona_envio", recurso_id=zona.pk,
            resumen=f"Zona de envío «{zona.nombre}» editada",
        )  # fmt: skip
        transaction.on_commit(catalogo.invalidar)
        return self.respuesta(request)

    @extend_schema(tags=TAG, responses={200: dict})
    @transaction.atomic
    def delete(self, request, pk: int):
        zona = self._zona(request, pk)
        zona.coberturas.filter(eliminado_en__isnull=True).delete()  # libera los lugares
        zona.tarifas.filter(eliminado_en__isnull=True).delete()
        zona.delete()
        registrar(
            "tienda.zona_eliminada", recurso_tipo="zona_envio", recurso_id=zona.pk,
            resumen=f"Zona de envío «{zona.nombre}» eliminada",
        )  # fmt: skip
        transaction.on_commit(catalogo.invalidar)
        return self.respuesta(request)


# ---------------------------------------------------------------------------
# Puntos de recojo
# ---------------------------------------------------------------------------
class PuntoEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=100)
    direccion = serializers.CharField(max_length=250)
    ubigeo = serializers.RegexField(r"^\d{6}$", required=False, allow_blank=True)
    horario = serializers.CharField(max_length=200, required=False, allow_blank=True)
    indicaciones = serializers.CharField(max_length=250, required=False, allow_blank=True)
    listo_en = serializers.CharField(max_length=80, required=False, allow_blank=True)
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)
    activo = serializers.BooleanField(required=False)
    orden = serializers.IntegerField(min_value=0, max_value=1000, required=False)
    almacenes = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=100
    )

    def validate(self, datos):
        for campo, valor in list(datos.items()):
            if isinstance(valor, str):
                datos[campo] = " ".join(valor.split())
        for obligatorio in ("nombre", "direccion"):
            if obligatorio in datos and not datos[obligatorio]:
                raise serializers.ValidationError({obligatorio: "Este dato es obligatorio."})
        return datos


def _guardar_punto(punto: PuntoRecojo, datos: dict) -> None:
    datos = dict(datos)
    ids = datos.pop("almacenes", None)
    for campo, valor in datos.items():
        setattr(punto, campo, valor)
    if ids is not None:
        elegidos = set(
            envios.almacenes_de_la_organizacion(punto.organizacion_id)
            .filter(pk__in=ids)
            .values_list("pk", flat=True)
        )
        if elegidos != set(ids):
            raise ValidationError({"almacenes": "Hay almacenes que no existen o están inactivos."})
    punto.save()
    if ids is not None:
        enlace = PuntoRecojo.almacenes.through
        filas = enlace.objects.filter(puntorecojo_id=punto.pk)
        filas.exclude(almacen_id__in=ids).delete()
        existentes = set(filas.values_list("almacen_id", flat=True))
        enlace.objects.bulk_create(
            [enlace(puntorecojo_id=punto.pk, almacen_id=i) for i in set(ids) - existentes]
        )


class PuntosView(_Admin):
    @extend_schema(tags=TAG, request=PuntoEntrada, responses={201: dict})
    @transaction.atomic
    def post(self, request):
        entrada = PuntoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        punto = PuntoRecojo(organizacion_id=request.user.organizacion_id)
        _guardar_punto(punto, entrada.validated_data)
        registrar(
            "tienda.punto_creado", recurso_tipo="punto_recojo", recurso_id=punto.pk,
            resumen=f"Punto de recojo «{punto.nombre}» creado",
        )  # fmt: skip
        transaction.on_commit(catalogo.invalidar)
        return self.respuesta(request, 201)


class PuntoView(_Admin):
    def _punto(self, request, pk: int) -> PuntoRecojo:
        punto = PuntoRecojo.objects.filter(
            pk=pk, organizacion_id=request.user.organizacion_id
        ).first()
        if punto is None:
            raise NotFound("No existe ese punto de recojo.")
        return punto

    @extend_schema(tags=TAG, request=PuntoEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request, pk: int):
        punto = self._punto(request, pk)
        entrada = PuntoEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        _guardar_punto(punto, entrada.validated_data)
        registrar(
            "tienda.punto_editado", recurso_tipo="punto_recojo", recurso_id=punto.pk,
            resumen=f"Punto de recojo «{punto.nombre}» editado",
        )  # fmt: skip
        transaction.on_commit(catalogo.invalidar)
        return self.respuesta(request)

    @extend_schema(tags=TAG, responses={200: dict})
    @transaction.atomic
    def delete(self, request, pk: int):
        punto = self._punto(request, pk)
        punto.delete()
        registrar(
            "tienda.punto_eliminado", recurso_tipo="punto_recojo", recurso_id=punto.pk,
            resumen=f"Punto de recojo «{punto.nombre}» eliminado",
        )  # fmt: skip
        transaction.on_commit(catalogo.invalidar)
        return self.respuesta(request)


# ---------------------------------------------------------------------------
# Lugares para elegir las coberturas
# ---------------------------------------------------------------------------
def datos_de_ubigeos(provincia: str):
    """Sin provincia: departamentos con sus provincias. Con ``provincia`` (4 dígitos): distritos."""
    if provincia:
        if len(provincia) != 4 or not provincia.isdigit():
            raise ValidationError({"provincia": "Indica la provincia con sus 4 dígitos."})
        filas = Ubigeo.objects.filter(codigo__startswith=provincia).order_by("distrito")
        return [{"codigo": u.codigo, "nombre": u.distrito} for u in filas]
    departamentos: dict[str, dict] = {}
    for u in Ubigeo.objects.order_by("codigo").only("codigo", "departamento", "provincia"):
        dep = departamentos.setdefault(
            u.codigo[:2], {"codigo": u.codigo[:2], "nombre": u.departamento, "provincias": {}}
        )
        dep["provincias"].setdefault(u.codigo[:4], {"codigo": u.codigo[:4], "nombre": u.provincia})
    return [{**d, "provincias": list(d["provincias"].values())} for d in departamentos.values()]


class UbigeosView(_Admin):
    """Sin parámetros: departamentos con sus provincias. Con ``?provincia=1501``: sus distritos."""

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        respuesta = Response(datos_de_ubigeos(request.query_params.get("provincia", "")))
        respuesta["Cache-Control"] = "private, max-age=3600"
        return respuesta
