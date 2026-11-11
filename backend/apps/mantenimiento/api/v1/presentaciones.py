"""API de las presentaciones de un producto (caja, docena…) y sus precios."""

from django.core.exceptions import ValidationError as ErrorDeModelo
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.mantenimiento import presentaciones
from apps.mantenimiento.models import (
    EstadoRegistro,
    PrecioPresentacion,
    PresentacionProducto,
    Producto,
)
from apps.mantenimiento.productos import margen_de_utilidad
from apps.seguridad.services import permisos_engine as motor

from .serializers import PrecioEntrada
from .views import CAMBIAR_PRECIO, TAG, MaestroViewSet

EDITAR_PRODUCTO = "MANTENIMIENTO.PRODUCTOS.EDITAR"


class PrecioPresentacionSerializer(serializers.ModelSerializer):
    lista_nombre = serializers.CharField(source="lista.nombre", read_only=True)
    margen = serializers.SerializerMethodField()

    class Meta:
        model = PrecioPresentacion
        fields = ("id", "lista", "lista_nombre", "precio", "utilidad", "margen")
        read_only_fields = fields

    def get_margen(self, fila) -> str | None:
        margen = margen_de_utilidad(fila.utilidad)
        return None if margen is None else f"{margen:.2f}"


class PresentacionProductoSerializer(serializers.ModelSerializer):
    """La utilidad (y con ella el costo) solo la ve quien puede cambiar precios."""

    unidad_nombre = serializers.CharField(source="unidad.nombre", read_only=True)
    unidad_abreviatura = serializers.CharField(source="unidad.abreviatura", read_only=True)
    equivalencia = serializers.CharField(read_only=True)
    precios = serializers.SerializerMethodField()

    class Meta:
        model = PresentacionProducto
        fields = (
            "id",
            "producto",
            "unidad",
            "unidad_nombre",
            "unidad_abreviatura",
            "factor",
            "equivalencia",
            "codigo_barras",
            "estado",
            "precios",
        )
        read_only_fields = fields

    def get_precios(self, presentacion) -> list[dict]:
        ve = bool(self.context.get("ve_costos"))
        filas = []
        for fila in presentacion.precios.all():
            dato = PrecioPresentacionSerializer(fila).data
            if not ve:
                dato.pop("utilidad", None)
                dato.pop("margen", None)
            filas.append(dato)
        return filas


class PresentacionEntrada(serializers.Serializer):
    """``producto`` y ``unidad`` se envían al crear: después no cambian."""

    producto = serializers.IntegerField(min_value=1, required=False)
    unidad = serializers.IntegerField(min_value=1, required=False)
    factor = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0, required=False)
    codigo_barras = serializers.CharField(max_length=60, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)
    precios = PrecioEntrada(many=True, required=False)


class PresentacionProductoViewSet(MaestroViewSet):
    """Presentaciones de los productos (``?producto=ID``, ``?estado=``).

    Ver las presentaciones pide ver productos; crearlas, cambiarlas o quitarlas pide editarlos, y
    poner precios, el permiso de cambiar precios.
    """

    modelo = PresentacionProducto
    campo_empresa = None
    campo_propio = "creado_por_id"
    serializer_class = PresentacionProductoSerializer
    entrada = PresentacionEntrada
    recurso = "presentacion"
    permisos_por_accion = {
        "list": "MANTENIMIENTO.PRODUCTOS.VER",
        "retrieve": "MANTENIMIENTO.PRODUCTOS.VER",
        "create": EDITAR_PRODUCTO,
        "partial_update": EDITAR_PRODUCTO,
        "destroy": EDITAR_PRODUCTO,
    }
    campos_busqueda = ("codigo_barras", "unidad__nombre", "producto__nombre")
    filtros_exactos = ("estado", "producto")
    ordenes = {"factor": ("factor",)}
    orden_por_defecto = ("producto_id", "factor")

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("unidad", "producto__unidad")
            .prefetch_related(
                Prefetch("precios", queryset=PrecioPresentacion.objects.select_related("lista"))
            )
        )

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["ve_costos"] = motor.tiene_permiso(self.request.user, CAMBIAR_PRECIO)
        return contexto

    def _exigir_precios(self, validados: dict) -> None:
        if "precios" in validados and not motor.tiene_permiso(self.request.user, CAMBIAR_PRECIO):
            motor.exigir_permiso(self.request.user, CAMBIAR_PRECIO)  # lanza PermisoDenegado

    @staticmethod
    def _como_error_de_api(error: ErrorDeModelo) -> ValidationError:
        return ValidationError(
            error.message_dict if hasattr(error, "error_dict") else error.messages
        )

    @extend_schema(tags=TAG)
    def create(self, request, *args, **kwargs):
        entrada = self.entrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        validados = dict(entrada.validated_data)
        for campo in ("producto", "unidad", "factor"):
            if campo not in validados:
                raise ValidationError({campo: "Es obligatorio."})
        self._exigir_precios(validados)
        producto = Producto.objects.filter(pk=validados["producto"]).first()
        if producto is None:
            raise ValidationError({"producto": "Elija un producto."})
        try:
            creada = presentaciones.crear_presentacion(
                producto=producto,
                unidad_id=validados["unidad"],
                factor=validados["factor"],
                codigo_barras=validados.get("codigo_barras", ""),
                precios=validados.get("precios"),
            )
        except ErrorDeModelo as error:
            raise self._como_error_de_api(error) from None
        return Response(
            self.get_serializer(self._recargar(creada.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(tags=TAG)
    def partial_update(self, request, *args, **kwargs):
        instancia = self.get_object()
        entrada = self.entrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        validados = dict(entrada.validated_data)
        for inmutable in ("producto", "unidad"):
            if validados.pop(inmutable, None) not in (None, getattr(instancia, f"{inmutable}_id")):
                raise ValidationError(
                    {inmutable: "No se cambia: quita la presentación y crea otra."}
                )
        self._exigir_precios(validados)
        precios = validados.pop("precios", None)
        try:
            presentaciones.actualizar_presentacion(instancia, datos=validados, precios=precios)
        except ErrorDeModelo as error:
            raise self._como_error_de_api(error) from None
        return Response(self.get_serializer(self._recargar(instancia.pk)).data)

    @extend_schema(tags=TAG)
    def destroy(self, request, *args, **kwargs):
        presentaciones.eliminar_presentacion(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _recargar(self, pk: int) -> PresentacionProducto:
        return self.get_queryset().get(pk=pk)
