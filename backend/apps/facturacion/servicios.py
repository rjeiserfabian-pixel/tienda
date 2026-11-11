"""Configuración de la facturación electrónica y envío de documentos a la API.

El envío tiene tres pasos para no dejar nada a medias ni bloquear la base de datos mientras se
espera a la API:

1. **Reservar** (transacción corta): se bloquea la fila del envío y se marca «enviando». Así dos
   personas no envían el mismo documento a la vez, y un envío colgado se libera a los 2 minutos.
2. **Enviar** (sin transacción abierta): la llamada HTTP, con tiempo máximo.
3. **Cerrar** (transacción corta): se guarda lo que respondió la API.

Lo que se envía lleva las claves SOL: nunca se guarda ni se registra. De la respuesta se descarta
el bloque ``respuesta_sunat`` (trae datos internos de la sesión de SUNAT).
"""

import json
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import Ubigeo
from apps.organizacion.models import ConfiguracionEmpresa, Empresa
from apps.ventas.models import ComprobanteVenta, GuiaRemision, NotaCredito

from . import cliente, constructores
from .exceptions import (
    ConfiguracionIncompleta,
    DocumentoNoEnviable,
    EnvioEnCurso,
    ErrorConexionSunat,
    FacturacionNoActiva,
    YaEnviado,
)
from .models import EnvioSunat, EstadoEnvio, OrigenDocumento

logger = logging.getLogger(__name__)

ENVIO_COLGADO = timedelta(minutes=2)
TOPE_RESPUESTA = 2_000_000  # caracteres: pasado esto se descartan los archivos de la respuesta

# origen → (modelo, tipos de documento electrónicos que admite)
DOCUMENTOS = {
    OrigenDocumento.COMPROBANTE: (ComprobanteVenta, ("01", "03")),
    OrigenDocumento.NOTA_CREDITO: (NotaCredito, ("07",)),
    OrigenDocumento.GUIA: (GuiaRemision, ("09",)),
}


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
def configuracion_de(empresa: Empresa) -> ConfiguracionEmpresa:
    """La configuración de la empresa (se crea vacía la primera vez)."""
    configuracion = ConfiguracionEmpresa.objects.sin_ambito().filter(empresa=empresa).first()
    if configuracion is None:
        configuracion = ConfiguracionEmpresa.objects.sin_ambito().create(empresa=empresa)
    return configuracion


def _pista(texto: str) -> str:
    """«SISTEMA2» → «SI*****»: se reconoce, pero no se revela."""
    return "" if not texto else texto[:2] + "*" * max(len(texto) - 2, 3)


def configuracion_json(empresa: Empresa, config: ConfiguracionEmpresa) -> dict:
    """Lo que ve el panel. Las claves NUNCA salen: solo si están puestas."""
    ubigeo = Ubigeo.objects.filter(codigo=config.ubigeo_fiscal).first()
    return {
        "empresa": empresa.pk,
        "activo": config.sunat_activo,
        "modo": config.modo_sunat,
        "usuario_sol": _pista(config.sunat_usuario_sol),
        "clave_sol_puesta": bool(config.sunat_clave_sol),
        "gre_client_id_puesto": bool(config.sunat_gre_client_id),
        "gre_client_secret_puesto": bool(config.sunat_gre_client_secret),
        "direccion_fiscal": empresa.direccion_fiscal,
        "ubigeo_fiscal": config.ubigeo_fiscal,
        "ubigeo_nombre": ubigeo.nombre_completo if ubigeo else "",
        "urbanizacion": config.urbanizacion,
        "codigo_sunat_defecto": config.codigo_sunat_defecto,
        "faltantes": constructores.faltantes(empresa, config),
        "faltantes_guia": constructores.faltantes(empresa, config, guia=True),
    }


_SECRETOS = {
    "usuario_sol": "sunat_usuario_sol",
    "clave_sol": "sunat_clave_sol",
    "gre_client_id": "sunat_gre_client_id",
    "gre_client_secret": "sunat_gre_client_secret",
}
_COMUNES = {
    "modo": "modo_sunat",
    "ubigeo_fiscal": "ubigeo_fiscal",
    "urbanizacion": "urbanizacion",
    "codigo_sunat_defecto": "codigo_sunat_defecto",
}


@transaction.atomic
def actualizar_configuracion(empresa: Empresa, datos: dict) -> ConfiguracionEmpresa:
    """Cambia la configuración. Un secreto vacío o ausente NO cambia el que ya está guardado."""
    _exigir_empresa(empresa)
    config = (
        ConfiguracionEmpresa.objects.sin_ambito()
        .select_for_update()
        .filter(empresa=empresa)
        .first()
    )
    if config is None:
        config = ConfiguracionEmpresa.objects.sin_ambito().create(empresa=empresa)
    cambios = []
    for clave, campo in _SECRETOS.items():
        if datos.get(clave):
            setattr(config, campo, datos[clave])
            cambios.append(clave)
    for clave, campo in _COMUNES.items():
        if clave in datos and getattr(config, campo) != datos[clave]:
            setattr(config, campo, datos[clave])
            cambios.append(clave)
    ubigeo = datos.get("ubigeo_fiscal")
    if ubigeo and not Ubigeo.objects.filter(codigo=ubigeo).exists():
        raise ConfiguracionIncompleta("Ese ubigeo no existe en la lista del INEI.")
    antes_activo = config.sunat_activo
    if "activo" in datos and datos["activo"] != config.sunat_activo:
        if datos["activo"]:
            config.sunat_activo = True  # se prueba abajo con lo que quedó guardado
            falta = constructores.faltantes(empresa, config)
            if falta:
                raise ConfiguracionIncompleta("Antes de activarla falta: " + "; ".join(falta) + ".")
        config.sunat_activo = datos["activo"]
        cambios.append("activo")
    if cambios:
        config.save()
        registrar(
            "facturacion.configurada",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen="Se cambió la configuración de la facturación electrónica de "
            f"{empresa.razon_social}",
            # Solo QUÉ cambió, nunca los valores de las claves.
            detalle={"campos": cambios, "activo_antes": antes_activo, "modo": config.modo_sunat},
        )
    return config


def _exigir_empresa(empresa: Empresa) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa.pk):
        raise EmpresaNoHabilitada()


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
def documento(origen: str, pk: int):
    """El documento (dentro de las empresas habilitadas), o ``None``."""
    modelo, _ = DOCUMENTOS[origen]
    consulta = modelo.objects.filter(pk=pk).select_related("tipo_comprobante", "serie_comprobante")
    if origen == OrigenDocumento.COMPROBANTE:
        consulta = consulta.select_related("venta__cliente")
    elif origen == OrigenDocumento.NOTA_CREDITO:
        consulta = consulta.select_related("venta__cliente", "comprobante__tipo_comprobante")
    else:
        consulta = consulta.select_related("comprobante__tipo_comprobante")
    return consulta.first()


def _tipo_enviable(origen: str, doc) -> str:
    _, tipos = DOCUMENTOS[origen]
    tipo = doc.tipo_comprobante.codigo
    if tipo not in tipos or not doc.serie_comprobante.es_electronica:
        raise DocumentoNoEnviable("Este documento no es electrónico: su serie no se envía a SUNAT.")
    if doc.estado != "EMITIDO":
        raise DocumentoNoEnviable("El documento está anulado: no se envía.")
    return tipo


def armar(origen: str, doc, *, credenciales: bool, exigir_activo: bool):
    """``(tipo, payload, configuración)`` listo para enviar (o para mostrar, con claves ocultas)."""
    tipo = _tipo_enviable(origen, doc)
    config = configuracion_de(doc.empresa)
    es_guia = origen == OrigenDocumento.GUIA
    if exigir_activo:
        if not config.sunat_activo:
            raise FacturacionNoActiva()
        falta = constructores.faltantes(doc.empresa, config, guia=es_guia)
        if falta:
            raise ConfiguracionIncompleta("Falta configurar: " + "; ".join(falta) + ".")
    bloque = constructores.bloque_empresa(
        doc.empresa, config, credenciales=credenciales, guia=es_guia
    )
    constructor = {
        OrigenDocumento.COMPROBANTE: constructores.armar_comprobante,
        OrigenDocumento.NOTA_CREDITO: constructores.armar_nota_credito,
        OrigenDocumento.GUIA: constructores.armar_guia,
    }[origen]
    return tipo, constructor(doc, bloque, config), config


def vista_previa(origen: str, doc) -> dict:
    """El JSON que se enviaría, con las claves ocultas, y lo que falta configurar."""
    tipo, payload, config = armar(origen, doc, credenciales=False, exigir_activo=False)
    es_guia = origen == OrigenDocumento.GUIA
    return {
        "tipo_documento": tipo,
        "payload": payload,
        "faltantes": constructores.faltantes(doc.empresa, config, guia=es_guia),
        "activo": config.sunat_activo,
        "modo": config.modo_sunat,
    }


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------
def _reservar(origen: str, doc, tipo: str, modo: str) -> EnvioSunat:
    with transaction.atomic():
        envio = (
            EnvioSunat.objects.select_for_update()
            .filter(empresa=doc.empresa, origen=origen, origen_id=doc.pk)
            .first()
        )
        ahora = timezone.now()
        if envio is None:
            try:
                with transaction.atomic():  # punto de guardado: otra persona pudo crearlo antes
                    envio = EnvioSunat.objects.create(
                        empresa=doc.empresa,
                        origen=origen,
                        origen_id=doc.pk,
                        tipo_documento=tipo,
                        serie=doc.serie,
                        numero=doc.numero,
                    )
            except IntegrityError:
                raise EnvioEnCurso() from None
        else:
            en_curso = envio.estado == EstadoEnvio.EN_PROCESO and (
                envio.iniciado_en is not None and ahora - envio.iniciado_en < ENVIO_COLGADO
            )
            if en_curso:
                raise EnvioEnCurso()
            if envio.estado == EstadoEnvio.ENVIADO:
                raise YaEnviado()
        envio.estado = EstadoEnvio.EN_PROCESO
        envio.intentos += 1
        envio.iniciado_en = ahora
        envio.modo = modo
        envio.save(update_fields=["estado", "intentos", "iniciado_en", "modo"])
        return envio


def _sin_sesion(datos: dict) -> dict:
    """La respuesta sin el bloque con datos de la sesión de SUNAT, y acotada de tamaño."""
    limpia = {k: v for k, v in datos.items() if k != "respuesta_sunat"}
    if len(json.dumps(limpia, default=str)) > TOPE_RESPUESTA:
        limpia = {k: v for k, v in limpia.items() if not str(k).endswith("_base_64")}
    return limpia


def _interpretar(respuesta: cliente.RespuestaApi) -> dict:
    """Lo mínimo que se entiende de la respuesta: si la API la recibió bien o devolvió un error."""
    datos = respuesta.datos
    if datos is None or respuesta.codigo_http >= 400 or "error" not in datos:
        return {
            "estado": EstadoEnvio.ERROR_API,
            "mensaje": f"La API respondió algo inesperado (código {respuesta.codigo_http}).",
        }
    con_error = str(datos.get("error")).strip().lower() == "true"
    return {
        "estado": EstadoEnvio.ERROR_API if con_error else EstadoEnvio.ENVIADO,
        "codigo_respuesta": str(datos.get("respuesta_sunat_codigo") or "")[:20],
        "mensaje": str(datos.get("respuesta_sunat_descripcion") or datos.get("mensaje") or "")[
            :500
        ],
        "ticket": str(datos.get("num_ticket") or "")[:80],
        "codigo_hash": str(datos.get("codigo_hash") or "")[:80],
        "respuesta": _sin_sesion(datos),
    }


def _cerrar(envio: EnvioSunat, *, estado: str, **campos) -> EnvioSunat:
    with transaction.atomic():
        envio = EnvioSunat.objects.select_for_update().get(pk=envio.pk)
        envio.estado = estado
        envio.enviado_en = timezone.now()
        for campo, valor in campos.items():
            setattr(envio, campo, valor)
        envio.save()
        registrar(
            "facturacion.envio",
            recurso_tipo="envio_sunat",
            recurso_id=envio.pk,
            empresa_id=envio.empresa_id,
            resumen=f"Envío de {envio.serie}-{envio.numero:08d} a SUNAT: "
            f"{envio.get_estado_display()}",
            detalle={
                "documento": f"{envio.tipo_documento} {envio.serie}-{envio.numero:08d}",
                "estado": estado,
                "intentos": envio.intentos,
                "modo": envio.modo,
                "codigo_respuesta": envio.codigo_respuesta,
            },
        )
    return envio


def enviar_documento(origen: str, doc) -> EnvioSunat:
    """Envía el documento a la API y deja el resultado en su ``EnvioSunat``.

    Si no se puede ni armar (configuración, datos del documento) se lanza el error antes de tocar
    nada. Si la API no responde o devuelve un error, el envío queda registrado con su estado para
    poder reintentarlo.
    """
    tipo, payload, config = armar(origen, doc, credenciales=True, exigir_activo=True)
    envio = _reservar(origen, doc, tipo, config.modo_sunat)
    try:
        respuesta = cliente.enviar(tipo, payload)
    except ErrorConexionSunat as error:
        return _cerrar(envio, estado=EstadoEnvio.SIN_CONEXION, mensaje=error.mensaje[:500])
    except Exception:
        # Pase lo que pase, el envío no se queda «enviando»: se registra y se vuelve a lanzar.
        logger.exception("envio_sunat_fallo_inesperado", extra={"envio_id": envio.pk})
        _cerrar(envio, estado=EstadoEnvio.ERROR_API, mensaje="Error inesperado al enviar.")
        raise
    return _cerrar(envio, **_interpretar(respuesta))
