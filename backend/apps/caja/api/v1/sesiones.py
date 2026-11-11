"""API de las sesiones de caja: abrir el turno, arquear, cerrar y reabrir."""

from decimal import Decimal

from django.db import transaction
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.caja import mostrador, servicios, sesiones
from apps.caja.models import ArqueoCaja, SesionCaja
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import CuentaFinanciera
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .views import TAG, _entero, _fecha

VER = "CAJA.SESIONES.VER"
ABRIR = "CAJA.SESIONES.ABRIR"
REABRIR = "CAJA.SESIONES.REABRIR"


class ArqueoSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = ArqueoCaja
        fields = [
            "id",
            "tipo",
            "tipo_nombre",
            "esperado",
            "contado",
            "diferencia",
            "conteo",
            "grupo",
            "observacion",
            "hecho_por_nombre",
            "creado_en",
        ]
        read_only_fields = fields


class SesionSerializer(serializers.ModelSerializer):
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    moneda = serializers.CharField(source="cuenta.moneda", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    esperado_actual = serializers.SerializerMethodField()
    arqueos = serializers.SerializerMethodField()
    mostrador = serializers.SerializerMethodField()

    class Meta:
        model = SesionCaja
        fields = [
            "id",
            "numero",
            "empresa",
            "cuenta",
            "cuenta_nombre",
            "moneda",
            "estado",
            "estado_nombre",
            "responsable_id",
            "responsable_nombre",
            "abierta_en",
            "saldo_apertura",
            "fondo_entregado",
            "cerrada_en",
            "cerrada_por_nombre",
            "esperado_cierre",
            "contado_cierre",
            "diferencia",
            "observacion",
            "reaperturas",
            "esperado_actual",
            "arqueos",
            "mostrador",
        ]
        read_only_fields = fields

    def get_esperado_actual(self, sesion):
        """Lo que el sistema espera que haya en la caja ahora (solo mientras está abierta)."""
        if sesion.estado != SesionCaja.Estado.ABIERTA:
            return None
        return f"{servicios.saldo_de(sesion.cuenta):.2f}"

    def get_mostrador(self, sesion):
        """Las cajas de otras empresas que comparten el cajón y se cuentan juntas."""
        if not self.context.get("con_arqueos") or sesion.estado != SesionCaja.Estado.ABIERTA:
            return None
        hermanas = mostrador.hermanas_de(sesion)
        if not hermanas:
            return None
        esperado_propio = servicios.saldo_de(sesion.cuenta)
        filas = [
            {
                "sesion": h.pk,
                "empresa": h.empresa_id,
                "empresa_nombre": h.empresa.nombre_comercial or h.empresa.razon_social,
                "cuenta_nombre": h.cuenta.nombre,
                "esperado": f"{servicios.saldo_de(h.cuenta):.2f}",
                "responsable_nombre": h.responsable_nombre,
            }
            for h in hermanas
        ]
        total = esperado_propio + sum((Decimal(f["esperado"]) for f in filas), Decimal("0"))
        return {"hermanas": filas, "esperado_total": f"{total:.2f}"}

    def get_arqueos(self, sesion):
        if not self.context.get("con_arqueos"):
            return None
        return ArqueoSerializer(sesion.arqueos.all(), many=True).data


class AbrirEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    cuenta = serializers.IntegerField(min_value=1)
    fondo = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=Decimal("0"), required=False
    )
    desde_cuenta = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    # Abrir también (sin fondo) las cajas de las otras empresas que comparten el mostrador.
    con_hermanas = serializers.BooleanField(required=False)


class ConteoEntrada(serializers.Serializer):
    conteo = serializers.DictField(child=serializers.IntegerField(min_value=0, max_value=10**6))
    # Contar el cajón compartido una sola vez para las cajas de todas las empresas que lo usan.
    mostrador = serializers.BooleanField(required=False)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    # Al cerrar: liquidar antes lo que las empresas se deben por ventas internas (si lo hay).
    liquidar_interna = serializers.BooleanField(required=False)


class ReabrirEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


class SesionCajaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Sesiones de caja de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``cuenta``, ``estado``, ``desde`` y ``hasta`` (por fecha de apertura). Solo la persona
    que abrió la sesión (o quien puede reabrir) la cuenta y la cierra.
    """

    modelo = SesionCaja
    serializer_class = SesionSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": ABRIR,
        "arquear": ABRIR,
        "cerrar": ABRIR,
        "reabrir": REABRIR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                SesionCaja.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["con_arqueos"] = self.action == "retrieve"
        return contexto

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = SesionCaja.objects.select_related("cuenta")
        if self.action != "list":
            return filtrar_por_alcance(queryset, self.request.user, codigo)
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (cuenta := _entero(params, "cuenta")) is not None:
            queryset = queryset.filter(cuenta_id=cuenta)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(abierta_en__date__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(abierta_en__date__lte=hasta)
        return queryset.order_by("-abierta_en", "-id")

    def _supervisor(self, sesion: SesionCaja) -> bool:
        return motor.tiene_permiso(self.request.user, REABRIR, sesion.empresa_id)

    def _empresas_del_mostrador(self, sesion: SesionCaja) -> list[int]:
        return [sesion.empresa_id, *(h.empresa_id for h in mostrador.hermanas_de(sesion))]

    def _exigir_en_hermanas(self, sesion: SesionCaja) -> None:
        """Contar el cajón compartido exige poder operar la caja en todas sus empresas."""
        motor.exigir_permiso_en_empresas(
            self.request.user, ABRIR, self._empresas_del_mostrador(sesion)
        )

    def _supervisor_de_todas(self, sesion: SesionCaja) -> bool:
        return all(
            motor.tiene_permiso(self.request.user, REABRIR, e)
            for e in self._empresas_del_mostrador(sesion)
        )

    @extend_schema(tags=TAG, request=AbrirEntrada, responses={201: SesionSerializer})
    def create(self, request, *args, **kwargs):
        datos = AbrirEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        cuentas = CuentaFinanciera.objects.filter(empresa=empresa)
        cuenta = cuentas.filter(pk=v["cuenta"]).first()
        if cuenta is None:
            raise ValidationError({"cuenta": "Elija una caja de la empresa."})
        desde = None
        if v.get("desde_cuenta"):
            desde = cuentas.filter(pk=v["desde_cuenta"]).first()
            if desde is None:
                raise ValidationError({"desde_cuenta": "Elija una caja de la empresa."})
        datos_de_apertura = {
            "fondo": v.get("fondo", Decimal("0")),
            "desde_cuenta": desde,
            "observacion": v.get("observacion", ""),
        }
        with transaction.atomic():
            if v.get("con_hermanas"):
                hermanas = mostrador.cajas_hermanas(cuenta)
                motor.exigir_permiso_en_empresas(
                    request.user, ABRIR, [h.empresa_id for h in hermanas]
                )
                sesion = mostrador.abrir_mostrador(
                    empresa=empresa, cuenta=cuenta, usuario=request.user, **datos_de_apertura
                )[0]
            else:
                sesion = sesiones.abrir_sesion(
                    empresa=empresa, cuenta=cuenta, usuario=request.user, **datos_de_apertura
                )
        return Response(SesionSerializer(sesion).data, status=201)

    @extend_schema(tags=TAG, request=ConteoEntrada, responses={200: ArqueoSerializer})
    @action(detail=True, methods=["post"], url_path="arquear")
    def arquear(self, request, pk=None):
        """Cuenta el efectivo sin cerrar la sesión."""
        sesion = self.get_object()
        datos = ConteoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        if datos.validated_data.get("mostrador"):
            self._exigir_en_hermanas(sesion)
            arqueos = mostrador.arquear_mostrador(
                sesion,
                conteo=datos.validated_data["conteo"],
                observacion=datos.validated_data.get("observacion", ""),
                usuario=request.user,
                supervisor=self._supervisor_de_todas(sesion),
            )
            return Response(ArqueoSerializer(arqueos[0]).data)
        arqueo = sesiones.arquear_sesion(
            sesion,
            conteo=datos.validated_data["conteo"],
            observacion=datos.validated_data.get("observacion", ""),
            usuario=request.user,
            supervisor=self._supervisor(sesion),
        )
        return Response(ArqueoSerializer(arqueo).data)

    def _liquidar_ventas_internas(self, sesion: SesionCaja, liquidar: bool) -> None:
        """Antes de contar: lo que las empresas se deben por ventas internas se liquida o se avisa.

        El efectivo de una venta interna entra a la caja de quien facturó aunque parte sea de la
        otra empresa. Liquidarlo antes del conteo deja a cada caja con lo que de verdad es suyo.
        """
        from apps.ventas import liquidacion_interna  # import tardío: Caja no depende de Ventas
        from apps.ventas.exceptions import LiquidacionInternaPendiente

        pendientes = liquidacion_interna.pendientes_del_cierre(sesion)
        if not pendientes:
            return
        puede = liquidar and all(
            motor.tiene_permiso(self.request.user, "VENTAS.LIQUIDAR_INTERNA", e)
            for p in pendientes
            for e in (p.pagadora.pk, p.receptora.pk)
        )
        if not puede:
            total = sum((p.monto for p in pendientes), Decimal("0"))
            raise LiquidacionInternaPendiente(
                f"Hay ventas internas por liquidar entre las empresas (S/ {total:,.2f}). "
                "Liquídalas antes de cerrar la caja"
                + (
                    "."
                    if liquidar
                    else ": quien tenga el permiso puede hacerlo en «Liquidación entre empresas»."
                ),
                detalle=[
                    {
                        "pagadora": p.pagadora.pk,
                        "receptora": p.receptora.pk,
                        "monto": f"{p.monto:.2f}",
                    }
                    for p in pendientes
                ],
            )
        for p in pendientes:
            liquidacion_interna.liquidar(pagadora=p.pagadora, receptora=p.receptora, local=p.local)

    @extend_schema(tags=TAG, request=ConteoEntrada, responses={200: SesionSerializer})
    @action(detail=True, methods=["post"], url_path="cerrar")
    def cerrar(self, request, pk=None):
        """Cuenta el efectivo y cierra; la diferencia queda asentada en el libro.

        Si las empresas se deben algo por ventas internas, se liquida primero (``liquidar_interna``)
        en la misma operación: si el cierre falla, la liquidación tampoco queda.
        """
        sesion = self.get_object()
        datos = ConteoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        with transaction.atomic():
            self._liquidar_ventas_internas(
                sesion, datos.validated_data.get("liquidar_interna", False)
            )
            if datos.validated_data.get("mostrador"):
                self._exigir_en_hermanas(sesion)
                cerradas = mostrador.cerrar_mostrador(
                    sesion,
                    conteo=datos.validated_data["conteo"],
                    observacion=datos.validated_data.get("observacion", ""),
                    usuario=request.user,
                    supervisor=self._supervisor_de_todas(sesion),
                )
                return Response(SesionSerializer(cerradas[0], context={"con_arqueos": True}).data)
            cerrada = sesiones.cerrar_sesion(
                sesion,
                conteo=datos.validated_data["conteo"],
                observacion=datos.validated_data.get("observacion", ""),
                usuario=request.user,
                supervisor=self._supervisor(sesion),
            )
            return Response(SesionSerializer(cerrada, context={"con_arqueos": True}).data)

    @extend_schema(tags=TAG, request=ReabrirEntrada, responses={200: SesionSerializer})
    @action(detail=True, methods=["post"], url_path="reabrir")
    def reabrir(self, request, pk=None):
        """Reabre la última sesión cerrada de la caja (permiso de supervisor)."""
        sesion = self.get_object()
        datos = ReabrirEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        abierta = sesiones.reabrir_sesion(
            sesion, motivo=datos.validated_data["motivo"], usuario=request.user
        )
        return Response(SesionSerializer(abierta, context={"con_arqueos": True}).data)
