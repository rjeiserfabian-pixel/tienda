"""Carrito abandonado: recordatorios por correo, con baja fácil y medición de lo recuperado.

Reglas (decididas con el negocio):

* Solo a clientes con cuenta confirmada que ACEPTARON recibir ofertas (promoción). Cada correo
  lleva un enlace para darse de baja con un clic.
* Dos recordatorios como máximo por carrito: el primero a las ``horas_primero`` de haberlo dejado
  (2 h) y el segundo ``horas_segundo`` después del primero (24 h), con un cupón de incentivo si el
  negocio lo eligió. Si el cliente cambia su carrito, vuelve a empezar de cero.
* No se recuerda un carrito si el cliente ya hizo un pedido después de dejarlo, ni si los
  productos ya no se pueden comprar.
* Cuando un cliente al que se le recordó paga un pedido, el recordatorio queda como «recuperado».
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db.models import Count, Exists, F, OuterRef, Sum
from django.utils import timezone

from . import carrito, catalogo
from .exceptions import EnlaceInvalido
from .models import (
    CarritoCuenta,
    ConfiguracionCarritoAbandonado,
    ConfiguracionTienda,
    CuentaCliente,
    Cupon,
    PedidoTienda,
    RecordatorioCarrito,
)

logger = logging.getLogger(__name__)

SAL_BAJA = "tienda.baja-promociones"
VIGENCIA_BAJA = 60 * 60 * 24 * 365 * 3  # el enlace de baja sirve 3 años
VENTANA_PRIMERO = timedelta(days=3)  # pasado este tiempo ya no se le escribe por ese carrito
VENTANA_SEGUNDO = timedelta(days=7)
DIAS_RECUPERADO = 7  # un pago hasta 7 días después del recordatorio cuenta como recuperado
TANDA = 100
MAX_LINEAS_EN_CORREO = 8


def configuracion(organizacion_id: int) -> ConfiguracionCarritoAbandonado | None:
    return (
        ConfiguracionCarritoAbandonado.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id)
        .first()
    )


# --- baja de promociones ---------------------------------------------------------------
def token_de_baja(cuenta: CuentaCliente) -> str:
    return signing.dumps(cuenta.pk, salt=SAL_BAJA)


def dar_de_baja(token: str) -> bool:
    """Quita el permiso de recibir ofertas a quien abrió su enlace. Siempre responde igual
    (no se revela si la cuenta existe)."""
    try:
        cuenta_id = signing.loads(token or "", salt=SAL_BAJA, max_age=VIGENCIA_BAJA)
    except signing.BadSignature:
        raise EnlaceInvalido() from None
    CuentaCliente.objects.sin_ambito().filter(pk=cuenta_id).update(acepta_ofertas=False)
    return True


# --- a quién se le recuerda ------------------------------------------------------------
def candidatos(config: ConfiguracionCarritoAbandonado, ahora=None) -> list[int]:
    """Los carritos a los que ya les toca un recordatorio (ids de ``CarritoCuenta``)."""
    ahora = ahora or timezone.now()
    base = (
        CarritoCuenta.objects.sin_ambito()
        .filter(
            organizacion_id=config.organizacion_id,
            cuenta__activa=True,
            cuenta__acepta_ofertas=True,
            cuenta__correo_verificado_en__isnull=False,
        )
        .exclude(lineas=[])
        .annotate(
            compro_despues=Exists(
                PedidoTienda.objects.sin_ambito().filter(
                    cuenta_id=OuterRef("cuenta_id"), creado_en__gte=OuterRef("actualizado_en")
                )
            )
        )
        .filter(compro_despues=False)
    )
    primero = base.filter(
        recordatorios_enviados=0,
        actualizado_en__lte=ahora - timedelta(hours=config.horas_primero),
        actualizado_en__gte=ahora - VENTANA_PRIMERO,
    )
    segundo = base.filter(
        recordatorios_enviados=1,
        ultimo_recordatorio_en__lte=ahora - timedelta(hours=config.horas_segundo),
        actualizado_en__lt=F("ultimo_recordatorio_en"),
        actualizado_en__gte=ahora - VENTANA_SEGUNDO,
    )
    ids = list(primero.values_list("pk", flat=True)[:TANDA])
    ids += list(segundo.values_list("pk", flat=True)[: max(TANDA - len(ids), 0)])
    return ids


# --- el correo -------------------------------------------------------------------------
def _cupon_de_incentivo(config: ConfiguracionCarritoAbandonado, ahora) -> Cupon | None:
    cupon = config.cupon
    if cupon is None or not cupon.activo:
        return None
    if cupon.inicia_en and ahora < cupon.inicia_en:
        return None
    if cupon.termina_en and ahora > cupon.termina_en:
        return None
    return cupon


def _texto_del_cupon(cupon: Cupon) -> str:
    if cupon.tipo == Cupon.Tipo.PORCENTAJE:
        ventaja = f"{cupon.valor.normalize():f} % de descuento"
    elif cupon.tipo == Cupon.Tipo.MONTO:
        ventaja = f"S/ {cupon.valor:,.2f} de descuento"
    else:
        ventaja = "envío gratis"
    hasta = (
        f" Es válido hasta el {timezone.localtime(cupon.termina_en).strftime('%d/%m/%Y')}."
        if cupon.termina_en
        else ""
    )
    return (
        f"Para ayudarte a decidir, usa el cupón {cupon.codigo} y tienes {ventaja} al pagar.{hasta}"
    )


def enviar(carrito_id: int, ahora=None) -> bool:
    """Manda el recordatorio que le toca a un carrito. Devuelve si lo mandó."""
    ahora = ahora or timezone.now()
    fila = CarritoCuenta.objects.sin_ambito().select_related("cuenta").filter(pk=carrito_id).first()
    if fila is None or not fila.lineas:
        return False
    config = configuracion(fila.organizacion_id)
    if config is None or not config.activo:
        return False
    cuenta = fila.cuenta
    if not (cuenta.activa and cuenta.acepta_ofertas and cuenta.verificada):
        return False
    numero = fila.recordatorios_enviados + 1
    if numero > 2:
        return False
    try:
        ctx = catalogo.contexto()
        calculo = carrito.calcular(ctx, carrito.normalizar(fila.lineas))
    except Exception:  # noqa: BLE001 - tienda cerrada o sin catálogo: se intentará más tarde
        logger.info("tienda_carrito_abandonado_sin_catalogo")
        return False
    lineas = [ln for ln in calculo["lineas"] if not ln["problema"] and ln["subtotal"]]
    if not lineas:
        return False
    nombre_tienda = (
        ConfiguracionTienda.objects.sin_ambito()
        .filter(organizacion_id=fila.organizacion_id)
        .values_list("nombre", flat=True)
        .first()
        or "la tienda"
    )
    detalle = "\n".join(
        f"  - {ln['cantidad']} x {ln['nombre']}: S/ {ln['subtotal']}"
        for ln in lineas[:MAX_LINEAS_EN_CORREO]
    )
    if len(lineas) > MAX_LINEAS_EN_CORREO:
        detalle += f"\n  … y {len(lineas) - MAX_LINEAS_EN_CORREO} más"
    cupon = _cupon_de_incentivo(config, ahora) if numero == 2 else None
    base = settings.TIENDA_URL.rstrip("/")
    cuerpo = (
        f"Hola {cuenta.nombres},\n\n"
        f"Dejaste estos productos en tu carrito de {nombre_tienda}:\n\n{detalle}\n\n"
        f"Total: S/ {calculo['subtotal']}\n\n"
        + (f"{_texto_del_cupon(cupon)}\n\n" if cupon else "")
        + f"Retoma tu compra aquí: {base}/carrito\n\n"
        "Recibes este correo porque aceptaste recibir ofertas. Si ya no quieres recibirlas, "
        f"puedes darte de baja aquí: {base}/cuenta/baja?t={token_de_baja(cuenta)}"
    )
    asunto = (
        f"¿Sigues interesado? Tu carrito te espera en {nombre_tienda}"
        if numero == 1
        else f"Tu carrito sigue esperándote en {nombre_tienda}"
    )
    send_mail(asunto, cuerpo, None, [cuenta.correo], fail_silently=False)
    RecordatorioCarrito.objects.sin_ambito().create(
        organizacion_id=fila.organizacion_id,
        cuenta=cuenta,
        numero=numero,
        total_carrito=Decimal(calculo["subtotal"]),
        cupon_codigo=cupon.codigo if cupon else "",
    )
    # ``update`` (no ``save``): no debe contar como «el cliente cambió su carrito».
    CarritoCuenta.objects.sin_ambito().filter(pk=fila.pk).update(
        recordatorios_enviados=numero, ultimo_recordatorio_en=ahora
    )
    return True


def recordar_carritos() -> int:
    """Revisa todas las tiendas con el recordatorio encendido y manda lo que toque."""
    enviados = 0
    ahora = timezone.now()
    for config in ConfiguracionCarritoAbandonado.objects.sin_ambito().filter(activo=True):
        for carrito_id in candidatos(config, ahora):
            try:
                enviados += enviar(carrito_id, ahora)
            except Exception:  # noqa: BLE001 - un correo caído no frena a los demás
                logger.exception("tienda_recordatorio_carrito_fallo", extra={"carrito": carrito_id})
    return enviados


# --- cuando el cliente vuelve y compra ----------------------------------------------------
def marcar_recuperado(pedido: PedidoTienda) -> None:
    """Si a este cliente se le recordó su carrito hace poco, ese recordatorio dio resultado."""
    ahora = timezone.now()
    RecordatorioCarrito.objects.sin_ambito().filter(
        cuenta_id=pedido.cuenta_id,
        recuperado_en__isnull=True,
        creado_en__gte=ahora - timedelta(days=DIAS_RECUPERADO),
    ).update(recuperado_en=ahora, pedido=pedido)


def estadisticas(organizacion_id: int) -> dict:
    """Cuánto se avisó y cuánto se recuperó (para el panel)."""
    todos = RecordatorioCarrito.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    recuperados = todos.filter(recuperado_en__isnull=False)
    pedidos = PedidoTienda.objects.sin_ambito().filter(
        pk__in=recuperados.exclude(pedido__isnull=True).values("pedido_id")
    )
    vendido = pedidos.aggregate(t=Sum("total"))["t"] or Decimal(0)
    return {
        "recordatorios": todos.count(),
        "clientes": todos.values("cuenta_id").distinct().count(),
        "recuperados": recuperados.values("cuenta_id").distinct().count(),
        "vendido": format(vendido, "f"),
        "por_numero": {
            str(f["numero"]): f["n"]
            for f in todos.values("numero").annotate(n=Count("id")).order_by("numero")
        },
    }
