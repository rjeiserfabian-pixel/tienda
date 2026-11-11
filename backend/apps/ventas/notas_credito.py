"""Notas de crédito: devolver al cliente parte o todo lo que compró en un comprobante.

Una nota de crédito de una empresa deshace, para las líneas que se devuelven:

* **El stock**: vuelve al almacén de donde salió, al mismo costo con que salió (con sus series).
* **Lo que el cliente debe**: si el comprobante fue a crédito, primero se reducen las cuotas que
  todavía debía, empezando por la última; así no se le devuelve dinero que nunca pagó.
* **El dinero**: lo que sobra se reembolsa al cliente, por los métodos que se indiquen, desde la
  caja o cuenta de la empresa (el reembolso debe sumar exactamente ese resto).

El IGV y el valor de cada línea son la parte proporcional de lo que se vendió, sin perder céntimos:
al devolver lo que quedaba de una línea se devuelve exactamente lo que faltaba. Las notas de
crédito no se anulan (como en SUNAT): un error se corrige con otra operación. Un comprobante con
notas de crédito ya no se puede anular.

Si lo devuelto vino de la otra empresa en una venta interna, vuelve a ella al costo con que
salió (ver ``ventas_internas``).

Motivos: «Anulación de la operación» (01) y «Devolución total» (06) devuelven todo lo que queda del
comprobante; la anulación solo sirve si todavía no se devolvió nada. «Devolución por ítem» (07)
devuelve las cantidades que se elijan. La serie de la nota sale del comprobante: una factura lleva
una serie que empieza con F (FC01), una boleta con B (BC01) y un documento interno (nota de venta)
una serie que no sea fiscal.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Exists, F, OuterRef, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.inventario import periodos
from apps.inventario.costeo import a_dos
from apps.inventario.models import OrigenMovimiento, TipoMovimiento
from apps.inventario.movimientos import LineaNueva
from apps.inventario.movimientos import registrar_movimiento as registrar_entrada
from apps.mantenimiento.models import EstadoRegistro, SerieComprobante, TipoComprobante
from apps.mantenimiento.series import formatear, siguiente_numero

from . import ventas_internas
from .exceptions import VentaInvalida
from .models import (
    CERO,
    MOTIVOS_TOTALES,
    AbonoVenta,
    CobroVenta,
    ComprobanteVenta,
    CuotaVenta,
    FormaPago,
    LineaNotaCredito,
    LineaVenta,
    MotivoNota,
    NotaCredito,
    ReduccionCuota,
    ReembolsoNota,
)
from .servicios import CobroEntrada, _cobros_validos, _texto, resolver_cuenta
from .servicios import serie_sugerida as servicios_serie_sugerida

logger = logging.getLogger(__name__)

MONEDA_SOLES = "PEN"


@dataclass(frozen=True, slots=True)
class LineaDevuelta:
    """Una línea de la venta y cuánto de ella se devuelve (con las series, si las lleva)."""

    linea: LineaVenta
    cantidad: Decimal
    series: tuple[str, ...] = ()


@dataclass(slots=True)
class _Devuelta:
    linea: LineaVenta
    cantidad: Decimal
    valor: Decimal
    igv: Decimal
    total: Decimal
    costo_total: Decimal
    series: tuple[str, ...]


@dataclass(slots=True)
class CalculoNota:
    """Lo que sería la nota de crédito: sus importes y a dónde va lo devuelto."""

    comprobante: ComprobanteVenta
    lineas: list[_Devuelta]
    op_gravada: Decimal
    op_exonerada: Decimal
    op_inafecta: Decimal
    igv: Decimal
    total: Decimal
    a_cuotas: Decimal
    a_reembolsar: Decimal
    reducciones: list[tuple[CuotaVenta, Decimal]] = field(default_factory=list)


def devuelto_antes(linea_ids: list[int]) -> dict[int, dict]:
    """Lo ya devuelto de cada línea por notas de crédito anteriores."""
    filas = LineaNotaCredito.objects.sin_ambito().filter(linea_venta_id__in=linea_ids)
    previo: dict[int, dict] = defaultdict(
        lambda: {"cantidad": CERO, "valor": CERO, "igv": CERO, "series": set()}
    )
    for f in filas:
        p = previo[f.linea_venta_id]
        p["cantidad"] += f.cantidad
        p["valor"] += f.valor_venta
        p["igv"] += f.igv
        p["series"].update(f.series)
    return previo


def con_algo_por_devolver(comprobantes: QuerySet) -> QuerySet:
    """Los comprobantes a los que todavía les queda alguna línea por devolver (en la base)."""
    cantidad = DecimalField(max_digits=14, decimal_places=3)
    devuelto = (
        LineaNotaCredito.objects.sin_ambito()
        .filter(linea_venta=OuterRef("pk"))
        .values("linea_venta")
        .annotate(total=Sum("cantidad"))
        .values("total")
    )
    por_devolver = (
        LineaVenta.objects.sin_ambito()
        .filter(comprobante=OuterRef("pk"))
        .annotate(
            ya_devuelto=Coalesce(
                Subquery(devuelto, output_field=cantidad), Value(CERO, output_field=cantidad)
            )
        )
        .filter(cantidad__gt=F("ya_devuelto"))
    )
    return comprobantes.filter(Exists(por_devolver))


def pendiente_de_devolver(comprobante: ComprobanteVenta) -> list[dict]:
    """Cada línea del comprobante con lo que todavía se puede devolver."""
    lineas = list(
        LineaVenta.objects.filter(comprobante=comprobante)
        .select_related("afectacion", "producto__unidad", "almacen")
        .order_by("orden")
    )
    previo = devuelto_antes([ln.pk for ln in lineas])
    return [
        {
            "linea": ln,
            "devuelto": previo[ln.pk]["cantidad"],
            "disponible": ln.cantidad - previo[ln.pk]["cantidad"],
            "series": [s for s in ln.series if s not in previo[ln.pk]["series"]],
        }
        for ln in lineas
    ]


def _proporcional(total: Decimal, cantidad: Decimal, de: Decimal) -> Decimal:
    return a_dos(total * cantidad / de)


def calcular_nota(
    comprobante: ComprobanteVenta, devueltas: list[LineaDevuelta], *, bloquear: bool = False
) -> CalculoNota:
    """Valida lo que se devuelve y calcula la nota: importes, a cuotas y a reembolsar."""
    if comprobante.estado != ComprobanteVenta.Estado.EMITIDO:
        raise VentaInvalida("El comprobante está anulado: no admite notas de crédito.")
    if not devueltas:
        raise VentaInvalida("Elija qué se devuelve.")
    por_id = {p["linea"].pk: p for p in pendiente_de_devolver(comprobante)}
    previo = devuelto_antes(list(por_id))
    vistas: set[int] = set()
    resultado: list[_Devuelta] = []
    for d in devueltas:
        pendiente = por_id.get(d.linea.pk)
        if pendiente is None:
            raise VentaInvalida("Una línea no pertenece al comprobante.")
        if d.linea.pk in vistas:
            raise VentaInvalida("Una línea se repite: indique la cantidad total en una sola.")
        vistas.add(d.linea.pk)
        linea, cantidad = d.linea, d.cantidad
        nombre = linea.descripcion
        if not isinstance(cantidad, Decimal) or cantidad <= 0:
            raise VentaInvalida(f"{nombre}: la cantidad a devolver debe ser mayor que cero.")
        if cantidad != cantidad.quantize(Decimal("0.001")):
            raise VentaInvalida(f"{nombre}: la cantidad admite hasta 3 decimales.")
        if cantidad > pendiente["disponible"]:
            raise VentaInvalida(
                f"{nombre}: solo se pueden devolver {pendiente['disponible']:g} "
                f"(ya se devolvieron {pendiente['devuelto']:g})."
            )
        series = tuple(" ".join(str(s).split()).upper() for s in d.series)
        if linea.series:
            if len(series) != int(cantidad) or cantidad != int(cantidad):
                raise VentaInvalida(f"{nombre}: indique {int(cantidad)} serie(s) devuelta(s).")
            if len(set(series)) != len(series) or not set(series) <= set(pendiente["series"]):
                raise VentaInvalida(
                    f"{nombre}: hay series que no se vendieron o ya se devolvieron."
                )
        elif series:
            raise VentaInvalida(f"{nombre} no lleva series.")
        antes = previo[linea.pk]
        if cantidad == pendiente["disponible"]:
            # Lo último que queda de la línea: se devuelve exactamente lo que faltaba.
            valor = linea.valor_venta - antes["valor"]
            igv = linea.igv - antes["igv"]
        else:
            valor = min(
                _proporcional(linea.valor_venta, cantidad, linea.cantidad),
                linea.valor_venta - antes["valor"],
            )
            igv = min(_proporcional(linea.igv, cantidad, linea.cantidad), linea.igv - antes["igv"])
        resultado.append(
            _Devuelta(
                linea=linea,
                cantidad=cantidad,
                valor=valor,
                igv=igv,
                total=valor + igv,
                costo_total=a_dos(linea.costo_unitario * cantidad),
                series=series,
            )
        )

    def base_de(grupo: str) -> Decimal:
        return sum((r.valor for r in resultado if r.linea.afectacion.grupo == grupo), CERO)

    total = sum((r.total for r in resultado), CERO)
    a_cuotas, reducciones = CERO, []
    if comprobante.venta.forma_pago == FormaPago.CREDITO:
        consulta = CuotaVenta.objects.filter(comprobante=comprobante).order_by("-numero")
        cuotas = list(consulta.select_for_update() if bloquear else consulta)
        restante = total
        for cuota in cuotas:
            pendiente = cuota.monto - cuota.pagado
            if pendiente <= 0 or restante <= 0:
                continue
            parte = min(pendiente, restante)
            reducciones.append((cuota, parte))
            restante -= parte
        a_cuotas = total - restante
    return CalculoNota(
        comprobante=comprobante,
        lineas=resultado,
        op_gravada=base_de("GRAVADO"),
        op_exonerada=base_de("EXONERADO"),
        op_inafecta=base_de("INAFECTO"),
        igv=sum((r.igv for r in resultado), CERO),
        total=total,
        a_cuotas=a_cuotas,
        a_reembolsar=total - a_cuotas,
        reducciones=reducciones,
    )


def devueltas_de_motivo(comprobante: ComprobanteVenta, motivo: str) -> list[LineaDevuelta]:
    """Lo que devuelve un motivo total (01 o 06): todo lo que queda del comprobante."""
    filas = pendiente_de_devolver(comprobante)
    pendientes = [
        LineaDevuelta(p["linea"], p["disponible"], tuple(p["series"]))
        for p in filas
        if p["disponible"] > 0
    ]
    if not pendientes:
        raise VentaInvalida("El comprobante ya se devolvió por completo.")
    if motivo == MotivoNota.ANULACION and any(p["devuelto"] > 0 for p in filas):
        raise VentaInvalida(
            "El comprobante ya tiene devoluciones: la anulación de la operación solo sirve para "
            "anularlo completo. Use «Devolución total» para devolver lo que falta."
        )
    return pendientes


def _tipo_nota(comprobante: ComprobanteVenta) -> TipoComprobante:
    tipo = (
        TipoComprobante.objects.sin_ambito()
        .filter(organizacion_id=comprobante.empresa.organizacion_id, codigo="07")
        .first()
    )
    if tipo is None or tipo.estado != EstadoRegistro.ACTIVO or not tipo.aplica_ventas:
        raise VentaInvalida("La nota de crédito no está disponible en esta organización.")
    return tipo


# La letra con que empieza la serie de la nota según el comprobante que se devuelve (SUNAT).
LETRA_DE_SERIE = {"01": "F", "03": "B"}
LETRAS_FISCALES = ("F", "B", "E")
REQUISITO_DE_SERIE = {
    "01": "una que empiece con F, por ejemplo FC01",
    "03": "una que empiece con B, por ejemplo BC01",
}
REQUISITO_INTERNO = "una interna, que no empiece con F, B ni E, por ejemplo 0001"


def _serie_encaja(serie: str, tipo_comprobante: str) -> bool:
    """Factura: serie F; boleta: serie B; documento interno: una que no sea fiscal."""
    serie = serie.upper()
    letra = LETRA_DE_SERIE.get(tipo_comprobante)
    if letra is not None:
        return serie.startswith(letra)
    return not serie.startswith(LETRAS_FISCALES)


def series_de_nota(comprobante: ComprobanteVenta) -> list[SerieComprobante]:
    """Las series activas con que la empresa puede emitir una nota sobre este comprobante."""
    tipo = _tipo_nota(comprobante)
    codigo = comprobante.tipo_comprobante.codigo
    return [
        s
        for s in SerieComprobante.objects.sin_ambito()
        .filter(empresa=comprobante.empresa, tipo_comprobante=tipo, estado=EstadoRegistro.ACTIVO)
        .order_by("serie")
        if _serie_encaja(s.serie, codigo)
    ]


def serie_sugerida(
    comprobante: ComprobanteVenta, series: list[SerieComprobante]
) -> SerieComprobante | None:
    """La serie que corresponde sola: la de la tienda de la venta o la general, si es una."""
    return servicios_serie_sugerida(comprobante.empresa, comprobante.venta.sucursal, series)


def elegir_serie_de_nota(
    comprobante: ComprobanteVenta, elegida: int | None = None
) -> SerieComprobante:
    """La serie de la nota: la elegida (si sirve para este comprobante) o la que corresponde."""
    series = series_de_nota(comprobante)
    empresa = comprobante.empresa
    nombre = empresa.nombre_comercial or empresa.razon_social
    if not series:
        codigo = comprobante.tipo_comprobante.codigo
        requisito = REQUISITO_DE_SERIE.get(codigo, REQUISITO_INTERNO)
        raise VentaInvalida(
            f"{nombre} no tiene una serie activa de nota de crédito para "
            f"{comprobante.tipo_comprobante.nombre.lower()}: cree {requisito} en "
            "Mantenimiento → Series de comprobantes."
        )
    if elegida is not None:
        serie = next((s for s in series if s.pk == elegida), None)
        if serie is None:
            raise VentaInvalida(
                f"La serie elegida no sirve para una nota sobre {comprobante.numero_completo}."
            )
        return serie
    sugerida = serie_sugerida(comprobante, series)
    if sugerida is None:
        raise VentaInvalida(
            f"{nombre} tiene varias series de nota de crédito para este comprobante: elija una."
        )
    return sugerida


def series_para_elegir(comprobante: ComprobanteVenta) -> dict:
    """Las series posibles de la nota con su próximo número, y cuál corresponde sola."""
    series = series_de_nota(comprobante)
    sugerida = serie_sugerida(comprobante, series)
    return {
        "series": [
            {
                "id": s.pk,
                "serie": s.serie,
                "nombre": s.nombre,
                "sucursal": s.sucursal_id,
                "proximo": formatear(s.serie, s.proximo_numero),
            }
            for s in series
        ],
        "serie_sugerida": sugerida.pk if sugerida else None,
    }


def reembolsable_por_metodo(comprobante: ComprobanteVenta) -> list[dict]:
    """Lo que el cliente pagó de este comprobante por cada método y lo que aún se le puede devolver.

    Suma el cobro al vender y los abonos de las cuotas (los anulados no cuentan) y resta lo ya
    reembolsado por notas anteriores. Los métodos van en el orden en que se usaron.
    """
    medios: dict[int, dict] = {}
    pagos = [
        *CobroVenta.objects.sin_ambito()
        .filter(comprobante=comprobante)
        .select_related("medio_pago")
        .order_by("id"),
        *AbonoVenta.objects.sin_ambito()
        .filter(comprobante=comprobante, anulado=False)
        .select_related("medio_pago")
        .order_by("id"),
    ]
    for p in pagos:
        fila = medios.setdefault(
            p.medio_pago_id,
            {
                "medio_pago": p.medio_pago_id,
                "nombre": p.medio_pago.nombre,
                "tipo": p.medio_pago.tipo,
                "requiere_referencia": p.medio_pago.requiere_referencia,
                "pagado": CERO,
                "devuelto": CERO,
            },
        )
        fila["pagado"] += p.monto
    for r in ReembolsoNota.objects.sin_ambito().filter(nota__comprobante=comprobante):
        if r.medio_pago_id in medios:
            medios[r.medio_pago_id]["devuelto"] += r.monto
    for fila in medios.values():
        fila["disponible"] = max(fila["pagado"] - fila["devuelto"], CERO)
    return list(medios.values())


def sugerir_reembolso(comprobante: ComprobanteVenta, monto: Decimal) -> tuple[list[dict], Decimal]:
    """Cómo devolver ``monto`` en dinero: por los mismos métodos con que el cliente pagó.

    Devuelve ``([{medio_pago, nombre, tipo, requiere_referencia, monto}], sin_asignar)``; lo que
    no cabe en lo pagado (``sin_asignar``) lo elige la persona.
    """
    restante, filas = monto, []
    for m in reembolsable_por_metodo(comprobante):
        parte = min(m["disponible"], restante)
        if parte <= 0:
            continue
        filas.append(
            {
                "medio_pago": m["medio_pago"],
                "nombre": m["nombre"],
                "tipo": m["tipo"],
                "requiere_referencia": m["requiere_referencia"],
                "monto": parte,
            }
        )
        restante -= parte
    return filas, restante


@transaction.atomic
def crear_nota_credito(
    comprobante: ComprobanteVenta,
    *,
    motivo: str,
    devueltas: list[LineaDevuelta] | None = None,
    reembolsos: list[CobroEntrada] | None = None,
    reingresa_stock: bool = True,
    descripcion: str = "",
    serie_id: int | None = None,
    usuario_id=None,
    usuario_nombre: str = "",
) -> NotaCredito:
    """Emite la nota de crédito: vuelve el stock, se corrigen las cuotas y se reembolsa el resto.

    ``devueltas`` se omite en los motivos totales (01 y 06: se devuelve todo lo pendiente).
    ``serie_id`` elige la serie cuando la empresa tiene varias que sirven para el comprobante.
    """
    periodos.exigir_empresa(comprobante.empresa)
    if motivo not in MotivoNota.values:
        raise VentaInvalida("El motivo de la nota de crédito no es válido.")
    # Si lo que se devuelve vino de otra empresa (venta interna) volverá a ella: acceso a las dos
    # empresas y bloqueo en el orden de siempre, antes de tocar nada.
    if reingresa_stock:
        ventas_internas.bloquear_para_devolver(
            comprobante,
            None if motivo in MOTIVOS_TOTALES else [d.linea.pk for d in devueltas or []],
        )
    # Se bloquea el comprobante: dos notas a la vez no devuelven dos veces lo mismo.
    comprobante = (
        ComprobanteVenta.objects.select_for_update()
        .select_related("venta", "empresa", "tipo_comprobante")
        .get(pk=comprobante.pk)
    )
    if motivo in MOTIVOS_TOTALES:
        devueltas = devueltas_de_motivo(comprobante, motivo)
    elif not devueltas:
        raise VentaInvalida("Elija qué se devuelve.")
    calculo = calcular_nota(comprobante, devueltas, bloquear=True)
    venta, empresa = comprobante.venta, comprobante.empresa
    # Primero la serie: si falta o hay que elegir, ese es el aviso, antes que el del reembolso.
    tipo = _tipo_nota(comprobante)
    serie_obj = elegir_serie_de_nota(comprobante, serie_id)

    validos = _cobros_validos(reembolsos or [])
    a_reembolsar = sum((v.monto for v in validos), CERO)
    if a_reembolsar != calculo.a_reembolsar:
        raise VentaInvalida(
            f"Los reembolsos ({a_reembolsar:,.2f}) deben sumar lo que se devuelve en dinero "
            f"({calculo.a_reembolsar:,.2f})."
        )
    cuentas = [
        resolver_cuenta(empresa, v.medio_pago, venta.sucursal, venta.moneda) for v in validos
    ]
    if any(v.recibido is not None for v in validos):
        raise VentaInvalida("Un reembolso lleva el método, el monto y la operación.")

    serie, numero = siguiente_numero(empresa, serie_obj.pk)
    fecha = timezone.localdate()
    nota = NotaCredito.objects.create(
        empresa=empresa,
        venta=venta,
        comprobante=comprobante,
        tipo_comprobante=tipo,
        serie_comprobante=serie_obj,
        serie=serie,
        numero=numero,
        fecha=fecha,
        motivo=motivo,
        descripcion=_texto(descripcion, 250),
        reingresa_stock=reingresa_stock,
        emitida_por_id=usuario_id,
        emitida_por_nombre=_texto(usuario_nombre, 150),
        op_gravada=calculo.op_gravada,
        op_exonerada=calculo.op_exonerada,
        op_inafecta=calculo.op_inafecta,
        igv=calculo.igv,
        total=calculo.total,
        a_cuotas=calculo.a_cuotas,
        reembolsado=calculo.a_reembolsar,
    )
    lineas_nota = [
        LineaNotaCredito.objects.create(
            empresa=empresa,
            nota=nota,
            linea_venta=d.linea,
            orden=orden,
            cantidad=d.cantidad,
            valor_venta=d.valor,
            igv=d.igv,
            total=d.total,
            costo_total=d.costo_total,
            series=list(d.series),
        )
        for orden, d in enumerate(calculo.lineas)
    ]
    if reingresa_stock:
        _reingresar_al_almacen(nota, comprobante, calculo, lineas_nota, fecha)
        # Lo devuelto que vino de la otra empresa vuelve a ella, al costo con que salió.
        ventas_internas.devolver_a_quien_entrego(nota, calculo, lineas_nota, fecha)
    for cuota, parte in calculo.reducciones:
        cuota.monto -= parte
        cuota.save(update_fields=["monto"])
        ReduccionCuota.objects.create(empresa=empresa, nota=nota, cuota=cuota, monto=parte)
    for v, cuenta in zip(validos, cuentas, strict=True):
        reembolso = ReembolsoNota.objects.create(
            empresa=empresa,
            nota=nota,
            medio_pago=v.medio_pago,
            cuenta=cuenta,
            monto=v.monto,
            referencia=v.referencia,
        )
        caja.registrar_reembolso_de_venta(
            empresa=empresa,
            cuenta=cuenta,
            monto=v.monto,
            fecha=fecha,
            referencia=v.referencia or nota.numero_completo,
            glosa=f"Devolución {nota.numero_completo} · {comprobante.numero_completo}",
            reembolso_id=reembolso.pk,
            medio_pago=v.medio_pago,
        )
    registrar(
        "ventas.nota_credito_emitida",
        recurso_tipo="nota_credito",
        recurso_id=nota.pk,
        empresa_id=empresa.pk,
        resumen=f"Nota de crédito {nota.numero_completo} de {comprobante.numero_completo}",
        detalle={
            "motivo": motivo,
            "a_cuotas": calculo.a_cuotas,
            "reembolsado": calculo.a_reembolsar,
            "reingresa_stock": reingresa_stock,
        },
    )
    return nota


def _reingresar_al_almacen(
    nota: NotaCredito,
    comprobante: ComprobanteVenta,
    calculo: CalculoNota,
    lineas_nota: list[LineaNotaCredito],
    fecha: date,
) -> None:
    """Una entrada por almacén, al costo con que salió cada línea."""
    por_almacen: dict[int, list[tuple[_Devuelta, LineaNotaCredito]]] = defaultdict(list)
    for d, ln in zip(calculo.lineas, lineas_nota, strict=True):
        if d.linea.movimiento_id is not None and d.linea.almacen_id is not None:
            por_almacen[d.linea.almacen_id].append((d, ln))
    for almacen_id in sorted(por_almacen):
        grupo = por_almacen[almacen_id]
        costo = sum((d.costo_total for d, _ in grupo), CERO)
        movimiento = registrar_entrada(
            empresa=nota.empresa,
            almacen=grupo[0][0].linea.almacen,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.DEVOLUCION_CLIENTE,
            fecha=fecha,
            lineas=[
                LineaNueva(
                    d.linea.producto, d.cantidad, d.linea.costo_unitario, series=tuple(d.series)
                )
                for d, _ in grupo
            ],
            cliente=comprobante.venta.cliente,
            comprobante_tipo=nota.tipo_comprobante.codigo,
            comprobante_serie=nota.serie,
            comprobante_numero=str(nota.numero),
            comprobante_fecha=fecha,
            moneda=MONEDA_SOLES,
            referencia_tipo="nota_credito",
            referencia_id=nota.pk,
            igv_porcentaje=CERO,
            totales=(costo, CERO, costo),
        )
        for _, ln in grupo:
            ln.movimiento = movimiento
            ln.save(update_fields=["movimiento"])
