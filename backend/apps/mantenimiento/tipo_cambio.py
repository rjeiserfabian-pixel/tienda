"""Tipo de cambio oficial (SUNAT y SBS) a través de Decolecta, y su consulta por fecha.

* El token vive solo en el entorno (``DECOLECTA_TOKEN``).
* Cada tasa se guarda con la fecha que DEVUELVE el servicio (la SBS publica con un día de retraso).
* Las filas oficiales se crean o se corrigen aquí; los usuarios solo cargan o editan las manuales.
* Si una fuente falla, las demás se actualizan igual: el resultado dice qué pasó con cada una.
"""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar

from . import cuota
from .exceptions import ConsultaNoConfigurada, CuotaAgotada, ServicioConsultaNoDisponible
from .models import FuenteTipoCambio, TipoCambio

logger = logging.getLogger(__name__)

OFICIALES = (FuenteTipoCambio.SUNAT, FuenteTipoCambio.SBS, FuenteTipoCambio.SBS_CONTABLE)
_RUTAS = {
    FuenteTipoCambio.SUNAT: ("/v1/tipo-cambio/sunat", {}),
    FuenteTipoCambio.SBS: ("/v1/tipo-cambio/sbs/average", {"currency": "USD"}),
    FuenteTipoCambio.SBS_CONTABLE: ("/v1/tipo-cambio/sbs/accounting", {"currency": "USD"}),
}
_CUATRO = Decimal("0.0001")
TTL_SIN_REPETIR = 6 * 60 * 60  # no se vuelve a consultar la misma fuente en 6 horas


def _decimal(valor) -> Decimal:
    try:
        numero = Decimal(str(valor)).quantize(_CUATRO)
    except (InvalidOperation, ValueError):
        raise ServicioConsultaNoDisponible() from None
    if numero <= 0:
        raise ServicioConsultaNoDisponible()
    return numero


def _pedir(fuente: str, fecha: date | None) -> tuple[date, Decimal, Decimal]:
    """Consulta una fuente. Devuelve ``(fecha_publicada, compra, venta)``."""
    token = settings.DECOLECTA_TOKEN
    if not token:
        raise ConsultaNoConfigurada()
    cuota.exigir_disponible()
    ruta, base = _RUTAS[fuente]
    params = {**base, **({"date": fecha.isoformat()} if fecha else {})}
    try:
        respuesta = requests.get(
            f"{settings.DECOLECTA_URL.rstrip('/')}{ruta}",
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=settings.DECOLECTA_TIMEOUT,
        )
    except requests.RequestException:
        logger.warning("tipo_cambio_sin_respuesta", extra={"fuente": fuente})
        raise ServicioConsultaNoDisponible() from None
    cuota.registrar_uso()  # llegó al proveedor: gasta cuota
    if respuesta.status_code != 200:
        logger.warning(
            "tipo_cambio_error", extra={"fuente": fuente, "estado": respuesta.status_code}
        )
        raise ServicioConsultaNoDisponible()
    try:
        datos = respuesta.json()
        publicada = datetime.strptime(str(datos["date"])[:10], "%Y-%m-%d").date()
        if fuente == FuenteTipoCambio.SBS_CONTABLE:  # un solo valor: compra = venta
            compra = venta = _decimal(datos["price"])
        else:
            compra, venta = _decimal(datos["buy_price"]), _decimal(datos["sell_price"])
    except (ValueError, KeyError, TypeError):
        raise ServicioConsultaNoDisponible() from None
    return publicada, compra, venta


def _ya_esta_al_dia(organizacion_id: int, fuente: str, fecha: date | None) -> bool:
    """¿Se puede saltar la consulta sin perder nada? Si ya hay esa fecha o se consultó hace poco."""
    objetivo = fecha or timezone.localdate()
    if (
        TipoCambio.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, moneda="USD", fuente=fuente, fecha=objetivo)
        .exists()
    ):
        return True
    return fecha is None and cache.get(f"tipo_cambio:{organizacion_id}:{fuente}") is not None


def sincronizar(
    organizacion_id: int,
    *,
    fecha: date | None = None,
    fuentes=(FuenteTipoCambio.SUNAT,),
    actor_id=None,
    forzar: bool = False,
) -> list[dict]:
    """Trae la tasa de cada fuente y la guarda o corrige. ``fecha=None`` es la más reciente.

    Cuida la cuota del proveedor: no consulta lo que ya se tiene (o se consultó hace menos de 6
    horas) salvo ``forzar``, y se detiene si la cuota del mes se agotó.
    """
    resultados = []
    for fuente in fuentes:
        if fuente not in OFICIALES:
            raise ValidationError({"fuentes": f"Fuente no válida: {fuente}"})
        if not forzar and _ya_esta_al_dia(organizacion_id, fuente, fecha):
            resultados.append({"fuente": fuente, "estado": "al_dia"})
            continue
        try:
            publicada, compra, venta = _pedir(fuente, fecha)
            estado = _guardar(organizacion_id, fuente, publicada, compra, venta)
            if fecha is None:
                cache.set(f"tipo_cambio:{organizacion_id}:{fuente}", True, TTL_SIN_REPETIR)
            resultados.append(
                {
                    "fuente": fuente,
                    "estado": estado,
                    "fecha": publicada.isoformat(),
                    "compra": str(compra),
                    "venta": str(venta),
                }
            )
        except (ConsultaNoConfigurada, ServicioConsultaNoDisponible, CuotaAgotada) as error:
            resultados.append({"fuente": fuente, "estado": "error", "mensaje": error.mensaje})
    nuevos = [r for r in resultados if r["estado"] in ("nuevo", "actualizado")]
    if nuevos:
        registrar(
            "tipo_cambio.actualizado",
            recurso_tipo="tipo_cambio",
            organizacion_id=organizacion_id,
            usuario_id=actor_id,
            resumen=f"Tipo de cambio actualizado desde SUNAT/SBS ({len(nuevos)} fuente(s))",
            detalle={"resultados": nuevos},
        )
    return resultados


@transaction.atomic
def _guardar(
    organizacion_id: int, fuente: str, fecha: date, compra: Decimal, venta: Decimal
) -> str:
    existente = (
        TipoCambio.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, fecha=fecha, moneda="USD", fuente=fuente)
        .first()
    )
    if existente is None:
        fila = TipoCambio(
            organizacion_id=organizacion_id, fecha=fecha, fuente=fuente, compra=compra, venta=venta
        )
        fila.full_clean(validate_unique=False, validate_constraints=False)
        fila.save()
        return "nuevo"
    if (existente.compra, existente.venta) == (compra, venta):
        return "sin_cambios"
    existente.compra, existente.venta = compra, venta
    existente.save(update_fields=["compra", "venta"])
    return "actualizado"


def vigente(organizacion_id: int, fecha: date, fuente: str = FuenteTipoCambio.SUNAT):
    """La tasa que aplica en ``fecha``: la de ese día o, si no hay (feriado), la anterior."""
    return (
        TipoCambio.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, moneda="USD", fuente=fuente, fecha__lte=fecha)
        .order_by("-fecha")
        .first()
    )
