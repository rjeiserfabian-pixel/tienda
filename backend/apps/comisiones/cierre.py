"""Cierre del mes: cuánto ganó cada persona y cuánto se le paga.

Qué hace ``cerrar_mes`` (todo en una transacción, o nada):

1. Aplica la escala y otorga los bonos de cada vendedor que vendió en el mes.
2. Suma, por persona, lo que ganó por ventas, por bonos y como técnico de Servicio Técnico.
3. Le suma lo que debía del mes anterior (devoluciones mayores a lo ganado): si el total sale
   negativo no se le cobra, se «arrastra» al mes siguiente.
4. Guarda la liquidación con el detalle venta por venta y la deja cerrada.

Reglas: solo se cierra un mes ya terminado, y en orden (no se salta un mes). Un mes cerrado no se
mueve: lo que llegue tarde cae en el mes que sigue (ver ``periodos.fecha_abierta``).

Una persona es UNA línea aunque sea vendedora y técnica a la vez, siempre que su usuario esté ligado
a su ficha de personal; si no, el vendedor sin ficha va por su usuario.

Límite conocido: la comisión de un técnico se toma al cerrar; si una venta de servicio se anula
DESPUÉS de cerrar su mes, esa comisión no se descuenta sola.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import ErrorDominio
from apps.mantenimiento.models import Personal
from apps.seguridad.models import Usuario
from apps.servicio_tecnico.models import EstadoOrden, OrdenServicio, PresupuestoOrden
from apps.ventas.models import Venta

from . import avance, periodos
from .models import (
    BonoGanado,
    ComisionComprobante,
    LineaLiquidacion,
    LiquidacionComision,
    MovimientoComision,
)

CERO = Decimal("0")


class CierreInvalido(ErrorDominio):
    status_code = 409
    codigo = "cierre_comisiones_invalido"
    mensaje = "No se puede cerrar ese mes."


def _siguiente(periodo: str) -> str:
    fin = periodos.fin_de_periodo(periodo) + timedelta(days=1)
    return f"{fin.year:04d}-{fin.month:02d}"


def _nombre_usuario(usuario: Usuario | None, respaldo: str = "Vendedor") -> str:
    if usuario is None:
        return respaldo
    return (usuario.get_full_name() or usuario.username).strip()


def mes_por_cerrar(organizacion_id: int, hoy: date | None = None) -> str | None:
    """El próximo mes que se puede cerrar (el siguiente al último cerrado), si ya terminó."""
    hoy = hoy or timezone.localdate()
    ultimo = periodos.ultimo_cerrado(organizacion_id)
    if ultimo is not None:
        candidato = _siguiente(ultimo.periodo)
    else:
        primero = (
            ComisionComprobante.objects.sin_ambito()
            .filter(empresa__organizacion_id=organizacion_id)
            .order_by("fecha_venta")
            .values_list("fecha_venta", flat=True)
            .first()
        )
        if primero is None:
            return None
        candidato = f"{primero.year:04d}-{primero.month:02d}"
    return candidato if periodos.fin_de_periodo(candidato) < hoy else None


def _validar(organizacion_id: int, periodo: str, hoy: date) -> date:
    fin = periodos.fin_de_periodo(periodo)
    if fin >= hoy:
        raise CierreInvalido("Ese mes todavía no termina: se cierra después de su último día.")
    ultimo = periodos.ultimo_cerrado(organizacion_id)
    if ultimo is not None:
        if periodo <= ultimo.periodo:
            raise CierreInvalido(f"El mes {periodo} ya está cerrado.")
        if periodo != _siguiente(ultimo.periodo):
            raise CierreInvalido(
                f"Primero cierra {_siguiente(ultimo.periodo)}: los meses van en orden."
            )
    return fin


def _fila(claves: dict, clave: str, **datos) -> dict:
    if clave not in claves:
        claves[clave] = {
            "vendedor_id": None,
            "personal": None,
            "nombre": "",
            "ventas": CERO,
            "bonos": CERO,
            "tecnico": CERO,
            "detalle": {"ventas": [], "bonos": [], "ordenes": []},
        }
    claves[clave].update({k: v for k, v in datos.items() if v is not None})
    return claves[clave]


@transaction.atomic
def cerrar_mes(
    organizacion_id: int,
    año: int,
    mes: int,
    *,
    usuario_id=None,
    hoy: date | None = None,
) -> LiquidacionComision:
    hoy = hoy or timezone.localdate()
    periodo = avance.periodo_de(año, mes)
    fin = _validar(organizacion_id, periodo, hoy)
    ultimo = periodos.ultimo_cerrado(organizacion_id)
    inicio = periodos.fin_de_periodo(ultimo.periodo) + timedelta(days=1) if ultimo else date.min

    # 1) La escala y los bonos de quienes vendieron en el mes (los ajustes caen en el mes).
    vendieron = set(
        ComisionComprobante.objects.sin_ambito()
        .filter(
            empresa__organizacion_id=organizacion_id,
            fecha_venta__gte=avance.rango_del_mes(año, mes)[0],
            fecha_venta__lte=fin,
        )
        .values_list("vendedor_id", flat=True)
    )
    for vendedor_id in sorted(vendieron, key=str):
        avance.aplicar_escala_del_mes(organizacion_id, vendedor_id, año, mes)
        avance.otorgar_bonos_del_mes(organizacion_id, vendedor_id, año, mes)

    personal_de_usuario = {
        p.usuario_id: p
        for p in Personal.objects.sin_ambito().filter(
            empresa__organizacion_id=organizacion_id, usuario__isnull=False
        )
    }
    filas: dict[str, dict] = {}

    def clave_de(vendedor_id=None, personal: Personal | None = None) -> str:
        if personal is None and vendedor_id is not None:
            personal = personal_de_usuario.get(vendedor_id)
        return f"P:{personal.pk}" if personal else f"U:{vendedor_id}"

    # 2a) Ventas: lo que se movió desde el cierre anterior hasta el último día del mes.
    movimientos = (
        MovimientoComision.objects.sin_ambito()
        .select_related("plan__comprobante")
        .filter(empresa__organizacion_id=organizacion_id, fecha__gte=inicio, fecha__lte=fin)
        .order_by("fecha", "id")
    )
    por_plan: dict[tuple, dict] = {}
    for m in movimientos:
        clave = clave_de(vendedor_id=m.vendedor_id)
        fila = _fila(filas, clave)
        fila["vendedor_id"] = m.vendedor_id
        fila["personal"] = personal_de_usuario.get(m.vendedor_id)
        fila["ventas"] += m.monto
        llave = (clave, m.plan_id)
        if llave not in por_plan:
            por_plan[llave] = {
                "comprobante": m.plan.comprobante.numero_completo,
                "fecha_venta": m.plan.fecha_venta.isoformat(),
                "monto": CERO,
            }
            fila["detalle"]["ventas"].append(por_plan[llave])
        por_plan[llave]["monto"] += m.monto

    # 2b) Bonos del mes.
    for b in BonoGanado.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, periodo=periodo
    ):
        fila = _fila(filas, clave_de(vendedor_id=b.vendedor_id))
        fila["vendedor_id"] = b.vendedor_id
        fila["personal"] = personal_de_usuario.get(b.vendedor_id)
        fila["bonos"] += b.monto
        fila["detalle"]["bonos"].append(
            {"nombre": b.nombre, "ventas_mes": str(b.ventas_mes), "monto": str(b.monto)}
        )

    # 2c) Técnicos: órdenes entregadas en la ventana, cobradas y con la venta vigente.
    ordenes = (
        OrdenServicio.objects.sin_ambito()
        .select_related("tecnico")
        .filter(
            empresa__organizacion_id=organizacion_id,
            estado=EstadoOrden.ENTREGADO,
            tecnico__isnull=False,
            comision_monto__isnull=False,
            fecha_entrega__date__gte=inicio,
            fecha_entrega__date__lte=fin,
        )
        .order_by("fecha_entrega", "id")
    )
    vigentes = set(
        PresupuestoOrden.objects.sin_ambito()
        .filter(
            orden__in=ordenes,
            vigente=True,
            venta__estado=Venta.Estado.EMITIDO,
        )
        .values_list("orden_id", flat=True)
    )
    for orden in ordenes:
        if orden.pk not in vigentes or orden.comision_monto == 0:
            continue
        fila = _fila(filas, clave_de(personal=orden.tecnico))
        fila["personal"] = orden.tecnico
        fila["vendedor_id"] = fila["vendedor_id"] or orden.tecnico.usuario_id
        fila["tecnico"] += orden.comision_monto
        fila["detalle"]["ordenes"].append(
            {
                "orden": orden.codigo,
                "mano_obra": str(orden.comision_base),
                "porcentaje": str(orden.comision_porcentaje),
                "monto": str(orden.comision_monto),
            }
        )

    # 3) Lo que se arrastra del mes anterior (aunque la persona no haya tenido nada este mes).
    arrastres: dict[str, LineaLiquidacion] = {}
    if ultimo is not None:
        for linea in LineaLiquidacion.objects.sin_ambito().filter(liquidacion=ultimo):
            if linea.arrastre_nuevo != 0:
                arrastres[linea.clave] = linea
                _fila(
                    filas,
                    linea.clave,
                    vendedor_id=linea.vendedor_id,
                    personal=linea.personal,
                    nombre=linea.nombre,
                )

    liquidacion = LiquidacionComision.objects.sin_ambito().create(
        organizacion_id=organizacion_id,
        periodo=periodo,
        cerrada_en=timezone.now(),
        cerrada_por_id=usuario_id,
    )
    nombres = {
        u.pk: _nombre_usuario(u)
        for u in Usuario.objects.filter(
            pk__in={f["vendedor_id"] for f in filas.values() if f["vendedor_id"]}
        )
    }
    total_general = CERO
    for clave, f in filas.items():
        arrastre = arrastres[clave].arrastre_nuevo if clave in arrastres else CERO
        total = f["ventas"] + f["bonos"] + f["tecnico"]
        saldo = total + arrastre
        if total == 0 and arrastre == 0:
            continue
        personal = f["personal"]
        nombre = (
            personal.nombre_completo
            if personal is not None
            else f["nombre"] or nombres.get(f["vendedor_id"], "Vendedor")
        )
        a_pagar = max(saldo, CERO)
        estado = (
            LineaLiquidacion.Estado.PENDIENTE if a_pagar > 0 else LineaLiquidacion.Estado.SIN_MONTO
        )
        detalle = {
            "ventas": [
                {**v, "monto": str(v["monto"])} for v in f["detalle"]["ventas"] if v["monto"] != 0
            ],
            "bonos": f["detalle"]["bonos"],
            "ordenes": f["detalle"]["ordenes"],
        }
        LineaLiquidacion.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            liquidacion=liquidacion,
            clave=clave,
            vendedor_id=f["vendedor_id"],
            personal=personal,
            nombre=nombre,
            comisiones_ventas=f["ventas"],
            bonos=f["bonos"],
            comisiones_tecnico=f["tecnico"],
            arrastre_anterior=arrastre,
            total=total,
            a_pagar=a_pagar,
            arrastre_nuevo=min(saldo, CERO),
            detalle=detalle,
            estado=estado,
        )
        total_general += a_pagar
    liquidacion.total_a_pagar = total_general
    liquidacion.save(update_fields=["total_a_pagar", "actualizado_en"])
    registrar(
        "comisiones.mes_cerrado",
        recurso_tipo="liquidacion_comision",
        recurso_id=liquidacion.pk,
        organizacion_id=organizacion_id,
        resumen=f"Comisiones de {periodo} cerradas: a pagar {total_general}",
        detalle={"periodo": periodo, "personas": liquidacion.lineas.count()},
    )
    return liquidacion


def totales_por_estado(liquidacion: LiquidacionComision) -> dict:
    filas = (
        LineaLiquidacion.objects.sin_ambito()
        .filter(liquidacion=liquidacion)
        .values("estado")
        .annotate(total=Sum("a_pagar"))
    )
    return {f["estado"]: str(f["total"] or CERO) for f in filas}
