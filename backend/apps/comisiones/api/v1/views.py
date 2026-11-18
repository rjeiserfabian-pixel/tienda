"""API de las reglas de comisión: lista, crea, cambia, borra, opciones y «¿qué porcentaje toca?»."""

from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.comisiones import servicios
from apps.comisiones.models import Alcance, ReglaComision
from apps.mantenimiento.models import Categoria, EstadoRegistro, Marca, Producto
from apps.organizacion.models import Empresa
from apps.seguridad.models import Usuario
from apps.seguridad.permissions import PermisoRBAC
from apps.seguridad.services import permisos_engine as motor

VER = "COMISIONES.VER"
GESTIONAR = "COMISIONES.GESTIONAR"
VENDER = "VENTAS.VENDER"
TAG = ["comisiones"]


def _nombre(usuario) -> str:
    return (usuario.get_full_name() or usuario.username).strip()


def _organizacion(request) -> int:
    if request.user.organizacion_id is None:
        raise ValidationError("No hay una organización activa.")
    return request.user.organizacion_id


def _salida(regla: ReglaComision, nombres: dict) -> dict:
    return {
        "id": regla.pk,
        "alcance": regla.alcance,
        "alcance_texto": regla.get_alcance_display(),
        "categoria": regla.categoria_id,
        "marca": regla.marca_id,
        "producto": regla.producto_id,
        "objetivo": servicios.explicar(regla).replace(" (solo de un vendedor)", ""),
        "vendedor": str(regla.vendedor_id) if regla.vendedor_id else None,
        "vendedor_nombre": nombres.get(regla.vendedor_id, "Todos los vendedores")
        if regla.vendedor_id
        else "Todos los vendedores",
        "porcentaje": str(regla.porcentaje),
        "vigente_desde": regla.vigente_desde.isoformat() if regla.vigente_desde else None,
        "vigente_hasta": regla.vigente_hasta.isoformat() if regla.vigente_hasta else None,
        "activa": regla.activa,
        "nota": regla.nota,
    }


def _nombres_de_vendedores(organizacion_id: int, reglas) -> dict:
    ids = {r.vendedor_id for r in reglas if r.vendedor_id}
    if not ids:
        return {}
    return {
        u.pk: _nombre(u)
        for u in Usuario.objects.filter(pk__in=ids, organizacion_id=organizacion_id)
    }


class ReglaEntrada(serializers.Serializer):
    alcance = serializers.ChoiceField(choices=Alcance.values, required=False)
    categoria = serializers.IntegerField(required=False, allow_null=True)
    marca = serializers.IntegerField(required=False, allow_null=True)
    producto = serializers.IntegerField(required=False, allow_null=True)
    vendedor_id = serializers.UUIDField(required=False, allow_null=True)
    porcentaje = serializers.CharField(max_length=12, required=False)
    vigente_desde = serializers.DateField(required=False, allow_null=True)
    vigente_hasta = serializers.DateField(required=False, allow_null=True)
    activa = serializers.BooleanField(required=False)
    nota = serializers.CharField(max_length=200, required=False, allow_blank=True)


class ReglasView(APIView):
    """Lista las reglas (ver) y crea una nueva (gestionar)."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "post": GESTIONAR}

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("alcance", str),
            OpenApiParameter("vendedor", str),
            OpenApiParameter("activa", str, description="true o false"),
        ],
    )
    def get(self, request):
        organizacion_id = _organizacion(request)
        reglas = ReglaComision.objects.filter(organizacion_id=organizacion_id).select_related(
            "categoria", "marca", "producto"
        )
        p = request.query_params
        if p.get("alcance") in Alcance.values:
            reglas = reglas.filter(alcance=p["alcance"])
        if p.get("vendedor") == "todos":
            reglas = reglas.filter(vendedor_id__isnull=True)
        elif p.get("vendedor"):
            reglas = reglas.filter(vendedor_id=p["vendedor"][:36])
        if p.get("activa") in ("true", "false"):
            reglas = reglas.filter(activa=p["activa"] == "true")
        filas = list(reglas.order_by("alcance", "-id")[:500])
        nombres = _nombres_de_vendedores(organizacion_id, filas)
        return Response({"results": [_salida(r, nombres) for r in filas]})

    @extend_schema(tags=TAG, request=ReglaEntrada)
    def post(self, request):
        entrada = ReglaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        regla = servicios.crear(_organizacion(request), dict(entrada.validated_data))
        regla = ReglaComision.objects.select_related("categoria", "marca", "producto").get(
            pk=regla.pk
        )
        return Response(
            _salida(regla, _nombres_de_vendedores(regla.organizacion_id, [regla])), status=201
        )


class ReglaView(APIView):
    """Cambia (gestionar) o borra (gestionar) una regla."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "patch": GESTIONAR, "delete": GESTIONAR}

    def _regla(self, request, pk: int) -> ReglaComision:
        regla = (
            ReglaComision.objects.select_related("categoria", "marca", "producto")
            .filter(pk=pk, organizacion_id=_organizacion(request))
            .first()
        )
        if regla is None:
            raise NotFound("No encontramos esa regla.")
        return regla

    @extend_schema(tags=TAG)
    def get(self, request, pk: int):
        regla = self._regla(request, pk)
        return Response(_salida(regla, _nombres_de_vendedores(regla.organizacion_id, [regla])))

    @extend_schema(tags=TAG, request=ReglaEntrada)
    def patch(self, request, pk: int):
        regla = self._regla(request, pk)
        entrada = ReglaEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        servicios.actualizar(regla, dict(entrada.validated_data))
        regla = self._regla(request, pk)
        return Response(_salida(regla, _nombres_de_vendedores(regla.organizacion_id, [regla])))

    @extend_schema(tags=TAG)
    def delete(self, request, pk: int):
        servicios.eliminar(self._regla(request, pk))
        return Response(status=204)


class OpcionesView(APIView):
    """Lo que necesita el formulario: categorías, marcas y los vendedores de la organización."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER

    @extend_schema(tags=TAG)
    def get(self, request):
        org = _organizacion(request)
        empresas = list(Empresa.objects.filter(organizacion_id=org).values_list("pk", flat=True))
        vendedores = [
            {"id": str(u.pk), "nombre": _nombre(u)}
            for u in Usuario.objects.filter(organizacion_id=org, is_active=True).order_by(
                "first_name", "username"
            )
            if any(motor.tiene_permiso(u, VENDER, e) for e in empresas)
        ]
        activo = {"estado": EstadoRegistro.ACTIVO}
        return Response(
            {
                "categorias": list(
                    Categoria.objects.filter(organizacion_id=org, **activo)
                    .order_by("nombre")
                    .values("id", "nombre")
                ),
                "marcas": list(
                    Marca.objects.filter(organizacion_id=org, **activo)
                    .order_by("nombre")
                    .values("id", "nombre")
                ),
                "vendedores": vendedores,
            }
        )


class SimularView(APIView):
    """«¿Qué porcentaje gana este vendedor por vender este producto?» y por qué."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("producto", int, required=True),
            OpenApiParameter("vendedor", str, description="Id del vendedor (vacío = cualquiera)"),
            OpenApiParameter("fecha", str, description="AAAA-MM-DD (por defecto hoy)"),
        ],
    )
    def get(self, request):
        org = _organizacion(request)
        try:
            producto = Producto.objects.filter(
                pk=int(request.query_params.get("producto", "")), organizacion_id=org
            ).first()
        except ValueError:
            producto = None
        if producto is None:
            raise ValidationError({"producto": "Elija un producto."})
        fecha = parse_date(request.query_params.get("fecha") or "") or timezone.localdate()
        resultado = servicios.porcentaje_para(
            org,
            vendedor_id=request.query_params.get("vendedor") or None,
            producto=producto,
            fecha=fecha,
        )
        return Response(
            {
                "porcentaje": str(resultado.porcentaje),
                "regla": resultado.regla.pk if resultado.regla else None,
                "texto": resultado.texto,
            }
        )
