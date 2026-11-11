"""API del transporte de mercadería: empresas de transporte, conductores y vehículos, y los ubigeos.

Se registran una vez en Mantenimiento y la guía de remisión solo los elige. Los ubigeos son la lista
oficial de distritos del INEI (de solo lectura) para buscar el de una dirección.
"""

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions, serializers
from rest_framework.exceptions import ValidationError

from apps.core.pagination import PaginaEstandar
from apps.mantenimiento import ubigeos
from apps.mantenimiento.models import (
    Conductor,
    EmpresaTransporte,
    EstadoRegistro,
    TipoDocumento,
    Ubigeo,
    Vehiculo,
)

from .views import TAG, _CatalogoViewSet, _permisos

PERMISO = "MANTENIMIENTO.TRANSPORTE"
MAXIMO_PALABRAS = 6


# ---------------------------------------------------------------------------
# Empresas de transporte
# ---------------------------------------------------------------------------
class EmpresaTransporteSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmpresaTransporte
        fields = (
            "id",
            "nombre",
            "ruc",
            "registro_mtc",
            "certificado_inspeccion",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class EmpresaTransporteEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=250)
    ruc = serializers.CharField(max_length=20)
    registro_mtc = serializers.CharField(max_length=30, required=False, allow_blank=True)
    certificado_inspeccion = serializers.CharField(max_length=30, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class EmpresaTransporteViewSet(_CatalogoViewSet):
    """Empresas de transporte de la organización (``?q=``, ``?estado=``)."""

    modelo = EmpresaTransporte
    serializer_class = EmpresaTransporteSerializer
    entrada = EmpresaTransporteEntrada
    recurso = "empresa_transporte"
    duplicado = "Ya existe una empresa de transporte con ese RUC."
    campo_duplicado = "ruc"
    permisos_por_accion = _permisos(PERMISO)
    campos_busqueda = ("nombre", "ruc", "registro_mtc")
    ordenes = {"nombre": ("nombre",), "reciente": ("-creado_en",)}


# ---------------------------------------------------------------------------
# Conductores
# ---------------------------------------------------------------------------
class ConductorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conductor
        fields = (
            "id",
            "nombre",
            "tipo_documento",
            "numero_documento",
            "licencia",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class ConductorEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=150)
    tipo_documento = serializers.ChoiceField(choices=TipoDocumento.choices, required=False)
    numero_documento = serializers.CharField(max_length=30)
    licencia = serializers.CharField(max_length=20, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class ConductorViewSet(_CatalogoViewSet):
    """Conductores de la organización (``?q=``, ``?estado=``)."""

    modelo = Conductor
    serializer_class = ConductorSerializer
    entrada = ConductorEntrada
    recurso = "conductor"
    duplicado = "Ya existe un conductor con ese documento."
    campo_duplicado = "numero_documento"
    permisos_por_accion = _permisos(PERMISO)
    campos_busqueda = ("nombre", "numero_documento", "licencia")
    ordenes = {"nombre": ("nombre",), "reciente": ("-creado_en",)}


# ---------------------------------------------------------------------------
# Vehículos
# ---------------------------------------------------------------------------
class VehiculoSerializer(serializers.ModelSerializer):
    descripcion = serializers.CharField(source="__str__", read_only=True)

    class Meta:
        model = Vehiculo
        fields = ("id", "placa", "marca", "modelo", "descripcion", "estado", "creado_en")
        read_only_fields = fields


class VehiculoEntrada(serializers.Serializer):
    placa = serializers.CharField(max_length=20)
    marca = serializers.CharField(max_length=60, required=False, allow_blank=True)
    modelo = serializers.CharField(max_length=60, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class VehiculoViewSet(_CatalogoViewSet):
    """Vehículos de la organización (``?q=``, ``?estado=``)."""

    modelo = Vehiculo
    serializer_class = VehiculoSerializer
    entrada = VehiculoEntrada
    recurso = "vehiculo"
    duplicado = "Ya existe un vehículo con esa placa."
    campo_duplicado = "placa"
    permisos_por_accion = _permisos(PERMISO)
    campos_busqueda = ("placa", "marca", "modelo")
    ordenes = {"placa": ("placa",), "reciente": ("-creado_en",)}
    orden_por_defecto = ("placa",)


# ---------------------------------------------------------------------------
# Ubigeos (lista oficial del INEI, de solo lectura)
# ---------------------------------------------------------------------------
class UbigeoSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.CharField(read_only=True)

    class Meta:
        model = Ubigeo
        fields = ("codigo", "departamento", "provincia", "distrito", "nombre_completo")
        read_only_fields = fields


class UbigeoListView(generics.ListAPIView):
    """Busca distritos por nombre o código: ``?q=san martin tarapoto`` (sin tildes ni mayúsculas).

    Cada palabra debe aparecer en el código o en los nombres. ``?codigo=220901`` trae uno exacto.
    Es una lista oficial de referencia: la ve cualquier persona con sesión.
    """

    queryset = Ubigeo.objects.all()
    serializer_class = UbigeoSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PaginaEstandar

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("q", str), OpenApiParameter("codigo", str)],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Ubigeo.objects.all()
        params = self.request.query_params
        if codigo := (params.get("codigo") or "").strip():
            return queryset.filter(codigo=codigo)
        palabras = ubigeos.normalizar((params.get("q") or "")[:80]).split()
        if len(palabras) > MAXIMO_PALABRAS:
            raise ValidationError({"q": f"Use hasta {MAXIMO_PALABRAS} palabras."})
        condicion = Q()
        for palabra in palabras:
            condicion &= Q(busqueda__contains=palabra)
        return queryset.filter(condicion).order_by("codigo")
