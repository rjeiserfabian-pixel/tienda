"""API del cierre mensual, de lo que se paga a cada persona y de «Mis comisiones»."""

from datetime import date

from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.comisiones import a_planilla, avance, cierre
from apps.comisiones.models import LineaLiquidacion, LiquidacionComision, MovimientoComision
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.servicio_tecnico.models import EstadoOrden, OrdenServicio

from .escalas import _MES, _vendedores
from .views import VER, _nombre, _organizacion

LIQUIDAR = "COMISIONES.LIQUIDAR"
VER_PROPIAS = "COMISIONES.VER_PROPIAS"
TAG = ["comisiones"]


def _periodo(texto, campo: str = "mes") -> tuple[int, int]:
    encontrado = _MES.match(str(texto or ""))
    if not encontrado:
        raise ValidationError({campo: "Use el formato AAAA-MM."})
    return int(encontrado.group(1)), int(encontrado.group(2))


def _linea(fila: LineaLiquidacion, *, con_detalle: bool = True) -> dict:
    datos = {
        "id": fila.pk,
        "nombre": fila.nombre,
        "tiene_ficha": fila.personal_id is not None,
        "comisiones_ventas": str(fila.comisiones_ventas),
        "bonos": str(fila.bonos),
        "comisiones_tecnico": str(fila.comisiones_tecnico),
        "arrastre_anterior": str(fila.arrastre_anterior),
        "total": str(fila.total),
        "a_pagar": str(fila.a_pagar),
        "arrastre_nuevo": str(fila.arrastre_nuevo),
        "estado": fila.estado,
        "estado_texto": fila.get_estado_display(),
        "enviada_en": fila.enviada_en.isoformat() if fila.enviada_en else None,
        "planilla_periodo": fila.planilla.periodo.isoformat() if fila.planilla_id else None,
        "pagada_nota": fila.pagada_nota,
    }
    if con_detalle:
        datos["detalle"] = fila.detalle
    return datos


def _resumen(liq: LiquidacionComision) -> dict:
    return {
        "id": liq.pk,
        "periodo": liq.periodo,
        "cerrada_en": liq.cerrada_en.isoformat(),
        "total_a_pagar": str(liq.total_a_pagar),
        "personas": liq.lineas.count(),
        "por_estado": cierre.totales_por_estado(liq),
    }


class CerrarEntrada(serializers.Serializer):
    mes = serializers.CharField(max_length=7)


class LiquidacionesView(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "post": LIQUIDAR}

    @extend_schema(tags=TAG)
    def get(self, request):
        org = _organizacion(request)
        filas = LiquidacionComision.objects.filter(organizacion_id=org).order_by("-periodo")[:60]
        return Response(
            {
                "por_cerrar": cierre.mes_por_cerrar(org),
                "results": [_resumen(f) for f in filas],
            }
        )

    @extend_schema(tags=TAG, request=CerrarEntrada)
    def post(self, request):
        entrada = CerrarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        año, mes = _periodo(entrada.validated_data["mes"])
        liq = cierre.cerrar_mes(_organizacion(request), año, mes, usuario_id=request.user.pk)
        return Response(_resumen(liq), status=201)


class LiquidacionView(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER

    @extend_schema(tags=TAG)
    def get(self, request, pk: int):
        liq = LiquidacionComision.objects.filter(
            pk=pk, organizacion_id=_organizacion(request)
        ).first()
        if liq is None:
            raise NotFound("No encontramos esa liquidación.")
        lineas = liq.lineas.select_related("planilla").order_by("nombre", "id")
        return Response({**_resumen(liq), "lineas": [_linea(fila) for fila in lineas]})


class _LineaBase(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = LIQUIDAR

    def _linea(self, request, pk: int) -> LineaLiquidacion:
        linea = LineaLiquidacion.objects.filter(
            pk=pk, organizacion_id=_organizacion(request)
        ).first()
        if linea is None:
            raise NotFound("No encontramos esa línea.")
        return linea


class PlanillaEntrada(serializers.Serializer):
    mes = serializers.CharField(max_length=7)


class LineaPlanillaView(_LineaBase):
    @extend_schema(tags=TAG, request=PlanillaEntrada)
    def post(self, request, pk: int):
        entrada = PlanillaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        año, mes = _periodo(entrada.validated_data["mes"])
        linea = self._linea(request, pk)
        hecha = a_planilla.llevar_a_planilla(
            linea.pk, date(año, mes, 1), usuario_id=request.user.pk
        )
        return Response(_linea(hecha))


class PagadaEntrada(serializers.Serializer):
    nota = serializers.CharField(max_length=200)


class LineaPagadaView(_LineaBase):
    @extend_schema(tags=TAG, request=PagadaEntrada)
    def post(self, request, pk: int):
        entrada = PagadaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        linea = self._linea(request, pk)
        hecha = a_planilla.marcar_pagada_aparte(
            linea.pk, entrada.validated_data["nota"], usuario_id=request.user.pk
        )
        return Response(_linea(hecha))


# --- «Mis comisiones» ----------------------------------------------------------------------------
class MisComisionesView(APIView):
    """Lo de la persona que entra: lo que lleva ganado, su avance, su ranking y sus liquidaciones.

    Solo ve lo SUYO. El ranking muestra cuánto vendió cada quien (para motivar), nunca lo que gana.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER_PROPIAS

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("mes", str, description="AAAA-MM (por defecto, el mes actual)"),
        ],
    )
    def get(self, request):
        org, usuario = _organizacion(request), request.user
        hoy = timezone.localdate()
        año, mes = _periodo(request.query_params.get("mes") or hoy.strftime("%Y-%m"))
        inicio, fin = avance.rango_del_mes(año, mes)
        personal = getattr(usuario, "trabajador", None)

        ventas = (
            MovimientoComision.objects.filter(
                vendedor_id=usuario.pk, fecha__gte=inicio, fecha__lte=fin
            ).aggregate(t=Sum("monto"))["t"]
            or 0
        )
        servicios = 0
        if personal is not None:
            servicios = (
                OrdenServicio.objects.filter(
                    tecnico=personal,
                    estado=EstadoOrden.ENTREGADO,
                    comision_monto__isnull=False,
                    fecha_entrega__date__gte=inicio,
                    fecha_entrega__date__lte=fin,
                ).aggregate(t=Sum("comision_monto"))["t"]
                or 0
            )
        ranking = sorted(
            ((avance.ventas_netas_del_mes(org, v.pk, año, mes), v) for v in _vendedores(org)),
            key=lambda x: (-x[0], _nombre(x[1])),
        )
        ranking = [(monto, v) for monto, v in ranking if monto > 0]
        posicion = next((i + 1 for i, (_, v) in enumerate(ranking) if v.pk == usuario.pk), None)
        mias = Q(vendedor_id=usuario.pk)
        if personal is not None:
            mias |= Q(personal=personal)
        propias = LineaLiquidacion.objects.filter(organizacion_id=org).filter(mias)
        return Response(
            {
                "periodo": avance.periodo_de(año, mes),
                "ganado_hasta_hoy": {
                    "ventas": str(ventas),
                    "servicios": str(servicios),
                    "nota": (
                        "Provisional: los bonos y el ajuste de la escala se fijan al cerrar el mes."
                    ),
                },
                "avance": avance.avance(org, usuario.pk, año, mes),
                "ranking": {
                    "posicion": posicion,
                    "de": len(ranking),
                    "top": [
                        {"nombre": _nombre(v), "ventas": str(monto), "soy_yo": v.pk == usuario.pk}
                        for monto, v in ranking[:10]
                    ],
                },
                "liquidaciones": [
                    {"periodo": fila.liquidacion.periodo, **_linea(fila)}
                    for fila in propias.select_related("liquidacion", "planilla").order_by(
                        "-liquidacion__periodo"
                    )[:24]
                ],
            }
        )
