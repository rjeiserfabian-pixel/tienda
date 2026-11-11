"""API de compras: permisos, aislamiento, idempotencia, vista previa y anulación."""

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.compras.models import Compra
from apps.core.tenant import establecer_contexto
from apps.inventario.models import MovimientoInventario, SaldoStock
from apps.mantenimiento.models import CuentaFinanciera, MedioPago, Periodicidad, Proveedor
from apps.mantenimiento.pagos import sembrar_catalogos_pago
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/compras"
_claves = itertools.count(1)
_numeros = itertools.count(1)


def clave():
    return f"compra-de-prueba-{next(_claves):06d}"


@pytest.fixture
def datos(mundo):  # noqa: F811
    e = mundo.e
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    sembrar_catalogos_pago(e.org_a.pk)
    proveedor = Proveedor.objects.sin_ambito().create(
        organizacion=e.org_a,
        tipo_documento="RUC",
        numero_documento=ruc_valido("2010000021"),
        nombre="Distribuidora Selva",
    )
    caja = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.emp_a1, nombre="Caja soles", tipo="CAJA", moneda="PEN"
    )
    efectivo = MedioPago.objects.sin_ambito().get(organizacion=e.org_a, nombre="Efectivo")
    mensual = Periodicidad.objects.sin_ambito().get(organizacion=e.org_a, nombre="Mensual")
    return type(
        "Datos",
        (),
        {
            "mundo": mundo,
            "proveedor": proveedor,
            "caja": caja,
            "efectivo": efectivo,
            "mensual": mensual,
        },
    )


def cuerpo(datos, producto=None, **extra):
    producto = producto or datos.mundo.producto()
    base = {
        "empresa": datos.mundo.e1.pk,
        "proveedor": datos.proveedor.pk,
        "almacen": datos.mundo.alm[1].pk,
        "tipo_comprobante": "01",
        "comprobante_serie": "F001",
        "comprobante_numero": str(next(_numeros)),
        "fecha_emision": (timezone.localdate() - timedelta(days=1)).isoformat(),
        "forma_pago": "CONTADO",
        "lineas": [{"producto": producto.pk, "cantidad": "10", "precio_unitario": "10"}],
        "pagos": [{"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "118.00"}],
    }
    return {**base, **extra}


def registrar(api, datos_enviados, llave=None):
    return api.post(
        f"{BASE}/", datos_enviados, format="json", HTTP_IDEMPOTENCY_KEY=llave or clave()
    )


class TestRegistrar:
    def test_registra_y_devuelve_el_detalle(self, datos):
        r = registrar(cliente_de("almacenero"), cuerpo(datos))
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["estado"], d["forma_pago"], d["total"]) == (
            1,
            "EMITIDO",
            "CONTADO",
            "118.00",
        )
        assert (d["op_gravada"], d["igv"]) == ("100.00", "18.00")
        assert d["proveedor_nombre"] == "Distribuidora Selva"
        assert d["comprobante"] == "F001-" + d["comprobante_numero"]
        assert d["lineas"][0]["costo_soles"] == "100.00"
        assert d["pagos"][0]["cuenta_nombre"] == "Caja soles"
        assert SaldoStock.objects.sin_ambito().get().cantidad == 10

    def test_reintento_con_la_misma_clave_no_duplica(self, datos):
        api, llave, c = cliente_de("almacenero"), clave(), None
        c = cuerpo(datos)
        primera = registrar(api, c, llave)
        segunda = registrar(api, c, llave)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda.json() == primera.json()
        assert segunda["Idempotency-Replayed"] == "true"
        assert Compra.objects.sin_ambito().count() == 1
        assert MovimientoInventario.objects.sin_ambito().count() == 1

    def test_sin_clave_no_registra(self, datos):
        r = cliente_de("almacenero").post(f"{BASE}/", cuerpo(datos), format="json")
        assert r.status_code == 400
        assert Compra.objects.sin_ambito().count() == 0

    def test_error_de_negocio_responde_400_con_codigo(self, datos):
        malo = cuerpo(datos, pagos=[])
        r = registrar(cliente_de("almacenero"), malo)
        assert r.status_code == 400
        assert "sumar" in r.content.decode()
        assert Compra.objects.sin_ambito().count() == 0

    def test_comprobante_repetido_responde_conflicto(self, datos):
        api = cliente_de("almacenero")
        c = cuerpo(datos, comprobante_numero="555")
        assert registrar(api, c).status_code == 201
        r = registrar(api, c)
        assert r.status_code == 409
        assert Compra.objects.sin_ambito().count() == 1

    def test_credito_con_cuotas(self, datos):
        c = cuerpo(
            datos,
            forma_pago="CREDITO",
            pagos=[],
            cuotas={
                "cantidad": 3,
                "primera_fecha": timezone.localdate().isoformat(),
                "periodicidad": datos.mensual.pk,
            },
        )
        r = registrar(cliente_de("almacenero"), c)
        assert r.status_code == 201, r.content
        cuotas = r.json()["cuotas"]
        assert [q["monto"] for q in cuotas] == ["39.34", "39.33", "39.33"]
        assert cuotas[0]["saldo"] == "39.34"

    def test_referencias_inexistentes_son_400(self, datos):
        for campo, valor in [
            ("proveedor", 999_999),
            ("almacen", 999_999),
            ("tipo_comprobante", "99"),
        ]:
            r = registrar(cliente_de("almacenero"), cuerpo(datos, **{campo: valor}))
            assert r.status_code == 400, campo

    def test_producto_inexistente(self, datos):
        malo = cuerpo(
            datos, lineas=[{"producto": 999_999, "cantidad": "1", "precio_unitario": "1"}]
        )
        assert registrar(cliente_de("almacenero"), malo).status_code == 400

    def test_cuerpo_incompleto(self, datos):
        r = registrar(cliente_de("almacenero"), {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 400

    def test_quien_no_tiene_el_permiso_no_registra(self, datos):
        for usuario in ("vendedor", "contador"):
            r = registrar(cliente_de(usuario), cuerpo(datos))
            assert r.status_code == 403, usuario
        assert Compra.objects.sin_ambito().count() == 0

    def test_otra_empresa_u_organizacion_no_registra(self, datos):
        assert registrar(cliente_de("vendedor_a2"), cuerpo(datos)).status_code == 403
        assert registrar(cliente_de("otra_org"), cuerpo(datos)).status_code in (400, 403)
        assert Compra.objects.sin_ambito().count() == 0

    def test_ubicacion_exige_su_permiso_y_ser_del_almacen(self, datos):
        producto = datos.mundo.producto()
        c = cuerpo(
            datos,
            producto,
            lineas=[
                {
                    "producto": producto.pk,
                    "cantidad": "10",
                    "precio_unitario": "10",
                    "ubicacion": 999_999,
                }
            ],
        )
        r = registrar(cliente_de("almacenero"), c)
        assert r.status_code == 400
        assert Compra.objects.sin_ambito().count() == 0


class TestConsulta:
    def _crear(self, datos, **extra):
        r = registrar(cliente_de("almacenero"), cuerpo(datos, **extra))
        assert r.status_code == 201, r.content
        return r.json()

    def test_listado_y_detalle(self, datos):
        creada = self._crear(datos, comprobante_numero="100")
        self._crear(datos, comprobante_numero="200")
        api = cliente_de("contador")
        r = api.get(f"{BASE}/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 200
        assert r.json()["count"] == 2
        assert r.json()["results"][0]["total"] == "118.00"
        d = api.get(f"{BASE}/{creada['id']}/")
        assert d.status_code == 200
        assert d.json()["lineas"][0]["producto_nombre"]

    def test_filtros(self, datos):
        self._crear(datos, comprobante_numero="100")
        self._crear(datos, comprobante_numero="200")
        api = cliente_de("contador")
        base = {"empresa": datos.mundo.e1.pk}
        assert api.get(f"{BASE}/", {**base, "q": "200"}).json()["count"] == 1
        assert api.get(f"{BASE}/", {**base, "q": "Selva"}).json()["count"] == 2
        assert api.get(f"{BASE}/", {**base, "estado": "ANULADO"}).json()["count"] == 0
        assert api.get(f"{BASE}/", {**base, "forma_pago": "CREDITO"}).json()["count"] == 0
        hoy = timezone.localdate().isoformat()
        assert api.get(f"{BASE}/", {**base, "desde": hoy}).json()["count"] == 0

    def test_exige_empresa_y_permiso(self, datos):
        assert cliente_de("contador").get(f"{BASE}/").status_code == 400
        assert (
            cliente_de("vendedor").get(f"{BASE}/", {"empresa": datos.mundo.e1.pk}).status_code
            == 403
        )

    def test_no_se_ve_lo_de_otra_empresa_ni_organizacion(self, datos):
        creada = self._crear(datos)
        assert cliente_de("vendedor_a2").get(f"{BASE}/{creada['id']}/").status_code in (403, 404)
        assert cliente_de("otra_org").get(f"{BASE}/{creada['id']}/").status_code in (403, 404)


class TestCalcular:
    def test_vista_previa_no_guarda(self, datos):
        c = cuerpo(
            datos,
            forma_pago="CREDITO",
            pagos=[],
            cuotas={
                "cantidad": 2,
                "primera_fecha": timezone.localdate().isoformat(),
                "periodicidad": datos.mensual.pk,
            },
        )
        r = cliente_de("almacenero").post(f"{BASE}/calcular/", c, format="json")
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["op_gravada"], d["igv"], d["total"]) == ("100.00", "18.00", "118.00")
        assert d["lineas"][0]["afectacion_codigo"] == "10"
        assert [q["monto"] for q in d["cuotas"]] == ["59.00", "59.00"]
        assert Compra.objects.sin_ambito().count() == 0
        assert MovimientoInventario.objects.sin_ambito().count() == 0

    def test_sin_pagos_todavia_calcula(self, datos):
        r = cliente_de("almacenero").post(
            f"{BASE}/calcular/", cuerpo(datos, pagos=[]), format="json"
        )
        assert r.status_code == 200
        assert r.json()["total"] == "118.00"

    def test_exige_permiso_de_crear(self, datos):
        r = cliente_de("contador").post(f"{BASE}/calcular/", cuerpo(datos), format="json")
        assert r.status_code == 403


class TestAnular:
    def _crear(self, datos):
        r = registrar(cliente_de("almacenero"), cuerpo(datos))
        assert r.status_code == 201, r.content
        return r.json()["id"]

    def test_admin_anula_y_el_stock_vuelve(self, datos):
        compra_id = self._crear(datos)
        r = cliente_de("admin").post(
            f"{BASE}/{compra_id}/anular/", {"motivo": "Error de digitación"}, format="json"
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["estado"], d["motivo_anulacion"]) == ("ANULADO", "Error de digitación")
        assert d["pagos"][0]["anulado"] is True
        assert SaldoStock.objects.sin_ambito().get().cantidad == 0

    def test_sin_permiso_o_sin_motivo_no_anula(self, datos):
        compra_id = self._crear(datos)
        assert (
            cliente_de("almacenero")
            .post(f"{BASE}/{compra_id}/anular/", {"motivo": "x"}, format="json")
            .status_code
            == 403
        )
        sin_motivo = cliente_de("admin").post(f"{BASE}/{compra_id}/anular/", {}, format="json")
        assert sin_motivo.status_code == 400
        assert Compra.objects.sin_ambito().get().estado == "EMITIDO"

    def test_anular_dos_veces(self, datos):
        compra_id = self._crear(datos)
        api = cliente_de("admin")
        assert (
            api.post(f"{BASE}/{compra_id}/anular/", {"motivo": "Uno"}, format="json").status_code
            == 200
        )
        assert (
            api.post(f"{BASE}/{compra_id}/anular/", {"motivo": "Dos"}, format="json").status_code
            == 409
        )


class TestCuerpoDelPanel:
    """El cuerpo que arma la pantalla: series con datos, flete con su pago y ajuste en cero."""

    def test_series_flete_y_ajuste(self, datos):
        celular = datos.mundo.producto("Celular", lleva_serie=True)
        c = cuerpo(
            datos,
            celular,
            ajuste_redondeo="0",
            nro_guia="",
            observacion="",
            lineas=[
                {
                    "producto": celular.pk,
                    "cantidad": "2",
                    "precio_unitario": "500.00",
                    "afectacion": "10",
                    "series": [{"numero": "IMEI0001", "otros_datos": "Negro"}, "IMEI0002"],
                }
            ],
            pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "1180.00"}],
            flete={
                "monto": "10.00",
                "al_costo": True,
                "comprobante_tipo": "01",
                "comprobante_serie": "F777",
                "comprobante_numero": "55",
                "pagos": [
                    {
                        "medio_pago": datos.efectivo.pk,
                        "cuenta": datos.caja.pk,
                        "monto": "10.00",
                        "referencia": "OP-9",
                    }
                ],
            },
        )
        r = registrar(cliente_de("almacenero"), c)
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["total"], d["flete"]) == ("1180.00", "10.00")
        assert d["lineas"][0]["flete_asignado"] == "10.00"
        assert d["lineas"][0]["costo_soles"] == "1010.00"
        assert {p["tipo"] for p in d["pagos"]} == {"COMPRA", "FLETE"}


class TestCuentasPorPagar:
    def _credito(self, datos, dias_primera=-1, cuotas=3, **extra):
        primera = (timezone.localdate() + timedelta(days=dias_primera)).isoformat()
        c = cuerpo(
            datos,
            forma_pago="CREDITO",
            pagos=[],
            cuotas={"cantidad": cuotas, "primera_fecha": primera, "periodicidad": datos.mensual.pk},
            **extra,
        )
        r = registrar(cliente_de("almacenero"), c)
        assert r.status_code == 201, r.content
        return r.json()["id"]

    def _pagar(self, datos, compra_id, monto, usuario="contador", llave=None, cuotas=None, **parte):
        pago = {"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": monto, **parte}
        cuerpo_pago = {"pagos": [pago], **({"cuotas": cuotas} if cuotas is not None else {})}
        return self._enviar_pagos(compra_id, cuerpo_pago, usuario, llave)

    def _enviar_pagos(self, compra_id, cuerpo_pago, usuario="contador", llave=None):
        return cliente_de(usuario).post(
            f"{BASE}/{compra_id}/pagar/",
            cuerpo_pago,
            format="json",
            HTTP_IDEMPOTENCY_KEY=llave or clave(),
        )

    def _por_pagar(self, datos, usuario="contador", **filtros):
        return cliente_de(usuario).get(
            f"{BASE}/por-pagar/", {"empresa": datos.mundo.e1.pk, **filtros}
        )

    def test_lista_lo_que_se_debe_con_su_vencimiento(self, datos):
        self._credito(datos)
        r = self._por_pagar(datos)
        assert r.status_code == 200, r.content
        fila = r.json()["results"][0]
        assert (fila["total"], fila["pagado"], fila["saldo"]) == ("118.00", "0.00", "118.00")
        assert (fila["saldo_vencido"], fila["dias_atraso"]) == ("39.34", 1)
        assert fila["proveedor_nombre"] == "Distribuidora Selva"

    def test_al_contado_no_aparece(self, datos):
        registrar(cliente_de("almacenero"), cuerpo(datos))
        assert self._por_pagar(datos).json()["count"] == 0

    def test_filtros_de_vencimiento(self, datos):
        self._credito(datos, dias_primera=-1, comprobante_numero="101")
        self._credito(datos, dias_primera=20, comprobante_numero="102")
        assert self._por_pagar(datos, vencimiento="vencidas").json()["count"] == 1
        assert self._por_pagar(datos, vencimiento="por_vencer").json()["count"] == 1
        assert self._por_pagar(datos, q="102").json()["count"] == 1
        hasta = (timezone.localdate() + timedelta(days=5)).isoformat()
        assert self._por_pagar(datos, vence_hasta=hasta).json()["count"] == 1

    def test_se_busca_por_serie_y_numero_juntos(self, datos):
        self._credito(datos, comprobante_numero="101")
        self._credito(datos, comprobante_numero="202")
        for q in ("F001-101", "f001-101", "F001-0000101", "F001-10", "101"):
            assert self._por_pagar(datos, q=q).json()["count"] == 1, q
        assert self._por_pagar(datos, q="F002-101").json()["count"] == 0
        assert self._por_pagar(datos, q="F001").json()["count"] == 2

    def test_las_mas_urgentes_van_primero(self, datos):
        self._credito(datos, dias_primera=20, comprobante_numero="201")
        self._credito(datos, dias_primera=-1, comprobante_numero="202")
        numeros = [f["comprobante"] for f in self._por_pagar(datos).json()["results"]]
        assert numeros == ["F001-202", "F001-201"]

    def test_resumen_por_moneda(self, datos):
        self._credito(datos, dias_primera=-1)
        r = cliente_de("contador").get(f"{BASE}/por-pagar/resumen/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 200, r.content
        assert r.json() == [
            {
                "moneda": "PEN",
                "saldo": "118.00",
                "vencido": "39.34",
                "por_vencer_7_dias": "0.00",
                "compras": 1,
            }
        ]

    def test_pagar_baja_la_deuda_y_deja_el_detalle(self, datos):
        compra_id = self._credito(datos)
        r = self._pagar(datos, compra_id, "50.00", referencia="")
        assert r.status_code == 201, r.content
        d = r.json()
        assert [q["pagado"] for q in d["cuotas"]] == ["39.34", "10.66", "0.00"]
        pago = d["pagos"][0]
        assert (pago["monto"], pago["cuenta_nombre"]) == ("50.00", "Caja soles")
        assert pago["cuotas_pagadas"] == [
            {"numero": 1, "monto": "39.34"},
            {"numero": 2, "monto": "10.66"},
        ]
        assert self._por_pagar(datos).json()["results"][0]["saldo"] == "68.00"

    def test_pagar_todo_saca_la_compra_de_la_lista(self, datos):
        compra_id = self._credito(datos)
        assert self._pagar(datos, compra_id, "118.00").status_code == 201
        assert self._por_pagar(datos).json()["count"] == 0

    def test_reintento_no_paga_dos_veces(self, datos):
        compra_id, llave = self._credito(datos), clave()
        primera = self._pagar(datos, compra_id, "10.00", llave=llave)
        segunda = self._pagar(datos, compra_id, "10.00", llave=llave)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda["Idempotency-Replayed"] == "true"
        assert self._por_pagar(datos).json()["results"][0]["saldo"] == "108.00"

    def test_dos_medios_de_pago_en_una_sola_operacion(self, datos):
        compra_id = self._credito(datos)
        transferencia = datos.mundo.e  # solo para no repetir el nombre
        assert transferencia
        from apps.mantenimiento.models import MedioPago

        transf = MedioPago.objects.sin_ambito().get(
            organizacion=datos.mundo.e.org_a, nombre="Transferencia o depósito"
        )
        r = self._enviar_pagos(
            compra_id,
            {
                "pagos": [
                    {"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "60.00"},
                    {
                        "medio_pago": transf.pk,
                        "cuenta": datos.caja.pk,
                        "monto": "40.00",
                        "referencia": "OP-55",
                    },
                ]
            },
        )
        assert r.status_code == 201, r.content
        d = r.json()
        assert [(p["medio_pago_nombre"], p["monto"]) for p in d["pagos"]] == [
            ("Efectivo", "60.00"),
            ("Transferencia o depósito", "40.00"),
        ]
        assert d["pagos"][1]["referencia"] == "OP-55"
        # 100 en total: cuota 1 (39,34) + cuota 2 (39,33) + 21,33 de la 3.ª, repartidos en orden.
        assert [q["pagado"] for q in d["cuotas"]] == ["39.34", "39.33", "21.33"]
        assert self._por_pagar(datos).json()["results"][0]["saldo"] == "18.00"

    def test_si_un_medio_falla_no_se_registra_ninguno(self, datos):
        from apps.mantenimiento.models import MedioPago

        compra_id = self._credito(datos)
        transf = MedioPago.objects.sin_ambito().get(
            organizacion=datos.mundo.e.org_a, nombre="Transferencia o depósito"
        )
        r = self._enviar_pagos(
            compra_id,
            {
                "pagos": [
                    {"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "60.00"},
                    {"medio_pago": transf.pk, "cuenta": datos.caja.pk, "monto": "40.00"},
                ]
            },
        )
        assert r.status_code == 400  # falta el número de operación del segundo
        assert self._por_pagar(datos).json()["results"][0]["saldo"] == "118.00"

    def test_los_medios_juntos_no_pasan_de_la_deuda(self, datos):
        compra_id = self._credito(datos)
        r = self._enviar_pagos(
            compra_id,
            {
                "pagos": [
                    {"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "100.00"},
                    {"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "18.01"},
                ]
            },
        )
        assert r.status_code == 400
        assert self._por_pagar(datos).json()["results"][0]["saldo"] == "118.00"

    def test_errores_de_negocio(self, datos):
        compra_id = self._credito(datos)
        assert self._pagar(datos, compra_id, "118.01").status_code == 400
        assert self._pagar(datos, compra_id, "10.00", cuenta=999_999).status_code == 400
        assert self._pagar(datos, compra_id, "10.00", cuotas=[999_999]).status_code == 400
        sin_clave = cliente_de("contador").post(
            f"{BASE}/{compra_id}/pagar/", {"monto": "10"}, format="json"
        )
        assert sin_clave.status_code == 400

    def test_solo_quien_puede_pagar_paga(self, datos):
        compra_id = self._credito(datos)
        assert self._pagar(datos, compra_id, "10.00", usuario="almacenero").status_code == 403
        assert self._pagar(datos, compra_id, "10.00", usuario="vendedor").status_code == 403
        assert self._pagar(datos, compra_id, "10.00", usuario="vendedor_a2").status_code in (
            403,
            404,
        )
        assert self._por_pagar(datos, usuario="vendedor").status_code == 403

    def test_la_empresa_es_obligatoria(self, datos):
        assert cliente_de("contador").get(f"{BASE}/por-pagar/").status_code == 400

    def test_anular_un_pago_lo_devuelve_a_las_cuotas(self, datos):
        compra_id = self._credito(datos)
        pago_id = self._pagar(datos, compra_id, "50.00").json()["pagos"][0]["id"]
        url = f"{BASE}/{compra_id}/pagos/{pago_id}/anular/"
        sin_permiso = cliente_de("contador").post(url, {"motivo": "Error"}, format="json")
        assert sin_permiso.status_code == 403
        r = cliente_de("admin").post(url, {"motivo": "Pagué la cuenta equivocada"}, format="json")
        assert r.status_code == 200, r.content
        d = r.json()
        assert [q["pagado"] for q in d["cuotas"]] == ["0.00", "0.00", "0.00"]
        assert (d["pagos"][0]["anulado"], d["pagos"][0]["motivo_anulacion"]) == (
            True,
            "Pagué la cuenta equivocada",
        )
        assert self._por_pagar(datos).json()["results"][0]["saldo"] == "118.00"
        otra = cliente_de("admin").post(url, {"motivo": "Otra vez"}, format="json")
        assert otra.status_code == 409

    def test_el_pago_de_otra_compra_no_se_anula(self, datos):
        uno, dos = (
            self._credito(datos, comprobante_numero="301"),
            self._credito(datos, comprobante_numero="302"),
        )
        pago_id = self._pagar(datos, uno, "10.00").json()["pagos"][0]["id"]
        r = cliente_de("admin").post(
            f"{BASE}/{dos}/pagos/{pago_id}/anular/", {"motivo": "Error"}, format="json"
        )
        assert r.status_code == 404


class TestLote:
    def test_el_lote_de_cada_linea_se_guarda_y_se_devuelve(self, datos):
        producto = datos.mundo.producto()
        c = cuerpo(
            datos,
            producto,
            lineas=[
                {
                    "producto": producto.pk,
                    "cantidad": "10",
                    "precio_unitario": "10",
                    "lote": " L-2026-10 ",
                },
                {
                    "producto": datos.mundo.producto("Otro").pk,
                    "cantidad": "1",
                    "precio_unitario": "5",
                },
            ],
            pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "123.90"}],
        )
        r = registrar(cliente_de("almacenero"), c)
        assert r.status_code == 201, r.content
        assert [ln["lote"] for ln in r.json()["lineas"]] == ["L-2026-10", ""]


class TestRegistroDeCompras:
    def _rango(self, datos, **extra):
        hoy = timezone.localdate()
        return {
            "empresa": datos.mundo.e1.pk,
            "desde": (hoy - timedelta(days=10)).isoformat(),
            "hasta": hoy.isoformat(),
            **extra,
        }

    def _vista(self, datos, usuario="contador", **extra):
        return cliente_de(usuario).get(
            f"{BASE}/reportes/registro-compras/vista/", self._rango(datos, **extra)
        )

    def test_la_vista_previa_trae_las_filas_y_los_totales_en_soles(self, datos):
        registrar(cliente_de("almacenero"), cuerpo(datos, comprobante_numero="501"))
        r = self._vista(datos)
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["total_filas"] == 1
        fila = d["filas"][0]
        assert [fila[k] for k in ("serie", "comprobante", "gravada", "igv", "total")] == [
            "F001",
            "501",
            "100.00",
            "18.00",
            "118.00",
        ]
        assert fila["proveedor"] == "Distribuidora Selva"
        assert d["totales"] == {
            "gravada": "100.00",
            "igv": "18.00",
            "exonerada": "0.00",
            "inafecta": "0.00",
            "total": "118.00",
        }

    def test_las_anuladas_no_entran(self, datos):
        compra_id = registrar(cliente_de("almacenero"), cuerpo(datos)).json()["id"]
        cliente_de("admin").post(f"{BASE}/{compra_id}/anular/", {"motivo": "Error"}, format="json")
        assert self._vista(datos).json()["total_filas"] == 0

    def test_en_dolares_el_total_en_soles_usa_su_tipo_de_cambio(self, datos):
        caja_usd = CuentaFinanciera.objects.sin_ambito().create(
            empresa=datos.mundo.e1, nombre="Caja dólares", tipo="CAJA", moneda="USD"
        )
        c = cuerpo(
            datos,
            moneda="USD",
            tipo_cambio="3.7500",
            pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": caja_usd.pk, "monto": "118.00"}],
        )
        assert registrar(cliente_de("almacenero"), c).status_code == 201
        d = self._vista(datos).json()
        assert d["filas"][0]["total_soles"] == "442.50"
        assert d["totales"]["total"] == "442.50"
        assert d["totales"]["gravada"] == "375.00"

    def test_descarga_el_excel_y_deja_auditoria(self, datos):
        from io import BytesIO

        from openpyxl import load_workbook

        registrar(cliente_de("almacenero"), cuerpo(datos, comprobante_numero="502"))
        r = cliente_de("contador").get(f"{BASE}/reportes/registro-compras/", self._rango(datos))
        assert r.status_code == 200, r.content
        assert "spreadsheetml" in r["Content-Type"]
        assert r["Content-Disposition"].startswith('attachment; filename="registro-compras_')
        hoja = load_workbook(BytesIO(r.content)).active
        celdas = [[c.value for c in fila] for fila in hoja.iter_rows(min_row=7, max_row=9)]
        assert celdas[0][3:5] == ["Serie", "Número"] and celdas[0][8] == "Base gravada"
        assert celdas[1][3:5] == ["F001", "502"] and celdas[1][8] == 100
        assert celdas[2][7] == "TOTALES EN SOLES" and celdas[2][16] == 118
        from apps.auditoria.models import AuditoriaEvento

        assert AuditoriaEvento.objects.filter(accion="compras.registro_exportado").exists()

    def test_un_proveedor_con_formula_en_el_nombre_se_escribe_como_texto(self, datos):
        from io import BytesIO

        from openpyxl import load_workbook

        datos.proveedor.nombre = '=HYPERLINK("http://malo")'
        datos.proveedor.save()
        registrar(cliente_de("almacenero"), cuerpo(datos))
        r = cliente_de("contador").get(f"{BASE}/reportes/registro-compras/", self._rango(datos))
        celda = load_workbook(BytesIO(r.content)).active.cell(row=8, column=8)
        assert celda.data_type == "s"

    def test_el_rango_es_obligatorio_y_acotado(self, datos):
        hoy = timezone.localdate()
        api = cliente_de("contador")
        url = f"{BASE}/reportes/registro-compras/vista/"
        base = {"empresa": datos.mundo.e1.pk}
        assert api.get(url, base).status_code == 400
        assert (
            api.get(
                url,
                {**base, "desde": hoy.isoformat(), "hasta": (hoy - timedelta(days=1)).isoformat()},
            ).status_code
            == 400
        )
        assert (
            api.get(
                url,
                {
                    **base,
                    "desde": (hoy - timedelta(days=400)).isoformat(),
                    "hasta": hoy.isoformat(),
                },
            ).status_code
            == 400
        )
        assert (
            api.get(
                url,
                {**base, "desde": hoy.isoformat(), "hasta": (hoy + timedelta(days=1)).isoformat()},
            ).status_code
            == 400
        )

    def test_solo_quien_puede_exportar(self, datos):
        assert self._vista(datos, usuario="almacenero").status_code == 403
        assert self._vista(datos, usuario="vendedor").status_code == 403
        assert self._vista(datos, usuario="vendedor_a2").status_code == 403
        sin_empresa = cliente_de("contador").get(f"{BASE}/reportes/registro-compras/vista/")
        assert sin_empresa.status_code == 400


class TestDeudasPorProveedor:
    def _credito(self, datos, proveedor=None, dias_primera=-1, numero="1", **extra):
        primera = (timezone.localdate() + timedelta(days=dias_primera)).isoformat()
        c = cuerpo(
            datos,
            forma_pago="CREDITO",
            pagos=[],
            comprobante_numero=numero,
            proveedor=(proveedor or datos.proveedor).pk,
            cuotas={"cantidad": 2, "primera_fecha": primera, "periodicidad": datos.mensual.pk},
            **extra,
        )
        r = registrar(cliente_de("almacenero"), c)
        assert r.status_code == 201, r.content
        return r.json()["id"]

    def _otro_proveedor(self, datos, nombre="Importadora Andina"):
        return Proveedor.objects.sin_ambito().create(
            organizacion=datos.mundo.e.org_a,
            tipo_documento="RUC",
            numero_documento=ruc_valido("2010000033"),
            nombre=nombre,
        )

    def _lista(self, datos, usuario="contador", **filtros):
        return cliente_de(usuario).get(
            f"{BASE}/por-pagar/proveedores/", {"empresa": datos.mundo.e1.pk, **filtros}
        )

    def test_una_fila_por_proveedor_con_sus_facturas_sumadas(self, datos):
        self._credito(datos, numero="101")
        self._credito(datos, numero="102")
        r = self._lista(datos)
        assert r.status_code == 200, r.content
        assert r.json()["count"] == 1
        fila = r.json()["results"][0]
        assert (fila["proveedor_nombre"], fila["facturas"]) == ("Distribuidora Selva", 2)
        assert fila["montos"] == [
            {
                "moneda": "PEN",
                "saldo": "236.00",
                "vencido": "118.00",
                "por_vencer_7_dias": "0.00",
                "facturas": 2,
            }
        ]
        assert fila["dias_atraso"] == 1

    def test_pagar_baja_la_deuda_del_proveedor(self, datos):
        compra_id = self._credito(datos, numero="101")
        cliente_de("contador").post(
            f"{BASE}/{compra_id}/pagar/",
            {
                "pagos": [
                    {"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "118.00"}
                ]
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=clave(),
        )
        assert self._lista(datos).json()["count"] == 0

    def test_proveedores_distintos_y_el_mas_atrasado_primero(self, datos):
        otro = self._otro_proveedor(datos)
        self._credito(datos, dias_primera=10, numero="201")  # al día
        self._credito(
            datos,
            proveedor=otro,
            dias_primera=-5,
            numero="202",
            fecha_emision=(timezone.localdate() - timedelta(days=10)).isoformat(),
        )  # atrasado
        nombres = [f["proveedor_nombre"] for f in self._lista(datos).json()["results"]]
        assert nombres == ["Importadora Andina", "Distribuidora Selva"]

    def test_soles_y_dolares_no_se_suman(self, datos):
        caja_usd = CuentaFinanciera.objects.sin_ambito().create(
            empresa=datos.mundo.e1, nombre="Caja dólares", tipo="CAJA", moneda="USD"
        )
        assert caja_usd.pk
        self._credito(datos, numero="301")
        self._credito(datos, numero="302", moneda="USD", tipo_cambio="3.7500")
        fila = self._lista(datos).json()["results"][0]
        assert fila["facturas"] == 2
        assert [(m["moneda"], m["saldo"]) for m in fila["montos"]] == [
            ("PEN", "118.00"),
            ("USD", "118.00"),
        ]

    def test_filtros_busqueda_y_vencimiento(self, datos):
        otro = self._otro_proveedor(datos)
        self._credito(datos, dias_primera=-1, numero="401")
        self._credito(datos, proveedor=otro, dias_primera=20, numero="402")
        assert self._lista(datos, q="andina").json()["count"] == 1
        assert self._lista(datos, q=datos.proveedor.numero_documento).json()["count"] == 1
        assert self._lista(datos, q="nadie").json()["count"] == 0
        vencidas = self._lista(datos, vencimiento="vencidas").json()["results"]
        assert [f["proveedor_nombre"] for f in vencidas] == ["Distribuidora Selva"]
        al_dia = self._lista(datos, vencimiento="por_vencer").json()["results"]
        assert [f["proveedor_nombre"] for f in al_dia] == ["Importadora Andina"]
        hasta = (timezone.localdate() + timedelta(days=5)).isoformat()
        assert self._lista(datos, vence_hasta=hasta).json()["count"] == 1

    def test_las_facturas_de_un_proveedor_se_piden_con_el_filtro(self, datos):
        otro = self._otro_proveedor(datos)
        self._credito(datos, numero="501")
        self._credito(datos, proveedor=otro, numero="502")
        r = cliente_de("contador").get(
            f"{BASE}/por-pagar/", {"empresa": datos.mundo.e1.pk, "proveedor": otro.pk}
        )
        assert [f["comprobante"] for f in r.json()["results"]] == ["F001-502"]

    def test_al_contado_y_anuladas_no_cuentan(self, datos):
        registrar(cliente_de("almacenero"), cuerpo(datos, comprobante_numero="601"))
        anulada = self._credito(datos, numero="602")
        cliente_de("admin").post(f"{BASE}/{anulada}/anular/", {"motivo": "Error"}, format="json")
        assert self._lista(datos).json()["count"] == 0

    def test_permisos_y_empresa(self, datos):
        self._credito(datos, numero="701")
        assert self._lista(datos, usuario="vendedor").status_code == 403
        assert self._lista(datos, usuario="vendedor_a2").status_code == 403
        assert cliente_de("contador").get(f"{BASE}/por-pagar/proveedores/").status_code == 400
