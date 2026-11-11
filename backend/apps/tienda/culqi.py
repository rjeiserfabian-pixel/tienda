"""Cliente de Culqi (pasarela de pagos): solo lo que la tienda necesita.

Reglas: tiempo máximo explícito, sin seguir redirecciones, y NUNCA se escribe en el log la llave
secreta, el token de la tarjeta ni lo que responde Culqi (puede traer datos de la tarjeta): solo el
código HTTP. Los errores se convierten en mensajes claros para quien configura o paga.
"""

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

URL_BASE = "https://api.culqi.com/v2"
TIEMPO_CONEXION = 5
TIEMPO_RESPUESTA = 20

PREFIJOS = {
    "PRUEBA": ("pk_test_", "sk_test_"),
    "PRODUCCION": ("pk_live_", "sk_live_"),
}


class ErrorCulqi(Exception):
    """No se pudo hablar con Culqi o Culqi rechazó la operación."""

    def __init__(self, mensaje: str, *, http: int | None = None, codigo: str = "") -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.http = http
        self.codigo = codigo


@dataclass(frozen=True, slots=True)
class RespuestaCulqi:
    http: int
    datos: dict


def validar_llaves(modo: str, publica: str, secreta: str) -> str | None:
    """Mensaje de error si las llaves no corresponden al modo; ``None`` si están bien."""
    pk, sk = PREFIJOS[modo]
    if publica and not publica.startswith(pk):
        return f"La llave pública de este modo debe empezar con «{pk}»."
    if secreta and not secreta.startswith(sk):
        return f"La llave secreta de este modo debe empezar con «{sk}»."
    return None


def llamar(
    metodo: str,
    ruta: str,
    llave_secreta: str,
    cuerpo: dict | None = None,
    *,
    idempotencia: str = "",
) -> RespuestaCulqi:
    """Una llamada a la API de Culqi con la llave secreta del negocio."""
    cabeceras = {"Authorization": f"Bearer {llave_secreta}", "Content-Type": "application/json"}
    if idempotencia:
        cabeceras["X-Culqi-Idempotency"] = idempotencia  # evita cobrar dos veces el mismo pedido
    try:
        respuesta = requests.request(
            metodo,
            f"{URL_BASE}/{ruta.lstrip('/')}",
            json=cuerpo,
            headers=cabeceras,
            timeout=(TIEMPO_CONEXION, TIEMPO_RESPUESTA),
            allow_redirects=False,
        )
    except requests.Timeout:
        raise ErrorCulqi("Culqi tardó demasiado en responder.") from None
    except requests.RequestException:
        raise ErrorCulqi("No pudimos conectar con Culqi.") from None
    logger.info(
        "culqi_respuesta", extra={"ruta": ruta.split("?")[0], "http": respuesta.status_code}
    )
    try:
        datos = respuesta.json()
    except ValueError:
        datos = {}
    return RespuestaCulqi(respuesta.status_code, datos if isinstance(datos, dict) else {})


def probar_conexion(llave_secreta: str) -> tuple[bool, str]:
    """¿La llave secreta es aceptada por Culqi? No cobra ni crea nada (solo lee)."""
    try:
        r = llamar("GET", "charges?limit=1", llave_secreta)
    except ErrorCulqi as error:
        return False, error.mensaje
    if r.http == 200:
        return True, "Culqi aceptó la llave."
    if r.http in (401, 403):
        return (
            False,
            "Culqi no aceptó la llave secreta. Revisa que sea del mismo modo y cuenta.",
        )
    return False, f"Culqi respondió con un error ({r.http}). Inténtalo de nuevo."


# ---------------------------------------------------------------------------
# Cargos (cobrar una tarjeta o Yape ya tokenizado en el navegador)
# ---------------------------------------------------------------------------
MENSAJE_GENERICO = "Tu banco no aprobó el pago. Prueba con otra tarjeta o medio de pago."


@dataclass(frozen=True, slots=True)
class Cargo:
    """Lo que la tienda necesita saber de un cargo de Culqi (sin datos de la tarjeta)."""

    id: str
    aprobado: bool
    monto_centimos: int
    pedido: str  # el número de pedido que la tienda puso en los metadatos
    medio: str  # "tarjeta" o "yape"
    mensaje: str  # texto seguro para mostrar al cliente si no se aprobó
    reembolsado_centimos: int = 0  # lo que Culqi ya devolvió de este cargo (``amount_refunded``)


def _como_cargo(datos: dict) -> Cargo:
    resultado = datos.get("outcome") if isinstance(datos.get("outcome"), dict) else {}
    meta = datos.get("metadata") if isinstance(datos.get("metadata"), dict) else {}
    fuente = datos.get("source") if isinstance(datos.get("source"), dict) else {}
    try:
        monto = int(datos.get("amount") or 0)
    except (TypeError, ValueError):
        monto = 0
    aprobado = (
        resultado.get("type") == "venta_exitosa"
        and str(datos.get("object", "charge")) == "charge"
        and str(datos.get("id", "")).startswith("chr_")
    )
    medio = "yape" if "yape" in str(fuente.get("type", "")).lower() else "tarjeta"
    try:
        devuelto = int(datos.get("amount_refunded") or 0)
    except (TypeError, ValueError):
        devuelto = 0
    return Cargo(
        id=str(datos.get("id", ""))[:40],
        aprobado=aprobado,
        monto_centimos=monto,
        pedido=str(meta.get("pedido", ""))[:12],
        medio=medio,
        mensaje="" if aprobado else _mensaje_seguro(datos),
        reembolsado_centimos=devuelto,
    )


def _mensaje_seguro(datos: dict) -> str:
    """El mensaje de Culqi pensado para el cliente (``user_message``); nunca el técnico."""
    texto = datos.get("user_message") or ""
    if isinstance(texto, str) and 3 <= len(texto) <= 200:
        return " ".join(texto.split())
    return MENSAJE_GENERICO


def crear_cargo(
    llave_secreta: str,
    *,
    token_id: str,
    monto_centimos: int,
    correo: str,
    descripcion: str,
    pedido: str,
    idempotencia: str,
) -> Cargo:
    """Cobra el token. El monto va en CÉNTIMOS enteros. Lanza ``ErrorCulqi`` si no se pudo hablar
    con Culqi (el resultado es incierto) y devuelve un ``Cargo`` no aprobado si Culqi lo rechazó."""
    r = llamar(
        "POST",
        "charges",
        llave_secreta,
        {
            "amount": int(monto_centimos),
            "currency_code": "PEN",
            "email": correo,
            "source_id": token_id,
            "description": descripcion[:80],
            "metadata": {"pedido": pedido},
        },
        idempotencia=idempotencia,
    )
    if r.http >= 500:
        raise ErrorCulqi("Culqi no pudo procesar el pago.", http=r.http)
    return _como_cargo(r.datos)


def obtener_cargo(llave_secreta: str, cargo_id: str) -> Cargo:
    """Consulta un cargo (para confirmar lo que avisó el webhook)."""
    if (
        not cargo_id.startswith("chr_")
        or len(cargo_id) > 40
        or not cargo_id.replace("_", "").isalnum()
    ):
        raise ErrorCulqi("Identificador de cargo no válido.")
    r = llamar("GET", f"charges/{cargo_id}", llave_secreta)
    if r.http == 404:
        raise ErrorCulqi("Culqi no conoce ese cargo.", http=404)
    if r.http != 200:
        raise ErrorCulqi("No pudimos consultar el cargo en Culqi.", http=r.http)
    return _como_cargo(r.datos)


# ---------------------------------------------------------------------------
# Reembolsos (devolver dinero de un cargo aprobado)
# ---------------------------------------------------------------------------
# Los motivos que acepta Culqi.
MOTIVOS_REEMBOLSO = ("duplicado", "fraudulento", "solicitud_comprador")


@dataclass(frozen=True, slots=True)
class Reembolso:
    """Lo que la tienda necesita saber de un reembolso de Culqi."""

    id: str
    aprobado: bool
    monto_centimos: int
    mensaje: str  # texto seguro para mostrar al negocio si no se aprobó


def _como_reembolso(datos: dict, http: int) -> Reembolso:
    try:
        monto = int(datos.get("amount") or 0)
    except (TypeError, ValueError):
        monto = 0
    id_ = str(datos.get("id", ""))[:40]
    aprobado = http in (200, 201) and id_.startswith("ref_")
    mensaje = ""
    if not aprobado:
        texto = datos.get("merchant_message") or datos.get("user_message") or ""
        mensaje = " ".join(texto.split())[:200] if isinstance(texto, str) else ""
        mensaje = mensaje or "Culqi no aceptó el reembolso."
    return Reembolso(id=id_, aprobado=aprobado, monto_centimos=monto, mensaje=mensaje)


def crear_reembolso(
    llave_secreta: str,
    *,
    cargo_id: str,
    monto_centimos: int,
    motivo: str,
    pedido: str,
    idempotencia: str,
) -> Reembolso:
    """Devuelve ``monto_centimos`` de un cargo. Lanza ``ErrorCulqi`` si no se pudo hablar con Culqi
    (el resultado es incierto: antes de reintentar hay que mirar el cargo) y devuelve un
    ``Reembolso`` no aprobado si Culqi lo rechazó."""
    if not cargo_id.startswith("chr_") or len(cargo_id) > 40:
        raise ErrorCulqi("Identificador de cargo no válido.")
    if motivo not in MOTIVOS_REEMBOLSO:
        motivo = "solicitud_comprador"
    r = llamar(
        "POST",
        "refunds",
        llave_secreta,
        {
            "amount": int(monto_centimos),
            "charge_id": cargo_id,
            "reason": motivo,
            "metadata": {"pedido": pedido},
        },
        idempotencia=idempotencia,
    )
    if r.http >= 500:
        raise ErrorCulqi("Culqi no pudo procesar el reembolso.", http=r.http)
    return _como_reembolso(r.datos, r.http)


def obtener_reembolso(llave_secreta: str, reembolso_id: str) -> Reembolso:
    """Consulta un reembolso."""
    if not reembolso_id.startswith("ref_") or len(reembolso_id) > 40:
        raise ErrorCulqi("Identificador de reembolso no válido.")
    r = llamar("GET", f"refunds/{reembolso_id}", llave_secreta)
    if r.http == 404:
        raise ErrorCulqi("Culqi no conoce ese reembolso.", http=404)
    if r.http != 200:
        raise ErrorCulqi("No pudimos consultar el reembolso en Culqi.", http=r.http)
    return _como_reembolso(r.datos, r.http)
