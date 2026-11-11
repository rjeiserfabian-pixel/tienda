"""API del reingreso por garantía: el equipo vuelve, ligado a la orden que se entregó."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.mantenimiento.models import EstadoRegistro, Personal
from apps.servicio_tecnico import garantia
from apps.servicio_tecnico.capacidades import capacidades_de
from apps.servicio_tecnico.models import AccesorioEquipo
from apps.servicio_tecnico.recepcion import AccesorioEntrada

from .serializers import AccesorioEntradaSerializer

TAG = ["servicio-tecnico"]


class ReingresoEntrada(serializers.Serializer):
    falla_reportada = serializers.CharField(max_length=1000)
    estado_fisico = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    clave_equipo = serializers.CharField(max_length=100, required=False, allow_blank=True)
    accesorios = AccesorioEntradaSerializer(many=True, required=False, max_length=30)
    tecnico = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class GarantiaAcciones:
    """Reingreso por garantía. Lo hace quien recibe equipos."""

    @extend_schema(tags=TAG, request=ReingresoEntrada)
    @action(detail=True, methods=["post"], url_path="reingreso")
    def reingreso(self, request, pk=None):
        """Recibe de nuevo el equipo de una orden entregada y con garantía vigente."""
        original = self.get_object()
        if not capacidades_de(request.user, original).recibe:
            raise PermissionDenied("No tiene permiso para recibir equipos.")
        datos = ReingresoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        org = original.empresa.organizacion_id
        tecnico = None
        if v.get("tecnico"):
            tecnico = Personal.objects.filter(
                pk=v["tecnico"], empresa_id=original.empresa_id
            ).first()
            if tecnico is None:
                raise ValidationError({"tecnico": "Elija un técnico de esta empresa."})
        accesorios = []
        for a in v.get("accesorios", []):
            catalogo = None
            if a.get("accesorio"):
                catalogo = AccesorioEquipo.objects.filter(
                    pk=a["accesorio"], organizacion_id=org, estado=EstadoRegistro.ACTIVO
                ).first()
                if catalogo is None:
                    raise ValidationError({"accesorios": "Hay accesorios que no existen."})
            accesorios.append(
                AccesorioEntrada(
                    accesorio=catalogo,
                    nombre=a.get("nombre", ""),
                    cantidad=a["cantidad"],
                    detalle=a.get("detalle", ""),
                )
            )
        nueva = garantia.reingreso_por_garantia(
            original,
            falla_reportada=v["falla_reportada"],
            estado_fisico=v.get("estado_fisico", ""),
            clave_equipo=v.get("clave_equipo", ""),
            accesorios=accesorios,
            tecnico=tecnico,
        )
        ficha = self.get_queryset().get(pk=nueva.pk)
        return Response(self.get_serializer(ficha).data, status=201)
