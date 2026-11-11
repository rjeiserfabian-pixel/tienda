"""API de la guía de remisión de un traspaso entre almacenes.

La guía no mueve stock: el traspaso de inventario ya lo movió. Desde cualquiera de las dos mitades
del traspaso (la salida o la entrada) se consulta lo que la guía propone y se emite.
"""

import json
from decimal import Decimal

from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.throttles import MostradorThrottle
from apps.inventario.models import MovimientoInventario
from apps.seguridad.mixins import filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC
from apps.ventas import guias

from .guias import (
    EMITIR,
    GuiaDetalleSerializer,
    GuiaEntrada,
    _detalle,
    _transporte_elegido,
    _ubigeo,
)
from .views import TAG, _nombre_usuario

MOTIVOS = [(m.value, m.label) for m in guias.MOTIVOS_DE_TRASPASO]


class PesoLineaEntrada(serializers.Serializer):
    """El peso de un producto del traspaso (``linea`` es el id de la línea del movimiento)."""

    linea = serializers.IntegerField(min_value=1)
    peso_kg = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0"))


class GuiaTrasladoEntrada(GuiaEntrada):
    """Los datos de la guía de un traspaso: los de una venta, sin destinatario ni almacén.

    Viaja todo lo traspasado, así que ``lineas`` solo sirve para anotar el peso de cada producto.
    """

    lineas = PesoLineaEntrada(many=True, required=False, max_length=200)
    motivo = serializers.ChoiceField(choices=MOTIVOS, required=False)
    destinatario = None  # es la propia empresa
    almacen_origen = None  # es el de la salida del traspaso


class _DeTraspaso(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = EMITIR
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        empresa_id = (
            MovimientoInventario.objects.filter(pk=self.kwargs["movimiento_id"])
            .values_list("empresa_id", flat=True)
            .first()
        )
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    def mitades(self) -> tuple[MovimientoInventario, MovimientoInventario]:
        """``(salida, entrada)`` del traspaso, venga el id de la una o de la otra."""
        movimiento = (
            filtrar_por_alcance(MovimientoInventario.objects, self.request.user, EMITIR)
            .filter(pk=self.kwargs["movimiento_id"])
            .first()
        )
        if movimiento is None:
            raise Http404
        return guias.mitades_de_traspaso(movimiento)


def _lugar(almacen, empresa) -> tuple[str, str]:
    """La dirección y el ubigeo de un almacén; si no los tiene, los de su tienda o la sede."""
    sucursal = almacen.sucursal
    direccion = next((o.direccion for o in (almacen, sucursal) if o.direccion), "")
    ubigeo = next((o.ubigeo for o in (almacen, sucursal) if o.ubigeo), "")
    return direccion or empresa.direccion_fiscal, ubigeo


class PendienteView(_DeTraspaso):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, movimiento_id: int):
        """Lo que la guía de un traspaso propone: quién envía, de dónde a dónde y qué viaja."""
        salida, entrada = self.mitades()
        empresa = salida.empresa
        vigente = guias.guia_vigente_del_traspaso(salida)
        anulado = guias.traspaso_anulado(salida, entrada)
        partida, ubigeo_partida = _lugar(salida.almacen, empresa)
        destinataria = entrada.empresa
        entre_empresas = destinataria.pk != empresa.pk
        llegada, ubigeo_llegada = _lugar(entrada.almacen, destinataria)
        respuesta = Response(
            {
                "movimiento": salida.pk,
                "empresa": empresa.pk,
                "numero": salida.numero,
                "fecha": salida.fecha.isoformat(),
                "anulado": anulado,
                "guia_vigente": (
                    {"id": vigente.pk, "numero_completo": vigente.numero_completo}
                    if vigente
                    else None
                ),
                "se_puede_enviar": not anulado and vigente is None,
                "remitente": {"nombre": empresa.razon_social, "ruc": empresa.ruc},
                "destinatario": {"nombre": destinataria.razon_social, "documento": destinataria.ruc},
                "entre_empresas": entre_empresas,
                "motivo": (
                    guias.MotivoTraslado.OTROS if entre_empresas
                    else guias.MotivoTraslado.ENTRE_ESTABLECIMIENTOS
                ).value,
                "motivos": [{"codigo": codigo, "nombre": nombre} for codigo, nombre in MOTIVOS],
                "punto_partida": partida,
                "ubigeo_partida": _ubigeo(ubigeo_partida),
                "punto_llegada": llegada,
                "ubigeo_llegada": _ubigeo(ubigeo_llegada),
                "almacen_origen": {"id": salida.almacen_id, "nombre": salida.almacen.nombre},
                "almacen_destino": {"id": entrada.almacen_id, "nombre": entrada.almacen.nombre},
                **guias.series_para_elegir(empresa, salida.almacen.sucursal),
                "lineas": [
                    {
                        "id": ln.pk,
                        "codigo": ln.producto.codigo,
                        "descripcion": ln.producto.nombre,
                        "unidad": ln.producto.unidad.abreviatura,
                        "cantidad": str(ln.cantidad),
                        "series": guias.series_de_linea(ln),
                    }
                    for ln in guias.lineas_del_traspaso(salida)
                ],
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class EmitirView(_DeTraspaso):
    @extend_schema(
        tags=TAG,
        request=GuiaTrasladoEntrada,
        responses={201: GuiaDetalleSerializer},
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
    )
    def post(self, request, movimiento_id: int):
        salida, _entrada = self.mitades()
        datos = GuiaTrasladoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        transporte, secundarios = _transporte_elegido(v, salida.empresa.organizacion_id)
        pesos = {d["linea"]: d["peso_kg"] for d in v.get("lineas", [])}
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            guia = guias.crear_guia_de_traslado(
                salida,
                fecha_traslado=v["fecha_traslado"],
                modalidad=v["modalidad"],
                punto_partida=v["punto_partida"],
                punto_llegada=v["punto_llegada"],
                motivo=v.get("motivo", guias.MotivoTraslado.ENTRE_ESTABLECIMIENTOS),
                serie_id=v.get("serie_guia"),
                ubigeo_partida=v.get("ubigeo_partida", ""),
                ubigeo_llegada=v.get("ubigeo_llegada", ""),
                traslado_m1_l=v.get("traslado_m1_l", False),
                transportista_nombre=v.get("transportista_nombre", ""),
                transportista_documento=v.get("transportista_documento", ""),
                placa=v.get("placa", ""),
                conductor_nombre=v.get("conductor_nombre", ""),
                conductor_licencia=v.get("conductor_licencia", ""),
                vehiculos_secundarios=secundarios,
                pesos=pesos,
                peso_kg=v.get("peso_kg"),
                bultos=v.get("bultos", 1),
                observacion=v.get("observacion", ""),
                usuario_nombre=_nombre_usuario(request.user),
                **transporte,
            )
            return 201, json.loads(
                json.dumps(GuiaDetalleSerializer(_detalle(guia.pk)).data, default=str)
            )

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
