"""Configuración de los cobros en línea (Culqi) desde el panel, y lo público que necesita la tienda.

La llave secreta entra por aquí y se guarda cifrada; nunca sale: ni en las respuestas, ni en el log,
ni en la auditoría. De ella solo se muestra que existe y sus últimos 4 caracteres.
"""

import logging
from decimal import Decimal

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.organizacion.models import Empresa
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import catalogo, culqi, transferencias
from apps.tienda.models import ConfiguracionPago

from .publica import _Publica

logger = logging.getLogger(__name__)

TAG = ["tienda"]
CONFIGURAR = "TIENDA.PAGOS.CONFIGURAR"


def _config_de(organizacion_id: int) -> ConfiguracionPago:
    existente = ConfiguracionPago.objects.filter(organizacion_id=organizacion_id).first()
    if existente is not None:
        return existente
    return ConfiguracionPago.objects.create(organizacion_id=organizacion_id)


def _empresas(organizacion_id: int):
    return Empresa.objects.sin_ambito().filter(organizacion_id=organizacion_id, estado="ACTIVO")


def _problemas_para_activar(config: ConfiguracionPago) -> list[str]:
    faltan = []
    if not config.culqi_llave_publica:
        faltan.append("Falta la llave pública.")
    if not config.culqi_llave_secreta:
        faltan.append("Falta la llave secreta.")
    if config.empresa_cobra_id is None:
        faltan.append("Elige la empresa cuya cuenta de Culqi recibe los pagos.")
    if not (config.acepta_tarjeta or config.acepta_yape):
        faltan.append("Activa al menos un medio de pago (tarjeta o Yape).")
    return faltan


def _salida(config: ConfiguracionPago) -> dict:
    secreta = config.culqi_llave_secreta
    return {
        "culqi_activo": config.culqi_activo,
        "culqi_modo": config.culqi_modo,
        "culqi_llave_publica": config.culqi_llave_publica,
        "tiene_llave_secreta": bool(secreta),
        "llave_secreta_final": secreta[-4:] if secreta else "",
        "acepta_tarjeta": config.acepta_tarjeta,
        "acepta_yape": config.acepta_yape,
        "empresa_cobra": config.empresa_cobra_id,
        "adelanto": {
            "activo": config.adelanto_activo,
            "porcentaje": format(config.adelanto_pct, "f"),
            "minimo": format(config.adelanto_minimo, "f"),
            "dias": config.adelanto_dias,
            "si_no_recoge": config.adelanto_si_no_recoge,
            "penalidad_pct": format(config.adelanto_penalidad_pct, "f"),
            "comision_pct": format(config.comision_pasarela_pct, "f"),
            "comision_fija": format(config.comision_pasarela_fija, "f"),
        },
        "transferencia": {
            "activa": config.transferencia_activa,
            "horas": config.transferencia_horas,
            "instrucciones": config.transferencia_instrucciones,
            "cuentas": sorted(transferencias.ids_de_cuentas(config)),
        },
        "faltan_para_activar": _problemas_para_activar(config),
        "opciones": {
            "cuentas": [
                {
                    "id": c.pk,
                    "nombre": c.nombre,
                    "banco": c.banco,
                    "numero": c.numero_cuenta,
                    "cci": c.cci,
                    "empresa": c.empresa.razon_social,
                }
                for c in transferencias.cuentas_posibles(config.organizacion_id)
            ],
            "empresas": [
                {"id": e.pk, "razon_social": e.razon_social, "ruc": e.ruc}
                for e in _empresas(config.organizacion_id).order_by("razon_social")
            ],
        },
    }


class PagosEntrada(serializers.Serializer):
    culqi_activo = serializers.BooleanField(required=False)
    culqi_modo = serializers.ChoiceField(choices=ConfiguracionPago.Modo.choices, required=False)
    culqi_llave_publica = serializers.CharField(max_length=80, required=False, allow_blank=True)
    # Solo escritura: vacío o ausente = no cambia.
    culqi_llave_secreta = serializers.CharField(
        max_length=80, required=False, allow_blank=True, write_only=True, trim_whitespace=True
    )
    quitar_llave_secreta = serializers.BooleanField(required=False)
    acepta_tarjeta = serializers.BooleanField(required=False)
    acepta_yape = serializers.BooleanField(required=False)
    empresa_cobra = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    # Transferencia o depósito con comprobante
    transferencia_activa = serializers.BooleanField(required=False)
    transferencia_horas = serializers.IntegerField(min_value=1, max_value=168, required=False)
    transferencia_instrucciones = serializers.CharField(
        max_length=600, required=False, allow_blank=True
    )
    cuentas_transferencia = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=20
    )
    # Pago con adelanto (solo para pedidos que se recogen en tienda)
    adelanto_activo = serializers.BooleanField(required=False)
    adelanto_pct = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("1"),
        max_value=Decimal("90"),
        required=False,
    )
    adelanto_minimo = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False
    )
    adelanto_dias = serializers.IntegerField(min_value=1, max_value=60, required=False)
    adelanto_si_no_recoge = serializers.ChoiceField(
        choices=ConfiguracionPago.SiNoRecoge.choices, required=False
    )
    adelanto_penalidad_pct = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
    )
    comision_pasarela_pct = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("30"),
        required=False,
    )
    comision_pasarela_fija = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("50"),
        required=False,
    )


class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = {"get": CONFIGURAR, "patch": CONFIGURAR, "post": CONFIGURAR}

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización, no de una empresa

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class PagosView(_Admin):
    @staticmethod
    def _transferencia(config, datos, cambios) -> None:
        """Guarda los datos de la transferencia; para activarla hace falta al menos una cuenta."""
        for campo in ("transferencia_horas", "transferencia_instrucciones"):
            if campo in datos:
                valor = datos[campo]
                if isinstance(valor, str):
                    valor = " ".join(valor.split())
                setattr(config, campo, valor)
                cambios[campo] = valor
        if "cuentas_transferencia" in datos:
            ids = set(datos["cuentas_transferencia"])
            validas = {
                c.pk for c in transferencias.cuentas_posibles(config.organizacion_id) if c.pk in ids
            }
            if validas != ids:
                raise ValidationError(
                    {"cuentas_transferencia": "Elige solo cuentas de banco o billetera en soles."}
                )
            config.pendientes_cuentas = validas
            cambios["cuentas_transferencia"] = sorted(validas)
        if "transferencia_activa" in datos:
            config.transferencia_activa = datos["transferencia_activa"]
            cambios["transferencia_activa"] = datos["transferencia_activa"]
        if config.transferencia_activa:
            elegidas = getattr(config, "pendientes_cuentas", None)
            if elegidas is None:
                elegidas = transferencias.ids_de_cuentas(config)
            if not elegidas:
                raise ValidationError(
                    {"transferencia_activa": "Elige al menos una cuenta para recibir pagos."}
                )

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(_salida(_config_de(request.user.organizacion_id)))

    @extend_schema(tags=TAG, request=PagosEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request):
        entrada = PagosEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        config = _config_de(request.user.organizacion_id)
        cambios: dict = {}

        for campo in (
            "adelanto_activo",
            "adelanto_pct",
            "adelanto_minimo",
            "adelanto_dias",
            "adelanto_si_no_recoge",
            "adelanto_penalidad_pct",
            "comision_pasarela_pct",
            "comision_pasarela_fija",
        ):
            if campo in datos:
                setattr(config, campo, datos[campo])
                cambios[campo] = str(datos[campo])
        for campo in ("culqi_modo", "acepta_tarjeta", "acepta_yape"):
            if campo in datos:
                setattr(config, campo, datos[campo])
                cambios[campo] = datos[campo]
        if "culqi_llave_publica" in datos:
            config.culqi_llave_publica = datos["culqi_llave_publica"].strip()
            cambios["culqi_llave_publica"] = config.culqi_llave_publica
        if datos.get("quitar_llave_secreta"):
            config.culqi_llave_secreta = ""
            config.culqi_activo = False  # sin llave no se puede cobrar
            cambios["llave_secreta"] = "quitada"
        elif datos.get("culqi_llave_secreta"):
            config.culqi_llave_secreta = datos["culqi_llave_secreta"].strip()
            cambios["llave_secreta"] = "cambiada"  # nunca el valor
        if "empresa_cobra" in datos:
            empresa_id = datos["empresa_cobra"]
            if (
                empresa_id is not None
                and not _empresas(config.organizacion_id).filter(pk=empresa_id).exists()
            ):
                raise ValidationError(
                    {"empresa_cobra": "Elige una empresa activa de tu organización."}
                )
            config.empresa_cobra_id = empresa_id
            cambios["empresa_cobra"] = empresa_id

        self._transferencia(config, datos, cambios)

        mensaje = culqi.validar_llaves(
            config.culqi_modo, config.culqi_llave_publica, config.culqi_llave_secreta
        )
        if mensaje:
            raise ValidationError(
                {"culqi_llave_publica" if "pública" in mensaje else "culqi_llave_secreta": mensaje}
            )

        if "culqi_activo" in datos:
            if datos["culqi_activo"]:
                faltan = _problemas_para_activar(config)
                if faltan:
                    raise ValidationError({"culqi_activo": " ".join(faltan)})
            config.culqi_activo = datos["culqi_activo"]
            cambios["culqi_activo"] = datos["culqi_activo"]
        elif config.culqi_activo and _problemas_para_activar(config):
            config.culqi_activo = False  # algo esencial se quitó: se apaga para no cobrar mal
            cambios["culqi_activo"] = False

        config.save()
        if getattr(config, "pendientes_cuentas", None) is not None:
            config.cuentas_transferencia.set(config.pendientes_cuentas)
        if cambios:
            registrar(
                "tienda.pagos_configurados",
                recurso_tipo="configuracion_pago",
                recurso_id=config.pk,
                resumen="Configuración de cobros en línea actualizada",
                detalle=cambios,
            )
        transaction.on_commit(catalogo.invalidar)
        return Response(_salida(config))


class ProbarPagosView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request):
        config = _config_de(request.user.organizacion_id)
        if not config.culqi_llave_secreta:
            raise ValidationError({"culqi_llave_secreta": "Primero guarda la llave secreta."})
        ok, mensaje = culqi.probar_conexion(config.culqi_llave_secreta)
        registrar(
            "tienda.pagos_probados",
            recurso_tipo="configuracion_pago",
            recurso_id=config.pk,
            resumen="Prueba de conexión con Culqi",
            detalle={"ok": ok},
        )
        return Response({"ok": ok, "mensaje": mensaje})


class PagosPublicaView(_Publica):
    """Lo que el navegador necesita para abrir el cobro: solo la llave PÚBLICA y los medios."""

    ttl = 60

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        ctx = self.contexto()

        def construir():
            config = (
                ConfiguracionPago.objects.sin_ambito()
                .filter(organizacion_id=ctx.organizacion_id)
                .first()
            )
            transferencia = transferencias.info_publica(ctx.organizacion_id)
            if config is None or not config.culqi_activo or _problemas_para_activar(config):
                return {"activo": False, "transferencia": transferencia}
            return {
                "activo": True,
                "proveedor": "culqi",
                "modo": config.culqi_modo,
                "llave_publica": config.culqi_llave_publica,
                "tarjeta": config.acepta_tarjeta,
                "yape": config.acepta_yape,
                "transferencia": transferencia,
            }

        return self.responder(request, construir)
