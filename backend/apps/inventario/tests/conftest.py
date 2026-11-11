"""Escenario de inventario: empresas con almacén y productos, y contexto de tenant activo."""

import itertools
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.core.tenant import establecer_contexto
from apps.inventario.models import OrigenMovimiento, SaldoStock, TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import (
    Almacen,
    Categoria,
    Cliente,
    Familia,
    Producto,
    Proveedor,
    TipoProducto,
    UnidadMedida,
)
from apps.organizacion.models import Sucursal
from apps.seguridad.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    api,
    nuevo_usuario,
    rbac,
)
from conftest import ruc_valido


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


def _catalogo(org):
    familia = Familia.objects.sin_ambito().create(organizacion=org, nombre="Materiales")
    categoria = Categoria.objects.sin_ambito().create(
        organizacion=org, familia=familia, nombre="Cemento"
    )
    unidad = UnidadMedida.objects.sin_ambito().create(
        organizacion=org, nombre="Bolsa", abreviatura="BLS", codigo_sunat="BG"
    )
    return categoria, unidad


@pytest.fixture
def entorno(escenario):
    """Contexto activo de la organización A (empresas A1 y A2) con sus almacenes y catálogo."""
    e = escenario
    contador = itertools.count(1)
    catalogos = {e.org_a.pk: _catalogo(e.org_a), e.org_b.pk: _catalogo(e.org_b)}
    suc1 = Sucursal.objects.sin_ambito().create(empresa=e.emp_a1, nombre="Principal", codigo="001")
    suc2 = Sucursal.objects.sin_ambito().create(empresa=e.emp_a2, nombre="Principal", codigo="001")
    alm1 = Almacen.objects.sin_ambito().create(
        empresa=e.emp_a1, sucursal=suc1, codigo="ALM1", nombre="Almacén A1"
    )
    alm2 = Almacen.objects.sin_ambito().create(
        empresa=e.emp_a2, sucursal=suc2, codigo="ALM1", nombre="Almacén A2"
    )

    def producto(nombre="Cemento Pacasmayo MS", org=None, **extra):
        org = org or e.org_a
        categoria, unidad = catalogos[org.pk]
        return Producto.objects.sin_ambito().create(
            organizacion=org,
            codigo=f"{next(contador):06d}",
            nombre=nombre,
            categoria=categoria,
            unidad=unidad,
            **extra,
        )

    def tercero(modelo, ruc_base, nombre):
        return modelo.objects.sin_ambito().create(
            organizacion=e.org_a,
            tipo_documento="RUC",
            numero_documento=ruc_valido(ruc_base),
            nombre=nombre,
        )

    ajeno = producto("Producto ajeno", org=e.org_b)  # de otra organización
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    hoy = timezone.localdate()
    return SimpleNamespace(
        e=e,
        e1=e.emp_a1,
        e2=e.emp_a2,
        eb=e.emp_b1,
        alm1=alm1,
        alm2=alm2,
        hoy=hoy,
        producto=producto,
        ajeno=ajeno,
        proveedor=tercero(Proveedor, "2010000011", "DSV Constructores"),
        otro_proveedor=tercero(Proveedor, "2010000012", "Todo a un Sol"),
        cliente=tercero(Cliente, "2010000013", "Mago SAC"),
        servicio=producto("Flete", tipo=TipoProducto.SERVICIO, controla_stock=False),
        hace=lambda dias: hoy - timedelta(days=dias),
    )


def saldo_de(entorno, producto, empresa=None, almacen=None) -> SaldoStock:
    return SaldoStock.objects.get(
        empresa=empresa or entorno.e1, almacen=almacen or entorno.alm1, producto=producto
    )


def comprar(entorno, producto, cantidad, precio, *, dias=0, empresa=None, almacen=None, **extra):
    return registrar_movimiento(
        empresa=empresa or entorno.e1,
        almacen=almacen or entorno.alm1,
        tipo=TipoMovimiento.ENTRADA,
        origen=OrigenMovimiento.COMPRA,
        fecha=entorno.hace(dias),
        lineas=[LineaNueva(producto, Decimal(str(cantidad)), Decimal(str(precio)))],
        **extra,
    )


def vender(
    entorno, producto, cantidad, *, dias=0, precio=None, empresa=None, almacen=None, **extra
):
    return registrar_movimiento(
        empresa=empresa or entorno.e1,
        almacen=almacen or entorno.alm1,
        tipo=TipoMovimiento.SALIDA,
        origen=OrigenMovimiento.VENTA,
        fecha=entorno.hace(dias),
        lineas=[
            LineaNueva(
                producto, Decimal(str(cantidad)), None if precio is None else Decimal(str(precio))
            )
        ],
        **extra,
    )


def fin_de_mes(hoy: date, meses_atras: int) -> date:
    """Último día de un mes anterior (1 = el mes pasado)."""
    dia = hoy.replace(day=1)
    for _ in range(meses_atras):
        dia = dia - timedelta(days=1)
        ultimo = dia
        dia = dia.replace(day=1)
    return ultimo


@pytest.fixture
def mundo(rbac, nuevo_usuario):  # noqa: F811
    e = rbac
    org = e.org_a
    familia = Familia.objects.sin_ambito().create(organizacion=org, nombre="Materiales")
    categoria = Categoria.objects.sin_ambito().create(
        organizacion=org, familia=familia, nombre="Cemento"
    )
    unidad = UnidadMedida.objects.sin_ambito().create(
        organizacion=org, nombre="Bolsa", abreviatura="BLS", codigo_sunat="BG"
    )
    sucursales = {
        1: Sucursal.objects.sin_ambito().create(empresa=e.emp_a1, nombre="Principal", codigo="001"),
        2: Sucursal.objects.sin_ambito().create(empresa=e.emp_a2, nombre="Principal", codigo="001"),
    }
    almacenes = {
        1: Almacen.objects.sin_ambito().create(
            empresa=e.emp_a1, sucursal=sucursales[1], codigo="ALM1", nombre="Almacén A1"
        ),
        2: Almacen.objects.sin_ambito().create(
            empresa=e.emp_a2, sucursal=sucursales[2], codigo="ALM1", nombre="Almacén A2"
        ),
    }

    def producto(nombre="Cemento Pacasmayo MS", **extra):
        return Producto.objects.sin_ambito().create(
            organizacion=org,
            codigo=f"{Producto.objects.sin_ambito().count() + 1:06d}",
            nombre=nombre,
            categoria=categoria,
            unidad=unidad,
            **extra,
        )

    usuarios = {
        "super": nuevo_usuario(org, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "admin": nuevo_usuario(org, "admin", [e.emp_a1], [("ADMIN", e.emp_a1)]),
        "almacenero": nuevo_usuario(org, "almacenero", [e.emp_a1], [("ALMACENERO", e.emp_a1)]),
        "vendedor": nuevo_usuario(org, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "contador": nuevo_usuario(org, "contador", [e.emp_a1], [("CONTADOR", e.emp_a1)]),
        "vendedor_a2": nuevo_usuario(org, "vendedor_a2", [e.emp_a2], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }
    return type(
        "Mundo",
        (),
        {
            "e": e,
            "e1": e.emp_a1,
            "e2": e.emp_a2,
            "alm": almacenes,
            "producto": staticmethod(producto),
            "usuarios": usuarios,
        },
    )
