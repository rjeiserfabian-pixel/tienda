"""Escenario de ventas: dos empresas (A1 la principal, A2) con caja, series, listas y stock."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.caja.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    api,
    compras,
    conceptos,
    dec,
    entorno,
    mundo,
    nuevo_usuario,
    rbac,
)
from apps.core.tenant import establecer_contexto
from apps.inventario.tests.conftest import comprar as ingresar_stock
from apps.mantenimiento.models import (
    Cliente,
    CuentaFinanciera,
    ListaPrecio,
    MedioPago,
    PrecioProducto,
    SerieComprobante,
    TipoComprobante,
)
from apps.mantenimiento.productos import sembrar_listas
from apps.organizacion.models import Empresa
from apps.ventas.models import CuentaDeCobro
from apps.ventas.servicios import CobroEntrada, CuotasEntrada, LineaEntrada, registrar_venta


@pytest.fixture
def tienda(nuevo_usuario, conceptos, compras, entorno):  # noqa: F811
    """A1 (principal) y A2 con su caja, su Yape, sus series de factura, boleta y nota de venta."""
    org = entorno.e.org_a
    for nombre, rol in (
        ("admin", "ADMIN"),
        ("contador", "CONTADOR"),
        ("cajero", "CAJERO"),
        ("vendedor", "VENDEDOR"),
    ):
        nuevo_usuario(org, nombre, [entorno.e1, entorno.e2], [(rol, None)])
    establecer_contexto(org.pk, [entorno.e1.pk, entorno.e2.pk], entorno.e.usuario_id)
    Empresa.objects.sin_ambito().filter(pk=entorno.e1.pk).update(es_principal=True)
    entorno.e1.refresh_from_db()
    sembrar_listas(org.pk)
    listas = {
        lista.uso: lista for lista in ListaPrecio.objects.sin_ambito().filter(organizacion=org)
    }

    def tipo(codigo):
        return TipoComprobante.objects.sin_ambito().get(organizacion=org, codigo=codigo)

    def medio(nombre):
        return MedioPago.objects.sin_ambito().get(organizacion=org, nombre=nombre)

    cajas, billeteras, series = {}, {}, {}
    yape = medio("Yape")
    for empresa, sufijo in ((entorno.e1, "1"), (entorno.e2, "2")):
        cajas[empresa.pk] = (
            compras.caja
            if empresa.pk == entorno.e1.pk
            else CuentaFinanciera.objects.sin_ambito().create(
                empresa=empresa, nombre="Caja soles", tipo="CAJA"
            )
        )
        billeteras[empresa.pk] = CuentaFinanciera.objects.sin_ambito().create(
            empresa=empresa, nombre="Yape", tipo="BILLETERA"
        )
        CuentaDeCobro.objects.create(
            empresa=empresa, medio_pago=yape, cuenta=billeteras[empresa.pk]
        )
        for codigo, prefijo, electronica in (
            ("01", "F", True),
            ("03", "B", True),
            ("NV", "N", False),
            ("07", "FC", True),  # la nota de crédito sobre factura: FC01, FC02
            ("09", "T", True),  # la guía de remisión: T001, T002
            ("RI", "RI", False),  # el recibo de cobranza de las cuotas: RI01, RI02
            ("PF", "P", False),  # la proforma: P001, P002
        ):
            series[(empresa.pk, codigo)] = SerieComprobante.objects.sin_ambito().create(
                empresa=empresa,
                tipo_comprobante=tipo(codigo),
                serie=f"{prefijo}{'0' if len(prefijo) == 2 else '00'}{sufijo}",
                es_electronica=electronica,
            )
        # Las otras series de nota de crédito: BC01 sobre boleta y una interna sobre nota de venta.
        for clave, serie, electronica in (
            ("07B", f"BC0{sufijo}", True),
            ("07N", f"00{sufijo}", False),
        ):
            series[(empresa.pk, clave)] = SerieComprobante.objects.sin_ambito().create(
                empresa=empresa,
                tipo_comprobante=tipo("07"),
                serie=serie,
                es_electronica=electronica,
            )

    def producto(nombre="Audífonos", *, costo="50", precios=None, stock=None, **extra):
        """``precios``: ``{uso: precio}``; ``stock``: ``{empresa: cantidad}`` comprado al costo."""
        p = entorno.producto(nombre, costo=Decimal(costo), **extra)
        for uso, precio in (precios or {"PUBLICO": "100"}).items():
            PrecioProducto.objects.sin_ambito().create(
                organizacion=org, producto=p, lista=listas[uso], precio=Decimal(precio)
            )
        for empresa, cantidad in (stock if stock is not None else {entorno.e1: 10}).items():
            ingresar_stock(
                entorno,
                p,
                cantidad,
                costo,
                empresa=empresa,
                almacen=entorno.alm1 if empresa.pk == entorno.e1.pk else entorno.alm2,
            )
        return p

    def almacen(empresa):
        return entorno.alm1 if empresa.pk == entorno.e1.pk else entorno.alm2

    def vender(lineas, cobros, **extra):
        """Vende al contado: por defecto, nota de venta pagada en efectivo."""
        datos = {
            "empresa": entorno.e1,
            "fecha": entorno.hoy,
            "tipo_comprobante": "NV",
            "vendedor_nombre": "Rosa Pérez",
            "puede_vender_stock_otra_empresa": True,
        }
        datos.update(extra)
        datos["lineas"] = lineas
        datos["cobros_entrada"] = cobros
        return registrar_venta(**datos)

    def cliente(limite="1000", numero="20100000017", tipo="RUC", **extra):
        """El cliente de ese documento (se crea o se actualiza su límite de crédito)."""
        fila, creada = Cliente.objects.sin_ambito().get_or_create(
            organizacion=org,
            tipo_documento=tipo,
            numero_documento=numero,
            defaults={
                "nombre": "Ferretería El Sol",
                "limite_credito": Decimal(limite),
                "credito_sin_limite": False,
                **extra,
            },
        )
        if not creada:
            fila.limite_credito = Decimal(limite)
            fila.credito_sin_limite = bool(extra.get("credito_sin_limite", False))
            fila.save()
        return fila

    def cuotas(cantidad=3, dias=30):
        return CuotasEntrada(cantidad, entorno.hoy + timedelta(days=dias), compras.mensual)

    def credito(lineas, cobros=(), **extra):
        """Vende a crédito con permiso: por defecto 3 cuotas a un cliente con límite de 1 000."""
        if "cliente" not in extra:
            extra["cliente"] = cliente()
        extra.setdefault("cuotas", cuotas())
        extra.setdefault("puede_credito", True)
        return vender(lineas, list(cobros), forma_pago="CREDITO", **extra)

    return SimpleNamespace(
        entorno=entorno,
        cliente=cliente,
        cuotas=cuotas,
        credito=credito,
        compras=compras,
        a=entorno.e1,
        b=entorno.e2,
        listas=listas,
        tipo=tipo,
        medio=medio,
        efectivo=medio("Efectivo"),
        yape=yape,
        tarjeta=medio("Tarjeta"),
        cajas=cajas,
        billeteras=billeteras,
        series=series,
        producto=producto,
        almacen=almacen,
        vender=vender,
        linea=lambda p, cantidad=1, empresa=None, **extra: LineaEntrada(
            p,
            Decimal(str(cantidad)),
            empresa or entorno.e1,
            almacen(empresa or entorno.e1),
            **extra,
        ),
        cobro=lambda medio_pago, monto, **extra: CobroEntrada(
            medio_pago, Decimal(str(monto)), **extra
        ),
    )


@pytest.fixture
def mixto(tienda):
    """Un producto de A (cuesta 50) y otro que solo tiene B (cuesta 30); ambos se venden a 100."""
    de_a = tienda.producto("Audífonos", costo="50", precios={"PUBLICO": "100"})
    de_b = tienda.producto("Cargador", costo="30", precios={"PUBLICO": "100"}, stock={tienda.b: 10})
    return de_a, de_b
