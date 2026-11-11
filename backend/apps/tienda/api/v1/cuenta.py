"""API de la cuenta del cliente de la tienda: registro, ingreso, perfil y direcciones.

Sesión por cookie HttpOnly (``tienda_sesion``). Como el navegador la envía sola, las operaciones que
cambian datos exigen además la cabecera ``X-Requested-With: tienda``: un sitio ajeno no puede
ponerla (el navegador pediría permiso por CORS y esta API no se lo da), lo que cierra el CSRF.
Nada de aquí se guarda en caché y ninguna respuesta incluye datos de otros clientes.
"""

import logging
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import LoginThrottle, TiendaCuentaThrottle
from apps.core.utils.red import ip_cliente
from apps.mantenimiento.models import Ubigeo
from apps.tienda import catalogo, cuentas
from apps.tienda.exceptions import DatosInvalidos, SesionNoValida, SolicitudNoPermitida
from apps.tienda.models import CuentaCliente, DireccionCuenta

from .publica import TiendaNoDisponible

logger = logging.getLogger(__name__)

TAG = ["tienda-cuenta"]
COOKIE = "tienda_sesion"
MAX_DIRECCIONES = 10
SEGUROS = {"GET", "HEAD", "OPTIONS"}
RESPUESTA_GENERICA = {"detalle": "Si los datos son correctos, te enviamos un correo."}
CELULAR = re.compile(r"^\+?\d[\d ]{7,17}$")


def _celular(valor: str) -> str:
    valor = (valor or "").strip()
    if valor and not CELULAR.match(valor):
        raise serializers.ValidationError("Escribe un número de celular válido.")
    return valor


class _Base(APIView):
    """Sin autenticación de DRF: la cuenta se identifica con su propia cookie."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TiendaCuentaThrottle]

    def initial(self, request, *args, **kwargs):
        if request.method not in SEGUROS and request.headers.get("X-Requested-With") != "tienda":
            raise SolicitudNoPermitida()
        super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def organizacion_id(self) -> int:
        ctx = catalogo.contexto()
        if ctx is None:
            raise TiendaNoDisponible()
        return ctx.organizacion_id

    def sesion(self, request) -> tuple[CuentaCliente, object]:
        encontrada = cuentas.cuenta_de_sesion(request.COOKIES.get(COOKIE, ""))
        if encontrada is None:
            raise SesionNoValida()
        cuenta, sesion = encontrada
        if cuenta.organizacion_id != self.organizacion_id():
            raise SesionNoValida()
        return cuenta, sesion


def _poner_cookie(respuesta: Response, token: str) -> None:
    respuesta.set_cookie(
        COOKIE,
        token,
        max_age=settings.TIENDA_SESION_DIAS * 24 * 3600,
        httponly=True,
        secure=settings.TIENDA_COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )


def _quitar_cookie(respuesta: Response) -> None:
    respuesta.delete_cookie(COOKIE, path="/", samesite="Lax")


def perfil_de(cuenta: CuentaCliente) -> dict:
    return {
        "correo": cuenta.correo,
        "nombres": cuenta.nombres,
        "apellidos": cuenta.apellidos,
        "celular": cuenta.celular,
        "correo_verificado": cuenta.verificada,
        "acepta_ofertas": cuenta.acepta_ofertas,
    }


# ---------------------------------------------------------------------------
# Registro, ingreso y recuperación
# ---------------------------------------------------------------------------
class RegistroEntrada(serializers.Serializer):
    correo = serializers.EmailField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    nombres = serializers.CharField(max_length=100)
    apellidos = serializers.CharField(max_length=100)
    celular = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    acepta_terminos = serializers.BooleanField()
    acepta_ofertas = serializers.BooleanField(required=False, default=False)

    def validate_celular(self, valor):
        return _celular(valor)

    def validate_acepta_terminos(self, valor):
        if not valor:
            raise serializers.ValidationError("Debes aceptar los términos para crear tu cuenta.")
        return valor

    def validate(self, datos):
        datos["nombres"] = " ".join(datos["nombres"].split())
        datos["apellidos"] = " ".join(datos["apellidos"].split())
        if not datos["nombres"] or not datos["apellidos"]:
            raise serializers.ValidationError("Escribe tu nombre y tus apellidos.")
        return datos


class RegistroView(_Base):
    throttle_classes = [LoginThrottle]

    @extend_schema(tags=TAG, request=RegistroEntrada, responses={202: dict})
    def post(self, request):
        entrada = RegistroEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        cuentas.registrar(
            self.organizacion_id(),
            correo=datos["correo"],
            password=datos["password"],
            nombres=datos["nombres"],
            apellidos=datos["apellidos"],
            celular=datos["celular"],
            acepta_ofertas=datos["acepta_ofertas"],
            ip=ip_cliente(request),
        )
        return Response(RESPUESTA_GENERICA, status=202)


class TokenEntrada(serializers.Serializer):
    token = serializers.CharField(max_length=100)


class VerificarView(_Base):
    throttle_classes = [LoginThrottle]

    @extend_schema(tags=TAG, request=TokenEntrada, responses={200: dict})
    def post(self, request):
        entrada = TokenEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        cuentas.verificar_correo(entrada.validated_data["token"])
        return Response({"detalle": "Tu correo quedó confirmado."})


class ReenviarVerificacionView(_Base):
    @extend_schema(tags=TAG, responses={202: dict})
    def post(self, request):
        cuenta, _ = self.sesion(request)
        cuentas.reenviar_verificacion(cuenta, ip_cliente(request))
        return Response(RESPUESTA_GENERICA, status=202)


class IngresoEntrada(serializers.Serializer):
    correo = serializers.EmailField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class IngresarView(_Base):
    throttle_classes = [LoginThrottle]

    @extend_schema(tags=TAG, request=IngresoEntrada, responses={200: dict})
    def post(self, request):
        entrada = IngresoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        token, cuenta = cuentas.ingresar(
            self.organizacion_id(),
            correo=entrada.validated_data["correo"],
            password=entrada.validated_data["password"],
            ip=ip_cliente(request),
            dispositivo=request.META.get("HTTP_USER_AGENT", ""),
        )
        respuesta = Response(perfil_de(cuenta))
        _poner_cookie(respuesta, token)
        return respuesta


class SalirView(_Base):
    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request):
        cuentas.salir(request.COOKIES.get(COOKIE, ""))
        respuesta = Response({"detalle": "Saliste de tu cuenta."})
        _quitar_cookie(respuesta)
        return respuesta


class CorreoEntrada(serializers.Serializer):
    correo = serializers.EmailField(max_length=150)


class RecuperarView(_Base):
    throttle_classes = [LoginThrottle]

    @extend_schema(tags=TAG, request=CorreoEntrada, responses={202: dict})
    def post(self, request):
        entrada = CorreoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        cuentas.solicitar_recuperacion(
            self.organizacion_id(), entrada.validated_data["correo"], ip_cliente(request)
        )
        return Response(RESPUESTA_GENERICA, status=202)


class NuevaClaveEntrada(serializers.Serializer):
    token = serializers.CharField(max_length=100)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class RecuperarConfirmarView(_Base):
    throttle_classes = [LoginThrottle]

    @extend_schema(tags=TAG, request=NuevaClaveEntrada, responses={200: dict})
    def post(self, request):
        entrada = NuevaClaveEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        cuentas.recuperar_password(
            entrada.validated_data["token"], entrada.validated_data["password"]
        )
        return Response({"detalle": "Listo: ya puedes ingresar con tu nueva contraseña."})


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
class PerfilEntrada(serializers.Serializer):
    nombres = serializers.CharField(max_length=100, required=False)
    apellidos = serializers.CharField(max_length=100, required=False)
    celular = serializers.CharField(max_length=20, required=False, allow_blank=True)
    acepta_ofertas = serializers.BooleanField(required=False)

    def validate_celular(self, valor):
        return _celular(valor)


class PerfilView(_Base):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        cuenta, _ = self.sesion(request)
        return Response(perfil_de(cuenta))

    @extend_schema(tags=TAG, request=PerfilEntrada, responses={200: dict})
    def patch(self, request):
        cuenta, _ = self.sesion(request)
        entrada = PerfilEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        for campo, valor in entrada.validated_data.items():
            if isinstance(valor, str):
                valor = " ".join(valor.split())
                if campo in ("nombres", "apellidos") and not valor:
                    raise DatosInvalidos("No puedes dejar el nombre vacío.")
            setattr(cuenta, campo, valor)
        cuenta.save()
        return Response(perfil_de(cuenta))


class SesionView(_Base):
    """¿Hay sesión? Responde 200 siempre (así el navegador no registra un error por cada visita)."""

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        encontrada = cuentas.cuenta_de_sesion(request.COOKIES.get(COOKIE, ""))
        if encontrada is None or encontrada[0].organizacion_id != self.organizacion_id():
            return Response({"autenticado": False, "perfil": None})
        return Response({"autenticado": True, "perfil": perfil_de(encontrada[0])})


class CambiarPasswordEntrada(serializers.Serializer):
    actual = serializers.CharField(max_length=128, trim_whitespace=False)
    nueva = serializers.CharField(max_length=128, trim_whitespace=False)


class CambiarPasswordView(_Base):
    throttle_classes = [LoginThrottle]

    @extend_schema(tags=TAG, request=CambiarPasswordEntrada, responses={200: dict})
    def post(self, request):
        cuenta, sesion = self.sesion(request)
        entrada = CambiarPasswordEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        cuentas.cambiar_password(
            cuenta, sesion, entrada.validated_data["actual"], entrada.validated_data["nueva"]
        )
        return Response({"detalle": "Contraseña actualizada. Se cerraron tus otras sesiones."})


# ---------------------------------------------------------------------------
# Direcciones de entrega
# ---------------------------------------------------------------------------
class DireccionEntrada(serializers.Serializer):
    etiqueta = serializers.CharField(max_length=40, required=False, allow_blank=True)
    receptor = serializers.CharField(max_length=150)
    celular = serializers.CharField(max_length=20)
    ubigeo = serializers.RegexField(r"^\d{6}$")
    direccion = serializers.CharField(max_length=250)
    referencia = serializers.CharField(max_length=200, required=False, allow_blank=True)
    es_principal = serializers.BooleanField(required=False)

    def validate_celular(self, valor):
        valor = _celular(valor)
        if not valor:
            raise serializers.ValidationError("Escribe un celular de contacto para la entrega.")
        return valor

    def validate_ubigeo(self, valor):
        if not Ubigeo.objects.filter(codigo=valor).exists():
            raise serializers.ValidationError("Elige un distrito de la lista.")
        return valor

    def validate(self, datos):
        for campo, valor in list(datos.items()):
            if isinstance(valor, str):
                datos[campo] = " ".join(valor.split())
        for obligatorio in ("receptor", "direccion"):
            if obligatorio in datos and not datos[obligatorio]:
                raise serializers.ValidationError({obligatorio: "Este dato es obligatorio."})
        return datos


def direccion_de(d: DireccionCuenta, nombres_ubigeo: dict | None = None) -> dict:
    ub = (nombres_ubigeo or {}).get(d.ubigeo)
    if ub is None:
        u = Ubigeo.objects.filter(codigo=d.ubigeo).first()
        ub = u.nombre_completo if u else ""
    return {
        "id": d.pk,
        "etiqueta": d.etiqueta,
        "receptor": d.receptor,
        "celular": d.celular,
        "ubigeo": d.ubigeo,
        "ubicacion": ub,
        "direccion": d.direccion,
        "referencia": d.referencia,
        "es_principal": d.es_principal,
    }


def _direcciones_de(cuenta: CuentaCliente):
    return DireccionCuenta.objects.sin_ambito().filter(cuenta=cuenta, eliminado_en__isnull=True)


def _salida_direcciones(cuenta: CuentaCliente) -> list[dict]:
    filas = list(_direcciones_de(cuenta).order_by("-es_principal", "id"))
    nombres = {
        u.codigo: u.nombre_completo
        for u in Ubigeo.objects.filter(codigo__in={f.ubigeo for f in filas})
    }
    return [direccion_de(f, nombres) for f in filas]


def _dejar_una_principal(cuenta: CuentaCliente, principal_id: int | None) -> None:
    """Como máximo una dirección principal; si hay direcciones y ninguna lo es, la más antigua."""
    filas = _direcciones_de(cuenta).order_by("id")
    if principal_id is None:
        if not filas.filter(es_principal=True).exists():
            primera = filas.first()
            if primera:
                filas.filter(pk=primera.pk).update(es_principal=True)
        return
    filas.exclude(pk=principal_id).filter(es_principal=True).update(es_principal=False)
    filas.filter(pk=principal_id).update(es_principal=True)


class DireccionesView(_Base):
    @extend_schema(tags=TAG, responses={200: list})
    def get(self, request):
        cuenta, _ = self.sesion(request)
        return Response(_salida_direcciones(cuenta))

    @extend_schema(tags=TAG, request=DireccionEntrada, responses={201: dict})
    @transaction.atomic
    def post(self, request):
        cuenta, _ = self.sesion(request)
        entrada = DireccionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        # Se bloquea la cuenta al contar y crear: dos pedidos a la vez no pasan el tope.
        CuentaCliente.objects.sin_ambito().select_for_update().get(pk=cuenta.pk)
        if _direcciones_de(cuenta).count() >= MAX_DIRECCIONES:
            raise DatosInvalidos(f"Puedes guardar hasta {MAX_DIRECCIONES} direcciones.")
        datos = entrada.validated_data
        es_principal = (
            bool(datos.pop("es_principal", False)) or not _direcciones_de(cuenta).exists()
        )
        nueva = DireccionCuenta.objects.sin_ambito().create(
            organizacion_id=cuenta.organizacion_id, cuenta=cuenta, **datos
        )
        _dejar_una_principal(cuenta, nueva.pk if es_principal else None)
        return Response(_salida_direcciones(cuenta), status=201)


class DireccionView(_Base):
    def _direccion(self, cuenta, pk: int) -> DireccionCuenta:
        direccion = _direcciones_de(cuenta).filter(pk=pk).first()
        if direccion is None:
            raise DatosInvalidos("No encontramos esa dirección.")
        return direccion

    @extend_schema(tags=TAG, request=DireccionEntrada, responses={200: list})
    @transaction.atomic
    def patch(self, request, pk: int):
        cuenta, _ = self.sesion(request)
        direccion = self._direccion(cuenta, pk)
        entrada = DireccionEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        principal = datos.pop("es_principal", None)
        for campo, valor in datos.items():
            setattr(direccion, campo, valor)
        direccion.save()
        if principal:
            _dejar_una_principal(cuenta, direccion.pk)
        return Response(_salida_direcciones(cuenta))

    @extend_schema(tags=TAG, responses={200: list})
    @transaction.atomic
    def delete(self, request, pk: int):
        cuenta, _ = self.sesion(request)
        direccion = self._direccion(cuenta, pk)
        # Se conserva el registro (un pedido futuro puede haber usado esta dirección).
        direccion.eliminado_en = timezone.now()
        direccion.es_principal = False
        direccion.save()
        _dejar_una_principal(cuenta, None)
        return Response(_salida_direcciones(cuenta))
