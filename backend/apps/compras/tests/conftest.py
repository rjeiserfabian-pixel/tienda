"""Escenario de compras: el de inventario más catálogos fiscales y de pago, cajas y un proveedor."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.compras.servicios import LineaEntrada, PagoEntrada, registrar_compra
from apps.inventario.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    api,
    entorno,
    mundo,
    nuevo_usuario,
    rbac,
)
from apps.mantenimiento.models import (
    AfectacionIGV,
    CuentaFinanciera,
    MedioPago,
    Periodicidad,
    TipoComprobante,
)
from apps.mantenimiento.pagos import sembrar_catalogos_pago
from apps.organizacion.models import ConfiguracionEmpresa


def dec(valor) -> Decimal:
    return Decimal(str(valor))


@pytest.fixture
def compras(entorno):  # noqa: F811
    """Todo lo necesario para registrar una compra de la empresa A1 en su almacén."""
    org = entorno.e.org_a
    sembrar_catalogos_pago(org.pk)

    def cuenta(nombre, moneda="PEN", empresa=None):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=empresa or entorno.e1, nombre=nombre, tipo="CAJA", moneda=moneda
        )

    def afectacion(codigo):
        return AfectacionIGV.objects.sin_ambito().get(organizacion=org, codigo=codigo)

    def configurar(*, regimen="NORMAL", al_costo=False):
        fila, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=entorno.e1)
        fila.regimen_igv, fila.igv_compras_al_costo = regimen, al_costo
        fila.save()

    ns = SimpleNamespace(
        entorno=entorno,
        empresa=entorno.e1,
        almacen=entorno.alm1,
        proveedor=entorno.proveedor,
        factura=TipoComprobante.objects.sin_ambito().get(organizacion=org, codigo="01"),
        efectivo=MedioPago.objects.sin_ambito().get(organizacion=org, nombre="Efectivo"),
        transferencia=MedioPago.objects.sin_ambito().get(
            organizacion=org, nombre="Transferencia o depósito"
        ),
        mensual=Periodicidad.objects.sin_ambito().get(organizacion=org, nombre="Mensual"),
        caja=cuenta("Caja soles"),
        caja_usd=cuenta("Caja dólares", "USD"),
        afectacion=afectacion,
        configurar=configurar,
    )

    contador = iter(range(1, 10_000))

    def comprar(lineas=None, **extra):
        """Compra al contado de 10 unidades a 10,00 (sin IGV): total 118,00 si no se indica más."""
        datos = {
            "empresa": ns.empresa,
            "proveedor": ns.proveedor,
            "almacen": ns.almacen,
            "tipo_comprobante": ns.factura,
            "comprobante_serie": "F001",
            "comprobante_numero": str(next(contador)),
            "fecha_emision": entorno.hoy,
            "forma_pago": "CONTADO",
        }
        datos.update(extra)
        if lineas is None:
            lineas = [LineaEntrada(entorno.producto(), dec(10), dec("10"))]
        datos["lineas"] = lineas
        if datos["forma_pago"] == "CONTADO" and "pagos" not in datos:
            from apps.compras.servicios import preparar_compra

            total = preparar_compra(**datos, completa=False).resultado.total
            datos["pagos"] = [PagoEntrada(ns.efectivo, ns.caja, total)]
        return registrar_compra(**datos)

    ns.comprar = comprar
    return ns
