"""Libro de Reclamaciones virtual (obligatorio para tiendas en línea en Perú).

Qué hace el sistema:

* Registra la hoja de reclamación con los datos que pide la norma y le da un número correlativo por
  año («0001-2026»). Se puede reclamar contra cualquiera de las empresas de la tienda.
* Manda al consumidor una constancia por correo con una copia de lo que registró, y avisa al
  negocio.
* El negocio tiene 15 días hábiles para responder (se calculan sin sábados ni domingos; los feriados
  no se descuentan, así que el plazo mostrado es el más corto posible: nunca se pasa de largo).
* Responder desde el panel guarda la respuesta y se la manda al consumidor por correo.

Un reclamo registrado nunca se borra ni se edita.
"""

import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Correlativo
from apps.organizacion.models import Empresa

from .exceptions import DatosInvalidos, PedidoNoEncontrado
from .models import ConfiguracionTienda, CuentaCliente, Reclamo

logger = logging.getLogger(__name__)

Estado = Reclamo.Estado
PLAZO_DIAS_HABILES = 15
AVISO_DIAS = 3  # «por vencer»: faltan 3 días o menos
TAM_PAGINA = 25
MAX_RESPUESTA = 2000
DOCUMENTOS = {
    "DNI": r"^\d{8}$",
    "RUC": r"^\d{11}$",
    "CE": r"^[A-Za-z0-9]{6,20}$",
    "PASAPORTE": r"^[A-Za-z0-9]{6,20}$",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sumar_dias_habiles(desde, dias: int):
    """La fecha de ``dias`` días hábiles después (sin sábados ni domingos)."""
    fecha = desde
    restantes = dias
    while restantes > 0:
        fecha += timedelta(days=1)
        if fecha.weekday() < 5:
            restantes -= 1
    return fecha


def _texto(valor, maximo: int, campo: str, *, obligatorio=True, multilinea=False) -> str:
    valor = _CONTROL.sub("", str(valor or ""))
    if multilinea:
        valor = "\n".join(" ".join(linea.split()) for linea in valor.strip().splitlines())
    else:
        valor = " ".join(valor.split())
    if obligatorio and not valor:
        raise DatosInvalidos(f"Completa «{campo}».")
    if len(valor) > maximo:
        raise DatosInvalidos(f"«{campo}» admite hasta {maximo} caracteres.")
    return valor


def empresas_del_libro(organizacion_id: int) -> list[Empresa]:
    return list(
        Empresa.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, estado="ACTIVO")
        .order_by("-es_principal", "razon_social")
    )


def datos_del_libro(organizacion_id: int) -> dict:
    """Lo que necesita el formulario público: los proveedores y el plazo de respuesta."""
    return {
        "plazo_dias_habiles": PLAZO_DIAS_HABILES,
        "empresas": [
            {
                "id": e.pk,
                "razon_social": e.razon_social,
                "ruc": e.ruc,
                "direccion": e.direccion_fiscal,
            }
            for e in empresas_del_libro(organizacion_id)
        ],
    }


def _siguiente_numero(organizacion_id: int, ahora) -> str:
    clave = f"reclamo_{ahora.year}"
    fila, _ = Correlativo.objects.get_or_create(organizacion_id=organizacion_id, clave=clave)
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return f"{fila.ultimo:04d}-{ahora.year}"


def _validar(organizacion_id: int, d: dict) -> dict:
    tipo = d.get("tipo")
    if tipo not in Reclamo.Tipo.values:
        raise DatosInvalidos("Elige si es un reclamo o una queja.")
    doc_tipo = str(d.get("documento_tipo", "")).upper()
    doc_num = _texto(d.get("documento_numero"), 20, "Número de documento").upper().replace(" ", "")
    if doc_tipo not in DOCUMENTOS or not re.match(DOCUMENTOS[doc_tipo], doc_num):
        raise DatosInvalidos("Revisa el tipo y el número de documento.")
    bien = d.get("bien_tipo")
    if bien not in ("PRODUCTO", "SERVICIO"):
        raise DatosInvalidos("Indica si se trata de un producto o de un servicio.")
    monto = d.get("monto")
    if monto in (None, ""):
        monto = None
    else:
        try:
            monto = Decimal(str(monto)).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise DatosInvalidos("El monto reclamado no es válido.") from None
        if monto < 0 or monto > Decimal("99999999"):
            raise DatosInvalidos("El monto reclamado no es válido.")
    empresas = {e.pk: e for e in empresas_del_libro(organizacion_id)}
    empresa = empresas.get(d.get("empresa"))
    if empresa is None:
        raise DatosInvalidos("Elige contra qué empresa es tu reclamo.")
    menor = bool(d.get("menor_de_edad"))
    apoderado = _texto(d.get("apoderado"), 150, "Padre, madre o apoderado", obligatorio=menor)
    correo = _texto(d.get("correo"), 150, "Correo electrónico").lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo):
        raise DatosInvalidos("Escribe un correo válido: ahí te enviaremos la constancia.")
    return {
        "empresa": empresa,
        "tipo": tipo,
        "nombre": _texto(d.get("nombre"), 150, "Nombres y apellidos"),
        "documento_tipo": doc_tipo,
        "documento_numero": doc_num,
        "domicilio": _texto(d.get("domicilio"), 250, "Domicilio"),
        "telefono": _texto(d.get("telefono"), 30, "Teléfono", obligatorio=False),
        "correo": correo,
        "menor_de_edad": menor,
        "apoderado": apoderado,
        "bien_tipo": bien,
        "monto": monto,
        "bien_descripcion": _texto(
            d.get("bien_descripcion"), 300, "Descripción del producto o servicio"
        ),
        "pedido_numero": _texto(d.get("pedido_numero"), 20, "Número de pedido", obligatorio=False),
        "detalle": _texto(d.get("detalle"), 2000, "Detalle", multilinea=True),
        "pedido_consumidor": _texto(
            d.get("pedido_consumidor"), 1000, "Lo que pides", multilinea=True
        ),
    }


def _nombre_tienda(organizacion_id: int) -> str:
    return (
        ConfiguracionTienda.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id)
        .values_list("nombre", flat=True)
        .first()
        or "la tienda"
    )


def _constancia(r: Reclamo, tienda: str) -> str:
    return (
        f"Hola {r.nombre},\n\n"
        f"Registramos tu {r.get_tipo_display().lower()} en el Libro de Reclamaciones "
        f"de {tienda}.\n\n"
        f"HOJA DE RECLAMACIÓN N.º {r.numero}\n"
        f"Fecha: {timezone.localtime(r.creado_en).strftime('%d/%m/%Y %H:%M')}\n"
        f"Proveedor: {r.empresa.razon_social} (RUC {r.empresa.ruc})\n"
        f"Consumidor: {r.nombre} · {r.documento_tipo} {r.documento_numero}\n"
        f"Bien contratado: {r.bien_tipo.capitalize()} · {r.bien_descripcion}"
        + (f" · monto S/ {r.monto}" if r.monto is not None else "")
        + (f"\nPedido: {r.pedido_numero}" if r.pedido_numero else "")
        + f"\n\nDetalle:\n{r.detalle}\n\nTu pedido:\n{r.pedido_consumidor}\n\n"
        f"Te responderemos a este correo en un plazo máximo de {PLAZO_DIAS_HABILES} días hábiles "
        f"(hasta el {timezone.localtime(r.vence_en).strftime('%d/%m/%Y')}).\n"
        "Conserva este mensaje: es tu constancia."
    )


def crear(organizacion_id: int, datos: dict, *, cuenta: CuentaCliente | None = None) -> Reclamo:
    limpios = _validar(organizacion_id, datos)
    ahora = timezone.now()
    with transaction.atomic():
        reclamo = Reclamo.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            numero=_siguiente_numero(organizacion_id, ahora),
            cuenta=cuenta,
            vence_en=sumar_dias_habiles(ahora, PLAZO_DIAS_HABILES),
            **limpios,
        )
        registrar(
            "tienda.reclamo_registrado",
            recurso_tipo="reclamo",
            recurso_id=reclamo.pk,
            organizacion_id=organizacion_id,
            resumen=f"Reclamo {reclamo.numero} registrado en el Libro de Reclamaciones",
            detalle={"tipo": reclamo.tipo, "empresa": reclamo.empresa_id},
        )
        transaction.on_commit(lambda: avisar_registro(reclamo.pk))
    return reclamo


def avisar_registro(reclamo_id: int) -> None:
    """Constancia al consumidor y aviso al negocio (un correo caído no deshace el registro)."""
    r = Reclamo.objects.sin_ambito().select_related("empresa").get(pk=reclamo_id)
    tienda = _nombre_tienda(r.organizacion_id)
    try:
        send_mail(
            f"Constancia de tu {r.get_tipo_display().lower()} N.º {r.numero}",
            _constancia(r, tienda),
            None,
            [r.correo],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001 - el reclamo ya quedó registrado
        logger.exception("tienda_reclamo_constancia_fallo", extra={"reclamo_id": r.pk})
    config = (
        ConfiguracionTienda.objects.sin_ambito().filter(organizacion_id=r.organizacion_id).first()
    )
    destino = (config.correo if config else "") or r.empresa.correo
    if not destino:
        return
    try:
        send_mail(
            f"Nuevo {r.get_tipo_display().lower()} en el Libro de Reclamaciones: {r.numero}",
            f"{r.nombre} registró un {r.get_tipo_display().lower()} contra "
            f"{r.empresa.razon_social}.\n"
            f"Tienes hasta el {timezone.localtime(r.vence_en).strftime('%d/%m/%Y')} para responder "
            f"({PLAZO_DIAS_HABILES} días hábiles).\n\n"
            f"Atiéndelo en el panel: Tienda › Reclamos.",
            None,
            [destino],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("tienda_reclamo_aviso_fallo", extra={"reclamo_id": r.pk})


# ---------------------------------------------------------------------------
# El panel
# ---------------------------------------------------------------------------
def _salida(r: Reclamo, ahora=None) -> dict:
    ahora = ahora or timezone.now()
    dias = (r.vence_en - ahora).total_seconds() / 86400
    return {
        "id": r.pk,
        "numero": r.numero,
        "tipo": r.tipo,
        "tipo_texto": r.get_tipo_display(),
        "estado": r.estado,
        "estado_texto": r.get_estado_display(),
        "empresa": r.empresa.razon_social,
        "nombre": r.nombre,
        "documento": f"{r.documento_tipo} {r.documento_numero}",
        "domicilio": r.domicilio,
        "telefono": r.telefono,
        "correo": r.correo,
        "menor_de_edad": r.menor_de_edad,
        "apoderado": r.apoderado,
        "bien_tipo": r.bien_tipo,
        "monto": format(r.monto, "f") if r.monto is not None else None,
        "bien_descripcion": r.bien_descripcion,
        "pedido_numero": r.pedido_numero,
        "detalle": r.detalle,
        "pedido_consumidor": r.pedido_consumidor,
        "fecha": r.creado_en.isoformat(),
        "vence_en": r.vence_en.isoformat(),
        "dias_restantes": None if r.estado == Estado.RESPONDIDO else int(dias // 1),
        "vencido": r.estado == Estado.PENDIENTE and r.vence_en < ahora,
        "respuesta": r.respuesta,
        "respondido_en": r.respondido_en.isoformat() if r.respondido_en else None,
        "respondido_por": r.respondido_por,
        "respuesta_enviada": r.respuesta_enviada,
    }


def listar(organizacion_id: int, params) -> dict:
    try:
        pagina = max(int(params.get("page", 1)), 1)
    except ValueError:
        pagina = 1
    ahora = timezone.now()
    base = Reclamo.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    qs = base.select_related("empresa")
    filtro = params.get("estado", "")
    if filtro == "PENDIENTE":
        qs = qs.filter(estado=Estado.PENDIENTE)
    elif filtro == "RESPONDIDO":
        qs = qs.filter(estado=Estado.RESPONDIDO)
    elif filtro == "por_vencer":
        qs = qs.filter(estado=Estado.PENDIENTE, vence_en__lte=ahora + timedelta(days=AVISO_DIAS))
    texto = (params.get("q") or "").strip()[:60]
    if texto:
        qs = qs.filter(
            Q(numero__icontains=texto)
            | Q(nombre__icontains=texto)
            | Q(documento_numero__icontains=texto)
            | Q(pedido_numero__icontains=texto)
        )
    total = qs.count()
    orden = ("vence_en",) if filtro in ("PENDIENTE", "por_vencer") else ("-id",)
    filas = qs.order_by(*orden)[(pagina - 1) * TAM_PAGINA : pagina * TAM_PAGINA]
    pendientes = base.filter(estado=Estado.PENDIENTE)
    return {
        "count": total,
        "page": pagina,
        "tamano": TAM_PAGINA,
        "results": [_salida(r, ahora) for r in filas],
        "resumen": {
            "total": base.count(),
            "pendientes": pendientes.count(),
            "por_vencer": pendientes.filter(
                vence_en__lte=ahora + timedelta(days=AVISO_DIAS)
            ).count(),
            "vencidos": pendientes.filter(vence_en__lt=ahora).count(),
            "respondidos": base.filter(estado=Estado.RESPONDIDO).count(),
        },
    }


def _de(organizacion_id: int, reclamo_id: int) -> Reclamo:
    r = (
        Reclamo.objects.sin_ambito()
        .select_related("empresa")
        .filter(organizacion_id=organizacion_id, pk=reclamo_id)
        .first()
    )
    if r is None:
        raise PedidoNoEncontrado("No encontramos ese reclamo.")
    return r


def _enviar_respuesta(r: Reclamo) -> bool:
    tienda = _nombre_tienda(r.organizacion_id)
    try:
        send_mail(
            f"Respuesta a tu {r.get_tipo_display().lower()} N.º {r.numero}",
            f"Hola {r.nombre},\n\n"
            f"Esta es la respuesta de {r.empresa.razon_social} a tu {r.get_tipo_display().lower()} "
            f"N.º {r.numero} en el Libro de Reclamaciones de {tienda}:\n\n{r.respuesta}\n\n"
            "Si no estás conforme, puedes acudir a INDECOPI.",
            None,
            [r.correo],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("tienda_reclamo_respuesta_fallo", extra={"reclamo_id": r.pk})
        return False
    return True


def responder(organizacion_id: int, reclamo_id: int, *, usuario, texto: str) -> dict:
    texto = _texto(texto, MAX_RESPUESTA, "Respuesta", multilinea=True)
    if len(texto) < 10:
        raise DatosInvalidos("Escribe la respuesta completa para el consumidor.")
    with transaction.atomic():
        r = _de(organizacion_id, reclamo_id)
        if r.estado == Estado.RESPONDIDO:
            raise DatosInvalidos("Este reclamo ya fue respondido.")
        r.respuesta = texto
        r.estado = Estado.RESPONDIDO
        r.respondido_en = timezone.now()
        r.respondido_por = (usuario.get_full_name() or usuario.get_username())[:150]
        r.save()
        registrar(
            "tienda.reclamo_respondido",
            recurso_tipo="reclamo",
            recurso_id=r.pk,
            organizacion_id=organizacion_id,
            resumen=f"Reclamo {r.numero} respondido",
        )
    r.respuesta_enviada = _enviar_respuesta(r)
    r.save(update_fields=["respuesta_enviada", "actualizado_en"])
    return _salida(r)


def reenviar_respuesta(organizacion_id: int, reclamo_id: int) -> dict:
    r = _de(organizacion_id, reclamo_id)
    if r.estado != Estado.RESPONDIDO:
        raise DatosInvalidos("Este reclamo todavía no tiene respuesta.")
    r.respuesta_enviada = _enviar_respuesta(r)
    r.save(update_fields=["respuesta_enviada", "actualizado_en"])
    return _salida(r)


def detalle(organizacion_id: int, reclamo_id: int) -> dict:
    return _salida(_de(organizacion_id, reclamo_id))
