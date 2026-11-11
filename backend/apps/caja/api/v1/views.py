import json
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.caja import bancarizacion, mostrador, servicios, transferencias
from apps.caja.models import MovimientoCaja, Origen, SesionCaja, Transferencia
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import ConceptoCaja, CuentaFinanciera, MedioPago
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import (
    AnulacionEntrada,
    MovimientoEntrada,
    MovimientoSerializer,
    TransferenciaEntrada,
    TransferenciaSerializer,
)

TAG = ["caja"]
VER = "CAJA.MOVIMIENTOS.VER"
CREAR = "CAJA.MOVIMIENTOS.CREAR"
ANULAR = "CAJA.MOVIMIENTOS.ANULAR"
TRANSFERIR = "CAJA.TRANSFERIR"
TRASLADAR_ENTRE_EMPRESAS = "CAJA.TRASLADAR_ENTRE_EMPRESAS"
_DINERO = DecimalField(max_digits=16, decimal_places=2)


def _entero(params, nombre: str) -> int | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    if not str(valor).isdigit():
        raise ValidationError({nombre: "Debe ser un número entero."})
    return int(valor)


def _fecha(params, nombre: str) -> date | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({nombre: "Use el formato AAAA-MM-DD."}) from None


class MovimientoCajaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Movimientos de caja y bancos de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``cuenta``, ``tipo``, ``concepto``, ``estado``, ``origen`` (``manual`` o
    ``automatico``), ``sesion`` (id, o ``sin``), ``desde``, ``hasta`` y ``q`` (glosa, número de
    operación, N° interno o concepto). Con ``cuenta`` cada fila trae el saldo que dejó
    (``saldo_despues``).
    """

    modelo = MovimientoCaja
    serializer_class = MovimientoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {"list": VER, "retrieve": VER, "create": CREAR, "anular": ANULAR}

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                MovimientoCaja.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = filtrar_por_alcance(
            MovimientoCaja.objects.select_related(
                "cuenta", "concepto", "sesion", "medio_pago"
            ).prefetch_related("adjuntos"),
            self.request.user,
            codigo,
        )
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa)
        if (cuenta := _entero(params, "cuenta")) is not None:
            queryset = queryset.filter(cuenta_id=cuenta).annotate(
                neto_acumulado=Subquery(self._acumulado(), output_field=_DINERO)
            )
        if (medio := _entero(params, "medio")) is not None:
            queryset = queryset.filter(medio_pago_id=medio)
        if (sesion := _entero(params, "sesion")) is not None:
            queryset = queryset.filter(sesion_id=sesion)
        elif params.get("sesion") == "sin":
            queryset = queryset.filter(sesion__isnull=True)
        if tipo_cuenta := params.get("tipo_cuenta"):
            queryset = queryset.filter(cuenta__tipo=tipo_cuenta)
        if (concepto := _entero(params, "concepto")) is not None:
            queryset = queryset.filter(concepto_id=concepto)
        for campo in ("tipo", "estado"):
            if valor := params.get(campo):
                queryset = queryset.filter(**{campo: valor})
        if params.get("sin_bancarizar") == "1":
            umbral = Q()
            for moneda, monto in bancarizacion.UMBRALES.items():
                umbral |= Q(cuenta__moneda=moneda, monto__gte=monto)
            queryset = (
                queryset.filter(cuenta__tipo="CAJA", estado=MovimientoCaja.Estado.EMITIDO)
                .filter(umbral)
                .exclude(concepto__codigo__in=bancarizacion.CONCEPTOS_EXENTOS)
                .exclude(origen_tipo__in=bancarizacion.ORIGENES_EXENTOS)
            )
        origen = params.get("origen")
        if origen == "manual":
            queryset = queryset.filter(origen_tipo=Origen.MANUAL)
        elif origen == "automatico":
            queryset = queryset.exclude(origen_tipo=Origen.MANUAL)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        q = (params.get("q") or "").strip()
        if q:
            condicion = (
                Q(glosa__icontains=q)
                | Q(referencia__icontains=q)
                | Q(concepto__nombre__icontains=q)
            )
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha", "-id")

    @staticmethod
    def _acumulado():
        """Lo que sumaron los movimientos vigentes de la cuenta hasta cada fila (inclusive)."""
        anteriores = (
            MovimientoCaja.objects.filter(
                cuenta_id=OuterRef("cuenta_id"), estado=MovimientoCaja.Estado.EMITIDO
            )
            .filter(
                Q(fecha__lt=OuterRef("fecha")) | Q(fecha=OuterRef("fecha"), id__lte=OuterRef("id"))
            )
            .order_by()
            .values("cuenta_id")
        )
        return anteriores.annotate(neto=Sum(servicios._firmado())).values("neto")

    # -- registrar ----------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=MovimientoEntrada,
        responses={201: MovimientoSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no registra dos veces.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = MovimientoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        cuenta = CuentaFinanciera.objects.filter(pk=v["cuenta"], empresa=empresa).first()
        if cuenta is None:
            raise ValidationError({"cuenta": "Elija una caja o cuenta de la empresa."})
        medio = None
        if v.get("medio_pago"):
            medio = MedioPago.objects.filter(
                pk=v["medio_pago"], organizacion_id=empresa.organizacion_id
            ).first()
            if medio is None:
                raise ValidationError({"medio_pago": "Elija un método de pago de la lista."})
        concepto = ConceptoCaja.objects.filter(pk=v["concepto"]).first()
        if concepto is None:
            raise ValidationError({"concepto": "No existe ese concepto."})
        if concepto.automatico:
            raise ValidationError({"concepto": "Ese concepto lo usa el sistema por su cuenta."})
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            movimiento = servicios.registrar_movimiento(
                empresa=empresa,
                cuenta=cuenta,
                tipo=v["tipo"],
                monto=v["monto"],
                concepto=concepto,
                fecha=v.get("fecha"),
                glosa=v.get("glosa", ""),
                referencia=v.get("referencia", ""),
                medio_pago=medio,
            )
            datos_respuesta = MovimientoSerializer(
                MovimientoCaja.objects.select_related("cuenta", "concepto", "sesion").get(
                    pk=movimiento.pk
                )
            ).data
            return 201, json.loads(json.dumps(datos_respuesta, default=str))

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

    # -- anular -------------------------------------------------------------------
    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: MovimientoSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula un movimiento hecho a mano; deja de contar en el saldo y queda con su motivo."""
        movimiento = self.get_object()
        datos = AnulacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        with transaction.atomic():
            servicios.anular_movimiento(movimiento, motivo=datos.validated_data["motivo"])
        movimiento.refresh_from_db()
        return Response(MovimientoSerializer(movimiento).data)


def _resumen_sesion(sesion) -> dict | None:
    if sesion is None:
        return None
    return {
        "id": sesion.pk,
        "numero": sesion.numero,
        "responsable_id": sesion.responsable_id,
        "responsable_nombre": sesion.responsable_nombre,
        "abierta_en": sesion.abierta_en,
    }


class SaldosView(APIView):
    """Saldo de cada caja y cuenta de la empresa (``?empresa=ID``) y su total por moneda."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("empresa", int, required=True)],
        responses={200: dict},
    )
    def get(self, request):
        empresa = Empresa.objects.filter(
            pk=empresa_declarada(request, self), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        filas = servicios.saldos_de_la_empresa(empresa)
        abiertas = {
            s.cuenta_id: s
            for s in SesionCaja.objects.filter(empresa=empresa, estado=SesionCaja.Estado.ABIERTA)
        }

        def dinero(valor) -> str:
            return f"{valor:.2f}"

        # Solo las cajas de efectivo con tienda pueden compartir mostrador con otra empresa.
        hermanas = {
            f["cuenta"].pk: (
                mostrador.cajas_hermanas(f["cuenta"])
                if f["cuenta"].tipo == "CAJA" and f["cuenta"].sucursal_id
                else []
            )
            for f in filas
        }
        totales: dict[str, dict] = {}
        for f in filas:
            if f["cuenta"].estado != "ACTIVO":
                continue
            t = totales.setdefault(f["cuenta"].moneda, {"moneda": f["cuenta"].moneda, "saldo": 0})
            t["saldo"] += f["saldo"]
        respuesta = Response(
            {
                "cuentas": [
                    {
                        "cuenta": f["cuenta"].pk,
                        "nombre": f["cuenta"].nombre,
                        "tipo": f["cuenta"].tipo,
                        "tipo_nombre": f["cuenta"].get_tipo_display(),
                        "moneda": f["cuenta"].moneda,
                        "sucursal_nombre": f["cuenta"].sucursal.nombre
                        if f["cuenta"].sucursal
                        else "",
                        "estado": f["cuenta"].estado,
                        # Las otras empresas cuyas cajas comparten este mostrador (el mismo local).
                        "comparte_con": [h.empresa.razon_social for h in hermanas[f["cuenta"].pk]],
                        "saldo_inicial": dinero(f["cuenta"].saldo_inicial),
                        "fecha_saldo_inicial": f["cuenta"].fecha_saldo_inicial,
                        "ingresos": dinero(f["ingresos"]),
                        "egresos": dinero(f["egresos"]),
                        "saldo": dinero(f["saldo"]),
                        "movimientos": f["movimientos"],
                        "ultimo_movimiento": f["ultimo_movimiento"],
                        "rol_caja": f["cuenta"].rol_caja,
                        "fondo_inicial": dinero(f["cuenta"].fondo_inicial),
                        "exige_sesion": f["cuenta"].exige_sesion,
                        "saldo_minimo": (
                            dinero(f["cuenta"].saldo_minimo)
                            if f["cuenta"].saldo_minimo is not None
                            else None
                        ),
                        "sesion": _resumen_sesion(abiertas.get(f["cuenta"].pk)),
                    }
                    for f in filas
                ],
                "totales": [
                    {"moneda": m, "saldo": dinero(t["saldo"])} for m, t in sorted(totales.items())
                ],
                "umbral_bancarizacion": {m: dinero(v) for m, v in bancarizacion.UMBRALES.items()},
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class TransferenciaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Transferencias, depósitos y retiros (``?empresa=ID`` obligatorio en el listado).

    El listado trae las que salieron de la empresa y las que entraron a ella. Filtros: ``cuenta``
    (de origen o de destino), ``clase``, ``estado``, ``desde``, ``hasta`` y ``q``.
    """

    modelo = Transferencia
    serializer_class = TransferenciaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {"list": VER, "retrieve": VER, "create": TRANSFERIR, "anular": ANULAR}

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                Transferencia.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = Transferencia.objects.select_related(
            "cuenta_origen", "cuenta_destino", "empresa", "empresa_destino"
        )
        if self.action != "list":
            return filtrar_por_alcance(queryset, self.request.user, codigo)
        params = self.request.query_params
        empresa = _entero(params, "empresa")
        # Las que salieron de la empresa y las que le entraron desde otra (si se puede verlas).
        queryset = queryset.filter(Q(empresa_id=empresa) | Q(empresa_destino_id=empresa))
        if (cuenta := _entero(params, "cuenta")) is not None:
            queryset = queryset.filter(Q(cuenta_origen_id=cuenta) | Q(cuenta_destino_id=cuenta))
        for campo in ("clase", "estado"):
            if valor := params.get(campo):
                queryset = queryset.filter(**{campo: valor})
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        q = (params.get("q") or "").strip()
        if q:
            condicion = (
                Q(glosa__icontains=q)
                | Q(referencia__icontains=q)
                | Q(cuenta_origen__nombre__icontains=q)
                | Q(cuenta_destino__nombre__icontains=q)
            )
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha", "-id")

    @extend_schema(
        tags=TAG,
        request=TransferenciaEntrada,
        responses={201: TransferenciaSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no transfiere dos veces.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = TransferenciaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        origen = CuentaFinanciera.objects.filter(pk=v["cuenta_origen"], empresa=empresa).first()
        if origen is None:
            raise ValidationError({"cuenta_origen": "Elija una caja o cuenta de la empresa."})
        destino = (
            CuentaFinanciera.objects.select_related("empresa")
            .filter(pk=v["cuenta_destino"], empresa__organizacion_id=empresa.organizacion_id)
            .first()
        )
        if destino is None:
            raise ValidationError({"cuenta_destino": "No existe esa caja o cuenta."})
        if destino.empresa_id != empresa.pk:
            # Pasar dinero a otra empresa es delicado: pide su permiso y poder registrar allá.
            motor.exigir_permiso(request.user, TRASLADAR_ENTRE_EMPRESAS, empresa.pk)
            motor.exigir_permiso(request.user, CREAR, destino.empresa_id)
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            transferencia = transferencias.registrar_transferencia(
                empresa=empresa,
                cuenta_origen=origen,
                cuenta_destino=destino,
                monto=v["monto"],
                fecha=v.get("fecha"),
                tipo_cambio=v.get("tipo_cambio"),
                monto_destino=v.get("monto_destino"),
                comision=v.get("comision", Decimal("0")),
                itf=v.get("itf", Decimal("0")),
                glosa=v.get("glosa", ""),
                referencia=v.get("referencia", ""),
            )
            datos_respuesta = TransferenciaSerializer(
                Transferencia.objects.select_related(
                    "cuenta_origen", "cuenta_destino", "empresa", "empresa_destino"
                ).get(pk=transferencia.pk)
            ).data
            return 201, json.loads(json.dumps(datos_respuesta, default=str))

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

    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: TransferenciaSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula la transferencia con todos sus movimientos: el dinero vuelve a su cuenta."""
        transferencia = self.get_object()
        datos = AnulacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        transferencias.anular_transferencia(transferencia, motivo=datos.validated_data["motivo"])
        transferencia.refresh_from_db()
        return Response(TransferenciaSerializer(transferencia).data)
