"""API de la facturación electrónica: configuración, lista de documentos, vista previa y envío."""

from django.db.models import Exists, OuterRef, Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.facturacion import cliente, servicios
from apps.facturacion.models import EnvioSunat, EstadoEnvio, OrigenDocumento
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

from .serializers import (
    ConfiguracionEntrada,
    DocumentoEntrada,
    EmpresaEntrada,
    EnvioSerializer,
)

TAG = ["facturacion"]
VER = "FACTURACION.VER"
ENVIAR = "FACTURACION.ENVIAR_SUNAT"
CONFIGURAR = "FACTURACION.CONFIGURAR"


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


class _PorEmpresa(APIView):
    """La empresa es obligatoria y explícita (``?empresa=ID`` o en el cuerpo)."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
class ConfiguracionView(_PorEmpresa):
    """Configuración de la facturación electrónica de una empresa (las claves nunca salen)."""

    permisos_por_accion = {"get": VER, "patch": CONFIGURAR}

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = _empresa_activa(empresa_declarada(request, self))
        return Response(servicios.configuracion_json(empresa, servicios.configuracion_de(empresa)))

    @extend_schema(tags=TAG, request=ConfiguracionEntrada)
    def patch(self, request):
        datos = ConfiguracionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        validados = dict(datos.validated_data)
        empresa = _empresa_activa(validados.pop("empresa"))
        configuracion = servicios.actualizar_configuracion(empresa, validados)
        return Response(servicios.configuracion_json(empresa, configuracion))


class ProbarView(_PorEmpresa):
    """Revisa si la configuración está completa y si la API de facturación responde."""

    permisos_por_accion = {"post": CONFIGURAR}

    @extend_schema(tags=TAG, request=EmpresaEntrada, responses={200: dict})
    def post(self, request):
        datos = EmpresaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        empresa = _empresa_activa(datos.validated_data["empresa"])
        config = servicios.configuracion_de(empresa)
        resumen = servicios.configuracion_json(empresa, config)
        return Response(
            {
                "api_alcanzable": cliente.alcanzable(),
                "faltantes": resumen["faltantes"],
                "faltantes_guia": resumen["faltantes_guia"],
                "activo": config.sunat_activo,
                "modo": config.modo_sunat,
            }
        )


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
_CAMPO_FECHA = {
    OrigenDocumento.COMPROBANTE: "fecha",
    OrigenDocumento.NOTA_CREDITO: "fecha",
    OrigenDocumento.GUIA: "fecha_emision",
}


def _fila(origen: str, doc, envio: EnvioSunat | None) -> dict:
    if origen == OrigenDocumento.GUIA:
        cliente_nombre, total, fecha = doc.destinatario_nombre, None, doc.fecha_emision
    else:
        cliente_nombre = doc.venta.cliente_nombre or "Clientes varios"
        total, fecha = doc.total, doc.fecha
    return {
        "id": doc.pk,
        "origen": origen,
        "tipo_documento": doc.tipo_comprobante.codigo,
        "tipo_nombre": doc.tipo_comprobante.nombre,
        "numero": doc.numero_completo,
        "fecha": fecha,
        "cliente": cliente_nombre,
        "total": total,
        "estado": doc.estado,
        "envio": EnvioSerializer(envio).data if envio else None,
    }


class DocumentosView(_PorEmpresa):
    """Los documentos electrónicos de una empresa con el estado de su envío a SUNAT.

    ``origen`` (obligatorio): ``COMPROBANTE``, ``NOTA_CREDITO`` o ``GUIA``. Filtros: ``envio``
    (``sin_enviar``, ``enviado`` o ``error``) y ``q`` (serie o número). Paginado.
    """

    permisos_por_accion = {"get": VER}

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("origen", str, required=True, enum=list(OrigenDocumento.values)),
            OpenApiParameter("envio", str, enum=["sin_enviar", "enviado", "error"]),
            OpenApiParameter("q", str),
        ],
        responses={200: dict},
    )
    def get(self, request):
        empresa = _empresa_activa(empresa_declarada(request, self))
        origen = request.query_params.get("origen", "")
        if origen not in OrigenDocumento.values:
            raise ValidationError({"origen": "Use COMPROBANTE, NOTA_CREDITO o GUIA."})
        modelo, tipos = servicios.DOCUMENTOS[origen]
        consulta = modelo.objects.filter(
            empresa=empresa,
            tipo_comprobante__codigo__in=tipos,
            serie_comprobante__es_electronica=True,
        ).select_related("tipo_comprobante")
        if origen != OrigenDocumento.GUIA:
            consulta = consulta.select_related("venta")
        envios = EnvioSunat.objects.filter(
            empresa_id=OuterRef("empresa_id"), origen=origen, origen_id=OuterRef("pk")
        )
        filtro = request.query_params.get("envio", "")
        if filtro == "sin_enviar":
            consulta = consulta.filter(~Exists(envios))
        elif filtro == "enviado":
            consulta = consulta.filter(Exists(envios.filter(estado=EstadoEnvio.ENVIADO)))
        elif filtro == "error":
            consulta = consulta.filter(
                Exists(envios.filter(estado__in=[EstadoEnvio.ERROR_API, EstadoEnvio.SIN_CONEXION]))
            )
        elif filtro:
            raise ValidationError({"envio": "Use sin_enviar, enviado o error."})
        q = " ".join((request.query_params.get("q") or "").split())
        if q:
            condicion = Q(serie__icontains=q)
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            consulta = consulta.filter(condicion)
        consulta = consulta.order_by(f"-{_CAMPO_FECHA[origen]}", "-id")

        paginador = PaginaEstandar()
        pagina = paginador.paginate_queryset(consulta, request)
        por_documento = {
            e.origen_id: e
            for e in EnvioSunat.objects.filter(
                empresa=empresa, origen=origen, origen_id__in=[d.pk for d in pagina]
            )
        }
        return paginador.get_paginated_response(
            [_fila(origen, doc, por_documento.get(doc.pk)) for doc in pagina]
        )


class _DeUnDocumento(APIView):
    """Vistas que actúan sobre UN documento: la empresa sale del propio documento."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]

    def _ubicar(self, origen: str, pk) -> tuple[str, int]:
        datos = DocumentoEntrada(data={"origen": origen, "id": pk})
        datos.is_valid(raise_exception=True)
        return datos.validated_data["origen"], datos.validated_data["id"]

    def empresas_de_la_operacion(self, request):
        origen, pk = self._ubicar(
            request.query_params.get("origen") or request.data.get("origen"),
            request.query_params.get("id") or request.data.get("id"),
        )
        modelo, _ = servicios.DOCUMENTOS[origen]
        empresa_id = modelo.objects.filter(pk=pk).values_list("empresa_id", flat=True).first()
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    def _documento(self, request):
        origen, pk = self._ubicar(
            request.query_params.get("origen") or request.data.get("origen"),
            request.query_params.get("id") or request.data.get("id"),
        )
        doc = servicios.documento(origen, pk)
        if doc is None:
            raise Http404
        return origen, doc


class VistaPreviaView(_DeUnDocumento):
    """El JSON que se enviaría a la API (con las claves ocultas) y lo que falta configurar."""

    permisos_por_accion = {"get": VER}

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("origen", str, required=True),
            OpenApiParameter("id", int, required=True),
        ],
        responses={200: dict},
    )
    def get(self, request):
        origen, doc = self._documento(request)
        respuesta = Response(servicios.vista_previa(origen, doc))
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class EnviarView(_DeUnDocumento):
    """Envía el documento a SUNAT por la API de facturación."""

    permisos_por_accion = {"post": ENVIAR}

    @extend_schema(tags=TAG, request=DocumentoEntrada, responses={200: EnvioSerializer})
    def post(self, request):
        origen, doc = self._documento(request)
        envio = servicios.enviar_documento(origen, doc)
        return Response(EnvioSerializer(envio).data)
