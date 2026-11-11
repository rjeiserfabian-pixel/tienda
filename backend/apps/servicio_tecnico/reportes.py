"""Lo que el taller necesita saber: cómo va, cuánto tarda, quién rinde y cuánto deja cada servicio.

Todo se calcula en la base de datos con consultas agrupadas. Los importes salen de lo que de verdad
se cobró (comprobantes vigentes) y el costo de los repuestos es el real con que salieron del stock;
una orden entregada sin cobrar o cuyo comprobante se anuló no suma ingresos ni comisión.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import (
    Avg,
    Count,
    DecimalField,
    DurationField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.mantenimiento.models import Area, EstadoRegistro, Personal
from apps.ventas.models import LineaProforma, Venta

from .flujo import ESTADOS_QUE_ESPERAN
from .models import (
    ComisionTecnico,
    EstadoOrden,
    EstadoRepuesto,
    HistorialEstado,
    OrdenServicio,
    PresupuestoOrden,
    RepuestoOrden,
)
from .servicios import DIAS_PARA_ABANDONO

CERO = Decimal("0")
MAXIMO_DIAS = 366
FILAS_MAXIMAS_HISTORIAL = 50_000
DINERO = DecimalField(max_digits=16, decimal_places=2)


@dataclass(frozen=True, slots=True)
class Periodo:
    desde: date
    hasta: date

    @classmethod
    def validar(cls, desde: date | None, hasta: date | None) -> "Periodo":
        hoy = timezone.localdate()
        hasta = hasta or hoy
        desde = desde or hasta.replace(day=1)
        if desde > hasta:
            raise ValueError("«Desde» no puede ser posterior a «Hasta».")
        if (hasta - desde).days > MAXIMO_DIAS:
            raise ValueError(f"El periodo admite hasta {MAXIMO_DIAS} días.")
        return cls(desde, hasta)


def _vigente_cobrada():
    """La orden tiene un presupuesto cobrado con un comprobante que sigue vigente."""
    return Exists(
        PresupuestoOrden.objects.filter(
            orden=OuterRef("pk"), vigente=True, venta__estado=Venta.Estado.EMITIDO
        )
    )


def _en_estado_desde():
    return Subquery(
        HistorialEstado.objects.sin_ambito()
        .filter(orden=OuterRef("pk"), estado_nuevo=OuterRef("estado"))
        .order_by("-id")
        .values("creado_en")[:1]
    )


def _entregadas(empresa_id: int, p: Periodo):
    return OrdenServicio.objects.filter(
        empresa_id=empresa_id,
        estado=EstadoOrden.ENTREGADO,
        fecha_entrega__date__gte=p.desde,
        fecha_entrega__date__lte=p.hasta,
    )


def _dias(valor) -> float | None:
    return round(valor.total_seconds() / 86_400, 1) if valor is not None else None


# ---------------------------------------------------------------------------
# Resumen y tiempos
# ---------------------------------------------------------------------------
def resumen(empresa_id: int, p: Periodo) -> dict:
    hoy = timezone.localdate()
    todas = OrdenServicio.objects.filter(empresa_id=empresa_id)
    abiertas = todas.exclude(estado=EstadoOrden.ENTREGADO)
    ingresadas = todas.filter(fecha_ingreso__date__gte=p.desde, fecha_ingreso__date__lte=p.hasta)
    entregadas = _entregadas(empresa_id, p)
    limite = timezone.now() - timedelta(days=DIAS_PARA_ABANDONO)
    ciclo = entregadas.aggregate(
        m=Avg(
            ExpressionWrapper(F("fecha_entrega") - F("fecha_ingreso"), output_field=DurationField())
        )
    )["m"]
    n_entregadas = entregadas.count()
    reingresos = ingresadas.filter(es_garantia=True).count()
    por_estado = dict(abiertas.values_list("estado").annotate(n=Count("id")))
    return {
        "ingresadas": ingresadas.count(),
        "entregadas": n_entregadas,
        "abiertas": abiertas.count(),
        "atrasadas": abiertas.filter(fecha_promesa__lt=hoy).count(),
        "por_abandonar": abiertas.annotate(desde=_en_estado_desde())
        .filter(estado__in=ESTADOS_QUE_ESPERAN, desde__lte=limite)
        .count(),
        "reingresos_garantia": reingresos,
        "reingresos_sobre_entregadas": (
            round(100 * reingresos / n_entregadas, 1) if n_entregadas else None
        ),
        "ciclo_promedio_dias": _dias(ciclo),
        "por_estado": [
            {"estado": e, "nombre": EstadoOrden(e).label, "cantidad": por_estado.get(e, 0)}
            for e in EstadoOrden.values
            if por_estado.get(e)
        ],
    }


def tiempos_por_estado(empresa_id: int, p: Periodo) -> dict:
    """Cuánto está una orden, en promedio, en cada estado (las ingresadas en el periodo)."""
    filas = (
        HistorialEstado.objects.filter(
            orden__empresa_id=empresa_id,
            orden__fecha_ingreso__date__gte=p.desde,
            orden__fecha_ingreso__date__lte=p.hasta,
        )
        .order_by("orden_id", "id")
        .values_list("orden_id", "estado_nuevo", "creado_en")[: FILAS_MAXIMAS_HISTORIAL + 1]
    )
    filas = list(filas)
    truncado = len(filas) > FILAS_MAXIMAS_HISTORIAL
    filas = filas[:FILAS_MAXIMAS_HISTORIAL]
    sumas: dict[str, float] = {}
    cuentas: dict[str, int] = {}
    for (orden, estado, desde), (orden_sig, _, hasta) in zip(filas, filas[1:], strict=False):
        if orden != orden_sig:
            continue  # el último estado de una orden sigue abierto: no tiene duración todavía
        sumas[estado] = sumas.get(estado, 0.0) + (hasta - desde).total_seconds()
        cuentas[estado] = cuentas.get(estado, 0) + 1
    return {
        "truncado": truncado,
        "estados": [
            {
                "estado": e,
                "nombre": EstadoOrden(e).label,
                "dias_promedio": round(sumas[e] / cuentas[e] / 86_400, 1),
                "veces": cuentas[e],
            }
            for e in EstadoOrden.values
            if e in sumas
        ],
    }


# ---------------------------------------------------------------------------
# Técnicos y comisiones
# ---------------------------------------------------------------------------
def tecnicos(empresa_id: int, p: Periodo, *, con_importes: bool) -> list[dict]:
    """Lo que rinde cada técnico en el periodo; con importes, también lo cobrado y su comisión."""
    personal = Personal.objects.filter(empresa_id=empresa_id, area=Area.TECNICO).select_related(
        "comision_servicio"
    )
    abiertas = dict(
        OrdenServicio.objects.filter(empresa_id=empresa_id, tecnico__isnull=False)
        .exclude(estado=EstadoOrden.ENTREGADO)
        .values_list("tecnico_id")
        .annotate(n=Count("id"))
    )
    entregadas = _entregadas(empresa_id, p).filter(tecnico__isnull=False)
    base = entregadas.values("tecnico_id").annotate(
        n=Count("id"),
        ciclo=Avg(
            ExpressionWrapper(F("fecha_entrega") - F("fecha_ingreso"), output_field=DurationField())
        ),
        garantias=Count("id", filter=Q(es_garantia=True)),
    )
    por_tecnico = {f["tecnico_id"]: f for f in base}
    cobradas = {}
    if con_importes:
        cobradas = {
            f["tecnico_id"]: f
            for f in entregadas.filter(_vigente_cobrada())
            .values("tecnico_id")
            .annotate(
                mano_obra=Coalesce(Sum("comision_base"), CERO, output_field=DINERO),
                comision=Coalesce(Sum("comision_monto"), CERO, output_field=DINERO),
            )
        }
    filas = []
    for t in personal.order_by("apellidos", "nombres"):
        e = por_tecnico.get(t.pk)
        if t.estado != EstadoRegistro.ACTIVO and e is None and t.pk not in abiertas:
            continue
        fila = {
            "id": t.pk,
            "nombre": t.nombre_completo,
            "tiene_usuario": bool(t.usuario_id),
            "abiertas": abiertas.get(t.pk, 0),
            "entregadas": e["n"] if e else 0,
            "ciclo_promedio_dias": _dias(e["ciclo"]) if e else None,
            "reingresos": e["garantias"] if e else 0,
        }
        if con_importes:
            c = cobradas.get(t.pk)
            comision = getattr(t, "comision_servicio", None)
            fila.update(
                porcentaje=str(comision.porcentaje) if comision else "0.00",
                mano_obra=str(c["mano_obra"]) if c else "0.00",
                comision=str(c["comision"]) if c else "0.00",
            )
        filas.append(fila)
    return filas


def comisiones_configuradas(empresa_id: int) -> list[dict]:
    """Los técnicos de la empresa y el porcentaje de comisión de cada uno."""
    filas = (
        Personal.objects.filter(
            empresa_id=empresa_id, area=Area.TECNICO, estado=EstadoRegistro.ACTIVO
        )
        .select_related("comision_servicio")
        .order_by("apellidos", "nombres")
    )
    filas = list(filas)
    return [
        {
            "id": t.pk,
            "nombre": t.nombre_completo,
            "porcentaje": f"{_porcentaje_de(t):.2f}",
        }
        for t in filas
    ]


def _porcentaje_de(tecnico: Personal) -> Decimal:
    fila = getattr(tecnico, "comision_servicio", None)
    return fila.porcentaje if fila else CERO


def fijar_comision(personal: Personal, porcentaje: Decimal) -> ComisionTecnico:
    """Guarda el porcentaje de comisión de un técnico (vale para las entregas que vengan)."""
    if personal.area != Area.TECNICO:
        raise ValueError("Solo el personal del área técnica tiene comisión.")
    if not (CERO <= porcentaje <= 100):
        raise ValueError("El porcentaje va de 0 a 100.")
    fila, _ = ComisionTecnico.objects.update_or_create(
        personal=personal, defaults={"empresa_id": personal.empresa_id, "porcentaje": porcentaje}
    )
    return fila


# ---------------------------------------------------------------------------
# Utilidad por servicio
# ---------------------------------------------------------------------------
def _expresiones():
    """Ingreso, costo de repuestos, comisión y utilidad de un presupuesto cobrado (en soles)."""
    ingresos = (
        LineaProforma.objects.sin_ambito()
        .filter(proforma=OuterRef("proforma_id"))
        .values("proforma")
        .annotate(s=Sum("valor_venta"))
        .values("s")
    )
    costo = (
        RepuestoOrden.objects.sin_ambito()
        .filter(presupuesto=OuterRef("pk"), estado=EstadoRepuesto.CONSUMIDO)
        .values("presupuesto")
        .annotate(s=Sum("costo_total"))
        .values("s")
    )
    ingreso = Coalesce(Subquery(ingresos, output_field=DINERO), CERO, output_field=DINERO)
    costo_repuestos = Coalesce(Subquery(costo, output_field=DINERO), CERO, output_field=DINERO)
    comision = Coalesce(F("orden__comision_monto"), CERO, output_field=DINERO)
    utilidad = ExpressionWrapper(ingreso - costo_repuestos - comision, output_field=DINERO)
    return ingreso, costo_repuestos, comision, utilidad


def _cobrados(empresa_id: int, p: Periodo):
    """Los presupuestos cobrados y entregados en el periodo (el comprobante sigue vigente)."""
    return PresupuestoOrden.objects.filter(
        orden__empresa_id=empresa_id,
        orden__estado=EstadoOrden.ENTREGADO,
        orden__fecha_entrega__date__gte=p.desde,
        orden__fecha_entrega__date__lte=p.hasta,
        vigente=True,
        venta__estado=Venta.Estado.EMITIDO,
    )


def utilidad_resumen(empresa_id: int, p: Periodo) -> dict:
    ingreso, costo, comision, utilidad = _expresiones()
    base = _cobrados(empresa_id, p)
    total = base.aggregate(
        servicios=Count("id"),
        ingreso=Coalesce(Sum(ingreso), CERO, output_field=DINERO),
        costo=Coalesce(Sum(costo), CERO, output_field=DINERO),
        comision=Coalesce(Sum(comision), CERO, output_field=DINERO),
        utilidad=Coalesce(Sum(utilidad), CERO, output_field=DINERO),
    )
    por_tipo = (
        base.values(
            nombre=Coalesce(F("orden__tipo_servicio__nombre"), Value("Sin tipo de servicio"))
        )
        .annotate(
            servicios=Count("id"),
            ingreso_total=Sum(ingreso),
            costo_total=Sum(costo),
            utilidad_total=Sum(utilidad),
        )
        .order_by("-utilidad_total", "nombre")
    )
    return {
        "totales": {k: str(v) for k, v in total.items()},
        "por_tipo_servicio": [
            {
                "nombre": f["nombre"],
                "servicios": f["servicios"],
                "ingreso": str(f["ingreso_total"]),
                "costo": str(f["costo_total"]),
                "utilidad": str(f["utilidad_total"]),
            }
            for f in por_tipo
        ],
    }


def utilidad_ordenes(empresa_id: int, p: Periodo):
    """Las órdenes cobradas del periodo, de la más reciente a la más antigua (para paginar)."""
    ingreso, costo, comision, utilidad = _expresiones()
    return (
        _cobrados(empresa_id, p)
        .annotate(ingreso=ingreso, costo_repuestos=costo, comision=comision, utilidad=utilidad)
        .select_related(
            "orden__cliente", "orden__equipo__tipo", "orden__tecnico", "orden__tipo_servicio"
        )
        .order_by("-orden__fecha_entrega", "-id")
    )


# ---------------------------------------------------------------------------
# Equipos más reparados
# ---------------------------------------------------------------------------
def equipos_mas_reparados(empresa_id: int, p: Periodo, limite: int = 10) -> dict:
    ingresadas = OrdenServicio.objects.filter(
        empresa_id=empresa_id,
        fecha_ingreso__date__gte=p.desde,
        fecha_ingreso__date__lte=p.hasta,
    )
    por_equipo = (
        ingresadas.values(
            "equipo_id",
            "equipo__marca",
            "equipo__modelo",
            "equipo__numero_serie",
            "equipo__tipo__nombre",
            "equipo__cliente__nombre",
        )
        .annotate(ingresos=Count("id"))
        .filter(ingresos__gte=2)
        .order_by("-ingresos", "equipo_id")[:limite]
    )
    por_modelo = (
        ingresadas.exclude(equipo__marca="", equipo__modelo="")
        .values("equipo__tipo__nombre", "equipo__marca", "equipo__modelo")
        .annotate(ingresos=Count("id"))
        .order_by("-ingresos", "equipo__marca", "equipo__modelo")[:limite]
    )
    return {
        "equipos": [
            {
                "equipo": f["equipo_id"],
                "tipo": f["equipo__tipo__nombre"],
                "marca": f["equipo__marca"],
                "modelo": f["equipo__modelo"],
                "numero_serie": f["equipo__numero_serie"],
                "cliente": f["equipo__cliente__nombre"],
                "ingresos": f["ingresos"],
            }
            for f in por_equipo
        ],
        "modelos": [
            {
                "tipo": f["equipo__tipo__nombre"],
                "marca": f["equipo__marca"],
                "modelo": f["equipo__modelo"],
                "ingresos": f["ingresos"],
            }
            for f in por_modelo
        ],
    }
