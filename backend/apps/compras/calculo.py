"""Totales de una compra: cálculo puro, sin base de datos.

Una sola regla de redondeo para todo el comprobante:

* Cada línea se redondea a céntimos: ``importe = cantidad × precio``.
* El IGV (o IVAP) se calcula sobre la SUMA de cada grupo de líneas con el mismo impuesto y tasa,
  como lo hace el proveedor en su factura. La diferencia de céntimos contra la suma de líneas se
  pone en la línea de mayor importe del grupo, así la suma de las líneas cuadra con el total.
* Si los precios incluyen IGV, la base es ``total ÷ (1 + tasa)`` y el impuesto es la diferencia.
* El costo de inventario es la base de cada línea (más el impuesto si la empresa lo lleva al
  costo), convertido a soles y redondeado a céntimos. El flete, si va al costo, se reparte en
  proporción a ese valor sin perder ni inventar céntimos.
* El ajuste de redondeo que traiga el comprobante (hasta ±0,10) forma parte del total a pagar,
  pero nunca del costo.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from apps.inventario.costeo import a_dos

from .exceptions import CompraInvalida

CERO = Decimal("0")
UNO = Decimal("1")
CIEN = Decimal("100")
CENTIMO = Decimal("0.01")
TOPE_AJUSTE = Decimal("0.10")

# Qué se imprime en cada total del comprobante.
GRAVADO = "GRAVADO"
EXONERADO = "EXONERADO"
INAFECTO = "INAFECTO"
IGV = "IGV"
IVAP = "IVAP"
NINGUNO = "NINGUNO"


@dataclass(frozen=True, slots=True)
class EntradaLinea:
    """Lo que dice el comprobante de una línea y su afectación (ya resuelta por quien llama)."""

    cantidad: Decimal  # en la unidad comprada
    precio_unitario: Decimal
    grupo: str  # GRAVADO | EXONERADO | INAFECTO
    impuesto: str  # IGV | IVAP | NINGUNO
    tasa: Decimal  # porcentaje; 0 si no paga impuesto


@dataclass(frozen=True, slots=True)
class ResultadoLinea:
    valor_venta: Decimal  # base de la línea
    impuesto: Decimal
    total: Decimal
    costo_soles: Decimal  # lo que entra al inventario, ya con el flete repartido
    flete_asignado: Decimal


@dataclass(frozen=True, slots=True)
class ResultadoCompra:
    lineas: tuple[ResultadoLinea, ...]
    op_gravada: Decimal
    igv: Decimal
    op_ivap: Decimal
    ivap: Decimal
    op_exonerada: Decimal
    op_inafecta: Decimal
    ajuste_redondeo: Decimal
    total: Decimal


def _paga_impuesto(linea: EntradaLinea) -> bool:
    return linea.impuesto != NINGUNO and linea.tasa > 0


def _validar(lineas: Sequence[EntradaLinea]) -> None:
    if not lineas:
        raise CompraInvalida("Agregue al menos un producto.")
    for ln in lineas:
        if ln.cantidad <= 0:
            raise CompraInvalida("La cantidad debe ser mayor que cero.")
        if ln.precio_unitario < 0:
            raise CompraInvalida("El precio no puede ser negativo.")
        if ln.grupo not in (GRAVADO, EXONERADO, INAFECTO):
            raise CompraInvalida("La afectación de una línea no es válida.")
        if ln.impuesto not in (IGV, IVAP, NINGUNO):
            raise CompraInvalida("El impuesto de una línea no es válido.")
        if (ln.grupo == GRAVADO) != (ln.impuesto != NINGUNO):
            raise CompraInvalida("Una línea gravada lleva IGV o IVAP; las demás, ninguno.")
        if not (CERO <= ln.tasa <= CIEN):
            raise CompraInvalida("La tasa del impuesto debe estar entre 0 y 100.")


def _bases_e_impuestos(
    lineas: Sequence[EntradaLinea], incluye_igv: bool
) -> tuple[list[Decimal], list[Decimal]]:
    """Base e impuesto de cada línea, cuadrados con el cálculo por grupo de impuesto y tasa."""
    importes = [a_dos(ln.cantidad * ln.precio_unitario) for ln in lineas]
    bases = list(importes)
    impuestos = [CERO] * len(lineas)

    grupos: dict[tuple[str, Decimal], list[int]] = {}
    for i, ln in enumerate(lineas):
        if _paga_impuesto(ln):
            grupos.setdefault((ln.impuesto, ln.tasa), []).append(i)

    for (_, tasa), indices in grupos.items():
        factor = tasa / CIEN
        suma = sum((importes[i] for i in indices), CERO)
        if incluye_igv:
            base_grupo = a_dos(suma / (UNO + factor))
            impuesto_grupo = suma - base_grupo
            for i in indices:
                bases[i] = a_dos(importes[i] / (UNO + factor))
                impuestos[i] = importes[i] - bases[i]
        else:
            base_grupo = suma
            impuesto_grupo = a_dos(suma * factor)
            for i in indices:
                impuestos[i] = a_dos(importes[i] * factor)
        # Los céntimos que sobran o faltan van a la línea de mayor importe (la primera si empatan).
        mayor = max(indices, key=lambda i: (importes[i], -i))
        bases[mayor] += base_grupo - sum((bases[i] for i in indices), CERO)
        impuestos[mayor] += impuesto_grupo - sum((impuestos[i] for i in indices), CERO)
    return bases, impuestos


# Lo reutiliza Ventas: la misma regla de redondeo para el IGV de cualquier comprobante.
bases_e_impuestos = _bases_e_impuestos


def repartir_por_peso(monto: Decimal, pesos: Sequence[Decimal]) -> list[Decimal]:
    """Reparte ``monto`` (en céntimos exactos) en proporción a ``pesos``: la suma es exacta.

    Método del mayor resto: cada parte se redondea hacia abajo al céntimo y los céntimos que
    faltan van a las partes con mayor resto (a igualdad, a las primeras).
    """
    total_pesos = sum(pesos, CERO)
    if total_pesos <= 0:
        raise CompraInvalida("No se puede repartir el flete: el valor de las líneas es cero.")
    cuotas = [(monto * p / total_pesos) for p in pesos]
    partes = [c.quantize(CENTIMO, rounding=ROUND_FLOOR) for c in cuotas]
    faltan = int(((monto - sum(partes, CERO)) / CENTIMO).to_integral_value())
    orden = sorted(range(len(pesos)), key=lambda i: (-(cuotas[i] - partes[i]), i))
    for i in orden[:faltan]:
        partes[i] += CENTIMO
    return partes


def calcular_compra(
    lineas: Sequence[EntradaLinea],
    *,
    precios_incluyen_igv: bool,
    igv_al_costo: bool,
    tipo_cambio: Decimal = UNO,
    flete: Decimal = CERO,
    flete_al_costo: bool = True,
    ajuste_redondeo: Decimal = CERO,
) -> ResultadoCompra:
    """Totales del comprobante y costo en soles de cada línea (ver las reglas del módulo)."""
    _validar(lineas)
    if tipo_cambio <= 0:
        raise CompraInvalida("El tipo de cambio debe ser mayor que cero.")
    if flete < 0:
        raise CompraInvalida("El flete no puede ser negativo.")
    if ajuste_redondeo != a_dos(ajuste_redondeo) or abs(ajuste_redondeo) > TOPE_AJUSTE:
        raise CompraInvalida("El ajuste de redondeo es de hasta 0.10, con dos decimales.")

    bases, impuestos = _bases_e_impuestos(lineas, precios_incluyen_igv)

    costos = []
    for base, impuesto in zip(bases, impuestos, strict=True):
        valor = base + impuesto if igv_al_costo else base
        costos.append(a_dos(valor * tipo_cambio))

    fletes = [CERO] * len(lineas)
    if flete > 0 and flete_al_costo:
        fletes = repartir_por_peso(flete, costos)

    resultado = []
    for base, impuesto, costo, parte in zip(bases, impuestos, costos, fletes, strict=True):
        resultado.append(ResultadoLinea(base, impuesto, base + impuesto, costo + parte, parte))

    def suma_base(grupo: str, impuesto: str | None = None) -> Decimal:
        return sum(
            (
                bases[i]
                for i, ln in enumerate(lineas)
                if ln.grupo == grupo and (impuesto is None or ln.impuesto == impuesto)
            ),
            CERO,
        )

    def suma_impuesto(impuesto: str) -> Decimal:
        return sum((impuestos[i] for i, ln in enumerate(lineas) if ln.impuesto == impuesto), CERO)

    # Una línea gravada con tasa 0 no cuenta como gravada con impuesto: su base es del grupo.
    suma_total = sum((r.total for r in resultado), CERO)
    return ResultadoCompra(
        lineas=tuple(resultado),
        op_gravada=suma_base(GRAVADO, IGV),
        igv=suma_impuesto(IGV),
        op_ivap=suma_base(GRAVADO, IVAP),
        ivap=suma_impuesto(IVAP),
        op_exonerada=suma_base(EXONERADO),
        op_inafecta=suma_base(INAFECTO),
        ajuste_redondeo=ajuste_redondeo,
        total=suma_total + ajuste_redondeo,
    )
