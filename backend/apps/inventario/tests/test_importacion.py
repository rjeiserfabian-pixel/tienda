"""Importación del saldo inicial: revisión, importación, errores por fila y seguridad."""

import io
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.inventario import importacion, periodos
from apps.inventario.models import LineaMovimiento, MovimientoInventario, SaldoStock
from apps.mantenimiento.models import TipoProducto
from apps.seguridad.tests.conftest import cliente_de

from .ayudas_api import BASE

pytestmark = pytest.mark.django_db

URL = f"{BASE}/saldo-inicial/importar/"
TITULOS = [
    "Código del producto",
    "Producto (solo referencia)",
    "Código del almacén",
    "Cantidad",
    "Costo unitario (S/ sin IGV)",
]


def xlsx(filas, titulos=TITULOS, nombre="saldo.xlsx"):
    libro = Workbook()
    hoja = libro.active
    hoja.append(titulos)
    for fila in filas:
        hoja.append(fila)
    buffer = io.BytesIO()
    libro.save(buffer)
    return SimpleUploadedFile(nombre, buffer.getvalue())


def subir(mundo, archivo, *, modo="validar", usuario="super", fecha=None, empresa=None):
    return cliente_de(usuario).post(
        URL,
        {
            "empresa": (empresa or mundo.e1).pk,
            "fecha": fecha or (timezone.localdate() - timedelta(days=3)).isoformat(),
            "modo": modo,
            "archivo": archivo,
        },
        format="multipart",
    )


def lineas():
    return LineaMovimiento.objects.sin_ambito()


@pytest.fixture
def catalogo(mundo):
    return [mundo.producto(n) for n in ("Cemento", "Arena", "Ladrillo")]


class TestRevision:
    def test_informa_sin_guardar_nada(self, mundo, catalogo):
        c, a, _ = catalogo
        r = subir(mundo, xlsx([[c.codigo, "x", "ALM1", 50, 20], [a.codigo, "y", "", 10.5, 8.25]]))
        assert r.status_code == 200, r.content
        datos = r.json()
        assert (datos["total"], datos["validas"], datos["con_error"], datos["repetidos"]) == (
            2,
            2,
            0,
            0,
        )
        assert datos["modo"] == "validar" and datos["creados"] == 0
        assert (datos["movimientos"], datos["valor_total"]) == (
            1,
            "1086.63",
        )  # 1000.00 + 86.625 redondeado al centavo
        assert MovimientoInventario.objects.sin_ambito().count() == 0
        assert SaldoStock.objects.sin_ambito().count() == 0

    def test_errores_por_fila_con_mensaje_claro(self, mundo, catalogo):
        c = catalogo[0]
        servicio = mundo.producto("Flete", tipo=TipoProducto.SERVICIO, controla_stock=False)
        r = subir(
            mundo,
            xlsx(
                [
                    [c.codigo, "", "ALM1", 5, 10],  # válida
                    ["999999", "", "ALM1", 5, 10],  # no existe
                    [servicio.codigo, "", "ALM1", 5, 10],  # servicio
                    [c.codigo, "", "NOEXISTE", 5, 10],  # almacén
                    ["", "", "ALM1", 5, 10],  # sin código
                    [catalogo[1].codigo, "", "ALM1", 0, 10],  # cantidad cero
                    [catalogo[1].codigo, "", "ALM1", "-3", 10],  # negativa
                    [catalogo[1].codigo, "", "ALM1", 1.2345, 10],  # 4 decimales
                    [catalogo[1].codigo, "", "ALM1", 5, ""],  # sin costo
                    [catalogo[1].codigo, "", "ALM1", 5, "abc"],  # costo no numérico
                ]
            ),
        )
        datos = r.json()
        assert (datos["total"], datos["validas"], datos["con_error"]) == (10, 1, 9)
        por_fila = {e["fila"]: e["mensaje"] for e in datos["errores"]}
        assert "No existe un producto" in por_fila[3]
        assert "no lleva control de stock" in por_fila[4]
        assert "almacén" in por_fila[5]
        assert "código del producto" in por_fila[6]
        assert "mayor que cero" in por_fila[7] and "mayor que cero" not in por_fila.get(10, "")
        assert "decimales" in por_fila[9]
        assert "Indique el costo" in por_fila[10] and "número" in por_fila[11]

    def test_repetidos_en_el_archivo_y_con_movimientos_previos(self, mundo, catalogo):
        c, a, _ = catalogo
        assert (
            subir(mundo, xlsx([[c.codigo, "", "ALM1", 5, 10]]), modo="importar").status_code == 200
        )
        r = subir(
            mundo,
            xlsx(
                [
                    [c.codigo, "", "ALM1", 9, 10],
                    [a.codigo, "", "ALM1", 1, 1],
                    [a.codigo, "", "ALM1", 2, 2],
                ]
            ),
        )
        datos = r.json()
        assert (datos["validas"], datos["repetidos"]) == (1, 2)
        motivos = {x["fila"]: x["motivo"] for x in datos["repetidos_detalle"]}
        assert "Ya tiene movimientos" in motivos[2] and "fila 3" in motivos[4]

    def test_codigos_sin_ceros_iniciales_y_coma_decimal(self, mundo, catalogo):
        c = catalogo[0]
        sin_ceros = str(int(c.codigo))  # Excel guarda 000001 como 1
        r = subir(mundo, xlsx([[int(sin_ceros), "", "", "2,5", "10,50"]]))
        assert r.json()["validas"] == 1

    def test_columnas_con_otros_nombres_y_columnas_sobrantes(self, mundo, catalogo):
        c = catalogo[0]
        titulos = ["codigo", "cant", "COSTO UNITARIO", "Observaciones"]
        r = subir(mundo, xlsx([[c.codigo, 4, 3, "x"]], titulos=titulos))
        datos = r.json()
        assert datos["validas"] == 1 and datos["columnas_ignoradas"] == ["Observaciones"]

    def test_falta_una_columna_obligatoria(self, mundo, catalogo):
        r = subir(mundo, xlsx([["000001", 5]], titulos=["Código del producto", "Cantidad"]))
        assert r.status_code == 400 and "Faltan columnas" in r.json()["error"]["detalle"]["archivo"]


class TestImportar:
    def test_crea_un_movimiento_de_saldo_inicial_con_su_costo(self, mundo, catalogo):
        c, a, _ = catalogo
        fecha = (timezone.localdate() - timedelta(days=10)).isoformat()
        r = subir(
            mundo,
            xlsx([[c.codigo, "", "ALM1", 50, 20], [a.codigo, "", "ALM1", 10, 8.25]]),
            modo="importar",
            fecha=fecha,
        )
        assert r.status_code == 200, r.content
        assert (r.json()["creados"], r.json()["movimientos"]) == (2, 1)
        movimiento = MovimientoInventario.objects.sin_ambito().get()
        assert (movimiento.origen, movimiento.tipo, movimiento.tipo_operacion) == (
            "SALDO_INICIAL",
            "ENTRADA",
            "16",
        )
        assert movimiento.fecha.isoformat() == fecha and movimiento.observacion
        saldo = SaldoStock.objects.sin_ambito().get(producto=c)
        assert (saldo.cantidad, saldo.costo_total, saldo.costo_unitario) == (50, 1000, 20)
        assert SaldoStock.objects.sin_ambito().get(producto=a).costo_total == 82.50

    def test_solo_entran_las_filas_validas(self, mundo, catalogo):
        c = catalogo[0]
        r = subir(
            mundo,
            xlsx([[c.codigo, "", "ALM1", 5, 10], ["999999", "", "ALM1", 5, 10]]),
            modo="importar",
        )
        assert (r.json()["creados"], r.json()["con_error"]) == (1, 1)
        assert SaldoStock.objects.sin_ambito().count() == 1

    def test_importar_dos_veces_no_duplica_el_stock(self, mundo, catalogo):
        c = catalogo[0]
        archivo = [[c.codigo, "", "ALM1", 5, 10]]
        subir(mundo, xlsx(archivo), modo="importar")
        r = subir(mundo, xlsx(archivo), modo="importar")
        assert (r.json()["creados"], r.json()["repetidos"]) == (0, 1)
        assert SaldoStock.objects.sin_ambito().get().cantidad == 5
        assert MovimientoInventario.objects.sin_ambito().count() == 1

    def test_acepta_csv_con_punto_y_coma(self, mundo, catalogo):
        c = catalogo[0]
        csv = f"Código del producto;Cantidad;Costo\n{c.codigo};12;4,5\n".encode("latin-1")
        r = subir(mundo, SimpleUploadedFile("saldo.csv", csv), modo="importar")
        assert r.status_code == 200 and r.json()["creados"] == 1
        assert SaldoStock.objects.sin_ambito().get().costo_total == 54

    def test_mas_de_200_productos_se_reparten_en_varios_movimientos(self, mundo):
        productos = [mundo.producto(f"Producto {i}") for i in range(450)]
        archivo = xlsx([[p.codigo, "", "ALM1", 1, 2] for p in productos])
        inicio = time.perf_counter()
        r = subir(mundo, archivo, modo="importar")
        print(f"IMPORTAR 450 PRODUCTOS: {time.perf_counter() - inicio:.2f} s")
        assert (r.json()["creados"], r.json()["movimientos"]) == (450, 3)
        cantidades = sorted(
            lineas().filter(movimiento=m).count() for m in MovimientoInventario.objects.sin_ambito()
        )
        assert cantidades == [50, 200, 200]
        assert SaldoStock.objects.sin_ambito().count() == 450

    def test_si_algo_falla_a_medias_no_entra_nada(self, mundo, monkeypatch):
        productos = [mundo.producto(f"Producto {i}") for i in range(250)]
        real = importacion.registrar_movimiento
        llamadas = []

        def con_falla(**kwargs):
            llamadas.append(1)
            if len(llamadas) == 2:
                raise RuntimeError("falla simulada")
            return real(**kwargs)

        monkeypatch.setattr(importacion, "registrar_movimiento", con_falla)
        r = subir(mundo, xlsx([[p.codigo, "", "ALM1", 1, 2] for p in productos]), modo="importar")
        assert r.status_code == 500
        assert MovimientoInventario.objects.sin_ambito().count() == 0
        assert SaldoStock.objects.sin_ambito().count() == 0
        assert lineas().count() == 0

    def test_con_dos_almacenes_hay_que_indicar_cual(self, mundo, catalogo):
        from apps.mantenimiento.models import Almacen

        Almacen.objects.sin_ambito().create(
            empresa=mundo.e1, sucursal=mundo.alm[1].sucursal, codigo="ALM2", nombre="Segundo"
        )
        c = catalogo[0]
        r = subir(mundo, xlsx([[c.codigo, "", "", 5, 1], [c.codigo, "", "alm2", 7, 1]]))
        datos = r.json()
        assert (datos["validas"], datos["con_error"]) == (1, 1)
        assert "Indique el código del almacén" in datos["errores"][0]["mensaje"]
        subir(mundo, xlsx([[c.codigo, "", "alm2", 7, 1]]), modo="importar")
        assert SaldoStock.objects.sin_ambito().get().almacen.codigo == "ALM2"


class TestFechaYPeriodos:
    def test_no_admite_fecha_futura(self, mundo, catalogo):
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = subir(mundo, xlsx([[catalogo[0].codigo, "", "", 1, 1]]), fecha=manana)
        assert r.status_code == 400

    def test_un_mes_cerrado_no_admite_el_saldo_inicial(self, mundo, catalogo):
        from apps.core.tenant import contexto_tenant
        from apps.inventario.models import OrigenMovimiento, TipoMovimiento
        from apps.inventario.movimientos import LineaNueva, registrar_movimiento

        hoy = timezone.localdate()
        fin_pasado = hoy.replace(day=1) - timedelta(days=1)
        with contexto_tenant(mundo.e.org_a.pk, [mundo.e1.pk, mundo.e2.pk]):
            registrar_movimiento(
                empresa=mundo.e1,
                almacen=mundo.alm[1],
                tipo=TipoMovimiento.ENTRADA,
                origen=OrigenMovimiento.COMPRA,
                fecha=fin_pasado,
                lineas=[LineaNueva(catalogo[1], Decimal("1"), Decimal("1"))],
            )
            periodos.cerrar_periodo(mundo.e1, f"{fin_pasado:%Y%m}")
        r = subir(mundo, xlsx([[catalogo[0].codigo, "", "", 1, 1]]), fecha=fin_pasado.isoformat())
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "periodo_cerrado")


class TestArchivoYPermisos:
    def test_archivo_invalido(self, mundo):
        for nombre, contenido in [
            ("saldo.txt", b"hola"),
            ("saldo.xlsx", b"no es un excel"),
            ("vacio.csv", b""),
        ]:
            r = subir(mundo, SimpleUploadedFile(nombre, contenido))
            assert r.status_code == 400, nombre

    def test_archivo_demasiado_grande(self, mundo):
        grande = SimpleUploadedFile("saldo.csv", b"a;b\n" + b"x" * (2 * 1024 * 1024 + 10))
        assert subir(mundo, grande).status_code == 400

    def test_mas_de_2000_filas(self, mundo, catalogo):
        c = catalogo[0]
        r = subir(mundo, xlsx([[c.codigo, "", "", 1, 1]] * 2001))
        assert r.status_code == 400 and "2000 filas" in r.json()["error"]["detalle"]["archivo"]

    def test_sin_archivo_o_con_datos_invalidos(self, mundo):
        api = cliente_de("super")
        base = {"empresa": mundo.e1.pk, "fecha": timezone.localdate().isoformat()}
        assert api.post(URL, base, format="multipart").status_code == 400
        assert api.post(URL, {**base, "modo": "otro"}, format="multipart").status_code == 400

    def test_solo_quien_puede_cargar_el_saldo_inicial(self, mundo, catalogo):
        archivo = [[catalogo[0].codigo, "", "", 1, 1]]
        for usuario in ("vendedor", "almacenero", "contador"):
            assert subir(mundo, xlsx(archivo), usuario=usuario).status_code == 403
        assert subir(mundo, xlsx(archivo), usuario="admin").status_code == 200
        assert subir(mundo, xlsx(archivo), usuario="otra_org").status_code == 403

    def test_no_se_carga_en_una_empresa_sin_acceso(self, mundo, catalogo):
        r = subir(
            mundo, xlsx([[catalogo[0].codigo, "", "", 1, 1]]), usuario="admin", empresa=mundo.e2
        )
        assert r.status_code == 403

    def test_queda_en_la_auditoria(self, mundo, catalogo):
        from apps.auditoria.models import AuditoriaEvento

        subir(mundo, xlsx([[catalogo[0].codigo, "", "", 3, 2]]), modo="importar")
        evento = AuditoriaEvento.objects.filter(accion="inventario.saldo_inicial_importado").latest(
            "id"
        )
        assert evento.detalle["productos"] == 1 and evento.detalle["valor_total"] == "6.00"


class TestPlantilla:
    def test_trae_los_productos_del_catalogo_con_el_codigo_como_texto(self, mundo, catalogo):
        servicio = mundo.producto("Flete", tipo=TipoProducto.SERVICIO, controla_stock=False)
        r = cliente_de("admin").get(f"{BASE}/saldo-inicial/plantilla/", {"empresa": mundo.e1.pk})
        assert r.status_code == 200 and "plantilla_saldo_inicial.xlsx" in r["Content-Disposition"]
        libro = load_workbook(io.BytesIO(r.content))
        assert libro.sheetnames == ["Saldo inicial", "Instrucciones"]
        filas = [list(f) for f in libro["Saldo inicial"].iter_rows(values_only=True)]
        assert filas[0] == [*TITULOS, "Ubicación (opcional)"]
        assert [f[1] for f in filas[1:]] == [
            "Arena",
            "Cemento",
            "Ladrillo",
        ]  # sin servicios, por nombre
        assert filas[1][0] == catalogo[1].codigo and isinstance(filas[1][0], str)
        assert filas[1][2] == "ALM1"  # un solo almacén: ya viene puesto
        assert servicio.nombre not in [f[1] for f in filas]

    def test_la_plantilla_llenada_se_importa(self, mundo, catalogo):
        r = cliente_de("admin").get(f"{BASE}/saldo-inicial/plantilla/", {"empresa": mundo.e1.pk})
        libro = load_workbook(io.BytesIO(r.content))
        hoja = libro["Saldo inicial"]
        for fila in range(2, 5):
            hoja.cell(row=fila, column=4, value=10)
            hoja.cell(row=fila, column=5, value=2.5)
        buffer = io.BytesIO()
        libro.save(buffer)
        r = subir(mundo, SimpleUploadedFile("llena.xlsx", buffer.getvalue()), modo="importar")
        assert (r.json()["creados"], r.json()["valor_total"]) == (3, "75.00")

    def test_permisos_de_la_plantilla(self, mundo):
        for usuario in ("vendedor", "contador"):
            r = cliente_de(usuario).get(
                f"{BASE}/saldo-inicial/plantilla/", {"empresa": mundo.e1.pk}
            )
            assert r.status_code == 403
        assert cliente_de("admin").get(f"{BASE}/saldo-inicial/plantilla/").status_code == 400
