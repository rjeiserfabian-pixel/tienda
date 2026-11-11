"""API de los catálogos del servicio técnico (los comparten las empresas de la organización)."""

from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.mantenimiento.api.v1.views import _CatalogoViewSet, _permisos, _ProtegeEnUso
from apps.mantenimiento.models import EstadoRegistro
from apps.servicio_tecnico.models import (
    AccesorioEquipo,
    CategoriaServicio,
    ItemChecklist,
    TipoEquipo,
    TipoServicio,
)

PERMISOS = _permisos("SERVICIOS.CATALOGOS")


class _CatalogoSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ("id", "nombre", "codigo", "estado", "creado_en")
        read_only_fields = fields


class _CatalogoEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=80)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


# -- tipos de equipo y accesorios -----------------------------------------------------------
class TipoEquipoSerializer(_CatalogoSerializer):
    class Meta(_CatalogoSerializer.Meta):
        model = TipoEquipo


class AccesorioEquipoSerializer(_CatalogoSerializer):
    class Meta(_CatalogoSerializer.Meta):
        model = AccesorioEquipo


class TipoEquipoViewSet(_ProtegeEnUso, _CatalogoViewSet):
    """Tipos de equipo de la organización (``?q=``, ``?estado=``)."""

    modelo = TipoEquipo
    serializer_class = TipoEquipoSerializer
    entrada = _CatalogoEntrada
    recurso = "tipo_equipo"
    duplicado = "Ya existe un tipo de equipo con ese nombre."
    permisos_por_accion = PERMISOS
    relaciones_en_uso = ("equipos", "revisiones")
    mensaje_en_uso = "Hay equipos o revisiones que lo usan. Desactívalo en lugar de eliminarlo."


class AccesorioEquipoViewSet(_CatalogoViewSet):
    """Accesorios que el cliente deja con el equipo (``?q=``, ``?estado=``)."""

    modelo = AccesorioEquipo
    serializer_class = AccesorioEquipoSerializer
    entrada = _CatalogoEntrada
    recurso = "accesorio_equipo"
    duplicado = "Ya existe un accesorio con ese nombre."
    permisos_por_accion = PERMISOS


# -- revisiones de ingreso ------------------------------------------------------------------
class ItemChecklistSerializer(serializers.ModelSerializer):
    tipo_equipo_nombre = serializers.CharField(
        source="tipo_equipo.nombre", default="", read_only=True
    )

    class Meta:
        model = ItemChecklist
        fields = (
            "id",
            "nombre",
            "codigo",
            "tipo_equipo",
            "tipo_equipo_nombre",
            "orden",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class ItemChecklistEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=120)
    tipo_equipo = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    orden = serializers.IntegerField(min_value=0, max_value=999, required=False)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class ItemChecklistViewSet(_CatalogoViewSet):
    """Revisiones al recibir el equipo (``?tipo_equipo=ID``, ``?q=``, ``?estado=``).

    Con ``?tipo_equipo=ID`` devuelve las de ese tipo más las que valen para todos.
    """

    modelo = ItemChecklist
    serializer_class = ItemChecklistSerializer
    entrada = ItemChecklistEntrada
    recurso = "item_checklist"
    duplicado = "Ya existe una revisión con ese nombre."
    permisos_por_accion = PERMISOS
    ordenes = {"nombre": ("nombre",), "orden": ("orden", "nombre")}
    orden_por_defecto = ("orden", "nombre")

    def get_queryset(self):
        queryset = super().get_queryset().select_related("tipo_equipo")
        tipo = self.request.query_params.get("tipo_equipo")
        if tipo:
            if not tipo.isdigit():
                raise ValidationError({"tipo_equipo": "Debe ser un número entero."})
            queryset = queryset.filter(Q(tipo_equipo_id=int(tipo)) | Q(tipo_equipo__isnull=True))
        return queryset

    @staticmethod
    def _tipo(tipo_id):
        tipo = TipoEquipo.objects.filter(pk=tipo_id, estado=EstadoRegistro.ACTIVO).first()
        if tipo is None:
            raise ValidationError({"tipo_equipo": "Elija un tipo de equipo activo."})
        return tipo

    def datos_de_alta(self, validados: dict) -> dict:
        tipo_id = validados.pop("tipo_equipo", None)
        validados["tipo_equipo"] = self._tipo(tipo_id) if tipo_id else None
        return super().datos_de_alta(validados)

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if "tipo_equipo" in validados:
            tipo_id = validados["tipo_equipo"]
            if tipo_id == instancia.tipo_equipo_id:
                del validados["tipo_equipo"]
            else:
                validados["tipo_equipo"] = self._tipo(tipo_id) if tipo_id else None
        return validados


# -- tipos de servicio ----------------------------------------------------------------------
class TipoServicioSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(source="get_categoria_display", read_only=True)

    class Meta:
        model = TipoServicio
        fields = (
            "id",
            "nombre",
            "codigo",
            "categoria",
            "categoria_nombre",
            "garantia_dias",
            "precio_referencial",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class TipoServicioEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=100)
    categoria = serializers.ChoiceField(choices=CategoriaServicio.choices, required=False)
    garantia_dias = serializers.IntegerField(min_value=0, max_value=3650, required=False)
    precio_referencial = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False
    )
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class TipoServicioViewSet(_ProtegeEnUso, _CatalogoViewSet):
    """Tipos de servicio (``?categoria=``, ``?q=``, ``?estado=``)."""

    modelo = TipoServicio
    serializer_class = TipoServicioSerializer
    entrada = TipoServicioEntrada
    recurso = "tipo_servicio"
    duplicado = "Ya existe un tipo de servicio con ese nombre."
    permisos_por_accion = PERMISOS
    filtros_exactos = ("estado", "categoria")
    relaciones_en_uso = ("ordenes",)
    mensaje_en_uso = "Hay órdenes que lo usan. Desactívalo en lugar de eliminarlo."
