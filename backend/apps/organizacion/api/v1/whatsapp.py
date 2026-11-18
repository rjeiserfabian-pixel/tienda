"""Pantalla «WhatsApp Business» del panel: la cuenta de Meta del negocio (compartida por la
tienda y el servicio técnico).

El token entra por aquí y se guarda cifrado; nunca sale: ni en las respuestas, ni en el log, ni
en la auditoría. De él solo se muestra que existe y sus últimos 4 caracteres.
"""

import logging

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.organizacion import whatsapp as catalogo
from apps.organizacion.models import ConfiguracionWhatsApp
from apps.seguridad.permissions import PermisoRBAC
from apps.servicio_tecnico import proveedores

logger = logging.getLogger(__name__)

TAG = ["organizacion"]
GESTIONAR = "SEGURIDAD.ORGANIZACION.GESTIONAR"
PLANTILLA_PRUEBA_META = "hello_world"  # la plantilla que Meta trae en toda cuenta nueva


def _config_de(organizacion_id: int) -> ConfiguracionWhatsApp:
    existente = ConfiguracionWhatsApp.objects.filter(organizacion_id=organizacion_id).first()
    if existente is not None:
        return existente
    return ConfiguracionWhatsApp.objects.create(organizacion_id=organizacion_id)


def _faltan_para_activar(config: ConfiguracionWhatsApp) -> list[str]:
    faltan = []
    if not config.telefono_id:
        faltan.append("Falta el ID del número de WhatsApp Business.")
    if not config.token:
        faltan.append("Falta el token de acceso.")
    if not any(str(v).strip() for v in (config.plantillas or {}).values()):
        faltan.append("Falta al menos una plantilla aprobada por Meta.")
    return faltan


def _salida(config: ConfiguracionWhatsApp) -> dict:
    token = config.token
    return {
        "modo": config.modo,
        "numero": config.numero,
        "telefono_id": config.telefono_id,
        "tiene_token": bool(token),
        "token_final": token[-4:] if token else "",
        "version_api": config.version_api,
        "idioma": config.idioma,
        "plantillas": {k: v for k, v in (config.plantillas or {}).items() if k in catalogo.CLAVES},
        "faltan_para_activar": _faltan_para_activar(config),
        "eventos": catalogo.catalogo(),
    }


class WhatsAppEntrada(serializers.Serializer):
    modo = serializers.ChoiceField(choices=ConfiguracionWhatsApp.Modo.choices, required=False)
    numero = serializers.CharField(max_length=20, required=False, allow_blank=True)
    telefono_id = serializers.RegexField(
        r"^\d{5,40}$", required=False, allow_blank=True, error_messages={"invalid": "Solo números."}
    )
    # Solo escritura: vacío o ausente = no cambia.
    token = serializers.CharField(
        max_length=600, required=False, allow_blank=True, write_only=True, trim_whitespace=True
    )
    quitar_token = serializers.BooleanField(required=False)
    version_api = serializers.RegexField(r"^v\d{1,2}\.\d$", required=False)
    idioma = serializers.RegexField(r"^[a-z]{2}(_[A-Z]{2})?$", required=False)
    plantillas = serializers.DictField(
        child=serializers.CharField(max_length=80, allow_blank=True), required=False
    )

    def validate_plantillas(self, valor):
        limpias = {}
        for clave, nombre in valor.items():
            if clave not in catalogo.CLAVES:
                raise ValidationError(f"«{clave}» no es un aviso conocido.")
            nombre = nombre.strip()
            if nombre and not catalogo.nombre_de_plantilla_valido(nombre):
                raise ValidationError(
                    f"La plantilla de «{clave}» solo puede tener minúsculas, números y guion bajo."
                )
            limpias[clave] = nombre
        return limpias


class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = {"get": GESTIONAR, "patch": GESTIONAR, "post": GESTIONAR}

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización, no de una empresa

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class WhatsAppView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(_salida(_config_de(request.user.organizacion_id)))

    @extend_schema(tags=TAG, request=WhatsAppEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request):
        entrada = WhatsAppEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        config = _config_de(request.user.organizacion_id)
        cambios: dict = {}

        for campo in ("numero", "telefono_id", "version_api", "idioma"):
            if campo in datos:
                setattr(config, campo, datos[campo].strip())
                cambios[campo] = getattr(config, campo)
        if "plantillas" in datos:
            actuales = dict(config.plantillas or {})
            actuales.update(datos["plantillas"])
            config.plantillas = {k: v for k, v in actuales.items() if v}
            cambios["plantillas"] = sorted(config.plantillas)  # solo cuáles, no hace falta más
        if datos.get("quitar_token"):
            config.token = ""
            cambios["clave_acceso"] = "quitada"
        elif datos.get("token"):
            config.token = datos["token"].strip()
            cambios["clave_acceso"] = "cambiada"  # nunca el valor

        if "modo" in datos:
            if datos["modo"] == ConfiguracionWhatsApp.Modo.ACTIVO:
                faltan = _faltan_para_activar(config)
                if faltan:
                    raise ValidationError({"modo": " ".join(faltan)})
            config.modo = datos["modo"]
            cambios["modo"] = datos["modo"]
        elif config.modo == ConfiguracionWhatsApp.Modo.ACTIVO and _faltan_para_activar(config):
            config.modo = ConfiguracionWhatsApp.Modo.APAGADO  # se quitó algo esencial: se apaga
            cambios["modo"] = ConfiguracionWhatsApp.Modo.APAGADO

        config.save()
        if cambios:
            registrar(
                "organizacion.whatsapp_configurado",
                recurso_tipo="configuracion_whatsapp",
                recurso_id=config.pk,
                resumen="Configuración de WhatsApp Business actualizada",
                detalle=cambios,
            )
        return Response(_salida(config))


class ProbarEntrada(serializers.Serializer):
    telefono = serializers.CharField(max_length=30)


class ProbarWhatsAppView(_Admin):
    """Manda un mensaje de prueba a un número (para comprobar que la cuenta funciona)."""

    @extend_schema(tags=TAG, request=ProbarEntrada, responses={200: dict})
    def post(self, request):
        entrada = ProbarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        telefono = catalogo.normalizar_telefono(entrada.validated_data["telefono"])
        if telefono is None:
            raise ValidationError({"telefono": "Escribe un número de celular válido."})
        config = _config_de(request.user.organizacion_id)
        proveedor = proveedores.obtener(request.user.organizacion_id)
        if proveedor.nombre == "apagado":
            raise ValidationError({"modo": "WhatsApp está apagado: elige «Prueba» o «Activo»."})
        if proveedor.nombre == "meta" and not proveedor.configurado():
            faltan = " ".join(_faltan_para_activar(config)) or "Falta configurar la cuenta."
            raise ValidationError({"modo": faltan})
        mensaje = proveedores.Mensaje(
            telefono=telefono, evento=catalogo.PRUEBA, texto="Mensaje de prueba", parametros=()
        )
        if proveedor.nombre == "meta" and not proveedor._plantilla(catalogo.PRUEBA):
            # Sin plantilla propia para la prueba se usa la que Meta trae de fábrica
            # (va en inglés y sin variables).
            proveedor._cuenta.plantillas = {
                **(config.plantillas or {}),
                catalogo.PRUEBA: PLANTILLA_PRUEBA_META,
            }
            mensaje = proveedores.Mensaje(
                telefono=telefono,
                evento=catalogo.PRUEBA,
                texto="Mensaje de prueba",
                parametros=(),
                idioma="en_US",
            )
        try:
            externo = proveedor.enviar(mensaje)
            ok = True
            texto = "Mensaje enviado." if proveedor.nombre == "meta" else "Prueba simulada."
        except (proveedores.ErrorProveedor, proveedores.ErrorTemporal) as error:
            ok, texto, externo = False, str(error)[:200], ""
        registrar(
            "organizacion.whatsapp_probado",
            recurso_tipo="configuracion_whatsapp",
            recurso_id=config.pk,
            resumen="Prueba de WhatsApp Business",
            detalle={"ok": ok, "proveedor": proveedor.nombre},
        )
        return Response({"ok": ok, "mensaje": texto, "referencia": externo})
