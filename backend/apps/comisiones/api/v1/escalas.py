"""API de escalas mensuales, metas con bono y avance del mes de los vendedores."""

import re

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.comisiones import avance as avances
from apps.comisiones import escalas
from apps.comisiones.models import EscalaComision, MetaBono
from apps.organizacion.models import Empresa
from apps.seguridad.models import Usuario
from apps.seguridad.permissions import PermisoRBAC
from apps.seguridad.services import permisos_engine as motor

from .views import GESTIONAR, VENDER, VER, _nombre, _organizacion

TAG = ["comisiones"]
_MES = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _nombres(organizacion_id: int, objetos) -> dict:
    ids = {o.vendedor_id for o in objetos if o.vendedor_id}
    if not ids:
        return {}
    return {
        u.pk: _nombre(u)
        for u in Usuario.objects.filter(pk__in=ids, organizacion_id=organizacion_id)
    }


def _escala_salida(e: EscalaComision, nombres: dict) -> dict:
    return {
        "id": e.pk,
        "nombre": e.nombre,
        "vendedor": str(e.vendedor_id) if e.vendedor_id else None,
        "vendedor_nombre": nombres.get(e.vendedor_id, "Todos los vendedores")
        if e.vendedor_id
        else "Todos los vendedores",
        "vigente_desde": e.vigente_desde.isoformat() if e.vigente_desde else None,
        "vigente_hasta": e.vigente_hasta.isoformat() if e.vigente_hasta else None,
        "activa": e.activa,
        "tramos": [
            {"desde": str(t.desde), "porcentaje": str(t.porcentaje)}
            for t in e.tramos.order_by("desde")
        ],
    }


def _meta_salida(m: MetaBono, nombres: dict) -> dict:
    return {
        "id": m.pk,
        "nombre": m.nombre,
        "vendedor": str(m.vendedor_id) if m.vendedor_id else None,
        "vendedor_nombre": nombres.get(m.vendedor_id, "Todos los vendedores")
        if m.vendedor_id
        else "Todos los vendedores",
        "meta": str(m.meta),
        "bono": str(m.bono),
        "vigente_desde": m.vigente_desde.isoformat() if m.vigente_desde else None,
        "vigente_hasta": m.vigente_hasta.isoformat() if m.vigente_hasta else None,
        "activa": m.activa,
        "otorgados": m.otorgados.count(),
    }


class TramoEntrada(serializers.Serializer):
    desde = serializers.CharField(max_length=20)
    porcentaje = serializers.CharField(max_length=12)


class EscalaEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=120, required=False)
    vendedor_id = serializers.UUIDField(required=False, allow_null=True)
    vigente_desde = serializers.DateField(required=False, allow_null=True)
    vigente_hasta = serializers.DateField(required=False, allow_null=True)
    activa = serializers.BooleanField(required=False)
    tramos = TramoEntrada(many=True, required=False, max_length=20)


class MetaEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=120, required=False)
    vendedor_id = serializers.UUIDField(required=False, allow_null=True)
    meta = serializers.CharField(max_length=20, required=False)
    bono = serializers.CharField(max_length=20, required=False)
    vigente_desde = serializers.DateField(required=False, allow_null=True)
    vigente_hasta = serializers.DateField(required=False, allow_null=True)
    activa = serializers.BooleanField(required=False)


class EscalasView(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "post": GESTIONAR}

    @extend_schema(tags=TAG)
    def get(self, request):
        org = _organizacion(request)
        filas = list(EscalaComision.objects.filter(organizacion_id=org).prefetch_related("tramos"))
        nombres = _nombres(org, filas)
        return Response({"results": [_escala_salida(e, nombres) for e in filas]})

    @extend_schema(tags=TAG, request=EscalaEntrada)
    def post(self, request):
        entrada = EscalaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        escala = escalas.crear_escala(_organizacion(request), _plano(datos))
        return Response(
            _escala_salida(escala, _nombres(escala.organizacion_id, [escala])), status=201
        )


def _plano(datos: dict) -> dict:
    """Los tramos del serializador vienen como diccionarios ordenados: se pasan tal cual."""
    if "tramos" in datos:
        datos["tramos"] = [dict(t) for t in datos["tramos"]]
    return datos


class EscalaView(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "patch": GESTIONAR, "delete": GESTIONAR}

    def _escala(self, request, pk: int) -> EscalaComision:
        escala = EscalaComision.objects.filter(
            pk=pk, organizacion_id=_organizacion(request)
        ).first()
        if escala is None:
            raise NotFound("No encontramos esa escala.")
        return escala

    @extend_schema(tags=TAG)
    def get(self, request, pk: int):
        e = self._escala(request, pk)
        return Response(_escala_salida(e, _nombres(e.organizacion_id, [e])))

    @extend_schema(tags=TAG, request=EscalaEntrada)
    def patch(self, request, pk: int):
        e = self._escala(request, pk)
        entrada = EscalaEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        escalas.actualizar_escala(e, _plano(dict(entrada.validated_data)))
        e = self._escala(request, pk)
        return Response(_escala_salida(e, _nombres(e.organizacion_id, [e])))

    @extend_schema(tags=TAG)
    def delete(self, request, pk: int):
        escalas.eliminar_escala(self._escala(request, pk))
        return Response(status=204)


class MetasView(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "post": GESTIONAR}

    @extend_schema(tags=TAG)
    def get(self, request):
        org = _organizacion(request)
        filas = list(MetaBono.objects.filter(organizacion_id=org))
        nombres = _nombres(org, filas)
        return Response({"results": [_meta_salida(m, nombres) for m in filas]})

    @extend_schema(tags=TAG, request=MetaEntrada)
    def post(self, request):
        entrada = MetaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        meta = escalas.crear_meta(_organizacion(request), dict(entrada.validated_data))
        return Response(_meta_salida(meta, _nombres(meta.organizacion_id, [meta])), status=201)


class MetaView(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "patch": GESTIONAR, "delete": GESTIONAR}

    def _meta(self, request, pk: int) -> MetaBono:
        meta = MetaBono.objects.filter(pk=pk, organizacion_id=_organizacion(request)).first()
        if meta is None:
            raise NotFound("No encontramos esa meta.")
        return meta

    @extend_schema(tags=TAG)
    def get(self, request, pk: int):
        m = self._meta(request, pk)
        return Response(_meta_salida(m, _nombres(m.organizacion_id, [m])))

    @extend_schema(tags=TAG, request=MetaEntrada)
    def patch(self, request, pk: int):
        m = self._meta(request, pk)
        entrada = MetaEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        escalas.actualizar_meta(m, dict(entrada.validated_data))
        m = self._meta(request, pk)
        return Response(_meta_salida(m, _nombres(m.organizacion_id, [m])))

    @extend_schema(tags=TAG)
    def delete(self, request, pk: int):
        escalas.eliminar_meta(self._meta(request, pk))
        return Response(status=204)


def _vendedores(org: int):
    empresas = list(Empresa.objects.filter(organizacion_id=org).values_list("pk", flat=True))
    return [
        u
        for u in Usuario.objects.filter(organizacion_id=org, is_active=True).order_by(
            "first_name", "username"
        )
        if any(motor.tiene_permiso(u, VENDER, e) for e in empresas)
    ]


class AvanceView(APIView):
    """Cuánto lleva vendido cada vendedor en el mes, su tramo de escala y sus metas."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("mes", str, description="AAAA-MM (por defecto, el mes actual)"),
            OpenApiParameter("vendedor", str, description="Id del vendedor (vacío = todos)"),
        ],
    )
    def get(self, request):
        from django.utils import timezone

        org = _organizacion(request)
        texto = request.query_params.get("mes") or timezone.localdate().strftime("%Y-%m")
        encontrado = _MES.match(texto)
        if not encontrado:
            raise ValidationError({"mes": "Use el formato AAAA-MM."})
        año, mes = int(encontrado.group(1)), int(encontrado.group(2))
        vendedores = _vendedores(org)
        elegido = request.query_params.get("vendedor")
        if elegido:
            vendedores = [v for v in vendedores if str(v.pk) == elegido]
        return Response(
            {
                "periodo": avances.periodo_de(año, mes),
                "results": [
                    {
                        "vendedor": str(v.pk),
                        "vendedor_nombre": _nombre(v),
                        **avances.avance(org, v.pk, año, mes),
                    }
                    for v in vendedores
                ],
            }
        )
