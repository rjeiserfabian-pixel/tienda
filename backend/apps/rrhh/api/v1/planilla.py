"""API de la planilla mensual de una empresa.

* ``RRHH.PLANILLA.VER``: ver las planillas y el detalle de cada trabajador (incluye sueldos).
* ``RRHH.PLANILLA.CALCULAR``: preparar, recalcular, ajustar a mano, diferir cuotas y descartar.
* ``RRHH.PLANILLA.CERRAR``: cerrar la planilla (fija los montos y bloquea el mes).
* ``RRHH.PLANILLA.REABRIR``: reabrir una planilla cerrada, con motivo.
"""

import json
from decimal import Decimal
from urllib.parse import quote

from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro, MedioPago
from apps.organizacion.models import Empresa, Estado
from apps.rrhh import pagos as servicio_pagos
from apps.rrhh import planilla as servicio
from apps.rrhh.api.v1.trabajadores import _entero, _PorEmpresa
from apps.rrhh.models import (
    EstadoPago,
    EstadoPlanilla,
    PagoPlanilla,
    Planilla,
    PlanillaTrabajador,
)
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

TAG = ["rrhh"]
VER = "RRHH.PLANILLA.VER"
CALCULAR = "RRHH.PLANILLA.CALCULAR"
CERRAR = "RRHH.PLANILLA.CERRAR"
REABRIR = "RRHH.PLANILLA.REABRIR"
PAGAR = "RRHH.PLANILLA.PAGAR"
ARCHIVO_BANCO = "RRHH.PLANILLA.ARCHIVO_BANCO"
SUELDOS_VER = "RRHH.SUELDOS.VER"


class PlanillaNuevaEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    anio = serializers.IntegerField(min_value=2000, max_value=2100)
    mes = serializers.IntegerField(min_value=1, max_value=12)


class CierreEntrada(serializers.Serializer):
    total_neto = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )


class ReaperturaEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


class AjusteEntrada(serializers.Serializer):
    detalle = serializers.IntegerField(min_value=1)
    concepto = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    explicacion = serializers.CharField(max_length=200, required=False, allow_blank=True)


class PagoEntrada(serializers.Serializer):
    detalles = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=200
    )
    fecha = serializers.DateField()
    cuenta = serializers.IntegerField(min_value=1)
    medio_pago = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)


class AnulacionPagoEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


class DiferirEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)


def _cabecera(planilla: Planilla) -> dict:
    return {
        "id": planilla.pk,
        "empresa": planilla.empresa_id,
        "periodo": planilla.periodo,
        "estado": planilla.estado,
        "estado_nombre": planilla.get_estado_display(),
        "num_trabajadores": planilla.num_trabajadores,
        "total_ingresos": str(planilla.total_ingresos),
        "total_descuentos": str(planilla.total_descuentos),
        "total_neto": str(planilla.total_neto),
        "total_aportes": str(planilla.total_aportes),
        "num_errores": planilla.num_errores,
        "num_avisos": planilla.num_avisos,
        "calculada_en": planilla.calculada_en,
        "cerrada_en": planilla.cerrada_en,
        "reabierta_en": planilla.reabierta_en,
        "motivo_reapertura": planilla.motivo_reapertura,
        "puede_cerrar": (
            planilla.estado == EstadoPlanilla.BORRADOR
            and planilla.num_errores == 0
            and planilla.num_trabajadores > 0
        ),
    }


def _fila(detalle: PlanillaTrabajador, pago: PagoPlanilla | None = None) -> dict:
    return {
        "id": detalle.pk,
        "pago": None
        if pago is None
        else {"id": pago.pk, "fecha": pago.fecha, "referencia": pago.referencia},
        "personal": detalle.personal_id,
        "nombre_completo": detalle.personal.nombre_completo,
        "numero_documento": detalle.personal.numero_documento,
        "cargo": detalle.cargo,
        "regimen_nombre": detalle.regimen_nombre,
        "sueldo_mensual": str(detalle.sueldo_mensual),
        "dias_laborados": detalle.dias_laborados,
        "dias_falta": detalle.dias_falta,
        "total_ingresos": str(detalle.total_ingresos),
        "total_descuentos": str(detalle.total_descuentos),
        "neto": str(detalle.neto),
        "aporte_empleador": str(detalle.aporte_empleador),
        "num_errores": sum(1 for a in detalle.avisos if a["nivel"] == servicio.ERROR),
        "num_avisos": sum(1 for a in detalle.avisos if a["nivel"] == servicio.AVISO),
    }


def _trabajador(detalle: PlanillaTrabajador, *, abierta: bool) -> dict:
    return {
        **_fila(detalle),
        "sistema_pension": detalle.sistema_pension,
        "afp": detalle.afp,
        "tipo_comision": detalle.tipo_comision,
        "metodo_pago": detalle.metodo_pago,
        "dias_contrato": detalle.dias_contrato,
        "dias_descanso_medico": detalle.dias_descanso_medico,
        "dias_vacaciones": detalle.dias_vacaciones,
        "horas_trabajadas": str(detalle.horas_trabajadas),
        "horas_extra": str(detalle.horas_extra),
        "base_pension": str(detalle.base_pension),
        "base_essalud": str(detalle.base_essalud),
        "avisos": detalle.avisos,
        "conceptos": [
            {
                "id": c.pk,
                "codigo": c.codigo,
                "nombre": c.nombre,
                "tipo": c.tipo,
                "monto": str(c.monto),
                "explicacion": c.explicacion,
                "manual": c.manual,
                # Solo las cuotas de adelantos se pasan al mes siguiente (y en revisión).
                "se_puede_diferir": abierta and c.cuota_id is not None,
                "se_puede_quitar": abierta and c.manual,
            }
            for c in detalle.conceptos.all()
        ],
    }


class PlanillaViewSet(
    _PorEmpresa,
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Planillas mensuales de una empresa (``?empresa=ID``). Filtros: ``anio``, ``estado``."""

    modelo = Planilla
    _modelo_de_pk = Planilla
    campo_propio = None
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "delete", "head", "options"]
    lookup_value_regex = r"\d+"
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "trabajador": VER,
        "boleta": VER,
        "opciones_pago": PAGAR,
        "pagar": PAGAR,
        "anular_pago": PAGAR,
        "archivo_banco": ARCHIVO_BANCO,
        "opciones": CALCULAR,
        "create": CALCULAR,
        "recalcular": CALCULAR,
        "ajustes": CALCULAR,
        "quitar_ajuste": CALCULAR,
        "diferir": CALCULAR,
        "destroy": CALCULAR,
        "cerrar": CERRAR,
        "reabrir": REABRIR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            return super().empresas_de_la_operacion(request)
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("empresa")
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (anio := _entero(params, "anio")) is not None:
            queryset = queryset.filter(periodo__year=anio)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("-periodo")

    # -- lectura -----------------------------------------------------------------------
    def _detalle(self, planilla: Planilla) -> dict:
        filas = (
            PlanillaTrabajador.objects.filter(planilla=planilla)
            .select_related("personal")
            .order_by("personal__apellidos", "personal__nombres", "id")
        )
        pagos = {
            p.detalle_id: p
            for p in PagoPlanilla.objects.filter(planilla=planilla, estado=EstadoPago.PAGADO)
        }
        return {
            **_cabecera(planilla),
            "avisos": planilla.avisos,
            "num_pagados": len(pagos),
            "total_pagado": str(sum((p.monto for p in pagos.values()), Decimal("0"))),
            "trabajadores": [_fila(d, pagos.get(d.pk)) for d in filas],
        }

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("anio", int),
            OpenApiParameter("estado", str),
        ],
        responses={200: dict},
    )
    def list(self, request, *args, **kwargs):
        pagina = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response([_cabecera(p) for p in pagina])

    @extend_schema(tags=TAG, responses={200: dict})
    def retrieve(self, request, *args, **kwargs):
        return Response(self._detalle(self.get_object()))

    @extend_schema(tags=TAG, responses={200: dict})
    @action(
        detail=True,
        methods=["get"],
        url_path=r"trabajadores/(?P<detalle_id>\d+)",
        url_name="trabajador",
    )
    def trabajador(self, request, pk=None, detalle_id=None):
        """Los renglones de un trabajador en esta planilla y lo que hay que revisar de él."""
        planilla = self.get_object()
        detalle = (
            PlanillaTrabajador.objects.filter(planilla=planilla, pk=detalle_id)
            .select_related("personal")
            .prefetch_related("conceptos")
            .first()
        )
        if detalle is None:
            raise Http404
        return Response(_trabajador(detalle, abierta=planilla.estado == EstadoPlanilla.BORRADOR))

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    @action(detail=False, methods=["get"])
    def opciones(self, request):
        """Los conceptos que se pueden agregar a mano a un trabajador (bonos, otros descuentos)."""
        empresa = Empresa.objects.filter(
            pk=empresa_declarada(request, self), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        return Response(
            {
                "conceptos": [
                    {"id": c.pk, "codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo}
                    for c in servicio.conceptos_para_ajuste(empresa.organizacion_id)
                ]
            }
        )

    # -- escritura ---------------------------------------------------------------------
    def _respuesta(self, planilla: Planilla) -> Response:
        return Response(self._detalle(self.get_queryset().get(pk=planilla.pk)))

    @extend_schema(
        tags=TAG,
        request=PlanillaNuevaEntrada,
        responses={201: dict},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no repite la operación.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        entrada = PlanillaNuevaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            planilla = servicio.crear_planilla(empresa=empresa, anio=v["anio"], mes=v["mes"])
            nueva = self.get_queryset().get(pk=planilla.pk)
            return 201, json.loads(json.dumps(self._detalle(nueva), default=str))

        codigo, contenido, repetida = ejecutar_idempotente(
            clave=clave,
            metodo=request.method,
            ruta=request.path,
            cuerpo=cuerpo,
            operacion=operacion,
        )
        respuesta = Response(contenido, status=codigo)
        if repetida:
            respuesta["Idempotency-Replayed"] = "true"
        return respuesta

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=True, methods=["post"])
    def recalcular(self, request, pk=None):
        planilla = self.get_object()
        servicio.recalcular(planilla)
        return self._respuesta(planilla)

    @extend_schema(tags=TAG, request=CierreEntrada, responses={200: dict})
    @action(detail=True, methods=["post"])
    def cerrar(self, request, pk=None):
        planilla = self.get_object()
        entrada = CierreEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        servicio.cerrar(planilla, neto_visto=entrada.validated_data.get("total_neto"))
        return self._respuesta(planilla)

    @extend_schema(tags=TAG, request=ReaperturaEntrada, responses={200: dict})
    @action(detail=True, methods=["post"])
    def reabrir(self, request, pk=None):
        planilla = self.get_object()
        entrada = ReaperturaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        servicio.reabrir(planilla, motivo=entrada.validated_data["motivo"])
        return self._respuesta(planilla)

    @extend_schema(tags=TAG, request=AjusteEntrada, responses={200: dict})
    @action(detail=True, methods=["post"])
    def ajustes(self, request, pk=None):
        planilla = self.get_object()
        entrada = AjusteEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        servicio.agregar_ajuste(
            planilla,
            detalle_id=v["detalle"],
            concepto_id=v["concepto"],
            monto=v["monto"],
            explicacion=v.get("explicacion", ""),
        )
        return self._respuesta(planilla)

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"ajustes/(?P<linea_id>\d+)",
        url_name="quitar-ajuste",
    )
    def quitar_ajuste(self, request, pk=None, linea_id=None):
        planilla = self.get_object()
        servicio.quitar_ajuste(planilla, linea_id=int(linea_id))
        return self._respuesta(planilla)

    @extend_schema(tags=TAG, request=DiferirEntrada, responses={200: dict})
    @action(detail=True, methods=["post"])
    def diferir(self, request, pk=None):
        planilla = self.get_object()
        entrada = DiferirEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        servicio.diferir_cuota(planilla, linea_id=entrada.validated_data["linea"])
        return self._respuesta(planilla)

    # -- pago, boleta y archivo del banco ---------------------------------------------------
    @extend_schema(tags=TAG, responses={200: dict})
    @action(
        detail=True,
        methods=["get"],
        url_path=r"trabajadores/(?P<detalle_id>\d+)/boleta",
        url_name="boleta",
    )
    def boleta(self, request, pk=None, detalle_id=None):
        """La boleta de pago de un trabajador, lista para imprimir."""
        planilla = self.get_object()
        detalle = (
            PlanillaTrabajador.objects.filter(planilla=planilla, pk=detalle_id)
            .select_related("personal")
            .prefetch_related("conceptos")
            .first()
        )
        if detalle is None:
            raise Http404
        return Response(servicio_pagos.boleta(planilla, detalle))

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=True, methods=["get"], url_path="opciones-pago")
    def opciones_pago(self, request, pk=None):
        """Cajas o cuentas en soles y métodos de pago para pagar los sueldos."""
        planilla = self.get_object()
        cuentas = CuentaFinanciera.objects.filter(
            empresa_id=planilla.empresa_id,
            estado=EstadoRegistro.ACTIVO,
            moneda=CuentaFinanciera.Moneda.PEN,
        ).order_by("nombre")
        medios = MedioPago.objects.filter(
            organizacion_id=planilla.empresa.organizacion_id, estado=EstadoRegistro.ACTIVO
        ).order_by("nombre")
        return Response(
            {
                "cuentas": [{"id": c.pk, "nombre": c.nombre, "tipo": c.tipo} for c in cuentas],
                "medios_pago": [{"id": m.pk, "nombre": m.nombre} for m in medios],
            }
        )

    @extend_schema(
        tags=TAG,
        request=PagoEntrada,
        responses={200: dict},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no paga dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"])
    def pagar(self, request, pk=None):
        planilla = self.get_object()
        entrada = PagoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        cuenta = CuentaFinanciera.objects.filter(
            pk=v["cuenta"], empresa_id=planilla.empresa_id
        ).first()
        if cuenta is None:
            raise ValidationError({"cuenta": "Elija una caja o cuenta de la lista."})
        medio = None
        if v.get("medio_pago"):
            medio = MedioPago.objects.filter(
                pk=v["medio_pago"], organizacion_id=planilla.empresa.organizacion_id
            ).first()
            if medio is None:
                raise ValidationError({"medio_pago": "Elija un método de pago de la lista."})
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            servicio_pagos.pagar(
                planilla,
                detalle_ids=v["detalles"],
                fecha=v["fecha"],
                cuenta=cuenta,
                medio_pago=medio,
                referencia=v.get("referencia", ""),
            )
            nueva = self.get_queryset().get(pk=planilla.pk)
            return 200, json.loads(json.dumps(self._detalle(nueva), default=str))

        codigo, contenido, repetida = ejecutar_idempotente(
            clave=clave,
            metodo=request.method,
            ruta=request.path,
            cuerpo=cuerpo,
            operacion=operacion,
        )
        respuesta = Response(contenido, status=codigo)
        if repetida:
            respuesta["Idempotency-Replayed"] = "true"
        return respuesta

    @extend_schema(tags=TAG, request=AnulacionPagoEntrada, responses={200: dict})
    @action(
        detail=True,
        methods=["post"],
        url_path=r"pagos/(?P<pago_id>\d+)/anular",
        url_name="anular-pago",
    )
    def anular_pago(self, request, pk=None, pago_id=None):
        planilla = self.get_object()
        pago = PagoPlanilla.objects.filter(pk=pago_id, planilla=planilla).first()
        if pago is None:
            raise Http404
        entrada = AnulacionPagoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        servicio_pagos.anular_pago(pago, motivo=entrada.validated_data["motivo"])
        return self._respuesta(planilla)

    @extend_schema(tags=TAG, responses={(200, "text/csv"): bytes})
    @action(detail=True, methods=["get"], url_path="archivo-banco", url_name="archivo-banco")
    def archivo_banco(self, request, pk=None):
        """El archivo de transferencias por hacer. Lleva cuentas: exige también ver sueldos."""
        planilla = self.get_object()
        motor.exigir_permiso(request.user, SUELDOS_VER, planilla.empresa_id)
        contenido, omitidos = servicio_pagos.archivo_banco(planilla)
        respuesta = HttpResponse(contenido, content_type="text/csv; charset=utf-8")
        respuesta["Content-Disposition"] = (
            f'attachment; filename="transferencias-{planilla.periodo:%Y-%m}.csv"'
        )
        respuesta["X-Omitidos"] = quote("; ".join(omitidos))
        return respuesta

    @extend_schema(tags=TAG, responses={204: None})
    def destroy(self, request, *args, **kwargs):
        servicio.descartar(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
