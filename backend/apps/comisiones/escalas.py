"""Escalas mensuales y metas con bono: crearlas con cuidado (validación y auditoría).

* Una ESCALA tiene tramos «desde S/ X vendidos en el mes, X % de comisión»: el primero empieza en
  0 y cada tramo siguiente empieza más arriba. Máximo 10 tramos.
* Una META CON BONO dice «si vende al menos S/ X en el mes, gana S/ Y» (un monto fijo).
* Cada una puede ser de un vendedor o de todos, con vigencia opcional. No puede haber dos activas
  iguales para el mismo vendedor en las mismas fechas.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from apps.auditoria.servicios import diferencia, registrar
from apps.seguridad.models import Usuario

from .models import EscalaComision, MetaBono, TramoEscala
from .servicios import ReglaInvalida, _fecha, _porcentaje, _solapan, _uuid

MAX_TRAMOS = 10
NOMBRE_MAXIMO = 80
TOPE_DINERO = Decimal("9999999999999.99")


def _dinero(valor, campo: str, *, positivo: bool = False) -> Decimal:
    try:
        numero = Decimal(str(valor).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise ReglaInvalida(f"Escriba «{campo}» como número, por ejemplo 20000.") from None
    if not numero.is_finite() or numero < 0 or numero > TOPE_DINERO:
        raise ReglaInvalida(f"El monto de «{campo}» no es válido.")
    if positivo and numero == 0:
        raise ReglaInvalida(f"«{campo}» debe ser mayor que cero.")
    return numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _nombre(valor) -> str:
    texto = " ".join(str(valor or "").split())
    if len(texto) < 2:
        raise ReglaInvalida("Escriba un nombre.")
    if len(texto) > NOMBRE_MAXIMO:
        raise ReglaInvalida(f"El nombre admite hasta {NOMBRE_MAXIMO} caracteres.")
    return texto


def _vendedor(organizacion_id: int, valor):
    vendedor_id = _uuid(valor)
    if (
        vendedor_id is not None
        and not Usuario.objects.filter(pk=vendedor_id, organizacion_id=organizacion_id).exists()
    ):
        raise ReglaInvalida("Elija un vendedor de esta organización.")
    return vendedor_id


def _vigencia(datos: dict, actual):
    def dato(campo):
        return datos[campo] if campo in datos else getattr(actual, campo, None)

    desde, hasta = _fecha(dato("vigente_desde"), "desde"), _fecha(dato("vigente_hasta"), "hasta")
    if desde and hasta and hasta < desde:
        raise ReglaInvalida("La fecha «hasta» no puede ser anterior a «desde».")
    return desde, hasta


def _sin_solapes(modelo, organizacion_id, vendedor_id, desde, hasta, actual, activa, que):
    if not activa:
        return
    otras = modelo.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, activa=True, vendedor_id=vendedor_id
    )
    if actual is not None:
        otras = otras.exclude(pk=actual.pk)
    if any(_solapan(desde, hasta, o.vigente_desde, o.vigente_hasta) for o in otras):
        raise ReglaInvalida(
            f"Ya hay {que} activa para ese vendedor en esas fechas. Cámbiala o páusala primero."
        )


# --- escalas -----------------------------------------------------------------------------
def _tramos(lista) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(lista, list) or not lista:
        raise ReglaInvalida("La escala necesita al menos un tramo.")
    if len(lista) > MAX_TRAMOS:
        raise ReglaInvalida(f"Una escala admite hasta {MAX_TRAMOS} tramos.")
    tramos = []
    for t in lista:
        if not isinstance(t, dict):
            raise ReglaInvalida("Los tramos no son válidos.")
        tramos.append((_dinero(t.get("desde"), "desde"), _porcentaje(t.get("porcentaje"))))
    tramos.sort(key=lambda t: t[0])
    if tramos[0][0] != 0:
        raise ReglaInvalida("El primer tramo debe empezar en 0 (desde la primera venta).")
    if len({t[0] for t in tramos}) != len(tramos):
        raise ReglaInvalida("Dos tramos no pueden empezar en el mismo monto.")
    return tramos


def escala_a_dict(escala: EscalaComision) -> dict:
    return {
        "nombre": escala.nombre,
        "vendedor": str(escala.vendedor_id) if escala.vendedor_id else None,
        "desde": escala.vigente_desde.isoformat() if escala.vigente_desde else None,
        "hasta": escala.vigente_hasta.isoformat() if escala.vigente_hasta else None,
        "activa": escala.activa,
        "tramos": [[str(t.desde), str(t.porcentaje)] for t in escala.tramos.order_by("desde")],
    }


def _validar_escala(organizacion_id: int, datos: dict, actual: EscalaComision | None):
    nombre = _nombre(datos["nombre"] if "nombre" in datos else getattr(actual, "nombre", ""))
    vendedor_id = _vendedor(
        organizacion_id,
        datos["vendedor_id"] if "vendedor_id" in datos else getattr(actual, "vendedor_id", None),
    )
    desde, hasta = _vigencia(datos, actual)
    activa = bool(datos["activa"]) if "activa" in datos else getattr(actual, "activa", True)
    _sin_solapes(
        EscalaComision, organizacion_id, vendedor_id, desde, hasta, actual, activa, "una escala"
    )
    tramos = _tramos(datos["tramos"]) if "tramos" in datos else None
    if tramos is None and actual is None:
        raise ReglaInvalida("La escala necesita al menos un tramo.")
    campos = {
        "nombre": nombre,
        "vendedor_id": vendedor_id,
        "vigente_desde": desde,
        "vigente_hasta": hasta,
        "activa": activa,
    }
    return campos, tramos


def _guardar_tramos(escala: EscalaComision, tramos) -> None:
    TramoEscala.objects.sin_ambito().filter(escala=escala).delete()
    for desde, porcentaje in tramos:
        TramoEscala.objects.sin_ambito().create(
            organizacion_id=escala.organizacion_id,
            escala=escala,
            desde=desde,
            porcentaje=porcentaje,
        )


@transaction.atomic
def crear_escala(organizacion_id: int, datos: dict) -> EscalaComision:
    campos, tramos = _validar_escala(organizacion_id, datos, None)
    escala = EscalaComision.objects.sin_ambito().create(organizacion_id=organizacion_id, **campos)
    _guardar_tramos(escala, tramos)
    registrar(
        "comisiones.escala_creada",
        recurso_tipo="escala_comision",
        recurso_id=escala.pk,
        resumen=f"Escala de comisión «{escala.nombre}» creada",
        detalle=escala_a_dict(escala),
    )
    return escala


@transaction.atomic
def actualizar_escala(escala: EscalaComision, datos: dict) -> EscalaComision:
    escala = EscalaComision.objects.sin_ambito().select_for_update().get(pk=escala.pk)
    antes = escala_a_dict(escala)
    campos, tramos = _validar_escala(escala.organizacion_id, datos, escala)
    for campo, valor in campos.items():
        setattr(escala, campo, valor)
    escala.save()
    if tramos is not None:
        _guardar_tramos(escala, tramos)
    despues = escala_a_dict(escala)
    if antes != despues:
        registrar(
            "comisiones.escala_editada",
            recurso_tipo="escala_comision",
            recurso_id=escala.pk,
            resumen=f"Escala de comisión «{escala.nombre}» modificada",
            detalle=diferencia(antes, despues),
        )
    return escala


@transaction.atomic
def eliminar_escala(escala: EscalaComision) -> None:
    escala = EscalaComision.objects.sin_ambito().select_for_update().get(pk=escala.pk)
    datos, escala_id, nombre = escala_a_dict(escala), escala.pk, escala.nombre
    escala.delete()  # sus tramos se van con ella
    registrar(
        "comisiones.escala_eliminada",
        recurso_tipo="escala_comision",
        recurso_id=escala_id,
        resumen=f"Escala de comisión «{nombre}» eliminada",
        detalle=datos,
    )


# --- metas con bono ----------------------------------------------------------------------
def meta_a_dict(meta: MetaBono) -> dict:
    return {
        "nombre": meta.nombre,
        "vendedor": str(meta.vendedor_id) if meta.vendedor_id else None,
        "meta": str(meta.meta),
        "bono": str(meta.bono),
        "desde": meta.vigente_desde.isoformat() if meta.vigente_desde else None,
        "hasta": meta.vigente_hasta.isoformat() if meta.vigente_hasta else None,
        "activa": meta.activa,
    }


def _validar_meta(organizacion_id: int, datos: dict, actual: MetaBono | None) -> dict:
    def dato(campo, por_defecto=None):
        return datos[campo] if campo in datos else getattr(actual, campo, por_defecto)

    desde, hasta = _vigencia(datos, actual)
    return {
        "nombre": _nombre(dato("nombre", "")),
        "vendedor_id": _vendedor(organizacion_id, dato("vendedor_id")),
        "meta": _dinero(dato("meta"), "meta", positivo=True),
        "bono": _dinero(dato("bono"), "bono", positivo=True),
        "vigente_desde": desde,
        "vigente_hasta": hasta,
        "activa": bool(dato("activa", True)),
    }


@transaction.atomic
def crear_meta(organizacion_id: int, datos: dict) -> MetaBono:
    campos = _validar_meta(organizacion_id, datos, None)
    meta = MetaBono.objects.sin_ambito().create(organizacion_id=organizacion_id, **campos)
    registrar(
        "comisiones.meta_creada",
        recurso_tipo="meta_bono",
        recurso_id=meta.pk,
        resumen=f"Meta «{meta.nombre}»: vender {meta.meta} gana un bono de {meta.bono}",
        detalle=meta_a_dict(meta),
    )
    return meta


@transaction.atomic
def actualizar_meta(meta: MetaBono, datos: dict) -> MetaBono:
    meta = MetaBono.objects.sin_ambito().select_for_update().get(pk=meta.pk)
    antes = meta_a_dict(meta)
    for campo, valor in _validar_meta(meta.organizacion_id, datos, meta).items():
        setattr(meta, campo, valor)
    meta.save()
    despues = meta_a_dict(meta)
    if antes != despues:
        registrar(
            "comisiones.meta_editada",
            recurso_tipo="meta_bono",
            recurso_id=meta.pk,
            resumen=f"Meta «{meta.nombre}» modificada",
            detalle=diferencia(antes, despues),
        )
    return meta


@transaction.atomic
def eliminar_meta(meta: MetaBono) -> None:
    meta = MetaBono.objects.sin_ambito().select_for_update().get(pk=meta.pk)
    if meta.otorgados.exists():
        raise ReglaInvalida(
            "Esta meta ya otorgó bonos y no se puede eliminar. Puedes pausarla para que no "
            "se otorgue más."
        )
    datos, meta_id, nombre = meta_a_dict(meta), meta.pk, meta.nombre
    meta.delete()
    registrar(
        "comisiones.meta_eliminada",
        recurso_tipo="meta_bono",
        recurso_id=meta_id,
        resumen=f"Meta «{nombre}» eliminada",
        detalle=datos,
    )
