"""Gastos recurrentes: plantillas de lo que se paga cada cierto tiempo, con aviso de cuándo toca.

El sistema nunca registra un gasto por su cuenta: avisa, propone los datos y, cuando la persona
registra el gasto, la plantilla pasa a su siguiente fecha. También se puede omitir un ciclo (por
ejemplo, un mes que no hubo gasto).
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import (
    CategoriaGasto,
    EstadoRegistro,
    Periodicidad,
    Proveedor,
    TipoComprobante,
)
from apps.mantenimiento.pagos import fecha_de_cuota
from apps.organizacion.models import Empresa

from .exceptions import GastoInvalido, GastoNoModificable
from .models import GastoRecurrente, Moneda

logger = logging.getLogger(__name__)

MAXIMO = Decimal("9999999999999.99")
MAX_AVISO = 30
MAX_ADELANTO_DIAS = 800  # la próxima fecha no se programa más allá de unos dos años


def _exigir_empresa(empresa: Empresa) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa.pk):
        raise EmpresaNoHabilitada()


def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def exigir_utilizable(empresa: Empresa, recurrente: GastoRecurrente) -> None:
    """La plantilla es de la empresa y está activa: solo así se registra un gasto con ella."""
    if recurrente.empresa_id != empresa.pk:
        raise GastoInvalido("El gasto recurrente no es de esta empresa.")
    if recurrente.estado != GastoRecurrente.Estado.ACTIVO:
        raise GastoInvalido("El gasto recurrente está inactivo.")


def siguiente_fecha(recurrente: GastoRecurrente) -> date:
    """La fecha del próximo ciclo: un período después de la que tocaba."""
    return fecha_de_cuota(recurrente.proxima_fecha, recurrente.periodicidad, 1)


def avanzar(recurrente: GastoRecurrente, *, registrada: date | None = None) -> GastoRecurrente:
    """Pasa la plantilla al siguiente ciclo (al registrar un gasto o al omitirlo)."""
    recurrente.proxima_fecha = siguiente_fecha(recurrente)
    campos = ["proxima_fecha"]
    if registrada is not None:
        recurrente.ultima_registrada = registrada
        campos.append("ultima_registrada")
    recurrente.save(update_fields=campos)
    return recurrente


def _validar(
    empresa: Empresa,
    *,
    nombre: str,
    categoria: CategoriaGasto,
    descripcion: str,
    con_comprobante: bool,
    tipo_comprobante: TipoComprobante | None,
    proveedor: Proveedor | None,
    moneda: str,
    importe_estimado: Decimal | None,
    periodicidad: Periodicidad,
    proxima_fecha: date,
    avisar_dias: int,
    excluir_pk: int | None,
) -> dict:
    nombre = _texto(nombre, 80)
    if len(nombre) < 3:
        raise GastoInvalido("Ponga un nombre (por ejemplo, «Alquiler del local»).")
    repetido = GastoRecurrente.objects.filter(empresa=empresa, nombre__iexact=nombre)
    if excluir_pk:
        repetido = repetido.exclude(pk=excluir_pk)
    if repetido.exists():
        raise GastoInvalido("Ya hay un gasto recurrente con ese nombre.")
    org = empresa.organizacion_id
    if categoria.organizacion_id != org or categoria.estado != EstadoRegistro.ACTIVO:
        raise GastoInvalido("La categoría no es válida.")
    if periodicidad.organizacion_id != org or periodicidad.estado != EstadoRegistro.ACTIVO:
        raise GastoInvalido("La frecuencia no es válida.")
    descripcion = _texto(descripcion, 250)
    if len(descripcion) < 3:
        raise GastoInvalido("Describa el gasto (qué es y para qué).")
    if moneda not in Moneda.values:
        raise GastoInvalido("La moneda no es válida.")
    if not isinstance(con_comprobante, bool):
        raise GastoInvalido("Indique si el gasto tiene comprobante.")
    if con_comprobante:
        if tipo_comprobante is not None and (
            tipo_comprobante.organizacion_id != org
            or tipo_comprobante.estado != EstadoRegistro.ACTIVO
            or not tipo_comprobante.aplica_compras
        ):
            raise GastoInvalido("El tipo de comprobante no es válido.")
        if proveedor is not None and (
            proveedor.organizacion_id != org or proveedor.estado != EstadoRegistro.ACTIVO
        ):
            raise GastoInvalido("El proveedor no es válido.")
    elif tipo_comprobante is not None or proveedor is not None:
        raise GastoInvalido("Un gasto sin comprobante no lleva tipo de comprobante ni proveedor.")
    if importe_estimado is not None and (
        not isinstance(importe_estimado, Decimal)
        or not importe_estimado.is_finite()
        or importe_estimado != importe_estimado.quantize(Decimal("0.01"))
        or not (0 < importe_estimado <= MAXIMO)
    ):
        raise GastoInvalido("El importe estimado debe ser mayor que cero (hasta 2 decimales).")
    if not isinstance(proxima_fecha, date) or isinstance(proxima_fecha, datetime):
        raise GastoInvalido("Indique cuándo toca el próximo gasto.")
    if proxima_fecha > timezone.localdate() + timedelta(days=MAX_ADELANTO_DIAS):
        raise GastoInvalido("La próxima fecha está demasiado lejos.")
    if (
        not isinstance(avisar_dias, int)
        or isinstance(avisar_dias, bool)
        or not (0 <= avisar_dias <= MAX_AVISO)
    ):
        raise GastoInvalido(f"Avisar con 0 a {MAX_AVISO} días de anticipación.")
    return {
        "nombre": nombre,
        "categoria": categoria,
        "descripcion": descripcion,
        "con_comprobante": con_comprobante,
        "tipo_comprobante": tipo_comprobante if con_comprobante else None,
        "proveedor": proveedor if con_comprobante else None,
        "moneda": moneda,
        "importe_estimado": importe_estimado,
        "periodicidad": periodicidad,
        "proxima_fecha": proxima_fecha,
        "avisar_dias": avisar_dias,
    }


@transaction.atomic
def guardar(
    empresa: Empresa,
    datos: dict,
    *,
    instancia: GastoRecurrente | None = None,
) -> GastoRecurrente:
    """Crea o edita un gasto recurrente. Al editar, lo no enviado se queda como estaba."""
    _exigir_empresa(empresa)
    if instancia is not None:
        actuales = {
            "nombre": instancia.nombre,
            "categoria": instancia.categoria,
            "descripcion": instancia.descripcion,
            "con_comprobante": instancia.con_comprobante,
            "tipo_comprobante": instancia.tipo_comprobante,
            "proveedor": instancia.proveedor,
            "moneda": instancia.moneda,
            "importe_estimado": instancia.importe_estimado,
            "periodicidad": instancia.periodicidad,
            "proxima_fecha": instancia.proxima_fecha,
            "avisar_dias": instancia.avisar_dias,
        }
        datos = {**actuales, **datos}
    validados = _validar(empresa, excluir_pk=instancia.pk if instancia else None, **datos)
    if instancia is None:
        instancia = GastoRecurrente.objects.create(empresa=empresa, **validados)
        accion = "creado"
    else:
        for campo, valor in validados.items():
            setattr(instancia, campo, valor)
        instancia.save()
        accion = "editado"
    registrar(
        f"gastos.recurrente_{accion}",
        recurso_tipo="gasto_recurrente",
        recurso_id=instancia.pk,
        empresa_id=empresa.pk,
        resumen=f"Gasto recurrente «{instancia.nombre}» {accion}",
        detalle={"proxima_fecha": instancia.proxima_fecha},
    )
    return instancia


@transaction.atomic
def cambiar_estado(recurrente: GastoRecurrente, estado: str) -> GastoRecurrente:
    _exigir_empresa(recurrente.empresa)
    if estado not in GastoRecurrente.Estado.values:
        raise GastoInvalido("El estado no es válido.")
    recurrente.estado = estado
    recurrente.save(update_fields=["estado"])
    registrar(
        "gastos.recurrente_estado",
        recurso_tipo="gasto_recurrente",
        recurso_id=recurrente.pk,
        empresa_id=recurrente.empresa_id,
        resumen=f"Gasto recurrente «{recurrente.nombre}»: {estado.lower()}",
        detalle={"estado": estado},
    )
    return recurrente


@transaction.atomic
def omitir(recurrente: GastoRecurrente) -> GastoRecurrente:
    """Salta el ciclo que tocaba (ese mes no hubo gasto) sin registrar nada."""
    recurrente = (
        GastoRecurrente.objects.select_for_update()
        .select_related("empresa", "periodicidad")
        .get(pk=recurrente.pk)
    )
    _exigir_empresa(recurrente.empresa)
    if recurrente.estado != GastoRecurrente.Estado.ACTIVO:
        raise GastoNoModificable("El gasto recurrente está inactivo.")
    anterior = recurrente.proxima_fecha
    avanzar(recurrente)
    registrar(
        "gastos.recurrente_omitido",
        recurso_tipo="gasto_recurrente",
        recurso_id=recurrente.pk,
        empresa_id=recurrente.empresa_id,
        resumen=f"Gasto recurrente «{recurrente.nombre}»: se omitió el ciclo {anterior:%d/%m/%Y}",
        detalle={"omitido": anterior, "proxima": recurrente.proxima_fecha},
    )
    return recurrente
