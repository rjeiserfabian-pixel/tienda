"""Cobro de los pedidos de la tienda con Culqi y paso a venta real.

Orden de las cosas (importa, porque el dinero sale del cliente en el paso 2):

1. ``abrir_intento``: se comprueba el pedido y se anota un INTENTO en curso (solo uno a la vez: dos
   clics no cobran dos veces). Es una transacción corta; no se llama a Culqi dentro de ella.
2. ``culqi.crear_cargo``: la llamada de red, fuera de toda transacción.
3. ``confirmar_pago``: una transacción atómica e idempotente que crea la venta (un comprobante por
   empresa), mete el dinero a la cuenta, consume la reserva y marca el pedido PAGADO.

Si el paso 3 falla DESPUÉS de cobrar, el dinero ya salió: el pedido queda PAGADO_SIN_COMPROBANTE
(con la reserva intacta y una alerta en auditoría) y una tarea lo reintenta sola. Un cobro aprobado
NUNCA se vuelve a cobrar. El monto que se cobra es siempre el total guardado en el pedido.

Pedido mixto (productos de las dos empresas): Culqi deposita todo en la cuenta de la empresa que
cobra. El cobro de cada comprobante entra a la cuenta «Culqi» de su empresa (la de la otra empresa
es una cuenta puente) y la parte ajena queda como ``DeudaCobroTienda`` hasta que se le transfiera.
"""

import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.tenant import contexto_tenant
from apps.mantenimiento.models import (
    Cliente,
    CuentaFinanciera,
    EstadoRegistro,
    ListaPrecio,
    MedioPago,
)
from apps.organizacion.models import Empresa
from apps.ventas import liquidacion_interna
from apps.ventas import servicios as ventas
from apps.ventas.cuentas_web import CUENTA_COBRA, CUENTA_PUENTE
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import CobroVenta, CuentaDeCobro

from . import catalogo, culqi, series_pedido
from .exceptions import (
    CorreoSinConfirmar,
    PagoEnProceso,
    PagoNoDisponible,
    PagoRechazado,
    PedidoNoEncontrado,
    PedidoVencido,
)
from .models import (
    ConfiguracionPago,
    ConfiguracionTienda,
    CuentaCliente,
    DeudaCobroTienda,
    IntentoPago,
    LineaPedido,
    PedidoTienda,
    ReservaStock,
)

logger = logging.getLogger(__name__)

Estado = PedidoTienda.Estado
TOKEN = re.compile(r"^[A-Za-z0-9_]{5,80}$")
MINUTOS_INTENTO_VIGENTE = 5  # un intento en curso o incierto bloquea otro durante este tiempo
MAX_REINTENTOS_COMPROBANTE = 12  # cada 5 minutos: una hora
YA_COBRADOS = frozenset(
    {
        Estado.PAGADO,
        Estado.EN_PREPARACION,
        Estado.LISTO_PARA_RECOJO,
        Estado.ENVIADO,
        Estado.ENTREGADO,
        Estado.PAGADO_FUERA_DE_PLAZO,
        # Un pedido en reembolso NO se vuelve a vender si llega un aviso tardío del cargo.
        Estado.REEMBOLSO_PENDIENTE,
        Estado.REEMBOLSADO_PARCIAL,
        Estado.REEMBOLSADO,
    }
)
NOMBRES_MEDIO = {"tarjeta": "Tarjeta (Culqi)", "yape": "Yape (Culqi)"}
TIPOS_MEDIO = {"tarjeta": MedioPago.Tipo.TARJETA, "yape": MedioPago.Tipo.BILLETERA}
VENDEDOR = "Tienda virtual"


MOTIVO_FUERA_DE_PLAZO = (
    "Pagó después de que el pedido venció o se canceló. Revisa si hay stock o reembolsa."
)


class MontoNoCoincide(Exception):  # noqa: N818 - es una señal interna, no un error de dominio
    """El cargo no es por el total del pedido (no se confirma nada)."""


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
def _config_activa(organizacion_id: int) -> ConfiguracionPago:
    config = ConfiguracionPago.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()
    if (
        config is None
        or not config.culqi_activo
        or not config.culqi_llave_secreta
        or config.empresa_cobra_id is None
    ):
        raise PagoNoDisponible()
    return config


def _centimos(monto: Decimal) -> int:
    return int((monto * 100).to_integral_value())


# ---------------------------------------------------------------------------
# Paso 1 y 2: intento y cargo
# ---------------------------------------------------------------------------
def _abrir_intento(cuenta: CuentaCliente, numero: str) -> tuple[PedidoTienda, IntentoPago]:
    ahora = timezone.now()
    corte = ahora - timedelta(minutes=MINUTOS_INTENTO_VIGENTE)
    with transaction.atomic():
        pedido = (
            PedidoTienda.objects.sin_ambito()
            .select_for_update()
            .filter(organizacion_id=cuenta.organizacion_id, cuenta=cuenta, numero=numero)
            .first()
        )
        if pedido is None:
            raise PedidoNoEncontrado()
        if pedido.estado in YA_COBRADOS:
            raise PagoEnProceso("Este pedido ya está pagado.")
        if pedido.estado != Estado.PENDIENTE_PAGO or pedido.expira_en <= ahora:
            raise PedidoVencido()
        intentos = IntentoPago.objects.sin_ambito().filter(pedido=pedido)
        # Un intento en curso muy viejo se da por perdido (el proceso se cayó): queda «incierto».
        intentos.filter(estado=IntentoPago.Estado.EN_CURSO, creado_en__lt=corte).update(
            estado=IntentoPago.Estado.INCIERTO, actualizado_en=ahora
        )
        if (
            intentos.filter(estado=IntentoPago.Estado.EN_CURSO).exists()
            or intentos.filter(
                estado=IntentoPago.Estado.INCIERTO, actualizado_en__gt=corte
            ).exists()
        ):
            raise PagoEnProceso()
        intento = IntentoPago.objects.sin_ambito().create(
            organizacion_id=pedido.organizacion_id, pedido=pedido, monto=pedido.total
        )
    return pedido, intento


def _cerrar_intento(intento: IntentoPago, estado: str, *, cargo_id: str = "", mensaje: str = ""):
    intento.estado = estado
    intento.culqi_cargo_id = cargo_id
    intento.mensaje = mensaje[:250]
    intento.save(update_fields=["estado", "culqi_cargo_id", "mensaje", "actualizado_en"])


def pagar(cuenta: CuentaCliente, numero: str, token: str) -> PedidoTienda:
    """Cobra el pedido con el token que el navegador obtuvo de Culqi (tarjeta o Yape)."""
    if not cuenta.verificada:
        raise CorreoSinConfirmar()
    if not TOKEN.match(token or ""):
        raise PagoRechazado("No pudimos leer los datos de tu pago. Inténtalo de nuevo.")
    config = _config_activa(cuenta.organizacion_id)
    pedido, intento = _abrir_intento(cuenta, numero)
    try:
        cargo = culqi.crear_cargo(
            config.culqi_llave_secreta,
            token_id=token,
            monto_centimos=_centimos(pedido.total),  # SIEMPRE el total guardado del pedido
            correo=cuenta.correo,
            descripcion=f"Pedido {pedido.numero}",
            pedido=pedido.numero,
            idempotencia=f"tienda-{pedido.organizacion_id}-{pedido.pk}-{intento.pk}",
        )
    except culqi.ErrorCulqi:
        # No sabemos si Culqi cobró: no hay otro intento hasta confirmarlo (webhook o espera).
        _cerrar_intento(intento, IntentoPago.Estado.INCIERTO, mensaje="Culqi no respondió")
        logger.warning("tienda_pago_incierto", extra={"pedido": pedido.numero})
        raise PagoEnProceso(
            "No pudimos confirmar tu pago. Si tu banco te lo cobró, tu pedido se confirmará solo "
            "en unos minutos: no vuelvas a pagar."
        ) from None
    if not cargo.aprobado:
        _cerrar_intento(intento, IntentoPago.Estado.RECHAZADO, mensaje=cargo.mensaje)
        registrar(
            "tienda.pago_rechazado",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=pedido.organizacion_id,
            resumen=f"Pago rechazado del pedido {pedido.numero}",
            exito=False,
        )
        raise PagoRechazado(cargo.mensaje or culqi.MENSAJE_GENERICO)
    _cerrar_intento(intento, IntentoPago.Estado.APROBADO, cargo_id=cargo.id)
    return confirmar_pago(pedido.pk, cargo)


# ---------------------------------------------------------------------------
# Paso 3: venta real
# ---------------------------------------------------------------------------
def _cuenta_de(empresa: Empresa, nombre: str) -> CuentaFinanciera:
    cuenta = (
        CuentaFinanciera.objects.sin_ambito().filter(empresa=empresa, nombre__iexact=nombre).first()
    )
    if cuenta is None:
        cuenta = CuentaFinanciera.objects.sin_ambito().create(
            empresa=empresa,
            nombre=nombre,
            tipo=CuentaFinanciera.Tipo.BILLETERA,
            moneda=CuentaFinanciera.Moneda.PEN,
            permite_saldo_negativo=True,  # la cuenta puente se compensa al transferir
        )
    return cuenta


def _preparar_cuentas(organizacion_id: int, empresas: list[Empresa], cobra: Empresa, medio: str):
    """El método de pago de Culqi y, en cada empresa, la cuenta donde entra (idempotente)."""
    nombre = NOMBRES_MEDIO[medio]
    pago = (
        MedioPago.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, nombre=nombre)
        .first()
    )
    if pago is None:
        pago = MedioPago.objects.sin_ambito().create(
            organizacion_id=organizacion_id, nombre=nombre, tipo=TIPOS_MEDIO[medio]
        )
    for empresa in empresas:
        cuenta = _cuenta_de(empresa, CUENTA_COBRA if empresa.pk == cobra.pk else CUENTA_PUENTE)
        existe = (
            CuentaDeCobro.objects.sin_ambito()
            .filter(empresa=empresa, medio_pago=pago, sucursal__isnull=True)
            .exists()
        )
        if not existe:
            CuentaDeCobro.objects.sin_ambito().create(
                empresa=empresa, medio_pago=pago, cuenta=cuenta
            )
    return pago


def _cliente_real(pedido: PedidoTienda, cuenta: CuentaCliente) -> Cliente:
    """El cliente del sistema (por su documento); se crea la primera vez y se enlaza a la cuenta."""
    tipo = pedido.documento_tipo or "OTRO"
    numero = pedido.documento_numero or f"TIENDA{cuenta.pk}"
    cliente = (
        Cliente.objects.sin_ambito()
        .select_for_update()
        .filter(
            organizacion_id=pedido.organizacion_id, tipo_documento=tipo, numero_documento=numero
        )
        .first()
    )
    nombre = pedido.nombre_comprobante or f"{cuenta.nombres} {cuenta.apellidos}".strip()
    if cliente is None:
        cliente = Cliente.objects.sin_ambito().create(
            organizacion_id=pedido.organizacion_id,
            nombre=nombre[:250],
            tipo_documento=tipo,
            numero_documento=numero,
            correo=cuenta.correo,
            telefono=(cuenta.celular or "")[:20],
            direccion=(pedido.direccion_fiscal or pedido.direccion_entrega)[:250],
            ubigeo=pedido.ubigeo_entrega,
            zona=pedido.zona_fiscal,
        )
    else:
        if cliente.estado != EstadoRegistro.ACTIVO:
            raise VentaInvalida("El cliente de este pedido está inactivo. Actívalo para emitir.")
        # La zona decide el IGV de ESTA compra (donde se entrega); lo demás solo se completa.
        cliente.zona = pedido.zona_fiscal
        cliente.correo = cliente.correo or cuenta.correo
        cliente.telefono = cliente.telefono or (cuenta.celular or "")[:20]
        cliente.save()
    if cuenta.cliente_id != cliente.pk:
        cuenta.cliente = cliente
        cuenta.save(update_fields=["cliente", "actualizado_en"])
    return cliente


def _lista_de(organizacion_id: int) -> ListaPrecio:
    config = (
        ConfiguracionTienda.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()
    )
    base = ListaPrecio.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO
    )
    lista = (
        base.filter(pk=config.lista_precio_id).first()
        if config and config.lista_precio_id
        else None
    )
    lista = lista or base.filter(es_principal=True).first()
    if lista is None:
        raise VentaInvalida("No hay una lista de precios para emitir la venta de la tienda.")
    return lista


def _registrar_venta(pedido: PedidoTienda, medio: str):
    """Crea la venta (un comprobante por empresa), el cobro y las deudas (en la transacción)."""
    config = _config_activa_para_venta(pedido.organizacion_id)
    empresas = {
        e.pk: e
        for e in Empresa.objects.sin_ambito().filter(
            organizacion_id=pedido.organizacion_id, estado=EstadoRegistro.ACTIVO
        )
    }
    cobra = empresas.get(config.empresa_cobra_id)
    if cobra is None:
        raise VentaInvalida("La empresa que cobra con Culqi no está activa.")
    lineas = list(
        LineaPedido.objects.sin_ambito()
        .filter(pedido=pedido)
        .select_related("producto", "empresa", "almacen")
        .order_by("id")
    )
    # Productos con número de serie: se asigna la unidad más antigua del almacén que surte.
    asignadas = series_pedido.asignar(lineas)
    entradas = [
        ventas.LineaEntrada(
            producto=ln.producto,
            cantidad=ln.cantidad,
            empresa=ln.empresa,
            almacen=ln.almacen,
            # El precio sin IGV que se acordó (no se recalcula con precios nuevos).
            precio_unitario=(ln.base / ln.cantidad).quantize(Decimal("0.000001")),
            series=tuple(asignadas.get(ln.pk, ())),
        )
        for ln in lineas
    ]
    involucradas = [empresas[e] for e in {ln.empresa_id for ln in lineas} | {cobra.pk}]
    pago = _preparar_cuentas(pedido.organizacion_id, involucradas, cobra, medio)
    cuenta = CuentaCliente.objects.sin_ambito().get(pk=pedido.cuenta_id)
    venta = ventas.registrar_venta(
        empresa=cobra,
        fecha=timezone.localdate(),
        tipo_comprobante=pedido.comprobante_tipo,
        lineas=entradas,
        cobros_entrada=[
            ventas.CobroEntrada(
                medio_pago=pago, monto=pedido.total, referencia=pedido.culqi_cargo_id
            )
        ],
        vendedor_nombre=VENDEDOR,
        cliente=_cliente_real(pedido, cuenta),
        lista=_lista_de(pedido.organizacion_id),
        observacion=f"Pedido {pedido.numero}",
        puede_descontar=True,
        puede_vender_bajo_minimo=True,
        puede_vender_stock_otra_empresa=True,
    )
    series_pedido.guardar(lineas, asignadas)
    # La parte de cada empresa ajena a la que cobró queda como deuda de quien recibió el dinero.
    por_empresa = (
        CobroVenta.objects.sin_ambito()
        .filter(venta=venta)
        .values("empresa_id")
        .annotate(t=Sum("monto"))
    )
    for fila in por_empresa:
        if fila["empresa_id"] != cobra.pk and fila["t"] > 0:
            deuda = DeudaCobroTienda.objects.sin_ambito().create(
                organizacion_id=pedido.organizacion_id,
                pedido=pedido,
                deudora=cobra,
                acreedora=empresas[fila["empresa_id"]],
                monto=fila["t"],
            )
            # La misma deuda entra a la libreta de «Liquidación entre empresas» (se compensa allí).
            liquidacion_interna.partida_de_cobro_web(
                cobro_id=deuda.pk,
                pedido=pedido.numero,
                cobra=cobra,
                otra=deuda.acreedora,
                monto=deuda.monto,
            )
    return venta


def _config_activa_para_venta(organizacion_id: int) -> ConfiguracionPago:
    """Para emitir la venta basta con saber QUÉ empresa cobra (aunque el cobro esté pausado)."""
    config = ConfiguracionPago.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()
    if config is None or config.empresa_cobra_id is None:
        raise VentaInvalida("Falta indicar qué empresa recibe los pagos de la tienda.")
    return config


def _alerta(pedido: PedidoTienda, resumen: str) -> None:
    logger.error(
        "tienda_pago_requiere_atencion", extra={"pedido": pedido.numero, "motivo": resumen}
    )
    registrar(
        "tienda.pago_requiere_atencion",
        recurso_tipo="pedido_tienda",
        recurso_id=pedido.pk,
        organizacion_id=pedido.organizacion_id,
        resumen=f"ALERTA: pedido {pedido.numero} cobrado que requiere atención. {resumen}"[:250],
        exito=False,
        inmediato=True,
    )


def _motivo(error: Exception) -> str:
    if isinstance(error, VentaInvalida):
        return str(error.mensaje)[:240]
    return "Error inesperado al emitir el comprobante. Se reintentará solo."


def confirmar_pago(
    pedido_id: int, cargo: culqi.Cargo, *, desde_reintento: bool = False
) -> PedidoTienda:
    """Registra la venta de un pedido ya COBRADO. Atómica e idempotente (se puede repetir)."""
    organizacion_id = None
    with transaction.atomic():
        pedido = PedidoTienda.objects.sin_ambito().select_for_update().get(pk=pedido_id)
        organizacion_id = pedido.organizacion_id
        if pedido.estado in YA_COBRADOS:
            return pedido
        if cargo.monto_centimos != _centimos(pedido.total):
            _alerta(pedido, "El monto cobrado no coincide con el total del pedido.")
            raise MontoNoCoincide()
        ahora = timezone.now()
        if pedido.estado in (Estado.EXPIRADO, Estado.CANCELADO):
            # Pagó cuando el pedido ya no estaba vigente: el stock pudo haberse soltado.
            pedido.estado = Estado.PAGADO_FUERA_DE_PLAZO
            pedido.culqi_cargo_id, pedido.culqi_medio, pedido.pagado_en = (
                cargo.id,
                cargo.medio,
                ahora,
            )
            pedido.motivo_atencion = MOTIVO_FUERA_DE_PLAZO
            pedido.save()
            _alerta(pedido, pedido.motivo_atencion)
            return pedido
        pedido.culqi_cargo_id, pedido.culqi_medio, pedido.pagado_en = cargo.id, cargo.medio, ahora
        try:
            empresas = list(
                Empresa.objects.sin_ambito()
                .filter(organizacion_id=pedido.organizacion_id)
                .values_list("pk", flat=True)
            )
            # Savepoint: si algo falla, el cobro no se pierde (ver el except).
            with transaction.atomic(), contexto_tenant(pedido.organizacion_id, empresas, None):
                venta = _registrar_venta(pedido, cargo.medio)
        except Exception as error:  # noqa: BLE001 - nada puede perder un cobro ya aprobado
            logger.exception("tienda_confirmar_pago_fallo", extra={"pedido": pedido.numero})
            pedido.estado = Estado.PAGADO_SIN_COMPROBANTE
            pedido.motivo_atencion = _motivo(error)
            if desde_reintento:
                pedido.reintentos_comprobante += 1
            pedido.save()
            _alerta(pedido, pedido.motivo_atencion)
            return pedido
        pedido.venta = venta
        pedido.estado = Estado.PAGADO
        pedido.motivo_atencion = ""
        pedido.save()
        # El stock ya salió con la venta: la reserva cumplió su papel.
        ReservaStock.objects.sin_ambito().filter(pedido=pedido, liberada_en__isnull=True).update(
            liberada_en=ahora
        )
        IntentoPago.objects.sin_ambito().filter(
            pedido=pedido, estado__in=[IntentoPago.Estado.EN_CURSO, IntentoPago.Estado.INCIERTO]
        ).update(estado=IntentoPago.Estado.APROBADO, culqi_cargo_id=cargo.id, actualizado_en=ahora)
        registrar(
            "tienda.pedido_pagado",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=pedido.organizacion_id,
            resumen=f"Pedido {pedido.numero} pagado con Culqi",
            detalle={"total": str(pedido.total), "medio": cargo.medio},
        )
        transaction.on_commit(catalogo.invalidar)
        transaction.on_commit(lambda: _encolar_correo(pedido.pk))
    logger.info("tienda_pedido_pagado", extra={"organizacion_id": organizacion_id})
    return pedido


def _encolar_correo(pedido_id: int) -> None:
    from .tasks import enviar_confirmacion_pedido

    enviar_confirmacion_pedido.delay(pedido_id)


# ---------------------------------------------------------------------------
# Reintentos y reconciliación
# ---------------------------------------------------------------------------
def reintentar_comprobantes() -> int:
    """Reintenta los pedidos cobrados a los que les faltó el comprobante. Nunca vuelve a cobrar."""
    ids = list(
        PedidoTienda.objects.sin_ambito()
        .filter(
            estado=Estado.PAGADO_SIN_COMPROBANTE,
            reintentos_comprobante__lt=MAX_REINTENTOS_COMPROBANTE,
        )
        .values_list("pk", flat=True)[:100]
    )
    reparados = 0
    for pk in ids:
        reparados += reintentar_pedido(pk).estado == Estado.PAGADO
    return reparados


def reintentar_pedido(pedido_id: int) -> PedidoTienda:
    """Un reintento de emitir el comprobante de un pedido cobrado (nunca vuelve a cobrar)."""
    pedido = PedidoTienda.objects.sin_ambito().get(pk=pedido_id)
    cargo = culqi.Cargo(
        id=pedido.culqi_cargo_id,
        aprobado=True,
        monto_centimos=_centimos(pedido.total),
        pedido=pedido.numero,
        medio=pedido.culqi_medio or "tarjeta",
        mensaje="",
    )
    return confirmar_pago(pedido_id, cargo, desde_reintento=True)


def reconciliar_cargo(organizacion_id: int, cargo_id: str) -> str:
    """Confirma con Culqi un cargo del que avisó el webhook y, si corresponde, termina el pedido.

    No se confía en lo que dice el aviso: el cargo se consulta a Culqi con la llave secreta.
    Devuelve qué pasó (para el registro): confirmado, ignorado, sin_pedido, monto_distinto…
    """
    config = ConfiguracionPago.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()
    if config is None or not config.culqi_llave_secreta:
        return "sin_llave"
    cargo = culqi.obtener_cargo(config.culqi_llave_secreta, cargo_id)  # puede lanzar ErrorCulqi
    if not cargo.aprobado or not cargo.pedido:
        return "ignorado"
    pedido = (
        PedidoTienda.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, numero=cargo.pedido)
        .first()
    )
    if pedido is None:
        return "sin_pedido"
    if pedido.estado in YA_COBRADOS:
        return "ya_confirmado"
    if pedido.estado == Estado.PAGADO_SIN_COMPROBANTE:
        return "en_reintento"
    try:
        confirmar_pago(pedido.pk, cargo)
    except MontoNoCoincide:
        return "monto_distinto"
    return "confirmado"


# ---------------------------------------------------------------------------
# Correo de confirmación
# ---------------------------------------------------------------------------
def enviar_confirmacion(pedido_id: int) -> bool:
    pedido = PedidoTienda.objects.sin_ambito().select_related("cuenta", "venta").get(pk=pedido_id)
    if pedido.estado not in YA_COBRADOS:
        return False
    lineas = LineaPedido.objects.sin_ambito().filter(pedido=pedido).order_by("id")
    detalle = "\n".join(
        f"  - {ln.cantidad.normalize():f} x {ln.descripcion}: S/ {ln.total}" for ln in lineas
    )
    if pedido.modalidad == "RECOJO":
        entrega = f"Recojo en tienda: {pedido.punto_nombre}"
    else:
        entrega = f"Envío a: {pedido.direccion_entrega}, {pedido.ubicacion_entrega}"
    cuerpo = (
        f"Hola {pedido.cuenta.nombres},\n\n"
        f"Recibimos tu pago. Tu pedido {pedido.numero} está confirmado.\n\n"
        f"{detalle}\n\nTotal pagado: S/ {pedido.total}\n{entrega}\n\n"
        f"Puedes ver el estado de tu pedido en {settings.TIENDA_URL.rstrip('/')}/cuenta/pedidos\n"
        "Te enviaremos tu comprobante electrónico a este correo."
    )
    send_mail(f"Pedido {pedido.numero} confirmado", cuerpo, None, [pedido.cuenta.correo])
    return True
