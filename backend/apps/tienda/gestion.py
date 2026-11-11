"""Gestión de los pedidos de la tienda desde el panel: lista, detalle, avance de estados y notas.

El pedido es de la organización (no de una empresa): quien tenga el permiso ve todos. Cada cambio
queda en el historial del pedido y en la auditoría. El avisar al cliente se hace con un correo en
segundo plano (nunca con datos de pago).
"""

import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.auditoria.servicios import registrar

from . import catalogo, deuda_web, pagar, pedidos, reembolsos, series_pedido
from .exceptions import PedidoInvalido, PedidoNoEncontrado, TransicionInvalida
from .models import (
    DeudaCobroTienda,
    HistorialPedido,
    IntentoPago,
    LineaPedido,
    PedidoTienda,
    ReembolsoPedido,
)

logger = logging.getLogger(__name__)

Estado = PedidoTienda.Estado
ATENCION = (
    Estado.PAGADO_SIN_COMPROBANTE,
    Estado.PAGADO_FUERA_DE_PLAZO,
    Estado.REEMBOLSO_PENDIENTE,
)

# Grupos que usa el panel para sus pestañas.
GRUPOS = {
    "por_atender": [Estado.PAGADO, Estado.EN_PREPARACION],
    "listos": [Estado.LISTO_PARA_RECOJO, Estado.ENVIADO],
    "entregados": [Estado.ENTREGADO],
    "sin_pagar": [Estado.PENDIENTE_PAGO, Estado.CANCELADO, Estado.EXPIRADO],
    "atencion": list(ATENCION),
    "reembolsados": [Estado.REEMBOLSADO, Estado.REEMBOLSADO_PARCIAL],
}
MAX_TEXTO = 500
TAM_PAGINA = 20
MAX_PAGINA = 50


def _base(organizacion_id: int):
    return PedidoTienda.objects.sin_ambito().filter(organizacion_id=organizacion_id)


def _fecha(texto: str | None) -> date | None:
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        raise PedidoInvalido("Las fechas deben ser como 2026-11-30.") from None


def _entero(valor, defecto: int, minimo: int, maximo: int) -> int:
    try:
        return min(max(int(valor), minimo), maximo)
    except (TypeError, ValueError):
        return defecto


# ---------------------------------------------------------------------------
# Lista y resumen
# ---------------------------------------------------------------------------
def listar(organizacion_id: int, params) -> dict:
    qs = _base(organizacion_id).select_related("cuenta")
    estados = [e for e in (params.get("estado") or "").split(",") if e in Estado.values]
    grupo = params.get("grupo", "")
    if estados:
        qs = qs.filter(estado__in=estados)
    elif grupo in GRUPOS:
        qs = qs.filter(estado__in=GRUPOS[grupo])
    if params.get("requiere_atencion") == "1":
        qs = qs.filter(estado__in=ATENCION)
    if params.get("modalidad") in PedidoTienda.Modalidad.values:
        qs = qs.filter(modalidad=params["modalidad"])
    texto = " ".join((params.get("q") or "").split())[:80]
    if texto:
        qs = qs.filter(
            Q(numero__icontains=texto)
            | Q(nombre_comprobante__icontains=texto)
            | Q(documento_numero__icontains=texto)
            | Q(receptor__icontains=texto)
            | Q(cuenta__correo__icontains=texto)
            | Q(cuenta__nombres__icontains=texto)
            | Q(cuenta__apellidos__icontains=texto)
        )
    zona = timezone.get_current_timezone()
    desde, hasta = _fecha(params.get("desde")), _fecha(params.get("hasta"))
    if desde:
        qs = qs.filter(creado_en__gte=datetime.combine(desde, time.min, tzinfo=zona))
    if hasta:
        qs = qs.filter(
            creado_en__lt=datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona)
        )
    pagina = _entero(params.get("page"), 1, 1, 100000)
    tam = _entero(params.get("page_size"), TAM_PAGINA, 1, MAX_PAGINA)
    total = qs.count()
    filas = list(qs.order_by("-id")[(pagina - 1) * tam : pagina * tam])
    return {
        "count": total,
        "page": pagina,
        "paginas": max((total + tam - 1) // tam, 1),
        "results": [_fila(p) for p in filas],
    }


def _fila(p: PedidoTienda) -> dict:
    return {
        **pedidos.pedido_salida(p, detalle=False),
        "cliente": f"{p.cuenta.nombres} {p.cuenta.apellidos}".strip(),
        "correo": p.cuenta.correo,
        "comprobante_tipo": p.comprobante_tipo,
        "nombre_comprobante": p.nombre_comprobante,
        "receptor": p.receptor,
        "punto": p.punto_nombre,
        "seguimiento": p.seguimiento,
        "motivo_atencion": p.motivo_atencion if p.estado in ATENCION else "",
    }


def resumen(organizacion_id: int) -> dict:
    conteo = dict(_base(organizacion_id).values_list("estado").annotate(n=Count("id")).order_by())
    por_estado = {e: conteo.get(e, 0) for e in Estado.values}
    return {
        "por_estado": por_estado,
        "grupos": {g: sum(por_estado[e] for e in estados) for g, estados in GRUPOS.items()},
        "requieren_atencion": sum(por_estado[e] for e in ATENCION),
    }


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
def _cargo_parcial(cargo: str) -> str:
    """El id del cargo de Culqi recortado (lo justo para buscarlo en el panel de Culqi)."""
    return f"{cargo[:9]}…{cargo[-4:]}" if len(cargo) > 16 else cargo


def pedido_de(organizacion_id: int, numero: str) -> PedidoTienda:
    pedido = _base(organizacion_id).select_related("cuenta", "venta").filter(numero=numero).first()
    if pedido is None:
        raise PedidoNoEncontrado()
    return pedido


def detalle(p: PedidoTienda) -> dict:
    lineas = (
        LineaPedido.objects.sin_ambito()
        .filter(pedido=p)
        .select_related("empresa", "almacen")
        .order_by("id")
    )
    comprobantes = []
    if p.venta_id:
        from apps.ventas.models import ComprobanteVenta

        comprobantes = [
            {
                "id": c.pk,
                "numero": c.numero_completo,
                "empresa": c.empresa.razon_social,
                "total": format(c.total, "f"),
            }
            for c in ComprobanteVenta.objects.sin_ambito()
            .filter(venta_id=p.venta_id)
            .select_related("empresa")
            .order_by("id")
        ]
    base = pedidos.pedido_salida(p, detalle=True)
    base["lineas"] = [
        {
            **salida,
            "id": ln.pk,
            "empresa": ln.empresa.razon_social,
            "almacen": ln.almacen.nombre if ln.almacen else "",
            # Lo que sale en el comprobante y lo que realmente se entrega (si el almacén la cambió).
            "series_panel": series_pedido.series_para_panel(ln),
        }
        for salida, ln in zip(base["lineas"], lineas, strict=True)
    ]
    deudas = (
        DeudaCobroTienda.objects.sin_ambito()
        .filter(pedido=p)
        .select_related("deudora", "acreedora")
    )
    return {
        **base,
        "comprobantes": comprobantes,
        "venta_id": p.venta_id,
        "seguimiento": p.seguimiento,
        "motivo_atencion": p.motivo_atencion if p.estado in ATENCION else "",
        "cliente": {
            "nombre": f"{p.cuenta.nombres} {p.cuenta.apellidos}".strip(),
            "correo": p.cuenta.correo,
            "correo_verificado": p.cuenta.verificada,
            "celular": p.cuenta.celular,
        },
        "pago": {
            "medio": p.culqi_medio,
            "cargo": _cargo_parcial(p.culqi_cargo_id),
            "pagado_en": p.pagado_en.isoformat() if p.pagado_en else None,
            "total": format(p.total, "f"),
            "reintentos_comprobante": p.reintentos_comprobante,
        },
        "intentos": [
            {
                "estado": i.estado,
                "estado_texto": i.get_estado_display(),
                "monto": format(i.monto, "f"),
                "mensaje": i.mensaje,
                "creado_en": i.creado_en.isoformat(),
            }
            for i in IntentoPago.objects.sin_ambito().filter(pedido=p).order_by("id")
        ],
        "deudas_entre_empresas": [
            {
                "deudora": d.deudora.razon_social,
                "acreedora": d.acreedora.razon_social,
                "monto": format(d.monto, "f"),
                **estado,
                "liquidada": estado["estado"] in ("LIQUIDADA", "REVERSA_LIQUIDADA"),
            }
            for d, estado in ((d, deuda_web.estado_de(d)) for d in deudas)
        ],
        "historial": [
            {
                "tipo": h.tipo,
                "estado": h.estado,
                "estado_texto": Estado(h.estado).label if h.estado in Estado.values else "",
                "texto": h.texto,
                "usuario": h.usuario_nombre,
                "creado_en": h.creado_en.isoformat(),
            }
            for h in p.historial.all()
        ],
        "reembolsos": [
            {
                "id": r.pk,
                "tipo": r.tipo,
                "tipo_texto": r.get_tipo_display(),
                "estado": r.estado,
                "estado_texto": r.get_estado_display(),
                "monto": format(r.monto, "f"),
                "motivo": r.motivo,
                "motivo_tipo_texto": r.get_motivo_tipo_display(),
                "mensaje": r.mensaje,
                "usuario": r.usuario_nombre,
                "creado_en": r.creado_en.isoformat(),
                "aprobado_en": r.aprobado_en.isoformat() if r.aprobado_en else None,
            }
            for r in ReembolsoPedido.objects.sin_ambito().filter(pedido=p).order_by("id")
        ],
        "monto_reembolsado": format(p.monto_reembolsado, "f"),
        "acciones": acciones_posibles(p),
    }


# ---------------------------------------------------------------------------
# Avance de estados
# ---------------------------------------------------------------------------
def siguiente_estados(p: PedidoTienda) -> list[str]:
    """Estados a los que se puede pasar desde el actual."""
    if p.estado == Estado.PAGADO:
        return [Estado.EN_PREPARACION]
    if p.estado == Estado.EN_PREPARACION:
        return [Estado.ENVIADO if p.modalidad == "ENVIO" else Estado.LISTO_PARA_RECOJO]
    if p.estado in (Estado.ENVIADO, Estado.LISTO_PARA_RECOJO):
        return [Estado.ENTREGADO]
    if p.estado == Estado.PENDIENTE_PAGO:
        return [Estado.CANCELADO]
    return []


def _puede_reembolsar(p: PedidoTienda) -> bool:
    try:
        reembolsos.ruta_de(p)
    except Exception:  # noqa: BLE001 - cualquier motivo por el que no se puede = no se ofrece
        return False
    return True


def acciones_posibles(p: PedidoTienda) -> dict:
    return {
        "cambiar_serie": p.estado in series_pedido.ESTADOS_EDITABLES and p.venta_id is not None,
        "siguientes": [{"estado": e, "texto": Estado(e).label} for e in siguiente_estados(p)],
        "reintentar_comprobante": p.estado == Estado.PAGADO_SIN_COMPROBANTE,
        "reembolsar": _puede_reembolsar(p),
        "reintentar_reembolso": p.estado == Estado.REEMBOLSO_PENDIENTE,
        "avisa_al_cliente": [
            e for e in siguiente_estados(p) if e in (Estado.ENVIADO, Estado.LISTO_PARA_RECOJO)
        ],
    }


def _limpio(texto: str | None) -> str:
    texto = " ".join((texto or "").split())
    if len(texto) > MAX_TEXTO:
        raise PedidoInvalido(f"El texto admite hasta {MAX_TEXTO} caracteres.")
    return texto


def _quien(usuario) -> dict:
    nombre = (usuario.get_full_name() or usuario.get_username())[:150]
    return {"usuario_id": usuario.pk, "usuario_nombre": nombre}


def cambiar_estado(
    organizacion_id: int, numero: str, nuevo: str, *, nota: str, seguimiento: str, usuario
) -> PedidoTienda:
    nota, seguimiento = _limpio(nota), _limpio(seguimiento)[:200]
    with transaction.atomic():
        pedido = (
            _base(organizacion_id)
            .select_for_update()
            .select_related("cuenta")
            .filter(numero=numero)
            .first()
        )
        if pedido is None:
            raise PedidoNoEncontrado()
        if nuevo not in Estado.values:
            raise TransicionInvalida("El estado no es válido.")
        if nuevo not in siguiente_estados(pedido):
            raise TransicionInvalida(
                f"Un pedido «{pedido.get_estado_display()}» no puede pasar a "
                f"«{Estado(nuevo).label}»."
            )
        anterior = pedido.estado
        if nuevo == Estado.CANCELADO:
            if pedidos._con_pago_en_camino().filter(pedido=pedido).exists():
                raise TransicionInvalida("El cliente está pagando en este momento: espera.")
            pedidos.liberar_reservas(pedido)
        pedido.estado = nuevo
        update = ["estado", "actualizado_en"]
        if seguimiento:
            pedido.seguimiento = seguimiento
            update.append("seguimiento")
        pedido.save(update_fields=update)
        HistorialPedido.objects.create(
            pedido=pedido,
            tipo=HistorialPedido.Tipo.ESTADO,
            estado=nuevo,
            texto=" · ".join(t for t in (seguimiento, nota) if t),
            **_quien(usuario),
        )
        registrar(
            "tienda.pedido_estado",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=organizacion_id,
            resumen=f"Pedido {pedido.numero}: {Estado(anterior).label} → {Estado(nuevo).label}",
            detalle={"de": anterior, "a": nuevo},
        )
        if nuevo in (Estado.ENVIADO, Estado.LISTO_PARA_RECOJO):
            transaction.on_commit(lambda: _encolar_aviso(pedido.pk, nota))
        transaction.on_commit(catalogo.invalidar)
    return pedido


def agregar_nota(organizacion_id: int, numero: str, texto: str, *, usuario) -> PedidoTienda:
    texto = _limpio(texto)
    if not texto:
        raise PedidoInvalido("Escribe la nota.")
    with transaction.atomic():
        pedido = _base(organizacion_id).select_for_update().filter(numero=numero).first()
        if pedido is None:
            raise PedidoNoEncontrado()
        HistorialPedido.objects.create(
            pedido=pedido, tipo=HistorialPedido.Tipo.NOTA, texto=texto, **_quien(usuario)
        )
        registrar(
            "tienda.pedido_nota",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=organizacion_id,
            resumen=f"Nota interna en el pedido {pedido.numero}",
        )
    return pedido


def reintentar_comprobante(organizacion_id: int, numero: str, *, usuario) -> PedidoTienda:
    """Vuelve a intentar emitir el comprobante de un pedido ya cobrado. Nunca vuelve a cobrar."""
    pedido = _base(organizacion_id).filter(numero=numero).first()
    if pedido is None:
        raise PedidoNoEncontrado()
    if pedido.estado != Estado.PAGADO_SIN_COMPROBANTE:
        raise TransicionInvalida("Este pedido no tiene un comprobante pendiente.")
    resultado = pagar.reintentar_pedido(pedido.pk)
    HistorialPedido.objects.create(
        pedido=resultado,
        tipo=HistorialPedido.Tipo.NOTA,
        texto="Se reintentó emitir el comprobante: "
        + ("quedó emitido." if resultado.estado == Estado.PAGADO else "sigue pendiente."),
        **_quien(usuario),
    )
    registrar(
        "tienda.pedido_reintento_comprobante",
        recurso_tipo="pedido_tienda",
        recurso_id=pedido.pk,
        organizacion_id=organizacion_id,
        resumen=f"Reintento manual del comprobante del pedido {pedido.numero}",
        detalle={"resultado": resultado.estado},
    )
    return resultado


# ---------------------------------------------------------------------------
# Aviso al cliente
# ---------------------------------------------------------------------------
def _encolar_aviso(pedido_id: int, nota: str) -> None:
    from .tasks import enviar_aviso_pedido

    enviar_aviso_pedido.delay(pedido_id, nota)


def enviar_aviso(pedido_id: int, nota: str = "") -> bool:
    """Correo al cliente cuando su pedido sale (envío) o queda listo para recoger."""
    pedido = PedidoTienda.objects.sin_ambito().select_related("cuenta", "punto").get(pk=pedido_id)
    url = f"{settings.TIENDA_URL.rstrip('/')}/cuenta/pedidos"
    if pedido.estado == Estado.ENVIADO:
        asunto = f"Tu pedido {pedido.numero} va en camino"
        cuerpo = (
            f"Hola {pedido.cuenta.nombres},\n\nTu pedido {pedido.numero} ya salió.\n"
            f"Dirección de entrega: {pedido.direccion_entrega}, {pedido.ubicacion_entrega}\n"
        )
        if pedido.envio_paga_en_destino:
            cuerpo += "Recuerda que el flete lo pagas a la agencia al recibir.\n"
        if pedido.seguimiento:
            cuerpo += f"Seguimiento: {pedido.seguimiento}\n"
    elif pedido.estado == Estado.LISTO_PARA_RECOJO:
        asunto = f"Tu pedido {pedido.numero} está listo para recoger"
        horario = pedido.punto.horario if pedido.punto_id else ""
        direccion = pedido.punto.direccion if pedido.punto_id else ""
        cuerpo = (
            f"Hola {pedido.cuenta.nombres},\n\nTu pedido {pedido.numero} ya está listo.\n"
            f"Recógelo en: {pedido.punto_nombre}" + (f", {direccion}" if direccion else "") + "\n"
        )
        if horario:
            cuerpo += f"Horario: {horario}\n"
        if pedido.seguimiento:
            cuerpo += f"{pedido.seguimiento}\n"
        cuerpo += "Lleva tu documento de identidad.\n"
    else:
        return False
    if nota:
        cuerpo += f"\n{nota}\n"
    cuerpo += f"\nPuedes ver tu pedido en {url}"
    send_mail(asunto, cuerpo, None, [pedido.cuenta.correo], fail_silently=False)
    return True
