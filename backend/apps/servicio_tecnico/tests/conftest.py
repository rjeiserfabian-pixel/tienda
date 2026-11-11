"""Escenario del servicio técnico: dos empresas, catálogos de fábrica y datos de ejemplo."""

from decimal import Decimal

import pytest

from apps.auditoria import servicios as auditoria
from apps.core.tenant import establecer_contexto
from apps.inventario.models import SaldoStock
from apps.mantenimiento.models import Cliente, Personal
from apps.seguridad.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    api,
    nuevo_usuario,
    rbac,
)
from apps.servicio_tecnico import presupuesto, servicios
from apps.servicio_tecnico.catalogos import sembrar_catalogos_servicio
from apps.servicio_tecnico.models import (
    Equipo,
    EstadoOrden,
    OrdenServicio,
    TipoEquipo,
    TipoServicio,
)
from apps.servicio_tecnico.presupuesto import LineaPresupuesto
from apps.ventas.tests.conftest import (  # noqa: F401
    compras,
    conceptos,
    dec,
    entorno,
    mundo,
    tienda,
)


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(auditoria.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def taller(rbac, nuevo_usuario):  # noqa: F811
    """Org A con catálogos, un cliente, un equipo, un técnico (Personal) y usuarios por rol."""
    e = rbac
    org = e.org_a
    sembrar_catalogos_servicio(org.pk)
    sembrar_catalogos_servicio(e.org_b.pk)
    admin = nuevo_usuario(org, "admin", [e.emp_a1, e.emp_a2], [("ADMIN", None)])
    tecnico_usuario = nuevo_usuario(org, "tecnico", [e.emp_a1], [("TECNICO", e.emp_a1)])
    vendedor = nuevo_usuario(org, "vendedor", [e.emp_a1], [("VENDEDOR", None)])
    otra_org = nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)])
    establecer_contexto(org.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)

    cliente = Cliente.objects.sin_ambito().create(
        organizacion=org, tipo_documento="DNI", numero_documento="45871236", nombre="Luis Ramos"
    )
    laptop = TipoEquipo.objects.get(codigo="LAPTOP")
    equipo = Equipo.objects.create(
        organizacion=org,
        cliente=cliente,
        tipo=laptop,
        marca="HP",
        modelo="Pavilion",
        numero_serie="5CD123",
    )
    personal = Personal.objects.create(
        empresa=e.emp_a1,
        tipo_documento="DNI",
        numero_documento="40123456",
        nombres="Mario",
        apellidos="Quispe",
        area="TECNICO",
        usuario=tecnico_usuario,
    )

    def orden(empresa=None, **extra):
        empresa = empresa or e.emp_a1
        datos = {
            "empresa": empresa,
            "numero": servicios.siguiente_numero(empresa),
            "cliente": cliente,
            "equipo": equipo,
            "falla_reportada": "No enciende",
            "tecnico": personal,
        }
        datos.update(extra)
        return OrdenServicio.objects.create(**datos)

    return type(
        "Taller",
        (),
        {
            "e": e,
            "org": org,
            "empresa": e.emp_a1,
            "otra_empresa": e.emp_a2,
            "cliente": cliente,
            "equipo": equipo,
            "personal": personal,
            "orden": staticmethod(orden),
            "tipo_servicio": staticmethod(lambda codigo: TipoServicio.objects.get(codigo=codigo)),
            "usuarios": {
                "admin": admin,
                "tecnico": tecnico_usuario,
                "vendedor": vendedor,
                "otra_org": otra_org,
            },
        },
    )


@pytest.fixture
def banco(tienda, nuevo_usuario):  # noqa: F811
    """El taller sobre el escenario de ventas: stock, precios, series y una orden en diagnóstico."""
    entorno = tienda.entorno  # noqa: F811
    org = entorno.e.org_a
    sembrar_catalogos_servicio(org.pk)
    nuevo_usuario(org, "tecnico", [entorno.e1], [("TECNICO", entorno.e1)])
    cliente = Cliente.objects.sin_ambito().create(
        organizacion=org, tipo_documento="DNI", numero_documento="45871236", nombre="Luis Ramos"
    )
    equipo = Equipo.objects.create(
        organizacion=org,
        cliente=cliente,
        tipo=TipoEquipo.objects.get(codigo="LAPTOP"),
        marca="HP",
        modelo="Pavilion",
    )
    ram = tienda.producto(
        "Memoria RAM 8GB", costo="50", precios={"PUBLICO": "100"}, stock={entorno.e1: 10}
    )
    pantalla = tienda.producto(
        "Pantalla 15.6", costo="200", precios={"PUBLICO": "400"}, stock={entorno.e1: 1}
    )
    servicio = tienda.producto(
        "Instalación de repuestos",
        precios={"PUBLICO": "50"},
        stock={},
        tipo="SERVICIO",
        controla_stock=False,
    )

    def orden(estado=EstadoOrden.EN_DIAGNOSTICO, **extra):
        datos = {
            "empresa": entorno.e1,
            "numero": servicios.siguiente_numero(entorno.e1),
            "cliente": cliente,
            "equipo": equipo,
            "falla_reportada": "No da video",
            "estado": estado,
        }
        datos.update(extra)
        return OrdenServicio.objects.create(**datos)

    def lineas(*cosas):
        return [
            LineaPresupuesto(producto=p, cantidad=Decimal(str(c)), empresa=(e or entorno.e1))
            for p, c, e in [(x + (None,))[:3] for x in cosas]
        ]

    def armar(o, *cosas, **extra):
        datos = {"vendedor_nombre": "Rosa Pérez", "puede_otra_empresa": True}
        datos.update(extra)
        return presupuesto.armar_presupuesto(o, lineas(*cosas), **datos)

    def stock(producto, almacen):
        fila = SaldoStock.objects.sin_ambito().filter(producto=producto, almacen=almacen).first()
        return fila.cantidad if fila else Decimal("0")

    return type(
        "Banco",
        (),
        {
            "tienda": tienda,
            "e": entorno,
            "empresa": entorno.e1,
            "otra": entorno.e2,
            "cliente": cliente,
            "equipo": equipo,
            "ram": ram,
            "pantalla": pantalla,
            "servicio": servicio,
            "orden": staticmethod(orden),
            "armar": staticmethod(armar),
            "stock": staticmethod(stock),
        },
    )
