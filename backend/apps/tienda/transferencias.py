"""Pago por transferencia o depósito, con el comprobante (voucher) que el personal verifica.

Flujo:

1. El cliente elige «Transferencia o depósito» y una de las cuentas que el negocio ofrece. Se crea
   el pedido (más tiempo para pagar que con tarjeta: ``transferencia_horas``) y el stock queda
   apartado.
2. El cliente paga en su banco y sube la foto de su comprobante (y, si quiere, el número de
   operación). El pedido pasa a «falta verificar el pago».
3. El personal ve el comprobante en el panel y lo CONFIRMA (se emite la venta y el dinero entra a
   la cuenta elegida) o lo RECHAZA con el motivo (el cliente puede subir otro; el plazo se
   renueva).

Reglas: solo pagos completos (no adelanto), y solo si todos los productos son de la empresa dueña
de la cuenta elegida (así el dinero y el comprobante son de la misma empresa).

El comprobante es un dato del cliente: solo lo ven él y el personal con permiso; se guarda
re-codificado (sin metadatos) y nunca se sirve por una dirección pública.
"""

import io
import logging
import uuid
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.auditoria.servicios import registrar
from apps.core.tenant import contexto_tenant
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa
from apps.ventas.exceptions import VentaInvalida

from . import avisos, carrito_abandonado, catalogo, cupones, pagar
from .exceptions import PedidoInvalido, PedidoNoEncontrado, PedidoVencido, TransicionInvalida
from .models import ConfiguracionPago, HistorialPedido, PedidoTienda, ReservaStock

logger = logging.getLogger(__name__)

Estado = PedidoTienda.Estado
Metodo = PedidoTienda.PagoMetodo

TAMANO_MAXIMO = 8 * 1024 * 1024
PIXELES_MAXIMOS = 40_000_000
FORMATOS = {"JPEG", "PNG", "WEBP"}
LADO_MAXIMO = 1600
MAX_TEXTO = 250


def configuracion(organizacion_id: int) -> ConfiguracionPago | None:
    return ConfiguracionPago.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()


def cuentas_posibles(organizacion_id: int):
    """Las cuentas que se pueden ofrecer: banco o billetera, en soles, de empresas activas."""
    return (
        CuentaFinanciera.objects.sin_ambito()
        .filter(
            empresa__organizacion_id=organizacion_id,
            empresa__estado=EstadoRegistro.ACTIVO,
            estado=EstadoRegistro.ACTIVO,
            tipo__in=[CuentaFinanciera.Tipo.BANCO, CuentaFinanciera.Tipo.BILLETERA],
            moneda=CuentaFinanciera.Moneda.PEN,
        )
        .select_related("empresa")
        .order_by("empresa__razon_social", "nombre")
    )


def ids_de_cuentas(config: ConfiguracionPago) -> set[int]:
    """Las cuentas elegidas (por la tabla intermedia: no exige una organización activa)."""
    relacion = ConfiguracionPago.cuentas_transferencia.through
    return set(
        relacion.objects.filter(configuracionpago_id=config.pk).values_list(
            "cuentafinanciera_id", flat=True
        )
    )


def cuentas_ofrecidas(config: ConfiguracionPago | None) -> list[CuentaFinanciera]:
    if config is None or not config.transferencia_activa:
        return []
    elegidas = ids_de_cuentas(config)
    return [c for c in cuentas_posibles(config.organizacion_id) if c.pk in elegidas]


def _cuenta_publica(c: CuentaFinanciera) -> dict:
    return {
        "id": c.pk,
        "nombre": c.nombre,
        "tipo": c.tipo,
        "banco": c.banco,
        "titular": c.empresa.razon_social,
        "ruc": c.empresa.ruc,
        "numero": c.numero_cuenta,
        "cci": c.cci,
    }


def info_publica(organizacion_id: int) -> dict:
    """Lo que ve el cliente al elegir transferencia (las cuentas son datos para que le paguen)."""
    config = configuracion(organizacion_id)
    cuentas = cuentas_ofrecidas(config)
    if not cuentas:
        return {"activa": False}
    return {
        "activa": True,
        "horas": config.transferencia_horas,
        "instrucciones": config.transferencia_instrucciones,
        "cuentas": [_cuenta_publica(c) for c in cuentas],
    }


def salida(p: PedidoTienda) -> dict | None:
    """Lo que ve el cliente (y el personal) de la transferencia de un pedido."""
    if p.pago_metodo != Metodo.TRANSFERENCIA:
        return None
    c = p.cuenta_transferencia
    return {
        "cuenta": _cuenta_publica(c) if c else None,
        "tiene_voucher": bool(p.voucher),
        "operacion": p.voucher_operacion,
        "subido_en": p.voucher_subido_en.isoformat() if p.voucher_subido_en else None,
        "rechazo": p.transferencia_rechazo,
        "instrucciones": (
            configuracion(p.organizacion_id) or ConfiguracionPago()
        ).transferencia_instrucciones,
    }


# ---------------------------------------------------------------------------
# Crear el pedido por transferencia
# ---------------------------------------------------------------------------
def validar_para_pedido(config: ConfiguracionPago | None, cuenta_id, calculo) -> CuentaFinanciera:
    """La cuenta elegida, si el pedido puede pagarse así; si no, ``PedidoInvalido``."""
    elegidas = {c.pk: c for c in cuentas_ofrecidas(config)}
    if not elegidas:
        raise PedidoInvalido("El pago por transferencia no está disponible.")
    cuenta = elegidas.get(cuenta_id)
    if cuenta is None:
        raise PedidoInvalido("Elige la cuenta a la que vas a transferir.")
    empresas = {ln["empresa"].pk for ln in calculo.lineas if not ln["es_envio"]}
    if empresas != {cuenta.empresa_id}:
        raise PedidoInvalido(
            "Este pedido tiene productos de más de una empresa: paga con tarjeta o Yape."
        )
    return cuenta


def plazo(config: ConfiguracionPago, desde=None):
    return (desde or timezone.now()) + timedelta(hours=config.transferencia_horas)


# ---------------------------------------------------------------------------
# El comprobante del cliente
# ---------------------------------------------------------------------------
def _procesar_imagen(archivo) -> bytes:
    if archivo is None:
        raise PedidoInvalido("Adjunta la foto de tu comprobante.")
    if archivo.size > TAMANO_MAXIMO:
        raise PedidoInvalido("La foto pesa más de 8 MB. Prueba con una más liviana.")
    try:
        with Image.open(archivo) as original:
            if original.format not in FORMATOS:
                raise PedidoInvalido("Usa una foto o captura JPG, PNG o WEBP.")
            if original.width * original.height > PIXELES_MAXIMOS:
                raise PedidoInvalido("La imagen es demasiado grande.")
            if original.format == "JPEG":
                original.draft("RGB", (LADO_MAXIMO, LADO_MAXIMO))
            original.load()
            imagen = ImageOps.exif_transpose(original)
            if imagen.mode in ("RGBA", "LA", "P"):
                imagen = imagen.convert("RGBA")
                fondo = Image.new("RGB", imagen.size, (255, 255, 255))
                fondo.paste(imagen, mask=imagen.getchannel("A"))
                imagen = fondo
            else:
                imagen = imagen.convert("RGB")
            imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.Resampling.LANCZOS)
            salida = io.BytesIO()
            imagen.save(salida, format="WEBP", quality=85, method=4)  # sin EXIF ni metadatos
            return salida.getvalue()
    except PedidoInvalido:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise PedidoInvalido("No pudimos leer la imagen. Prueba con otra foto.") from None


def _borrar_archivo(pedido: PedidoTienda) -> None:
    try:
        if pedido.voucher and pedido.voucher.name:
            pedido.voucher.storage.delete(pedido.voucher.name)
    except OSError:
        logger.warning("tienda_voucher_no_borrado", extra={"pedido_id": pedido.pk})


def _limpio(texto: str | None, maximo: int) -> str:
    return " ".join((texto or "").split())[:maximo]


def subir_voucher(cuenta, numero: str, archivo, operacion: str = "") -> PedidoTienda:
    """El cliente sube la foto de su comprobante: el pedido queda por verificar."""
    contenido = _procesar_imagen(archivo)
    with transaction.atomic():
        pedido = (
            PedidoTienda.objects.sin_ambito()
            .select_for_update()
            .filter(organizacion_id=cuenta.organizacion_id, cuenta=cuenta, numero=numero)
            .first()
        )
        if pedido is None:
            raise PedidoNoEncontrado()
        if pedido.pago_metodo != Metodo.TRANSFERENCIA:
            raise PedidoInvalido("Este pedido se paga con tarjeta o Yape.")
        if pedido.estado != Estado.PENDIENTE_PAGO or pedido.expira_en <= timezone.now():
            raise PedidoVencido()
        _borrar_archivo(pedido)
        pedido.voucher.save(f"{uuid.uuid4().hex}.webp", ContentFile(contenido), save=False)
        pedido.voucher_operacion = _limpio(operacion, 40)
        pedido.voucher_subido_en = timezone.now()
        pedido.transferencia_rechazo = ""
        pedido.estado = Estado.POR_VERIFICAR
        pedido.save()
        HistorialPedido.objects.create(
            pedido=pedido,
            tipo=HistorialPedido.Tipo.ESTADO,
            estado=Estado.POR_VERIFICAR,
            texto="El cliente subió su comprobante de transferencia",
        )
        registrar(
            "tienda.voucher_subido",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=pedido.organizacion_id,
            resumen=f"Pedido {pedido.numero}: comprobante de transferencia recibido",
        )
        transaction.on_commit(lambda: avisos.encolar(pedido.pk, "PEDIDO_VOUCHER"))
    return pedido


def leer_voucher(organizacion_id: int, numero: str) -> bytes:
    pedido = (
        PedidoTienda.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, numero=numero)
        .first()
    )
    if pedido is None:
        raise PedidoNoEncontrado()
    if not pedido.voucher:
        raise PedidoNoEncontrado("Este pedido no tiene comprobante.")
    try:
        with pedido.voucher.open("rb") as f:
            return f.read()
    except (FileNotFoundError, ValueError):
        raise PedidoNoEncontrado("No encontramos el archivo del comprobante.") from None


# ---------------------------------------------------------------------------
# El personal verifica
# ---------------------------------------------------------------------------
def _quien(usuario) -> dict:
    nombre = (usuario.get_full_name() or usuario.get_username())[:150]
    return {"usuario_id": usuario.pk, "usuario_nombre": nombre}


def confirmar(organizacion_id: int, numero: str, *, usuario, referencia: str = "") -> PedidoTienda:
    """El dinero llegó: se emite la venta (un comprobante) y el pedido queda pagado. Todo o nada."""
    referencia = _limpio(referencia, 40)
    with transaction.atomic():
        pedido = (
            PedidoTienda.objects.sin_ambito()
            .select_for_update(of=("self",))
            .filter(organizacion_id=organizacion_id, numero=numero)
            .first()
        )
        if pedido is None:
            raise PedidoNoEncontrado()
        if pedido.estado != Estado.POR_VERIFICAR or pedido.pago_metodo != Metodo.TRANSFERENCIA:
            raise TransicionInvalida(
                "Este pedido no está esperando que verifiques una transferencia."
            )
        cuenta = pedido.cuenta_transferencia
        if cuenta is None:
            raise TransicionInvalida("El pedido no tiene la cuenta de la transferencia.")
        if referencia:
            pedido.voucher_operacion = referencia
        empresas = list(
            Empresa.objects.sin_ambito()
            .filter(organizacion_id=organizacion_id)
            .values_list("pk", flat=True)
        )
        try:
            with contexto_tenant(organizacion_id, empresas, None):
                venta = pagar._registrar_venta(pedido, "tarjeta", transferencia=cuenta)
        except VentaInvalida as error:
            raise PedidoInvalido(error.mensaje) from None
        ahora = timezone.now()
        cupones.consumir(pedido)
        carrito_abandonado.marcar_recuperado(pedido)
        pedido.venta = venta
        pedido.estado = Estado.PAGADO
        pedido.pagado_en = ahora
        pedido.motivo_atencion = ""
        pedido.save()
        ReservaStock.objects.sin_ambito().filter(pedido=pedido, liberada_en__isnull=True).update(
            liberada_en=ahora
        )
        HistorialPedido.objects.create(
            pedido=pedido,
            tipo=HistorialPedido.Tipo.ESTADO,
            estado=Estado.PAGADO,
            texto=f"Transferencia verificada (cuenta {cuenta.nombre})",
            **_quien(usuario),
        )
        registrar(
            "tienda.transferencia_confirmada",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=organizacion_id,
            resumen=f"Pedido {pedido.numero}: transferencia de S/ {pedido.total} confirmada",
            detalle={"cuenta": cuenta.nombre, "referencia": pedido.voucher_operacion},
        )
        transaction.on_commit(catalogo.invalidar)
        transaction.on_commit(lambda: pagar._encolar_correo(pedido.pk))
        transaction.on_commit(lambda: avisos.encolar(pedido.pk, "PEDIDO_PAGADO"))
    return pedido


def rechazar(organizacion_id: int, numero: str, *, usuario, motivo: str) -> PedidoTienda:
    """No se pudo verificar el pago: el cliente puede subir otro comprobante (plazo renovado)."""
    motivo = _limpio(motivo, MAX_TEXTO)
    if len(motivo) < 5:
        raise PedidoInvalido("Explica al cliente por qué no se pudo verificar (unas palabras).")
    with transaction.atomic():
        pedido = (
            PedidoTienda.objects.sin_ambito()
            .select_for_update(of=("self",))
            .filter(organizacion_id=organizacion_id, numero=numero)
            .first()
        )
        if pedido is None:
            raise PedidoNoEncontrado()
        if pedido.estado != Estado.POR_VERIFICAR:
            raise TransicionInvalida(
                "Este pedido no está esperando que verifiques una transferencia."
            )
        config = configuracion(organizacion_id)
        horas = config.transferencia_horas if config else 24
        _borrar_archivo(pedido)
        pedido.voucher = ""
        pedido.transferencia_rechazo = motivo
        pedido.estado = Estado.PENDIENTE_PAGO
        pedido.expira_en = timezone.now() + timedelta(hours=horas)
        pedido.save()
        veces = HistorialPedido.objects.filter(
            pedido=pedido, texto__startswith="Comprobante rechazado"
        ).count()
        HistorialPedido.objects.create(
            pedido=pedido,
            tipo=HistorialPedido.Tipo.ESTADO,
            estado=Estado.PENDIENTE_PAGO,
            texto=f"Comprobante rechazado: {motivo}"[:500],
            **_quien(usuario),
        )
        registrar(
            "tienda.transferencia_rechazada",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=organizacion_id,
            resumen=f"Pedido {pedido.numero}: comprobante rechazado",
            detalle={"motivo": motivo},
        )
        evento = f"PEDIDO_PAGO_RECHAZADO_{veces + 1}"
        transaction.on_commit(lambda: avisos.encolar(pedido.pk, evento))
        transaction.on_commit(catalogo.invalidar)
    return pedido


def cancelar_por_el_personal(pedido: PedidoTienda) -> None:
    """Si el personal cancela un pedido por verificar, también se borra su comprobante."""
    from .pedidos import liberar_reservas  # import tardío: pedidos usa este módulo

    _borrar_archivo(pedido)
    liberar_reservas(pedido)
