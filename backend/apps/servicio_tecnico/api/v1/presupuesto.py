"""API del presupuesto de una orden: armarlo, aprobarlo, reservar repuestos y buscar qué cotizar."""

import json
from decimal import Decimal

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import EstadoRegistro, MedioPago, Producto
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.models import Usuario
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor
from apps.servicio_tecnico import adelantos, entrega, presupuesto, repuestos
from apps.servicio_tecnico.capacidades import capacidades_de
from apps.servicio_tecnico.models import (
    EstadoOrden,
    MedioAviso,
    OrdenServicio,
)
from apps.ventas import catalogo, precios
from apps.ventas.api.v1.serializers import CobroEntradaSerializer, VentaDetalleSerializer
from apps.ventas.api.v1.views import VentaViewSet
from apps.ventas.models import Venta
from apps.ventas.servicios import CobroEntrada

from .serializers import nombre_usuario

TAG = ["servicio-tecnico"]
PRESUPUESTAR = "SERVICIOS.PRESUPUESTAR"
OTRA_EMPRESA = "VENTAS.VENDER_STOCK_OTRA_EMPRESA"
VENDER = "VENTAS.VENDER"
BAJO_MINIMO = "VENTAS.VENDER_BAJO_MINIMO"


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class LineaPresupuestoEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    empresa = serializers.IntegerField(min_value=1, required=False)
    precio_unitario = serializers.DecimalField(
        max_digits=16,
        decimal_places=6,
        min_value=Decimal("0.000001"),
        required=False,
        allow_null=True,
    )


class PresupuestoEntrada(serializers.Serializer):
    lineas = LineaPresupuestoEntrada(many=True, max_length=presupuesto.MAXIMO_LINEAS)
    validez_dias = serializers.IntegerField(
        min_value=1, max_value=60, default=presupuesto.VALIDEZ_POR_DEFECTO
    )
    condiciones = serializers.CharField(max_length=300, required=False, allow_blank=True)


class EntregarEntrada(serializers.Serializer):
    """Cobra el presupuesto y entrega: tipo de comprobante y cobros, o entregar sin cobrar."""

    tipo_comprobante = serializers.CharField(max_length=2, required=False, allow_blank=True)
    cobros = CobroEntradaSerializer(many=True, required=False, max_length=10)
    serie_por_empresa = serializers.DictField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    sin_cobro = serializers.BooleanField(required=False, default=False)
    motivo = serializers.CharField(max_length=500, required=False, allow_blank=True)
    # Quién se lleva el equipo: el titular (basta marcarlo) u otra persona con su documento.
    recoge_es_titular = serializers.BooleanField(required=False, default=True)
    recoge_nombre = serializers.CharField(max_length=120, required=False, allow_blank=True)
    recoge_documento = serializers.CharField(max_length=20, required=False, allow_blank=True)


class AprobarEntrada(serializers.Serializer):
    medio = serializers.ChoiceField(choices=MedioAviso.choices)
    nota = serializers.CharField(max_length=500)


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
def presupuesto_de(orden: OrdenServicio, usuario) -> dict | None:
    """El presupuesto vigente tal como lo ve ``usuario`` (sin precios si no le corresponden)."""
    vigente = presupuesto.vigente_de(orden)
    if vigente is None:
        return None
    poder = capacidades_de(usuario, orden)
    p = vigente.proforma
    repuestos_por_linea = {
        r.linea_id: r for r in vigente.repuestos.select_related("producto").order_by("id")
    }
    lineas = []
    for ln in p.lineas.select_related("producto__unidad", "empresa").order_by("orden"):
        r = repuestos_por_linea.get(ln.pk)
        fila = {
            "id": ln.pk,
            "producto": ln.producto_id,
            "codigo": ln.producto.codigo,
            "descripcion": ln.descripcion,
            "cantidad": str(ln.cantidad),
            "unidad": ln.producto.unidad.abreviatura,
            "tipo": ln.producto.tipo,
            "empresa": ln.empresa_id,
            "empresa_nombre": ln.empresa.nombre_comercial or ln.empresa.razon_social,
            "repuesto": (
                {"id": r.pk, "estado": r.estado, "estado_nombre": r.get_estado_display()}
                if r
                else None
            ),
        }
        if poder.ve_importes:
            fila.update(
                precio_unitario=str(ln.precio_unitario),
                precio_lista=str(ln.precio_lista),
                total=str(ln.total),
            )
        lineas.append(fila)
    aprobador = ""
    if vigente.aprobado_por_id:
        quien = Usuario.objects.filter(pk=vigente.aprobado_por_id).first()
        aprobador = nombre_usuario(quien) if quien else ""
    pendientes = sum(1 for r in repuestos_por_linea.values() if r.estado == "PENDIENTE")
    return {
        "venta": _venta_de(vigente),
        "entregado_sin_cobro": vigente.entregado_sin_cobro,
        "por_empresa": _por_empresa(p) if poder.ve_importes else [],
        "id": vigente.pk,
        "version": vigente.version,
        "ve_importes": poder.ve_importes,
        "proforma": {
            "id": p.pk,
            "numero_completo": p.numero_completo,
            "fecha": p.fecha,
            "valida_hasta": p.valida_hasta,
            "moneda": p.moneda,
            "estado": p.estado,
        },
        "total": str(p.total) if poder.ve_importes else None,
        "lineas": lineas,
        "aprobado": vigente.aprobado,
        "aprobado_en": vigente.aprobado_en,
        "aprobado_por_nombre": aprobador,
        "aprobacion_medio_nombre": (
            MedioAviso(vigente.aprobacion_medio).label if vigente.aprobacion_medio else ""
        ),
        "aprobacion_nota": vigente.aprobacion_nota,
        "repuestos_pendientes": pendientes,
    }


def _venta_de(vigente) -> dict | None:
    if not vigente.venta_id:
        return None
    comprobantes = vigente.venta.comprobantes.select_related("empresa", "tipo_comprobante")
    return {
        "id": vigente.venta_id,
        "total": str(vigente.venta.total),
        "comprobantes": [
            {
                "numero_completo": c.numero_completo,
                "empresa_nombre": c.empresa.nombre_comercial or c.empresa.razon_social,
                "tipo_nombre": c.tipo_comprobante.nombre,
                "total": str(c.total),
            }
            for c in comprobantes.order_by("id")
        ],
    }


def _por_empresa(proforma) -> list[dict]:
    """Lo que cobraría cada empresa (un comprobante por cada una)."""
    sumas: dict[int, dict] = {}
    for ln in proforma.lineas.select_related("empresa"):
        fila = sumas.setdefault(
            ln.empresa_id,
            {
                "empresa": ln.empresa_id,
                "nombre": ln.empresa.nombre_comercial or ln.empresa.razon_social,
                "total": Decimal("0"),
            },
        )
        fila["total"] += ln.total
    return [{**f, "total": str(f["total"])} for f in sumas.values()]


def _deuda_interna(orden: OrdenServicio, pendiente) -> list[dict]:
    """Lo que la empresa de la orden le deberá a la otra por los repuestos que esta surtió."""
    costos: dict[int, dict] = {}
    for r in pendiente.repuestos.select_related("empresa"):
        if r.empresa_id == orden.empresa_id or not r.costo_total:
            continue
        fila = costos.setdefault(
            r.empresa_id,
            {
                "empresa": r.empresa_id,
                "nombre": r.empresa.nombre_comercial or r.empresa.razon_social,
                "monto": Decimal("0"),
            },
        )
        fila["monto"] += r.costo_total
    return [{**f, "monto": str(f["monto"])} for f in costos.values()]


def entrega_de(orden: OrdenServicio, usuario) -> dict | None:
    """Lo que hace falta para entregar el equipo, para quien puede entregarlo."""
    poder = capacidades_de(usuario, orden)
    if orden.estado != EstadoOrden.LISTO_ENTREGA or not poder.entrega:
        return None
    pendiente = entrega.a_cobrar(orden)
    libres = adelantos.total_disponible(orden)
    # Cobra siempre la empresa dueña de la orden: todo el total es suyo.
    del_cobro = pendiente.proforma.total if pendiente else Decimal("0")
    por_empresa = _por_empresa(pendiente.proforma) if pendiente else []
    deuda_interna = _deuda_interna(orden, pendiente) if pendiente else []
    aplicables = min(libres, del_cobro)
    return {
        "adelantos": {
            "total": str(libres),
            "aplicables": str(aplicables),
            "exceso": str(libres - aplicables),
            "por_cobrar": str(pendiente.proforma.total - aplicables) if pendiente else None,
        },
        "cobra": pendiente is not None,
        "garantia_dias": entrega.dias_de_garantia(orden),
        "total": str(pendiente.proforma.total) if pendiente else None,
        "moneda": pendiente.proforma.moneda if pendiente else "PEN",
        "por_empresa": [
            {
                "empresa": orden.empresa_id,
                "nombre": orden.empresa.nombre_comercial or orden.empresa.razon_social,
                "total": str(del_cobro),
            }
        ]
        if pendiente
        else [],
        "deuda_interna": deuda_interna,
        "sin_cobro_permitido": motor.tiene_permiso(
            usuario, "SERVICIOS.ENTREGAR_SIN_COBRAR", orden.empresa_id
        ),
    }


def permisos_de_presupuesto(orden: OrdenServicio, usuario, vigente: dict | None) -> dict:
    """Qué botones del presupuesto le sirven a esta persona."""
    poder = capacidades_de(usuario, orden)
    abierto = orden.estado in presupuesto.ESTADOS_EDITABLES
    return {
        "presupuestar": poder.presupuesta and abierto,
        "aprobar": (
            poder.recepcion
            and (
                orden.estado == EstadoOrden.PENDIENTE_APROBACION
                or (orden.es_garantia and orden.estado == EstadoOrden.DIAGNOSTICADO)
            )
            and vigente is not None
        ),
        "reservar": (
            poder.recepcion
            and orden.estado in (EstadoOrden.APROBADO, EstadoOrden.PENDIENTE_REPUESTO)
            and bool(vigente and vigente["repuestos_pendientes"])
        ),
    }


# ---------------------------------------------------------------------------
# Acciones de la orden (se suman a ``OrdenServicioViewSet``)
# ---------------------------------------------------------------------------
class PresupuestoAcciones:
    """Armar, aprobar y reservar. Cada acción comprueba lo que esta persona puede hacer."""

    @extend_schema(tags=TAG, request=PresupuestoEntrada)
    @action(detail=True, methods=["post"], url_path="presupuesto")
    def armar_presupuesto(self, request, pk=None):
        """Arma (o rehace) el presupuesto: servicios y repuestos con la empresa que los surte."""
        orden = self.get_object()
        if not capacidades_de(request.user, orden).presupuesta:
            raise PermissionDenied("No tiene permiso para armar presupuestos.")
        datos = PresupuestoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        org = orden.empresa.organizacion_id
        lineas = []
        for ln in v["lineas"]:
            producto = Producto.objects.filter(
                pk=ln["producto"], organizacion_id=org, estado=EstadoRegistro.ACTIVO
            ).first()
            surte = Empresa.objects.filter(
                pk=ln.get("empresa", orden.empresa_id), organizacion_id=org, estado=Estado.ACTIVO
            ).first()
            if producto is None or surte is None:
                raise ValidationError({"lineas": "Hay productos o empresas que no existen."})
            lineas.append(
                presupuesto.LineaPresupuesto(
                    producto=producto,
                    cantidad=ln["cantidad"],
                    empresa=surte,
                    precio_unitario=ln.get("precio_unitario"),
                )
            )
        presupuesto.armar_presupuesto(
            orden,
            lineas,
            vendedor_nombre=nombre_usuario(request.user),
            vendedor_id=request.user.pk,
            validez_dias=v["validez_dias"],
            condiciones=v.get("condiciones", ""),
            puede_otra_empresa=motor.tiene_permiso(request.user, OTRA_EMPRESA, orden.empresa_id),
            puede_bajo_minimo=motor.tiene_permiso(request.user, BAJO_MINIMO, orden.empresa_id),
        )
        return self._ficha(orden)

    @extend_schema(tags=TAG, request=AprobarEntrada)
    @action(detail=True, methods=["post"], url_path="aprobar")
    def aprobar(self, request, pk=None):
        """Registra que el cliente aprobó el presupuesto y reserva los repuestos."""
        orden = self.get_object()
        if not capacidades_de(request.user, orden).recepcion:
            raise PermissionDenied("No tiene permiso para registrar la aprobación.")
        datos = AprobarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        _, reserva = presupuesto.aprobar_presupuesto(
            orden, medio=datos.validated_data["medio"], nota=datos.validated_data["nota"]
        )
        respuesta = self._ficha(orden)
        respuesta.data["reserva"] = {
            "reservados": reserva.reservados,
            "pendientes": reserva.pendientes,
        }
        return respuesta

    @extend_schema(tags=TAG)
    @action(detail=True, methods=["post"], url_path="reservar")
    def reservar(self, request, pk=None):
        """Reintenta reservar los repuestos que faltaban (por ejemplo, ya llegó la compra)."""
        orden = self.get_object()
        if not capacidades_de(request.user, orden).recepcion:
            raise PermissionDenied("No tiene permiso para reservar repuestos.")
        if orden.estado not in (EstadoOrden.APROBADO, EstadoOrden.PENDIENTE_REPUESTO):
            raise ValidationError("Los repuestos se reservan cuando el presupuesto está aprobado.")
        reserva = repuestos.reservar_pendientes(orden)
        respuesta = self._ficha(orden)
        respuesta.data["reserva"] = {
            "reservados": reserva.reservados,
            "pendientes": reserva.pendientes,
        }
        return respuesta

    @extend_schema(tags=TAG, request=EntregarEntrada)
    @action(detail=True, methods=["post"], url_path="entregar")
    def entregar(self, request, pk=None):
        """Cobra el presupuesto (un comprobante por empresa) y entrega el equipo al cliente."""
        orden = self.get_object()
        poder = capacidades_de(request.user, orden)
        if not poder.entrega:
            raise PermissionDenied("No tiene permiso para entregar equipos.")
        datos = EntregarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        pendiente = entrega.a_cobrar(orden)
        if v["sin_cobro"] and not motor.tiene_permiso(
            request.user, "SERVICIOS.ENTREGAR_SIN_COBRAR", orden.empresa_id
        ):
            raise PermissionDenied("No tiene permiso para entregar sin cobrar.")
        if pendiente is not None and not v["sin_cobro"]:
            # Cobrar es vender: hace falta poder vender en cada empresa que emite un comprobante.
            empresas = set(pendiente.proforma.lineas.values_list("empresa_id", flat=True))
            for empresa_id in empresas:
                if not motor.tiene_permiso(request.user, VENDER, empresa_id):
                    raise PermissionDenied("No tiene permiso para cobrar en una de las empresas.")
        cobros = []
        for c in v.get("cobros", []):
            medio = MedioPago.objects.filter(
                pk=c["medio_pago"], organizacion_id=orden.empresa.organizacion_id
            ).first()
            if medio is None:
                raise ValidationError({"cobros": "Hay métodos de pago que no existen."})
            cobros.append(
                CobroEntrada(
                    medio,
                    c["monto"],
                    referencia=c.get("referencia", ""),
                    recibido=c.get("recibido"),
                )
            )
        _, venta = entrega.entregar_equipo(
            orden,
            tipo_comprobante=v.get("tipo_comprobante", ""),
            cobros=cobros,
            vendedor_nombre=nombre_usuario(request.user),
            vendedor_id=request.user.pk,
            series={int(k): n for k, n in (v.get("serie_por_empresa") or {}).items()} or None,
            sin_cobro=v["sin_cobro"],
            motivo_sin_cobro=v.get("motivo", ""),
            recoge_es_titular=v["recoge_es_titular"],
            recoge_nombre=v.get("recoge_nombre", ""),
            recoge_documento=v.get("recoge_documento", ""),
        )
        respuesta = self._ficha(orden)
        if venta is not None:
            completa = VentaViewSet._consulta(Venta.objects.all(), detalle=True).get(pk=venta.pk)
            respuesta.data["venta"] = json.loads(
                json.dumps(VentaDetalleSerializer(completa).data, default=str)
            )
        return respuesta


class CatalogoView(APIView):
    """Qué cotizar: productos y servicios con su precio de lista y el stock por empresa.

    ``?empresa=ID`` (la de la orden), ``?q=`` busca, ``?categoria=`` filtra, ``?pagina=`` recorre.
    Nunca devuelve costos. Incluye stock de otras empresas solo a quien puede venderlo.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = PRESUPUESTAR
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        propia = Empresa.objects.filter(pk=empresa_declarada(request, self)).first()
        if propia is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        otras = motor.tiene_permiso(request.user, OTRA_EMPRESA, propia.pk)
        ids = motor.empresas_ids_de(request.user) if otras else [propia.pk]
        empresas = list(
            Empresa.objects.filter(
                pk__in=ids, organizacion_id=propia.organizacion_id, estado=Estado.ACTIVO
            ).order_by("-es_principal", "id")
        )
        params = request.query_params
        categoria = params.get("categoria")
        pagina = params.get("pagina")
        if (categoria and not categoria.isdigit()) or (pagina and not pagina.isdigit()):
            raise ValidationError("Parámetros no válidos.")
        fichas, exacto, hay_mas = catalogo.buscar(
            empresas,
            q=params.get("q", ""),
            categoria=int(categoria) if categoria else None,
            pagina=int(pagina) if pagina else 1,
        )
        respuesta = Response(
            {
                "results": fichas,
                "exacto": exacto,
                "hay_mas": hay_mas,
                "lista_principal": getattr(
                    precios.cargar_listas(propia.organizacion_id).principal, "pk", None
                ),
                "empresas": [
                    {"id": e.pk, "nombre": e.nombre_comercial or e.razon_social} for e in empresas
                ],
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta
