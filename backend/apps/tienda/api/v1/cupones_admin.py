"""Panel: cupones de descuento de la tienda (crear, pausar, ver su uso)."""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import Categoria, EstadoRegistro, Marca, Producto
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import carrito_abandonado, cupones
from apps.tienda.exceptions import CuponInvalido, DatosInvalidos
from apps.tienda.models import ConfiguracionCarritoAbandonado, Cupon, UsoCupon

logger = logging.getLogger(__name__)

TAG = ["tienda"]
GESTIONAR = "TIENDA.OFERTAS.GESTIONAR"
TAM_PAGINA = 25
MAX_ALCANCE = 200  # categorías, marcas o productos que puede tener un cupón

VIGENTE, PROGRAMADO, VENCIDO, PAUSADO, AGOTADO = (
    "VIGENTE",
    "PROGRAMADO",
    "VENCIDO",
    "PAUSADO",
    "AGOTADO",
)


def _estado(c: Cupon, usos: int, ahora) -> str:
    if not c.activo:
        return PAUSADO
    if c.termina_en and ahora > c.termina_en:
        return VENCIDO
    if c.usos_maximos is not None and usos >= c.usos_maximos:
        return AGOTADO
    if c.inicia_en and ahora < c.inicia_en:
        return PROGRAMADO
    return VIGENTE


def _d2(valor) -> str:
    return format(Decimal(valor).quantize(Decimal("0.01")), "f")


def _salida(c: Cupon, ahora=None) -> dict:
    ahora = ahora or timezone.now()
    usos = UsoCupon.objects.sin_ambito().filter(cupon=c)
    vigentes = usos.filter(estado__in=[UsoCupon.Estado.RESERVADO, UsoCupon.Estado.CONSUMIDO])
    descontado = usos.filter(estado=UsoCupon.Estado.CONSUMIDO).aggregate(t=Sum("monto"))[
        "t"
    ] or Decimal(0)
    n_vigentes = vigentes.count()
    return {
        "id": c.pk,
        "codigo": c.codigo,
        "nombre": c.nombre,
        "tipo": c.tipo,
        "tipo_texto": c.get_tipo_display(),
        "valor": _d2(c.valor),
        "tope_descuento": None if c.tope_descuento is None else _d2(c.tope_descuento),
        "compra_minima": _d2(c.compra_minima),
        "inicia_en": c.inicia_en.isoformat() if c.inicia_en else None,
        "termina_en": c.termina_en.isoformat() if c.termina_en else None,
        "usos_maximos": c.usos_maximos,
        "usos_por_cliente": c.usos_por_cliente,
        "alcance": c.alcance,
        "categorias": [{"id": x.pk, "nombre": x.nombre} for x in c.categorias.all()],
        "marcas": [{"id": x.pk, "nombre": x.nombre} for x in c.marcas.all()],
        "productos": [
            {"id": x.pk, "codigo": x.codigo, "nombre": x.nombre} for x in c.productos.all()
        ],
        "solo_primera_compra": c.solo_primera_compra,
        "incluye_ofertas": c.incluye_ofertas,
        "activo": c.activo,
        "estado": _estado(c, n_vigentes, ahora),
        "usos": n_vigentes,
        "usos_pagados": usos.filter(estado=UsoCupon.Estado.CONSUMIDO).count(),
        "descontado": _d2(descontado),
    }


class CuponEntrada(serializers.Serializer):
    codigo = serializers.CharField(max_length=30, required=False)
    nombre = serializers.CharField(max_length=100, required=False, allow_blank=True)
    tipo = serializers.ChoiceField(choices=Cupon.Tipo.choices, required=False)
    valor = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False
    )
    tope_descuento = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )
    compra_minima = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False
    )
    inicia_en = serializers.DateTimeField(required=False, allow_null=True)
    termina_en = serializers.DateTimeField(required=False, allow_null=True)
    usos_maximos = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    usos_por_cliente = serializers.IntegerField(min_value=1, max_value=100, required=False)
    alcance = serializers.ChoiceField(choices=Cupon.Alcance.choices, required=False)
    categorias = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=MAX_ALCANCE
    )
    marcas = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=MAX_ALCANCE
    )
    productos = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=MAX_ALCANCE
    )
    solo_primera_compra = serializers.BooleanField(required=False)
    incluye_ofertas = serializers.BooleanField(required=False)
    activo = serializers.BooleanField(required=False)


class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = dict.fromkeys(("get", "post", "patch", "delete"), GESTIONAR)

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización, no de una empresa

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


def _cupones_de(request):
    return Cupon.objects.sin_ambito().filter(organizacion_id=request.user.organizacion_id)


def _cupon_de(request, pk: int) -> Cupon:
    cupon = _cupones_de(request).filter(pk=pk).first()
    if cupon is None:
        raise NotFound("No encontramos ese cupón.")
    return cupon


def _validar(datos: dict, actual: Cupon | None) -> dict:
    """Reglas entre campos (el valor depende del tipo, etc.). Devuelve los datos ya limpios."""
    tipo = datos.get("tipo", actual.tipo if actual else None)
    valor = datos.get("valor", actual.valor if actual else Decimal(0))
    if tipo is None:
        raise DatosInvalidos("Elige qué tipo de cupón es.")
    if tipo == Cupon.Tipo.PORCENTAJE:
        if not (Decimal(0) < valor <= Decimal(100)):
            raise DatosInvalidos("El porcentaje debe estar entre 1 y 100.")
    elif tipo == Cupon.Tipo.MONTO:
        if valor <= 0:
            raise DatosInvalidos("El monto del descuento debe ser mayor que cero.")
        datos["tope_descuento"] = None
    else:  # ENVIO_GRATIS
        datos["valor"] = Decimal(0)
        datos["tope_descuento"] = None
    if tipo != Cupon.Tipo.PORCENTAJE:
        datos["tope_descuento"] = None
    inicia = datos.get("inicia_en", actual.inicia_en if actual else None)
    termina = datos.get("termina_en", actual.termina_en if actual else None)
    if inicia and termina and termina <= inicia:
        raise DatosInvalidos("La fecha final debe ser posterior a la de inicio.")
    return datos


def _alcance(request, datos: dict, cupon: Cupon | None) -> dict:
    """Los ids de categorías, marcas y productos, verificados contra la organización."""
    org = request.user.organizacion_id
    modelos = {
        "categorias": (Categoria, "Elige categorías de tu tienda."),
        "marcas": (Marca, "Elige marcas de tu tienda."),
        "productos": (Producto, "Elige productos de tu tienda."),
    }
    elegidos = {}
    for clave, (modelo, mensaje) in modelos.items():
        if clave not in datos:
            continue
        ids = set(datos[clave])
        validos = set(
            modelo.objects.sin_ambito()
            .filter(organizacion_id=org, pk__in=ids)
            .values_list("pk", flat=True)
        )
        if validos != ids:
            raise DatosInvalidos(mensaje)
        elegidos[clave] = validos
    return elegidos


def _aplicar(request, cupon: Cupon, datos: dict) -> None:
    elegidos = _alcance(request, datos, cupon)
    for clave in ("categorias", "marcas", "productos"):
        datos.pop(clave, None)
    for campo, valor in datos.items():
        setattr(cupon, campo, valor)
    alcance = cupon.alcance
    if alcance == Cupon.Alcance.TODO:
        elegidos = {"categorias": set(), "marcas": set(), "productos": set()}
    cupon.save()
    for clave, ids in elegidos.items():
        getattr(cupon, clave).set(ids)
    # Un alcance sin elementos no serviría para nada: se avisa.
    faltante = {
        Cupon.Alcance.CATEGORIAS: cupon.categorias,
        Cupon.Alcance.MARCAS: cupon.marcas,
        Cupon.Alcance.PRODUCTOS: cupon.productos,
    }.get(alcance)
    if faltante is not None and not faltante.exists():
        raise DatosInvalidos("Elige al menos un elemento para el alcance del cupón.")


class CuponesView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        ahora = timezone.now()
        qs = _cupones_de(request).prefetch_related("categorias", "marcas", "productos")
        if texto := (request.query_params.get("q") or "").strip()[:60]:
            qs = qs.filter(Q(codigo__icontains=texto) | Q(nombre__icontains=texto))
        try:
            pagina = max(int(request.query_params.get("page", 1)), 1)
        except ValueError:
            pagina = 1
        filas = list(qs.order_by("-id")[(pagina - 1) * TAM_PAGINA : pagina * TAM_PAGINA])
        salidas = [_salida(c, ahora) for c in filas]
        estado = request.query_params.get("estado", "")
        if estado in (VIGENTE, PROGRAMADO, VENCIDO, PAUSADO, AGOTADO):
            salidas = [s for s in salidas if s["estado"] == estado]
        return Response(
            {
                "count": qs.count(),
                "page": pagina,
                "page_size": TAM_PAGINA,
                "results": salidas,
            }
        )

    @extend_schema(tags=TAG, request=CuponEntrada, responses={201: dict})
    @transaction.atomic
    def post(self, request):
        entrada = CuponEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        if "codigo" not in datos:
            raise DatosInvalidos("Escribe el código del cupón.")
        try:
            datos["codigo"] = cupones.normalizar_codigo(datos["codigo"])
        except CuponInvalido:
            raise DatosInvalidos(
                "El código solo puede tener letras, números, guion y guion bajo (3 a 30)."
            ) from None
        if _cupones_de(request).filter(codigo__iexact=datos["codigo"]).exists():
            raise DatosInvalidos("Ya tienes un cupón con ese código.")
        datos = _validar(datos, None)
        cupon = Cupon(organizacion_id=request.user.organizacion_id)
        _aplicar(request, cupon, datos)
        registrar(
            "tienda.cupon_creado",
            recurso_tipo="cupon",
            recurso_id=cupon.pk,
            resumen=f"Cupón {cupon.codigo} creado",
            detalle={"tipo": cupon.tipo, "valor": str(cupon.valor)},
        )
        return Response(_salida(cupon), status=201)


class CuponView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, pk: int):
        return Response(_salida(_cupon_de(request, pk)))

    @extend_schema(tags=TAG, request=CuponEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request, pk: int):
        cupon = _cupon_de(request, pk)
        entrada = CuponEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        if "codigo" in datos:
            try:
                nuevo = cupones.normalizar_codigo(datos["codigo"])
            except CuponInvalido:
                raise DatosInvalidos("El código no es válido.") from None
            if nuevo != cupon.codigo:
                if UsoCupon.objects.sin_ambito().filter(cupon=cupon).exists():
                    raise DatosInvalidos("Este cupón ya se usó: no se puede cambiar su código.")
                if _cupones_de(request).filter(codigo__iexact=nuevo).exclude(pk=cupon.pk).exists():
                    raise DatosInvalidos("Ya tienes un cupón con ese código.")
            datos["codigo"] = nuevo
        datos = _validar(datos, cupon)
        _aplicar(request, cupon, datos)
        registrar(
            "tienda.cupon_editado",
            recurso_tipo="cupon",
            recurso_id=cupon.pk,
            resumen=f"Cupón {cupon.codigo} editado",
            detalle={"campos": sorted(datos)},
        )
        return Response(_salida(cupon))

    @extend_schema(tags=TAG, responses={204: None})
    @transaction.atomic
    def delete(self, request, pk: int):
        cupon = _cupon_de(request, pk)
        if UsoCupon.objects.sin_ambito().filter(cupon=cupon).exists():
            raise DatosInvalidos("Este cupón ya se usó: pausa el cupón en vez de borrarlo.")
        cupon.eliminado_en = timezone.now()
        cupon.save(update_fields=["eliminado_en"])
        registrar(
            "tienda.cupon_eliminado",
            recurso_tipo="cupon",
            recurso_id=cupon.pk,
            resumen=f"Cupón {cupon.codigo} eliminado",
        )
        return Response(status=204)


class UsosCuponView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, pk: int):
        cupon = _cupon_de(request, pk)
        usos = (
            UsoCupon.objects.sin_ambito()
            .filter(cupon=cupon)
            .select_related("pedido", "cuenta")
            .order_by("-id")[:50]
        )
        return Response(
            {
                "results": [
                    {
                        "pedido": u.pedido.numero,
                        "cliente": u.cuenta.correo,
                        "monto": _d2(u.monto),
                        "estado": u.estado,
                        "estado_texto": u.get_estado_display(),
                        "fecha": u.creado_en.isoformat(),
                    }
                    for u in usos
                ]
            }
        )


class OpcionesCuponView(_Admin):
    """Categorías y marcas para elegir el alcance de un cupón."""

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        org = request.user.organizacion_id
        activos = {"organizacion_id": org, "estado": EstadoRegistro.ACTIVO}
        return Response(
            {
                "categorias": [
                    {"id": c.pk, "nombre": c.nombre}
                    for c in Categoria.objects.sin_ambito().filter(**activos).order_by("nombre")
                ],
                "marcas": [
                    {"id": m.pk, "nombre": m.nombre}
                    for m in Marca.objects.sin_ambito().filter(**activos).order_by("nombre")
                ],
            }
        )


# ---------------------------------------------------------------------------
# Carrito abandonado (recordatorios por correo)
# ---------------------------------------------------------------------------
class CarritoAbandonadoEntrada(serializers.Serializer):
    activo = serializers.BooleanField(required=False)
    horas_primero = serializers.IntegerField(min_value=1, max_value=72, required=False)
    horas_segundo = serializers.IntegerField(min_value=1, max_value=168, required=False)
    cupon = serializers.IntegerField(min_value=1, required=False, allow_null=True)


def _config_carrito(organizacion_id: int) -> ConfiguracionCarritoAbandonado:
    existente = carrito_abandonado.configuracion(organizacion_id)
    if existente is not None:
        return existente
    return ConfiguracionCarritoAbandonado.objects.sin_ambito().create(
        organizacion_id=organizacion_id
    )


def _salida_carrito(config: ConfiguracionCarritoAbandonado) -> dict:
    ahora = timezone.now()
    ofrecibles = [
        c
        for c in Cupon.objects.sin_ambito().filter(
            organizacion_id=config.organizacion_id, activo=True
        )
        if _estado(c, 0, ahora) in (VIGENTE, PROGRAMADO)
    ]
    return {
        "activo": config.activo,
        "horas_primero": config.horas_primero,
        "horas_segundo": config.horas_segundo,
        "cupon": config.cupon_id,
        "cupones": [{"id": c.pk, "codigo": c.codigo, "nombre": c.nombre} for c in ofrecibles],
        "estadisticas": carrito_abandonado.estadisticas(config.organizacion_id),
    }


class CarritoAbandonadoView(_Admin):
    """Enciende y ajusta los recordatorios de carrito abandonado y muestra sus resultados."""

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(_salida_carrito(_config_carrito(request.user.organizacion_id)))

    @extend_schema(tags=TAG, request=CarritoAbandonadoEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request):
        entrada = CarritoAbandonadoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        config = _config_carrito(request.user.organizacion_id)
        cambios = {}
        for campo in ("activo", "horas_primero", "horas_segundo"):
            if campo in datos:
                setattr(config, campo, datos[campo])
                cambios[campo] = datos[campo]
        if "cupon" in datos:
            if datos["cupon"] is None:
                config.cupon = None
            else:
                cupon = _cupon_de(request, datos["cupon"])
                if not cupon.activo:
                    raise DatosInvalidos("Elige un cupón activo.")
                config.cupon = cupon
            cambios["cupon"] = datos["cupon"]
        config.save()
        if cambios:
            registrar(
                "tienda.carrito_abandonado_configurado",
                recurso_tipo="configuracion_carrito",
                recurso_id=config.pk,
                resumen="Recordatorios de carrito abandonado actualizados",
                detalle=cambios,
            )
        return Response(_salida_carrito(config))
