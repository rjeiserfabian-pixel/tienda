"""API de los conceptos de caja (para qué entra o sale dinero)."""

from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.mantenimiento import services
from apps.mantenimiento.models import ConceptoCaja, EstadoRegistro

from .views import _CatalogoViewSet, _permisos


class ConceptoCajaSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = ConceptoCaja
        fields = ("id", "nombre", "tipo", "tipo_nombre", "automatico", "estado", "creado_en")
        read_only_fields = fields


class ConceptoCajaEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=80)
    tipo = serializers.ChoiceField(choices=ConceptoCaja.Tipo.choices)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class ConceptoCajaViewSet(_CatalogoViewSet):
    """Conceptos de caja de la organización (``?q=``, ``?estado=``, ``?tipo=``, ``?manual=1``).

    ``manual=1`` deja fuera los que usa el sistema por su cuenta: son los que se ofrecen al
    registrar un ingreso o egreso a mano.
    """

    modelo = ConceptoCaja
    serializer_class = ConceptoCajaSerializer
    entrada = ConceptoCajaEntrada
    recurso = "concepto_caja"
    duplicado = "Ya existe un concepto de ese tipo con ese nombre."
    permisos_por_accion = _permisos("MANTENIMIENTO.CONCEPTOS_CAJA")
    filtros_exactos = ("estado", "tipo")
    ordenes = {"nombre": ("nombre",), "tipo": ("tipo", "nombre")}
    orden_por_defecto = ("tipo", "nombre")

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("manual") in ("1", "true"):
            queryset = queryset.filter(automatico=False)
        return queryset

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if "tipo" in validados and validados["tipo"] != instancia.tipo:
            raise ValidationError({"tipo": "El tipo no se cambia: crea otro concepto."})
        if instancia.automatico and validados.get("estado") == EstadoRegistro.INACTIVO:
            raise ValidationError({"estado": "Lo usa el sistema: no se puede desactivar."})
        return validados

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        if instancia.automatico:
            raise ValidationError("Lo usa el sistema por su cuenta: no se puede eliminar.")
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)
