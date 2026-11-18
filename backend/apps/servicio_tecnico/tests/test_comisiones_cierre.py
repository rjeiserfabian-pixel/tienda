"""La comisión de los técnicos en el cierre mensual, y que su venta no le pague al vendedor."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.comisiones import avance, cierre, periodos, servicios
from apps.comisiones.models import ComisionComprobante
from apps.seguridad.models import Usuario
from apps.servicio_tecnico.tests.test_garantia import _entregar, _terminada
from apps.servicio_tecnico.tests.test_reportes import _tecnico

pytestmark = pytest.mark.django_db


def _cerrar_este_mes(banco):
    hoy = banco.tienda.entorno.hoy
    fin = periodos.fin_de_periodo(avance.periodo_de(hoy.year, hoy.month))
    return cierre.cerrar_mes(
        banco.empresa.organizacion_id, hoy.year, hoy.month, hoy=fin + timedelta(days=2)
    )


def test_el_tecnico_cobra_su_comision_y_la_venta_no_le_paga_al_vendedor(banco):
    org = banco.empresa.organizacion_id
    servicios.crear(org, {"alcance": "GENERAL", "porcentaje": "5"})  # el vendedor ganaría 5 %
    tecnico = _tecnico(banco, comision="10")
    orden = _terminada(banco, (banco.servicio, 1), (banco.ram, 2), tecnico=tecnico)
    vendedor = Usuario.objects.get(username="vendedor")
    _entregar(banco, orden, "295.00", vendedor_id=vendedor.pk)

    # La venta de servicio NO genera comisión de vendedor (el técnico ya tiene la suya).
    assert not ComisionComprobante.objects.sin_ambito().exists()

    liquidacion = _cerrar_este_mes(banco)
    linea = liquidacion.lineas.get()
    assert linea.clave == f"P:{tecnico.pk}" and linea.personal_id == tecnico.pk
    # 10 % de la mano de obra (50 sin IGV); los repuestos no comisionan.
    assert (linea.comisiones_tecnico, linea.comisiones_ventas, linea.a_pagar) == (
        Decimal("5.00"),
        Decimal("0"),
        Decimal("5.00"),
    )
    (detalle,) = linea.detalle["ordenes"]
    assert detalle["orden"] == orden.codigo and detalle["monto"] == "5.00"
    assert detalle["porcentaje"] == "10.00" and detalle["mano_obra"] == "50.00"
