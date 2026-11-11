import logging

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.compras import xml_proveedor
from apps.compras.models import Compra
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.api.v1.serializers import ProductoSerializer
from apps.mantenimiento.models import (
    EstadoRegistro,
    Producto,
    Proveedor,
    TipoComprobante,
    TipoProducto,
)
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

logger = logging.getLogger(__name__)

CREAR = "COMPRAS.CREAR"
CAMBIAR_PRECIO = "MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO"


class XmlEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    archivo = serializers.FileField(max_length=200, allow_empty_file=False)


def _n(valor) -> str:
    """Número del XML como texto simple: «10», «2.5», «0.8475» (sin ceros de relleno)."""
    texto = format(valor.normalize(), "f")
    return texto if "." not in texto else texto.rstrip("0").rstrip(".")


def _producto_sugerido(codigo: str, contexto: dict) -> dict | None:
    """El producto del catálogo cuyo código coincide EXACTAMENTE con el del XML, si hay uno."""
    if not codigo:
        return None
    producto = (
        Producto.objects.select_related("categoria__familia", "marca", "unidad", "afectacion_igv")
        .prefetch_related("precios__lista", "presentaciones__unidad", "fotos")
        .filter(tipo=TipoProducto.BIEN, estado=EstadoRegistro.ACTIVO)
        .filter(Q(codigo_fabricante__iexact=codigo) | Q(codigo_barras=codigo) | Q(codigo=codigo))
        .first()
    )
    return ProductoSerializer(producto, context=contexto).data if producto else None


class LeerXmlView(APIView):
    """Lee la factura XML de un proveedor y devuelve lo que se puede precargar en la compra.

    No guarda nada: solo interpreta el archivo y busca coincidencias (proveedor por RUC y productos
    por código exacto). La persona revisa todo en la pantalla antes de registrar.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = CREAR
    requiere_empresa = True
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=["compras"], request=XmlEntrada, responses={200: dict})
    def post(self, request):
        datos = XmlEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        empresa = Empresa.objects.filter(
            pk=datos.validated_data["empresa"], estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        archivo = datos.validated_data["archivo"]
        if archivo.size > xml_proveedor.TAMANO_MAXIMO:
            raise xml_proveedor.XmlInvalido("El archivo es demasiado grande para ser una factura.")
        factura = xml_proveedor.leer_factura(archivo.read(xml_proveedor.TAMANO_MAXIMO + 1))

        proveedor = Proveedor.objects.filter(
            tipo_documento=factura.proveedor_tipo_documento,
            numero_documento=factura.proveedor_documento,
        ).first()
        tipo = TipoComprobante.objects.filter(
            organizacion_id=empresa.organizacion_id,
            codigo=factura.tipo_comprobante,
            estado=EstadoRegistro.ACTIVO,
            aplica_compras=True,
        ).first()
        duplicado = bool(
            proveedor
            and Compra.objects.filter(
                empresa=empresa,
                proveedor=proveedor,
                tipo_comprobante__codigo=factura.tipo_comprobante,
                comprobante_serie=factura.serie,
                comprobante_numero__in={factura.numero, factura.numero.zfill(8)},
                estado=Compra.Estado.EMITIDO,
            ).exists()
        )
        contexto = {
            "request": request,
            "ve_costos": motor.alcance_de(request.user, CAMBIAR_PRECIO, None) is not None,
        }
        t = factura.totales
        logger.info(
            "xml_proveedor_leido",
            extra={"empresa_id": empresa.pk, "lineas": len(factura.lineas)},
        )
        respuesta = Response(
            {
                "comprobante": {
                    "tipo": factura.tipo_comprobante,
                    "tipo_nombre": xml_proveedor.TIPOS_ADMITIDOS[factura.tipo_comprobante],
                    "serie": factura.serie,
                    "numero": factura.numero,
                    "fecha_emision": factura.fecha_emision.isoformat(),
                    "moneda": factura.moneda,
                    "forma_pago": factura.forma_pago,
                    "cuotas": [
                        {
                            "fecha_vencimiento": c["fecha_vencimiento"].isoformat(),
                            "monto": _n(c["monto"]),
                        }
                        for c in factura.cuotas
                    ],
                },
                "proveedor": {
                    "tipo_documento": factura.proveedor_tipo_documento,
                    "numero_documento": factura.proveedor_documento,
                    "nombre": factura.proveedor_nombre,
                    "existente": (
                        {
                            "id": proveedor.pk,
                            "nombre": proveedor.nombre,
                            "tipo_documento": proveedor.tipo_documento,
                            "numero_documento": proveedor.numero_documento,
                            "zona": proveedor.zona,
                            "ciudad": proveedor.ciudad,
                        }
                        if proveedor
                        else None
                    ),
                },
                "receptor_documento": factura.receptor_documento,
                "receptor_coincide": factura.receptor_documento == empresa.ruc,
                "tipo_valido": tipo is not None,
                "duplicado": duplicado,
                "lineas": [
                    {
                        "numero": ln.numero,
                        "descripcion": ln.descripcion,
                        "codigo": ln.codigo,
                        "unidad": ln.unidad,
                        "cantidad": _n(ln.cantidad),
                        "precio_unitario": _n(ln.precio_unitario),
                        "valor_venta": _n(ln.valor_venta),
                        "afectacion": ln.afectacion,
                        "producto": _producto_sugerido(ln.codigo, contexto),
                    }
                    for ln in factura.lineas
                ],
                "totales": {k: _n(v) for k, v in t.items()},
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta
