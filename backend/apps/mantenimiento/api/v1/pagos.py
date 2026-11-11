"""API de los métodos de pago, las periodicidades de cuotas y el cálculo del cronograma."""

from datetime import date
from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.mantenimiento import pagos
from apps.mantenimiento.models import EstadoRegistro, MedioPago, Periodicidad

from .views import TAG, _CatalogoViewSet, _permisos

VER_PERIODICIDADES = "MANTENIMIENTO.PERIODICIDADES.VER"


# ---------------------------------------------------------------------------
# Métodos de pago
# ---------------------------------------------------------------------------
class MedioPagoSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = MedioPago
        fields = (
            "id",
            "nombre",
            "tipo",
            "tipo_nombre",
            "requiere_referencia",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class MedioPagoEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=60)
    tipo = serializers.ChoiceField(choices=MedioPago.Tipo.choices, required=False)
    requiere_referencia = serializers.BooleanField(required=False)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class MedioPagoViewSet(_CatalogoViewSet):
    """Métodos de pago de la organización (``?q=``, ``?estado=``, ``?tipo=``)."""

    modelo = MedioPago
    serializer_class = MedioPagoSerializer
    entrada = MedioPagoEntrada
    recurso = "medio_pago"
    duplicado = "Ya existe un método de pago con ese nombre."
    permisos_por_accion = _permisos("MANTENIMIENTO.MEDIOS_PAGO")
    filtros_exactos = ("estado", "tipo")


# ---------------------------------------------------------------------------
# Periodicidades de cuotas
# ---------------------------------------------------------------------------
class PeriodicidadSerializer(serializers.ModelSerializer):
    unidad_nombre = serializers.CharField(source="get_unidad_display", read_only=True)
    descripcion = serializers.CharField(read_only=True)

    class Meta:
        model = Periodicidad
        fields = (
            "id",
            "nombre",
            "unidad",
            "unidad_nombre",
            "cantidad",
            "descripcion",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class PeriodicidadEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=60)
    unidad = serializers.ChoiceField(choices=Periodicidad.Unidad.choices, required=False)
    cantidad = serializers.IntegerField(
        min_value=1, max_value=Periodicidad.MAXIMO_DIAS, required=False
    )
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class PeriodicidadViewSet(_CatalogoViewSet):
    """Periodicidades de cuotas (``?q=``, ``?estado=``, ``?unidad=``).

    ``GET cronograma/`` reparte un monto en cuotas con sus fechas (sin guardar nada).
    """

    modelo = Periodicidad
    serializer_class = PeriodicidadSerializer
    entrada = PeriodicidadEntrada
    recurso = "periodicidad"
    duplicado = "Ya existe una periodicidad con ese nombre."
    permisos_por_accion = {
        **_permisos("MANTENIMIENTO.PERIODICIDADES"),
        "cronograma": VER_PERIODICIDADES,
    }
    filtros_exactos = ("estado", "unidad")
    ordenes = {"nombre": ("nombre",), "frecuencia": ("unidad", "cantidad")}
    orden_por_defecto = ("unidad", "cantidad", "nombre")

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("periodicidad", int, required=True),
            OpenApiParameter("monto", str, required=True, description="Con hasta 2 decimales"),
            OpenApiParameter("cuotas", int, required=True),
            OpenApiParameter("primera_fecha", str, required=True, description="AAAA-MM-DD"),
        ],
        responses={200: dict},
    )
    @action(detail=False, methods=["get"], url_path="cronograma", pagination_class=None)
    def cronograma(self, request):
        """Cuotas con su fecha y monto; la última absorbe el redondeo."""
        p = request.query_params
        faltan = [n for n in ("periodicidad", "monto", "cuotas", "primera_fecha") if not p.get(n)]
        if faltan:
            raise ValidationError(dict.fromkeys(faltan, "Es obligatorio."))
        if not p["periodicidad"].isdigit():
            raise ValidationError({"periodicidad": "Debe ser un número entero."})
        periodicidad = Periodicidad.objects.filter(
            pk=int(p["periodicidad"]), estado=EstadoRegistro.ACTIVO
        ).first()
        if periodicidad is None:
            raise ValidationError({"periodicidad": "Elija una periodicidad activa."})
        try:
            monto = Decimal(p["monto"])
        except InvalidOperation:
            raise ValidationError({"monto": "Escriba un número."}) from None
        if not p["cuotas"].isdigit():
            raise ValidationError({"cuotas": "Debe ser un número entero."})
        try:
            primera = date.fromisoformat(p["primera_fecha"])
        except ValueError:
            raise ValidationError({"primera_fecha": "Use el formato AAAA-MM-DD."}) from None
        if not (2000 <= primera.year <= 2100):
            raise ValidationError({"primera_fecha": "La fecha no es válida."})
        try:
            cuotas = pagos.generar_cronograma(monto, int(p["cuotas"]), primera, periodicidad)
        except ValueError as error:
            raise ValidationError({"cuotas": str(error)}) from None
        return Response(
            {
                "periodicidad": PeriodicidadSerializer(periodicidad).data,
                "monto": str(monto),
                "cuotas": len(cuotas),
                "total": str(sum((c.monto for c in cuotas), Decimal("0"))),
                "cronograma": [
                    {"numero": c.numero, "fecha": c.fecha.isoformat(), "monto": str(c.monto)}
                    for c in cuotas
                ],
            }
        )
