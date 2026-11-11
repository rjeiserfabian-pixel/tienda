"""API de las categorías de gasto (en qué se gasta)."""

from rest_framework import serializers

from apps.mantenimiento.models import CategoriaGasto, EstadoRegistro

from .views import _CatalogoViewSet, _permisos


class CategoriaGastoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoriaGasto
        fields = ("id", "nombre", "codigo", "estado", "creado_en")
        read_only_fields = fields


class CategoriaGastoEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=80)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class CategoriaGastoViewSet(_CatalogoViewSet):
    """Categorías de gasto de la organización (``?q=``, ``?estado=``)."""

    modelo = CategoriaGasto
    serializer_class = CategoriaGastoSerializer
    entrada = CategoriaGastoEntrada
    recurso = "categoria_gasto"
    duplicado = "Ya existe una categoría de gasto con ese nombre."
    permisos_por_accion = _permisos("MANTENIMIENTO.CATEGORIAS_GASTO")
    filtros_exactos = ("estado",)
    ordenes = {"nombre": ("nombre",)}
    orden_por_defecto = ("nombre",)
