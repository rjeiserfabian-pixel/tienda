"""Cuentas de clientes de la tienda: registro, correo confirmado, ingreso y recuperación.

Diseño contra abuso (mismas ideas que la recuperación de contraseña de los usuarios internos):

* Los clientes NO son usuarios del sistema: tienen su propio modelo y su propia sesión.
* La sesión es un token aleatorio de 256 bits; en la base solo se guarda su huella SHA-256. Viaja en
  una cookie HttpOnly (nunca en el cuerpo de la respuesta, así un script de la página no la lee).
* El registro y la recuperación responden SIEMPRE igual exista o no el correo (no se revela quién
  tiene cuenta), y el correo se envía en segundo plano. Los tokens se crean dentro de la tarea.
* El ingreso se bloquea por correo después de varios fallos (espera creciente) y verifica siempre
  una contraseña (aunque no exista la cuenta) para que el tiempo de respuesta no delate nada.
* Al cambiar o recuperar la contraseña se cierran las demás sesiones.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import (
    CommonPasswordValidator,
    MinimumLengthValidator,
    NumericPasswordValidator,
    validate_password,
)
from django.core.cache import cache
from django.core.exceptions import ValidationError as ErrorDjango
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar as auditar

from .exceptions import CredencialesInvalidas, CuentaBloqueada, DatosInvalidos, EnlaceInvalido
from .models import ConfiguracionTienda, CuentaCliente, SesionCuenta, TokenCuenta

logger = logging.getLogger(__name__)

FALLOS_PARA_BLOQUEO = 5
BLOQUEO_MAX_MINUTOS = 30
VALIDADORES = [MinimumLengthValidator(8), CommonPasswordValidator(), NumericPasswordValidator()]
# Hash de una contraseña inexistente: se verifica cuando no hay cuenta (tiempo parejo).
_HASH_FALSO = make_password(secrets.token_urlsafe(16))


def huella(valor: str) -> str:
    return hashlib.sha256((valor or "").encode()).hexdigest()


def normalizar_correo(correo: str) -> str:
    return " ".join((correo or "").split()).lower()[:150]


def validar_password(password: str, correo: str = "") -> None:
    try:
        validate_password(password, password_validators=VALIDADORES)
    except ErrorDjango as error:
        raise DatosInvalidos(" ".join(error.messages)) from None
    if correo and password.lower() == correo.lower():
        raise DatosInvalidos("La contraseña no puede ser igual al correo.")


def _cuentas(organizacion_id: int):
    return CuentaCliente.objects.sin_ambito().filter(organizacion_id=organizacion_id)


def _nombre_tienda(organizacion_id: int) -> str:
    config = (
        ConfiguracionTienda.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()
    )
    return config.nombre if config else "la tienda"


# ---------------------------------------------------------------------------
# Registro y confirmación del correo
# ---------------------------------------------------------------------------
def registrar(
    organizacion_id: int,
    *,
    correo: str,
    password: str,
    nombres: str,
    apellidos: str,
    celular: str = "",
    acepta_ofertas: bool = False,
    ip: str | None = None,
) -> None:
    """Crea la cuenta (o toma una sin confirmar) y encola el correo. Responde igual siempre."""
    from .tasks import enviar_correo_cuenta

    correo = normalizar_correo(correo)
    validar_password(password, correo)
    clave = make_password(password)  # siempre se calcula: el tiempo no delata si ya existía
    ahora = timezone.now()
    with transaction.atomic():
        existente = (
            _cuentas(organizacion_id).select_for_update().filter(correo__iexact=correo).first()
        )
        if existente is None:
            cuenta = CuentaCliente.objects.sin_ambito().create(
                organizacion_id=organizacion_id,
                correo=correo,
                password=clave,
                nombres=nombres,
                apellidos=apellidos,
                celular=celular,
                acepta_terminos_en=ahora,
                acepta_ofertas=acepta_ofertas,
            )
            tipo = "VERIFICAR"
        elif not existente.verificada:
            # Nadie confirmó este correo: quien lo confirme con el enlace es su dueño. La nueva
            # solicitud reemplaza los datos y cierra cualquier sesión abierta con la anterior.
            existente.password = clave
            existente.nombres, existente.apellidos, existente.celular = nombres, apellidos, celular
            existente.acepta_terminos_en = ahora
            existente.acepta_ofertas = acepta_ofertas
            existente.save()
            SesionCuenta.objects.filter(cuenta=existente).update(revocada=True)
            cuenta, tipo = existente, "VERIFICAR"
        else:
            cuenta, tipo = existente, "YA_TIENE_CUENTA"
    if _limite_de_correos(organizacion_id, correo, ip):
        return
    enviar_correo_cuenta.delay(cuenta.pk, tipo, ip)  # ya fuera de la transaccion


def _limite_de_correos(organizacion_id: int, correo: str, ip: str | None) -> bool:
    """True si ya se enviaron demasiados correos a esa dirección en la última hora."""
    clave = f"tienda:correos:{huella(f'{organizacion_id}|{correo}')[:32]}"
    cache.add(clave, 0, 3600)
    if cache.incr(clave) > settings.TIENDA_CORREOS_MAX_HORA:
        logger.warning("tienda_correos_limitados", extra={"ip": ip})
        return True
    return False


def _crear_token(cuenta: CuentaCliente, tipo: str, minutos: int) -> str:
    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        TokenCuenta.objects.filter(cuenta=cuenta, tipo=tipo, usado_en__isnull=True).delete()
        TokenCuenta.objects.create(
            cuenta=cuenta,
            tipo=tipo,
            huella=huella(token),
            expira_en=timezone.now() + timedelta(minutes=minutos),
        )
    return token


def enviar_correo(cuenta_id: int, tipo: str, ip: str | None = None) -> bool:
    """Arma el enlace y envía el correo. Lo llama la tarea en segundo plano."""
    cuenta = CuentaCliente.objects.sin_ambito().filter(pk=cuenta_id, activa=True).first()
    if cuenta is None:
        return False
    tienda = _nombre_tienda(cuenta.organizacion_id)
    base = settings.TIENDA_URL.rstrip("/")
    saludo = f"Hola {cuenta.nombres},\n\n"
    if tipo == "VERIFICAR":
        horas = settings.TIENDA_VERIFICACION_HORAS
        token = _crear_token(cuenta, TokenCuenta.Tipo.VERIFICAR, horas * 60)
        asunto = f"Confirma tu correo en {tienda}"
        cuerpo = (
            f"{saludo}Gracias por crear tu cuenta en {tienda}. Confirma tu correo con este enlace "
            f"(vale {horas} horas):\n\n{base}/cuenta/verificar#token={token}\n\n"
            "Si no creaste esta cuenta, ignora este mensaje."
        )
    elif tipo == "RECUPERAR":
        minutos = settings.TIENDA_RECUPERACION_MIN
        token = _crear_token(cuenta, TokenCuenta.Tipo.RECUPERAR, minutos)
        asunto = f"Recupera tu contraseña de {tienda}"
        cuerpo = (
            f"{saludo}Recibimos una solicitud para cambiar tu contraseña. Abre este enlace (vale "
            f"{minutos} minutos y se usa una sola vez):\n\n"
            f"{base}/cuenta/nueva-clave#token={token}\n\n"
            "Si no lo pediste, ignora este mensaje: tu contraseña no cambia."
        )
    elif tipo == "YA_TIENE_CUENTA":
        asunto = f"Ya tienes una cuenta en {tienda}"
        cuerpo = (
            f"{saludo}Alguien intentó crear una cuenta con este correo, pero ya tienes una. "
            f"Ingresa aquí: {base}/cuenta/ingresar\nSi olvidaste tu contraseña, puedes recuperarla "
            f"en: {base}/cuenta/recuperar\n\nSi no fuiste tú, ignora este mensaje."
        )
    else:
        return False
    send_mail(asunto, cuerpo, None, [cuenta.correo], fail_silently=False)
    return True


def verificar_correo(token: str) -> CuentaCliente:
    ahora = timezone.now()
    with transaction.atomic():
        pendiente = (
            TokenCuenta.objects.select_for_update()
            .select_related("cuenta")
            .filter(
                huella=huella(token),
                tipo=TokenCuenta.Tipo.VERIFICAR,
                usado_en__isnull=True,
                expira_en__gt=ahora,
            )
            .first()
        )
        if pendiente is None or not pendiente.cuenta.activa:
            raise EnlaceInvalido()
        cuenta = pendiente.cuenta
        pendiente.usado_en = ahora
        pendiente.save(update_fields=["usado_en"])
        cuenta.correo_verificado_en = cuenta.correo_verificado_en or ahora
        cuenta.save(update_fields=["correo_verificado_en", "actualizado_en"])
    auditar(
        "tienda.cuenta_verificada",
        recurso_tipo="cuenta_tienda",
        recurso_id=cuenta.pk,
        organizacion_id=cuenta.organizacion_id,
        resumen="Cliente de la tienda confirmó su correo",
    )
    return cuenta


def reenviar_verificacion(cuenta: CuentaCliente, ip: str | None = None) -> None:
    from .tasks import enviar_correo_cuenta

    if cuenta.verificada or _limite_de_correos(cuenta.organizacion_id, cuenta.correo, ip):
        return
    enviar_correo_cuenta.delay(cuenta.pk, "VERIFICAR", ip)


# ---------------------------------------------------------------------------
# Ingreso y sesión
# ---------------------------------------------------------------------------
def _clave_fallos(organizacion_id: int, correo: str) -> str:
    return f"tienda:fallos:{huella(f'{organizacion_id}|{correo}')[:32]}"


def ingresar(
    organizacion_id: int,
    *,
    correo: str,
    password: str,
    ip: str | None = None,
    dispositivo: str = "",
) -> tuple[str, CuentaCliente]:
    """Valida las credenciales y abre una sesión. Devuelve (token de la cookie, cuenta)."""
    correo = normalizar_correo(correo)
    estado = cache.get(_clave_fallos(organizacion_id, correo)) or {"n": 0, "hasta": None}
    ahora = timezone.now()
    if estado["hasta"] and estado["hasta"] > ahora:
        raise CuentaBloqueada()
    cuenta = _cuentas(organizacion_id).filter(correo__iexact=correo, activa=True).first()
    correcta = check_password(password or "", cuenta.password if cuenta else _HASH_FALSO)
    if cuenta is None or not correcta:
        n = estado["n"] + 1
        hasta = None
        if n >= FALLOS_PARA_BLOQUEO:
            minutos = min(2 ** (n - FALLOS_PARA_BLOQUEO), BLOQUEO_MAX_MINUTOS)
            hasta = ahora + timedelta(minutes=minutos)
        cache.set(_clave_fallos(organizacion_id, correo), {"n": n, "hasta": hasta}, 24 * 3600)
        logger.info("tienda_ingreso_fallido", extra={"ip": ip})
        raise CredencialesInvalidas()
    cache.delete(_clave_fallos(organizacion_id, correo))
    token = secrets.token_urlsafe(32)
    SesionCuenta.objects.create(
        cuenta=cuenta,
        huella=huella(token),
        expira_en=ahora + timedelta(days=settings.TIENDA_SESION_DIAS),
        ip=ip,
        dispositivo=dispositivo[:200],
    )
    cuenta.ultimo_ingreso = ahora
    cuenta.save(update_fields=["ultimo_ingreso", "actualizado_en"])
    return token, cuenta


def cuenta_de_sesion(token: str) -> tuple[CuentaCliente, SesionCuenta] | None:
    if not token or len(token) > 100:
        return None
    sesion = (
        SesionCuenta.objects.select_related("cuenta")
        .filter(huella=huella(token), revocada=False, expira_en__gt=timezone.now())
        .first()
    )
    if sesion is None or not sesion.cuenta.activa or sesion.cuenta.eliminado_en is not None:
        return None
    return sesion.cuenta, sesion


def salir(token: str) -> None:
    SesionCuenta.objects.filter(huella=huella(token)).update(revocada=True)


# ---------------------------------------------------------------------------
# Recuperar y cambiar la contraseña
# ---------------------------------------------------------------------------
def solicitar_recuperacion(organizacion_id: int, correo: str, ip: str | None = None) -> None:
    """Responde siempre igual; si la cuenta existe, encola el correo (con límite por dirección)."""
    from .tasks import enviar_correo_cuenta

    correo = normalizar_correo(correo)
    cuenta = _cuentas(organizacion_id).filter(correo__iexact=correo, activa=True).first()
    if cuenta is None or _limite_de_correos(organizacion_id, correo, ip):
        return
    enviar_correo_cuenta.delay(cuenta.pk, "RECUPERAR", ip)


def recuperar_password(token: str, nueva: str) -> None:
    ahora = timezone.now()
    with transaction.atomic():
        pendiente = (
            TokenCuenta.objects.select_for_update()
            .select_related("cuenta")
            .filter(
                huella=huella(token),
                tipo=TokenCuenta.Tipo.RECUPERAR,
                usado_en__isnull=True,
                expira_en__gt=ahora,
            )
            .first()
        )
        if pendiente is None or not pendiente.cuenta.activa:
            raise EnlaceInvalido()
        cuenta = pendiente.cuenta
        validar_password(nueva, cuenta.correo)
        cuenta.password = make_password(nueva)
        # Abrir el enlace del correo demuestra que el correo es suyo.
        cuenta.correo_verificado_en = cuenta.correo_verificado_en or ahora
        cuenta.save(update_fields=["password", "correo_verificado_en", "actualizado_en"])
        pendiente.usado_en = ahora
        pendiente.save(update_fields=["usado_en"])
        TokenCuenta.objects.filter(cuenta=cuenta, usado_en__isnull=True).delete()
        SesionCuenta.objects.filter(cuenta=cuenta).update(revocada=True)
    cache.delete(_clave_fallos(cuenta.organizacion_id, normalizar_correo(cuenta.correo)))
    auditar(
        "tienda.password_recuperada",
        recurso_tipo="cuenta_tienda",
        recurso_id=cuenta.pk,
        organizacion_id=cuenta.organizacion_id,
        resumen="Cliente de la tienda restableció su contraseña",
        inmediato=True,
    )


def cambiar_password(cuenta: CuentaCliente, sesion: SesionCuenta, actual: str, nueva: str) -> None:
    if not check_password(actual or "", cuenta.password):
        raise DatosInvalidos("La contraseña actual no es correcta.")
    validar_password(nueva, cuenta.correo)
    with transaction.atomic():
        cuenta.password = make_password(nueva)
        cuenta.save(update_fields=["password", "actualizado_en"])
        SesionCuenta.objects.filter(cuenta=cuenta).exclude(pk=sesion.pk).update(revocada=True)
    auditar(
        "tienda.password_cambiada",
        recurso_tipo="cuenta_tienda",
        recurso_id=cuenta.pk,
        organizacion_id=cuenta.organizacion_id,
        resumen="Cliente de la tienda cambió su contraseña",
        inmediato=True,
    )
