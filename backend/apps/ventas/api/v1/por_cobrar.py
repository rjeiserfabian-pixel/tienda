"""Ventas por cobrar: lo que deben los clientes, abonos y su anulación.

Cada empresa ve y cobra lo suyo: todo se pide con ``?empresa=ID`` (la que emitió los comprobantes).
"""

import json
from decimal import Decimal

from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import MostradorThrottle
from apps.mantenimiento.models import Cliente, MedioPago
from apps.seguridad.mixins import filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.ventas import cartera, cuentas_por_cobrar, servicios
from apps.ventas.models import AbonoVenta, AplicacionAbono, ComprobanteVenta, ReciboCobranza

from .serializers import AbonoEntrada, AnulacionVentaEntrada, ComprobanteVentaSerializer
from .views import (
    ANULAR,
    COBRAR,
    TAG,
    VER,
    _empresa_activa,
    _fecha,
    _nombre_usuario,
    _situacion,
)


def _dinero(valor) -> str:
    return f"{valor:.2f}"


def _comprobantes_visibles(request, empresa_id: int):
    """Los comprobantes a crédito vigentes de la empresa que la persona puede ver."""
    return filtrar_por_alcance(cartera.comprobantes_a_credito(empresa_id), request.user, VER)


def _fila_json(f: dict, hoy, series_recibo: list | None = None) -> dict:
    """Un comprobante con deuda y sus cuotas, tal como lo muestran las pantallas de cobranza."""
    c = f["comprobante"]
    return {
        "id": c.pk,
        "numero_completo": c.numero_completo,
        "tipo_nombre": c.tipo_comprobante.nombre,
        "fecha": c.fecha.isoformat(),
        "venta": c.venta_id,
        "venta_numero": c.venta.numero,
        "cliente": c.venta.cliente_id,
        "cliente_nombre": c.venta.cliente_nombre,
        "cliente_documento": c.venta.cliente_documento,
        "moneda": c.venta.moneda,
        "total": _dinero(c.total),
        "saldo": _dinero(f["saldo"]),
        "vencido": _dinero(f["vencido"]),
        "proximo_vencimiento": f["proximo"].isoformat(),
        "dias_atraso": f["dias_atraso"],
        "series_recibo": series_recibo or [],
        "cuotas": [
            {
                "id": q.pk,
                "numero": q.numero,
                "fecha_vencimiento": q.fecha_vencimiento.isoformat(),
                "monto": _dinero(q.monto),
                "pagado": _dinero(q.pagado),
                "saldo": _dinero(q.saldo),
                "vencida": q.pagado < q.monto and q.fecha_vencimiento < hoy,
            }
            for q in f["cuotas"]
        ],
    }


class _PorCobrarBase(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]


class ResumenView(_PorCobrarBase):
    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        """Totales de lo que se debe, por moneda: todo, lo vencido y lo que vence en 7 días."""
        empresa = _empresa_activa(empresa_declarada(request, self))
        filas = cartera.resumen(
            _comprobantes_visibles(request, empresa.pk), hoy=timezone.localdate()
        )
        return Response(
            [
                {
                    **f,
                    "saldo": _dinero(f["saldo"]),
                    "vencido": _dinero(f["vencido"]),
                    "por_vencer_7_dias": _dinero(f["por_vencer_7_dias"]),
                }
                for f in filas
            ]
        )


class ClientesView(_PorCobrarBase):
    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        """Lo que debe cada cliente, sumado por moneda (``q``, ``vencimiento``, ``vence_hasta``)."""
        empresa = _empresa_activa(empresa_declarada(request, self))
        params = request.query_params
        filas = cartera.deudas_por_cliente(
            _comprobantes_visibles(request, empresa.pk),
            hoy=timezone.localdate(),
            q=(params.get("q") or "").strip(),
            vencimiento=params.get("vencimiento", ""),
            vence_hasta=_fecha(params, "vence_hasta"),
        )
        paginador = PaginaEstandar()
        pagina = paginador.paginate_queryset(filas, request, view=self)
        return paginador.get_paginated_response(
            [
                {
                    **f,
                    "proximo_vencimiento": f["proximo_vencimiento"].isoformat(),
                    "montos": [
                        {
                            **m,
                            "saldo": _dinero(m["saldo"]),
                            "vencido": _dinero(m["vencido"]),
                            "por_vencer_7_dias": _dinero(m["por_vencer_7_dias"]),
                        }
                        for m in f["montos"]
                    ],
                }
                for f in pagina
            ]
        )


class ComprobantesView(_PorCobrarBase):
    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        """Los comprobantes a crédito con deuda y sus cuotas (q, vencimiento, vence_hasta)."""
        empresa = _empresa_activa(empresa_declarada(request, self))
        params = request.query_params
        hoy = timezone.localdate()
        filas = cartera.comprobantes_con_deuda(
            _comprobantes_visibles(request, empresa.pk),
            hoy=hoy,
            q=(params.get("q") or "").strip(),
            vencimiento=params.get("vencimiento", ""),
            vence_hasta=_fecha(params, "vence_hasta"),
        )
        paginador = PaginaEstandar()
        pagina = paginador.paginate_queryset(filas, request, view=self)
        series = cuentas_por_cobrar.series_de_recibo(empresa.pk)
        return paginador.get_paginated_response([_fila_json(f, hoy, series) for f in pagina])


class ReciboView(_PorCobrarBase):
    """Todo lo que lleva el recibo de un cobro de cuotas, listo para imprimir."""

    def empresas_de_la_operacion(self, request):
        empresa_id = (
            ReciboCobranza.objects.sin_ambito()
            .filter(pk=self.kwargs["recibo_id"])
            .values_list("empresa_id", flat=True)
            .first()
        )
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, recibo_id: int):
        recibo = (
            filtrar_por_alcance(
                ReciboCobranza.objects.select_related(
                    "empresa", "comprobante__venta__sucursal", "comprobante__tipo_comprobante"
                ),
                request.user,
                VER,
            )
            .filter(pk=recibo_id)
            .first()
        )
        if recibo is None:
            raise Http404
        abonos = list(recibo.abonos.select_related("medio_pago").order_by("id"))
        vigentes = [a for a in abonos if not a.anulado]
        comprobante, venta, empresa = recibo.comprobante, recibo.comprobante.venta, recibo.empresa
        # Lo que había cobrado cada cuota hasta este recibo (los cobros posteriores no cuentan).
        hasta = max((a.pk for a in abonos), default=0)
        aplicado_aqui: dict[int, object] = {}
        for ap in AplicacionAbono.objects.filter(abono__in=vigentes).select_related("cuota"):
            aplicado_aqui[ap.cuota_id] = aplicado_aqui.get(ap.cuota_id, 0) + ap.monto
        cuotas = []
        saldo_total = 0
        for cuota in comprobante.cuotas.order_by("numero"):
            previo = sum(
                (
                    ap.monto
                    for ap in AplicacionAbono.objects.filter(
                        cuota=cuota, abono__anulado=False, abono__pk__lte=hasta
                    )
                ),
                0,
            )
            saldo = cuota.monto - previo
            saldo_total += saldo
            if cuota.pk in aplicado_aqui:
                cuotas.append(
                    {
                        "numero": cuota.numero,
                        "fecha_vencimiento": cuota.fecha_vencimiento.isoformat(),
                        "monto": _dinero(cuota.monto),
                        "aplicado": _dinero(aplicado_aqui[cuota.pk]),
                        "saldo": _dinero(saldo),
                        "pagada": saldo <= 0,
                    }
                )
        # El saldo que queda del crédito después de cada cuota de este recibo.
        restante = saldo_total + sum(
            (aplicado_aqui[c.pk] for c in comprobante.cuotas.all() if c.pk in aplicado_aqui), 0
        )
        for fila in cuotas:
            restante -= Decimal(fila["aplicado"])
            fila["saldo_credito"] = _dinero(restante)
        sucursal = venta.sucursal
        return Response(
            {
                "id": recibo.pk,
                "numero_completo": recibo.numero_completo,
                "fecha": recibo.fecha.isoformat(),
                "hora": recibo.creado_en.astimezone().strftime("%H:%M"),
                "anulado": bool(abonos) and not vigentes,
                "cajero": recibo.cajero_nombre,
                "emisor": {
                    "empresa": empresa.pk,
                    "nombre": empresa.nombre_comercial or empresa.razon_social,
                    "razon_social": empresa.razon_social,
                    "ruc": empresa.ruc,
                    "local": (sucursal.direccion if sucursal and sucursal.direccion else "")
                    or empresa.direccion_fiscal,
                    "telefono": empresa.telefono,
                    "sitio_web": empresa.sitio_web,
                    "tienda_web": empresa.tienda_web,
                    "tiene_logo": bool(empresa.logo),
                },
                "cliente": {
                    "nombre": venta.cliente_nombre,
                    "tipo_documento": venta.cliente_tipo_documento,
                    "documento": venta.cliente_documento,
                },
                "moneda": venta.moneda,
                "comprobante": {
                    "numero_completo": comprobante.numero_completo,
                    "tipo_nombre": comprobante.tipo_comprobante.nombre,
                    "total": _dinero(comprobante.total),
                    "fecha": comprobante.fecha.isoformat(),
                },
                "pagos": [
                    {
                        "medio": a.medio_pago.nombre,
                        "monto": _dinero(a.monto),
                        "referencia": a.referencia,
                        "anulado": a.anulado,
                    }
                    for a in abonos
                ],
                "total": _dinero(sum((a.monto for a in vigentes), 0)),
                "cuotas": cuotas,
                "saldo_credito": _dinero(saldo_total),
            }
        )


class DeudaDeClienteView(_PorCobrarBase):
    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request, cliente_id: int):
        """Los comprobantes que debe un cliente en esta empresa, con sus cuotas."""
        empresa = _empresa_activa(empresa_declarada(request, self))
        hoy = timezone.localdate()
        cliente = Cliente.objects.filter(pk=cliente_id).first()
        if cliente is None:
            raise Http404
        filas = cartera.comprobantes_del_cliente(
            _comprobantes_visibles(request, empresa.pk), cliente.pk, hoy=hoy
        )
        series = cuentas_por_cobrar.series_de_recibo(empresa.pk)
        return Response(
            {
                "cliente": {
                    "id": cliente.pk,
                    "nombre": cliente.nombre,
                    "tipo_documento": cliente.tipo_documento,
                    "numero_documento": cliente.numero_documento,
                    "telefono": cliente.telefono,
                    "credito": _situacion(cliente),
                },
                "comprobantes": [_fila_json(f, hoy, series) for f in filas],
            }
        )


class CreditoDeClienteView(_PorCobrarBase):
    permiso_requerido = "VENTAS.VENDER"

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request, cliente_id: int):
        """Límite de crédito, deuda en todas las empresas y lo que todavía se le puede vender."""
        _empresa_activa(empresa_declarada(request, self))
        cliente = Cliente.objects.filter(pk=cliente_id).first()
        if cliente is None:
            raise Http404
        respuesta = Response(_situacion(cliente))
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class AbonarView(APIView):
    """Cobra una parte (o todo) de lo que debe un comprobante vendido a crédito."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = COBRAR
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        empresa_id = (
            ComprobanteVenta.objects.filter(pk=self.kwargs["comprobante_id"])
            .values_list("empresa_id", flat=True)
            .first()
        )
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    @extend_schema(
        tags=TAG,
        request=AbonoEntrada,
        responses={201: ComprobanteVentaSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no cobra dos veces.",
            )
        ],
    )
    def post(self, request, comprobante_id: int):
        comprobante = (
            filtrar_por_alcance(
                ComprobanteVenta.objects.select_related("venta", "empresa"), request.user, COBRAR
            )
            .filter(pk=comprobante_id)
            .first()
        )
        if comprobante is None:
            raise Http404
        datos = AbonoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        medios = {
            m.pk: m
            for m in MedioPago.objects.filter(
                pk__in={a["medio_pago"] for a in v["abonos"]},
                organizacion_id=comprobante.empresa.organizacion_id,
            )
        }
        abonos = []
        for a in v["abonos"]:
            if a["medio_pago"] not in medios:
                raise ValidationError({"abonos": "Hay métodos de pago que no existen."})
            abonos.append(
                servicios.CobroEntrada(
                    medio_pago=medios[a["medio_pago"]],
                    monto=a["monto"],
                    referencia=a.get("referencia", ""),
                    recibido=a.get("recibido"),
                )
            )
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            creados = cuentas_por_cobrar.registrar_abonos(
                comprobante,
                abonos=abonos,
                cuota_ids=v.get("cuotas"),
                usuario_nombre=_nombre_usuario(request.user),
                serie_recibo=v.get("serie_recibo"),
            )
            return 201, {**_comprobante_json(comprobante.pk), "recibo": creados[0].recibo_id}

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


def _comprobante_json(pk: int) -> dict:
    from django.db.models import Prefetch

    from apps.ventas.models import LineaVenta

    comprobante = (
        ComprobanteVenta.objects.select_related("empresa", "tipo_comprobante", "venta")
        .prefetch_related(
            Prefetch(
                "lineas",
                queryset=LineaVenta.objects.select_related("producto__unidad", "afectacion"),
            ),
            "cobros__medio_pago",
            "cobros__cuenta",
            "cuotas",
            Prefetch(
                "abonos",
                queryset=AbonoVenta.objects.select_related("medio_pago", "cuenta")
                .prefetch_related("aplicaciones__cuota")
                .order_by("id"),
            ),
        )
        .get(pk=pk)
    )
    return json.loads(json.dumps(ComprobanteVentaSerializer(comprobante).data, default=str))


class AnularAbonoView(APIView):
    """Anula un abono: el dinero sale de la caja y las cuotas recuperan su deuda."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = ANULAR
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        empresa_id = (
            AbonoVenta.objects.filter(pk=self.kwargs["abono_id"])
            .values_list("empresa_id", flat=True)
            .first()
        )
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    @extend_schema(
        tags=TAG, request=AnulacionVentaEntrada, responses={200: ComprobanteVentaSerializer}
    )
    def post(self, request, abono_id: int):
        abono = AbonoVenta.objects.filter(pk=abono_id).first()
        if abono is None:
            raise Http404
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        cuentas_por_cobrar.anular_abono(abono, motivo=datos.validated_data["motivo"])
        return Response(_comprobante_json(abono.comprobante_id))
