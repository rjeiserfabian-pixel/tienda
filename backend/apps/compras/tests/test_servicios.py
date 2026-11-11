from datetime import timedelta

import pytest
from rest_framework.exceptions import ValidationError as ErrorDeApi

from apps.compras.exceptions import CompraInvalida, CompraNoAnulable
from apps.compras.models import Compra, CuotaCompra, LineaCompra, PagoCompra
from apps.compras.servicios import (
    CuotasEntrada,
    FleteEntrada,
    LineaEntrada,
    PagoEntrada,
    anular_compra,
    preparar_compra,
)
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.inventario.exceptions import AnulacionNoPermitida, ComprobanteDuplicado
from apps.inventario.models import MovimientoInventario, SerieProducto
from apps.inventario.tests.conftest import saldo_de, vender
from apps.mantenimiento.models import Ubicacion

from .conftest import dec

pytestmark = pytest.mark.django_db


def una_linea(compras, cantidad="10", precio="10", **extra):
    producto = extra.pop("producto", None) or compras.entorno.producto()
    return producto, LineaEntrada(producto, dec(cantidad), dec(precio), **extra)


class TestContado:
    def test_registra_compra_y_entrada_de_inventario(self, compras):
        producto, linea = una_linea(compras)
        c = compras.comprar([linea])
        assert (c.numero, c.estado, c.forma_pago) == (1, "EMITIDO", "CONTADO")
        assert (c.op_gravada, c.igv, c.total) == (dec("100"), dec("18"), dec("118"))
        saldo = saldo_de(compras.entorno, producto)
        assert (saldo.cantidad, saldo.costo_total) == (dec("10"), dec("100"))
        m = c.movimiento
        assert (m.tipo, m.origen, m.proveedor_id) == ("ENTRADA", "COMPRA", compras.proveedor.pk)
        assert (m.subtotal, m.igv, m.total) == (dec("100"), dec("18"), dec("118"))
        assert (m.comprobante_serie, m.referencia_tipo) == ("F001", "compra")
        pago = c.pagos.get()
        assert (pago.tipo, pago.monto, pago.anulado) == ("COMPRA", dec("118"), False)
        ln = c.lineas.get()
        assert (ln.valor_venta, ln.impuesto, ln.total, ln.costo_soles) == (
            dec("100"),
            dec("18"),
            dec("118"),
            dec("100"),
        )

    def test_el_correlativo_avanza_por_empresa(self, compras):
        assert [compras.comprar().numero for _ in range(3)] == [1, 2, 3]

    def test_igv_al_costo(self, compras):
        compras.configurar(al_costo=True)
        producto, linea = una_linea(compras)
        c = compras.comprar([linea])
        assert c.igv_al_costo is True
        assert saldo_de(compras.entorno, producto).costo_total == dec("118")
        assert c.total == dec("118")

    def test_precios_con_igv(self, compras):
        producto, linea = una_linea(compras, cantidad="1", precio="118")
        c = compras.comprar([linea], precios_incluyen_igv=True)
        assert (c.op_gravada, c.igv, c.total) == (dec("100"), dec("18"), dec("118"))
        assert saldo_de(compras.entorno, producto).costo_total == dec("100")

    def test_amazonia_proveedor_dentro_es_exonerado(self, compras):
        compras.configurar(regimen="AMAZONIA", al_costo=True)
        compras.proveedor.zona = "DENTRO"
        compras.proveedor.save()
        producto, linea = una_linea(compras)
        c = compras.comprar([linea])
        assert (c.op_exonerada, c.igv, c.total) == (dec("100"), dec("0"), dec("100"))
        assert c.lineas.get().afectacion_codigo == "20"
        assert saldo_de(compras.entorno, producto).costo_total == dec("100")

    def test_amazonia_proveedor_fuera_es_gravado(self, compras):
        compras.configurar(regimen="AMAZONIA", al_costo=True)
        compras.proveedor.zona = "FUERA"
        compras.proveedor.save()
        producto, linea = una_linea(compras)
        c = compras.comprar([linea])
        assert (c.op_gravada, c.igv) == (dec("100"), dec("18"))
        assert saldo_de(compras.entorno, producto).costo_total == dec("118")

    def test_afectacion_elegida_a_mano(self, compras):
        producto, linea = una_linea(compras, afectacion=compras.afectacion("30"))
        c = compras.comprar([linea])
        assert (c.op_inafecta, c.igv, c.total) == (dec("100"), dec("0"), dec("100"))

    def test_afectacion_de_exportacion_no_se_usa_en_compras(self, compras):
        _, linea = una_linea(compras, afectacion=compras.afectacion("40"))
        with pytest.raises(CompraInvalida):
            compras.comprar([linea])

    def test_dolares_con_tipo_de_cambio(self, compras):
        producto, linea = una_linea(compras)
        caja = compras.caja_usd
        c = compras.comprar(
            [linea],
            moneda="USD",
            tipo_cambio=dec("3.7500"),
            pagos=[PagoEntrada(compras.efectivo, caja, dec("118"))],
        )
        assert (c.moneda, c.tipo_cambio, c.total) == ("USD", dec("3.7500"), dec("118"))
        assert saldo_de(compras.entorno, producto).costo_total == dec("375")

    def test_pago_en_otra_moneda_se_rechaza(self, compras):
        _, linea = una_linea(compras)
        with pytest.raises(CompraInvalida, match="moneda"):
            compras.comprar(
                [linea],
                moneda="USD",
                tipo_cambio=dec("3.75"),
                pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"))],
            )

    def test_pagos_deben_sumar_el_total(self, compras):
        _, linea = una_linea(compras)
        for monto in ("117.99", "118.01"):
            with pytest.raises(CompraInvalida, match="sumar"):
                compras.comprar(
                    [linea], pagos=[PagoEntrada(compras.efectivo, compras.caja, dec(monto))]
                )
        assert Compra.objects.count() == 0

    def test_pago_dividido_en_dos_cajas(self, compras):
        _, linea = una_linea(compras)
        c = compras.comprar(
            [linea],
            pagos=[
                PagoEntrada(compras.efectivo, compras.caja, dec("100")),
                PagoEntrada(compras.transferencia, compras.caja, dec("18"), referencia="OP-1"),
            ],
        )
        assert c.pagos.count() == 2

    def test_transferencia_exige_numero_de_operacion(self, compras):
        _, linea = una_linea(compras)
        with pytest.raises(CompraInvalida, match="operación"):
            compras.comprar(
                [linea], pagos=[PagoEntrada(compras.transferencia, compras.caja, dec("118"))]
            )

    def test_contado_sin_pagos_o_con_cuotas_se_rechaza(self, compras):
        _, linea = una_linea(compras)
        with pytest.raises(CompraInvalida):
            compras.comprar([linea], pagos=[])
        cuotas = CuotasEntrada(2, compras.entorno.hoy, compras.mensual)
        with pytest.raises(CompraInvalida, match="contado"):
            compras.comprar(
                [linea],
                cuotas=cuotas,
                pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"))],
            )


class TestFlete:
    def test_flete_al_costo_se_reparte_y_se_paga_aparte(self, compras):
        p1, l1 = una_linea(compras, cantidad="1", precio="100")
        p2, l2 = una_linea(compras, cantidad="1", precio="200")
        flete = FleteEntrada(
            dec("10"),
            True,
            "01",
            "F777",
            "55",
            (PagoEntrada(compras.efectivo, compras.caja, dec("10")),),
        )
        c = compras.comprar([l1, l2], flete=flete)
        assert c.total == dec("354")  # el flete no es parte del comprobante del proveedor
        assert saldo_de(compras.entorno, p1).costo_total == dec("103.33")
        assert saldo_de(compras.entorno, p2).costo_total == dec("206.67")
        assert sum(ln.flete_asignado for ln in c.lineas.all()) == dec("10")
        assert sorted(c.pagos.values_list("tipo", "monto")) == [
            ("COMPRA", dec("354")),
            ("FLETE", dec("10")),
        ]
        assert (c.flete_comprobante_serie, c.flete_comprobante_numero) == ("F777", "55")

    def test_flete_fuera_del_costo(self, compras):
        producto, linea = una_linea(compras)
        flete = FleteEntrada(
            dec("10"), False, pagos=(PagoEntrada(compras.efectivo, compras.caja, dec("10")),)
        )
        c = compras.comprar([linea], flete=flete)
        assert saldo_de(compras.entorno, producto).costo_total == dec("100")
        assert c.flete_al_costo is False

    def test_pagos_del_flete_deben_cuadrar(self, compras):
        _, linea = una_linea(compras)
        flete = FleteEntrada(
            dec("10"), pagos=(PagoEntrada(compras.efectivo, compras.caja, dec("9")),)
        )
        with pytest.raises(CompraInvalida, match="flete"):
            compras.comprar([linea], flete=flete)
        with pytest.raises(CompraInvalida, match="flete"):
            compras.comprar([linea], flete=FleteEntrada(dec("10")))


class TestCredito:
    def datos(self, compras, **extra):
        return {
            "forma_pago": "CREDITO",
            "cuotas": CuotasEntrada(3, compras.entorno.hoy, compras.mensual),
            **extra,
        }

    def test_crea_el_cronograma_en_centavos_exactos(self, compras):
        _, linea = una_linea(compras, cantidad="1", precio="100")  # total 118,00
        c = compras.comprar([linea], **self.datos(compras))
        cuotas = list(c.cuotas.order_by("numero"))
        assert [q.monto for q in cuotas] == [dec("39.34"), dec("39.33"), dec("39.33")]
        assert sum(q.monto for q in cuotas) == c.total
        assert all(q.pagado == 0 for q in cuotas)
        assert c.pagos.count() == 0

    def test_no_lleva_pagos(self, compras):
        _, linea = una_linea(compras)
        with pytest.raises(CompraInvalida, match="crédito"):
            compras.comprar(
                [linea],
                pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"))],
                **self.datos(compras),
            )

    def test_exige_cuotas_y_fecha_valida(self, compras):
        _, linea = una_linea(compras)
        with pytest.raises(CompraInvalida, match="cuotas"):
            compras.comprar([linea], forma_pago="CREDITO")
        antes = CuotasEntrada(2, compras.entorno.hoy - timedelta(days=1), compras.mensual)
        with pytest.raises(CompraInvalida, match="antes"):
            compras.comprar([linea], forma_pago="CREDITO", cuotas=antes)


class TestValidaciones:
    def test_comprobante_duplicado_no_deja_nada(self, compras):
        compras.comprar(comprobante_numero="777")
        compras_antes = Compra.objects.count()
        movimientos_antes = MovimientoInventario.objects.count()
        with pytest.raises(ComprobanteDuplicado):
            compras.comprar(comprobante_numero="777")
        assert Compra.objects.count() == compras_antes
        assert MovimientoInventario.objects.count() == movimientos_antes

    def test_error_al_final_deshace_toda_la_compra(self, compras):
        _, linea = una_linea(compras, ubicacion_id=999_999)
        antes = (Compra.objects.count(), MovimientoInventario.objects.count())
        with pytest.raises(ErrorDeApi):
            compras.comprar([linea])
        assert (Compra.objects.count(), MovimientoInventario.objects.count()) == antes
        assert PagoCompra.objects.count() == 0

    def test_ubicacion_valida(self, compras):
        ubicacion = Ubicacion.objects.sin_ambito().create(
            empresa=compras.empresa, almacen=compras.almacen, codigo="A1", nombre="Pasillo A"
        )
        producto, linea = una_linea(compras, ubicacion_id=ubicacion.pk)
        compras.comprar([linea])
        assert producto.ubicaciones.filter(ubicacion=ubicacion).exists()

    def test_proveedor_de_otra_organizacion(self, compras):
        compras.proveedor.organizacion_id = compras.entorno.e.org_b.pk  # solo en memoria
        with pytest.raises(CompraInvalida, match="organización"):
            compras.comprar()

    def test_proveedor_inactivo(self, compras):
        compras.proveedor.estado = "INACTIVO"
        compras.proveedor.save()
        with pytest.raises(CompraInvalida, match="inactivo"):
            compras.comprar()

    def test_almacen_de_otra_empresa(self, compras):
        with pytest.raises(CompraInvalida, match="almacén"):
            compras.comprar(almacen=compras.entorno.alm2)

    def test_fecha_futura(self, compras):
        with pytest.raises(CompraInvalida, match="futura"):
            compras.comprar(fecha_emision=compras.entorno.hoy + timedelta(days=1))

    def test_serie_con_formato_incorrecto(self, compras):
        with pytest.raises(CompraInvalida, match="formato"):
            compras.comprar(comprobante_serie="X999")

    def test_sin_numero_de_comprobante(self, compras):
        with pytest.raises(CompraInvalida, match="número"):
            compras.comprar(comprobante_numero="")

    def test_sin_lineas(self, compras):
        with pytest.raises(CompraInvalida):
            compras.comprar([])

    def test_servicio_no_es_inventariable(self, compras):
        linea = LineaEntrada(compras.entorno.servicio, dec(1), dec(10))
        with pytest.raises(CompraInvalida, match="stock"):
            compras.comprar([linea])

    def test_producto_de_otra_organizacion(self, compras):
        linea = LineaEntrada(compras.entorno.ajeno, dec(1), dec(10))
        with pytest.raises(CompraInvalida, match="organización"):
            compras.comprar([linea])

    def test_cantidad_y_precio_invalidos(self, compras):
        producto = compras.entorno.producto()
        for cantidad, precio in [("0", "1"), ("-1", "1"), ("1", "-1"), ("1.0001", "1")]:
            with pytest.raises(CompraInvalida):
                compras.comprar([LineaEntrada(producto, dec(cantidad), dec(precio))])

    def test_ajuste_de_redondeo_entra_al_total_no_al_costo(self, compras):
        producto, linea = una_linea(compras, cantidad="1", precio="100")
        c = compras.comprar([linea], ajuste_redondeo=dec("-0.02"))
        assert (c.total, c.ajuste_redondeo) == (dec("117.98"), dec("-0.02"))
        assert saldo_de(compras.entorno, producto).costo_total == dec("100")

    def test_vista_previa_no_escribe(self, compras):
        _, linea = una_linea(compras)
        p = preparar_compra(
            empresa=compras.empresa,
            proveedor=compras.proveedor,
            almacen=compras.almacen,
            tipo_comprobante=compras.factura,
            comprobante_serie="F001",
            comprobante_numero="1",
            fecha_emision=compras.entorno.hoy,
            lineas=[linea],
            forma_pago="CREDITO",
            cuotas=CuotasEntrada(2, compras.entorno.hoy, compras.mensual),
        )
        assert p.resultado.total == dec("118")
        assert [q.monto for q in p.cuotas] == [dec("59"), dec("59")]
        assert (Compra.objects.count(), MovimientoInventario.objects.count()) == (0, 0)


class TestPresentacionYSeries:
    def test_compra_por_caja_ingresa_en_unidades_base(self, compras):
        from apps.mantenimiento.models import PresentacionProducto, UnidadMedida

        producto = compras.entorno.producto()
        caja = UnidadMedida.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a, nombre="Caja", abreviatura="CJ", codigo_sunat="BX"
        )
        presentacion = PresentacionProducto.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a, producto=producto, unidad=caja, factor=dec(12)
        )
        linea = LineaEntrada(producto, dec(2), dec("120"), presentacion=presentacion)
        c = compras.comprar([linea])
        ln = c.lineas.get()
        assert (ln.unidad, ln.factor, ln.cantidad, ln.cantidad_base) == (
            "Caja",
            dec(12),
            dec(2),
            dec(24),
        )
        saldo = saldo_de(compras.entorno, producto)
        assert (saldo.cantidad, saldo.costo_total) == (dec(24), dec(240))
        assert saldo.costo_unitario == dec("10")

    def test_presentacion_de_otro_producto(self, compras):
        from apps.mantenimiento.models import PresentacionProducto, UnidadMedida

        otro = compras.entorno.producto("Otro")
        caja = UnidadMedida.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a, nombre="Caja", abreviatura="CJ", codigo_sunat="BX"
        )
        presentacion = PresentacionProducto.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a, producto=otro, unidad=caja, factor=dec(12)
        )
        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(1), presentacion=presentacion)
        with pytest.raises(CompraInvalida, match="presentación"):
            compras.comprar([linea])

    def test_series_con_sus_otros_datos(self, compras):
        producto = compras.entorno.producto("Celular", lleva_serie=True)
        linea = LineaEntrada(
            producto, dec(2), dec(500), series=("IMEI0001", "IMEI0002"), datos_series=("Negro", "")
        )
        compras.comprar([linea])
        series = list(
            SerieProducto.objects.filter(producto=producto)
            .order_by("numero")
            .values_list("numero", "otros_datos")
        )
        assert series == [("IMEI0001", "Negro"), ("IMEI0002", "")]

    def test_cantidad_de_series_debe_coincidir(self, compras):
        producto = compras.entorno.producto("Celular", lleva_serie=True)
        linea = LineaEntrada(producto, dec(2), dec(500), series=("IMEI0001",))
        with pytest.raises(CompraInvalida, match="serie"):
            compras.comprar([linea])


class TestAnulacion:
    def test_devuelve_el_inventario_y_marca_los_pagos(self, compras):
        producto, linea = una_linea(compras)
        c = compras.comprar([linea])
        anular_compra(c, motivo="Error de digitación")
        c.refresh_from_db()
        assert (c.estado, c.motivo_anulacion) == ("ANULADO", "Error de digitación")
        saldo = saldo_de(compras.entorno, producto)
        assert (saldo.cantidad, saldo.costo_total) == (dec(0), dec(0))
        assert c.pagos.get().anulado is True
        assert MovimientoInventario.objects.get(pk=c.movimiento_id).estado == "ANULADO"

    def test_se_puede_registrar_de_nuevo_el_mismo_comprobante(self, compras):
        c = compras.comprar(comprobante_numero="900")
        anular_compra(c, motivo="Mal ingresada")
        otra = compras.comprar(comprobante_numero="900")
        assert otra.numero == 2

    def test_si_la_mercaderia_ya_salio_no_se_anula(self, compras):
        producto, linea = una_linea(compras)
        c = compras.comprar([linea])
        vender(compras.entorno, producto, 4)
        with pytest.raises(AnulacionNoPermitida):
            anular_compra(c, motivo="Quiero anularla")
        c.refresh_from_db()
        assert c.estado == "EMITIDO"
        assert c.pagos.get().anulado is False
        assert saldo_de(compras.entorno, producto).cantidad == dec(6)

    def test_con_cuota_pagada_no_se_anula(self, compras):
        _, linea = una_linea(compras)
        c = compras.comprar(
            [linea],
            forma_pago="CREDITO",
            cuotas=CuotasEntrada(2, compras.entorno.hoy, compras.mensual),
        )
        CuotaCompra.objects.filter(compra=c, numero=1).update(pagado=dec("10"))
        with pytest.raises(CompraNoAnulable):
            anular_compra(c, motivo="Quiero anularla")
        c.refresh_from_db()
        assert c.estado == "EMITIDO"
        assert MovimientoInventario.objects.get(pk=c.movimiento_id).estado == "EMITIDO"

    def test_a_credito_sin_pagos_se_anula(self, compras):
        _, linea = una_linea(compras)
        c = compras.comprar(
            [linea],
            forma_pago="CREDITO",
            cuotas=CuotasEntrada(2, compras.entorno.hoy, compras.mensual),
        )
        anular_compra(c, motivo="Proveedor la canceló")
        c.refresh_from_db()
        assert c.estado == "ANULADO"

    def test_motivo_obligatorio_y_doble_anulacion(self, compras):
        c = compras.comprar()
        with pytest.raises(MotivoObligatorio):
            anular_compra(c, motivo="   ")
        anular_compra(c, motivo="Primera vez")
        with pytest.raises(DocumentoYaAnulado):
            anular_compra(c, motivo="Segunda vez")

    def test_las_lineas_se_conservan(self, compras):
        c = compras.comprar()
        anular_compra(c, motivo="Error")
        assert LineaCompra.objects.filter(compra=c).count() == 1


class TestVistaPrevia:
    def test_sin_series_todavia_calcula_pero_registrar_las_exige(self, compras):
        producto = compras.entorno.producto("Celular 2", lleva_serie=True)
        linea = LineaEntrada(producto, dec(2), dec(500))
        datos = {
            "empresa": compras.empresa,
            "proveedor": compras.proveedor,
            "almacen": compras.almacen,
            "tipo_comprobante": compras.factura,
            "comprobante_serie": "F001",
            "comprobante_numero": "7",
            "fecha_emision": compras.entorno.hoy,
            "lineas": [linea],
            "forma_pago": "CONTADO",
        }
        assert preparar_compra(**datos, completa=False).resultado.total == dec("1180")
        with pytest.raises(CompraInvalida, match="serie"):
            preparar_compra(**datos)
