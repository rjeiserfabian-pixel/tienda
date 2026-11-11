"""Importación masiva de clientes y proveedores desde Excel (.xlsx) o CSV."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento.models import Cliente, Proveedor
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"
RUC = ruc_valido("2060308400")
RUC_2 = ruc_valido("2010000001")

ENCABEZADO = "Tipo de documento,Número de documento,Nombre o razón social,Teléfono,Correo\n"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        # El vendedor puede crear clientes pero NO importarlos en masa.
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def csv_(contenido: str, nombre="clientes.csv"):
    return SimpleUploadedFile(nombre, contenido.encode("utf-8-sig"), content_type="text/csv")


def xlsx(filas, nombre="clientes.xlsx"):
    libro = Workbook()
    hoja = libro.active
    for fila in filas:
        hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return SimpleUploadedFile(
        nombre,
        salida.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def subir(api, ruta, archivo, modo="validar"):
    return api.post(
        f"{BASE}/{ruta}/importar/", {"archivo": archivo, "modo": modo}, format="multipart"
    )


# ---------------------------------------------------------------------------
# Plantilla y permisos
# ---------------------------------------------------------------------------
class TestPlantillaYPermisos:
    def test_la_plantilla_es_un_csv_que_el_propio_importador_acepta(self, equipo):
        api = cliente_de("super")
        r = api.get(f"{BASE}/clientes/plantilla/")
        assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
        assert "plantilla_clientes.csv" in r["Content-Disposition"]
        contenido = r.content
        assert contenido.startswith(b"\xef\xbb\xbf")  # BOM: Excel respeta las tildes
        informe = subir(api, "clientes", SimpleUploadedFile("p.csv", contenido)).json()
        assert (informe["total"], informe["validas"], informe["con_error"]) == (1, 1, 0)

    def test_la_plantilla_de_proveedores_tambien_se_acepta(self, equipo):
        api = cliente_de("super")
        r = api.get(f"{BASE}/proveedores/plantilla/")
        informe = subir(api, "proveedores", SimpleUploadedFile("p.csv", r.content)).json()
        assert (informe["total"], informe["validas"]) == (1, 1), informe

    def test_importar_exige_su_propio_permiso(self, equipo):
        archivo = csv_(ENCABEZADO + "DNI,45871236,Ana Ruiz,,\n")
        # El vendedor crea clientes de a uno, pero la importación masiva es otro permiso.
        assert subir(cliente_de("vendedor"), "clientes", archivo).status_code == 403
        assert cliente_de("vendedor").get(f"{BASE}/clientes/plantilla/").status_code == 403
        assert subir(cliente_de("cajero"), "clientes", csv_(ENCABEZADO)).status_code == 403
        assert Cliente.objects.sin_ambito().count() == 0


# ---------------------------------------------------------------------------
# Validar (no guarda nada)
# ---------------------------------------------------------------------------
class TestValidar:
    def test_informa_validas_errores_y_repetidos_sin_crear_nada(self, equipo):
        api = cliente_de("super")
        api.post(
            f"{BASE}/clientes/",
            {"tipo_documento": "DNI", "numero_documento": "11111111", "nombre": "Ya existe"},
            format="json",
        )
        contenido = (
            ENCABEZADO
            + "DNI,45871236,Ana Ruiz,987654321,ana@correo.com\n"  # válida
            + "DNI,123,Mal Documento,,\n"  # DNI inválido
            + "RUC,20100000018,Ruc Malo SAC,,\n"  # RUC con dígito verificador malo
            + f"RUC,{RUC},Empresa Buena SAC,,\n"  # válida
            + "DNI,45871236,Ana Repetida,,\n"  # repetida en el archivo
            + "DNI,11111111,Ya Existe Otra Vez,,\n"  # ya existe en el sistema
            + "DNI,22222222,,,\n"  # sin nombre
            + "DNI,33333333,Correo Malo,,no-es-correo\n"  # correo inválido
        )
        r = subir(api, "clientes", csv_(contenido))
        assert r.status_code == 200, r.content
        informe = r.json()
        assert (informe["total"], informe["validas"]) == (8, 2)
        assert (informe["con_error"], informe["repetidos"]) == (4, 2)
        assert {e["fila"] for e in informe["errores"]} == {
            3,
            4,
            8,
            9,
        }  # filas del archivo (1 = encabezado)
        motivos = {x["fila"]: x["motivo"] for x in informe["repetidos_detalle"]}
        assert "fila 2" in motivos[6] and "Ya existe" in motivos[7]
        assert informe["creados"] == 0 and informe["modo"] == "validar"
        assert Cliente.objects.sin_ambito().count() == 1  # solo el que ya existía

    def test_encabezados_con_otros_nombres_tildes_y_columnas_de_mas(self, equipo):
        contenido = (
            "Doc.;DNI/RUC;Razon Social;Celular;E-mail;Observaciones\n"
            ";45871236;Ana Ruiz;987654321;ana@correo.com;vip\n"
        )
        informe = subir(cliente_de("super"), "clientes", csv_(contenido)).json()
        assert informe["validas"] == 1
        assert "Observaciones" in informe["columnas_ignoradas"]

    def test_deduce_el_tipo_y_repone_los_ceros_que_excel_se_come(self, equipo):
        api = cliente_de("super")
        # Excel guarda 04587123 como número 4587123 y el RUC como entero.
        archivo = xlsx(
            [
                ["Número de documento", "Nombre o razón social"],
                [4587123, "Ana con cero inicial"],
                [float(RUC_2), "Empresa por RUC"],
            ]
        )
        assert subir(api, "clientes", archivo, "importar").json()["creados"] == 2
        tipos = dict(Cliente.objects.sin_ambito().values_list("numero_documento", "tipo_documento"))
        assert tipos == {"04587123": "DNI", RUC_2: "RUC"}

    def test_archivos_invalidos_se_rechazan_con_un_mensaje_claro(self, equipo):
        api = cliente_de("super")
        casos = {
            "formato": SimpleUploadedFile("datos.txt", b"hola"),
            "vacio": csv_(""),
            "sin_columnas": csv_("Foo,Bar\n1,2\n"),
            "sin_filas": csv_(ENCABEZADO),
            "xlsx_falso": SimpleUploadedFile("malo.xlsx", b"esto no es un excel"),
        }
        for nombre, archivo in casos.items():
            r = subir(api, "clientes", archivo)
            assert r.status_code == 400, nombre
            assert "archivo" in str(r.json()).lower(), nombre
        assert api.post(f"{BASE}/clientes/importar/", {}, format="multipart").status_code == 400

    def test_los_limites_de_tamano_y_de_filas(self, equipo):
        api = cliente_de("super")
        filas = "".join(f"DNI,{40000000 + i},Persona {i},,\n" for i in range(2001))
        r = subir(api, "clientes", csv_(ENCABEZADO + filas))
        assert r.status_code == 400 and "2000" in str(r.json())
        enorme = SimpleUploadedFile("grande.csv", b"x" * (2 * 1024 * 1024 + 1))
        assert subir(api, "clientes", enorme).status_code == 400

    def test_el_modo_debe_ser_valido(self, equipo):
        r = subir(
            cliente_de("super"), "clientes", csv_(ENCABEZADO + "DNI,45871236,Ana,,\n"), "borrar"
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Importar (crea las válidas)
# ---------------------------------------------------------------------------
class TestImportar:
    def test_crea_las_validas_omite_el_resto_y_deja_un_evento_de_auditoria(self, equipo):
        api = cliente_de("super")
        contenido = (
            ENCABEZADO
            + "DNI,45871236,Ana Ruiz,987654321,ana@correo.com\n"
            + "DNI,123,Mal Documento,,\n"
            + f"RUC,{RUC},Empresa Buena SAC,,\n"
        )
        r = subir(api, "clientes", csv_(contenido), "importar")
        assert r.status_code == 200, r.content
        assert (r.json()["creados"], r.json()["con_error"]) == (2, 1)
        creados = Cliente.objects.sin_ambito().order_by("numero_documento")
        assert creados.count() == 2
        assert all(c.asesor_id == equipo["super"].pk for c in creados)  # quien importa es el asesor
        assert all(c.creado_por_id == equipo["super"].pk for c in creados)
        eventos = AuditoriaEvento.objects.filter(accion="cliente.importado")
        assert eventos.count() == 1  # un solo evento resumen, no uno por fila
        assert eventos[0].detalle["creados"] == 2 and eventos[0].detalle["con_error"] == 1
        assert api.get(f"{BASE}/clientes/").json()["count"] == 2

    def test_importar_dos_veces_el_mismo_archivo_no_duplica(self, equipo):
        api = cliente_de("super")
        contenido = ENCABEZADO + "DNI,45871236,Ana Ruiz,,\n"
        assert subir(api, "clientes", csv_(contenido), "importar").json()["creados"] == 1
        segunda = subir(api, "clientes", csv_(contenido), "importar").json()
        assert (segunda["creados"], segunda["repetidos"]) == (0, 1)
        assert Cliente.objects.sin_ambito().count() == 1

    def test_una_organizacion_no_ve_ni_choca_con_lo_importado_por_otra(self, equipo):
        contenido = ENCABEZADO + "DNI,45871236,Ana Ruiz,,\n"
        subir(cliente_de("super"), "clientes", csv_(contenido), "importar")
        otra = cliente_de("otra_org")
        assert otra.get(f"{BASE}/clientes/").json()["count"] == 0
        # El mismo documento en otra organización es válido, no un repetido.
        assert subir(otra, "clientes", csv_(contenido), "importar").json()["creados"] == 1

    def test_proveedores_con_banco_cuenta_y_productos(self, equipo):
        api = cliente_de("super")
        contenido = (
            "Tipo de documento,Número de documento,Razón social,Contacto,Banco,"
            "Número de cuenta bancaria,Productos de referencia\n"
            f"RUC,{RUC},Distribuidora Andina SAC,Marta Silva,Banco de la Nación,"
            "00-123-456789,Baterías\n"
            f"RUC,{RUC_2},Otra SAC,,,193-1234567,\n"  # cuenta sin banco
        )
        informe = subir(api, "proveedores", csv_(contenido, "prov.csv"), "importar").json()
        assert (informe["creados"], informe["con_error"]) == (1, 1)
        assert "banco" in str(informe["errores"]).lower()
        proveedor = Proveedor.objects.sin_ambito().get()
        assert (proveedor.banco, proveedor.cuenta_bancaria) == ("BANCO_NACION", "00-123-456789")
        assert proveedor.contacto == "Marta Silva" and proveedor.productos_referencia == "Baterías"
        assert AuditoriaEvento.objects.filter(accion="proveedor.importado").exists()

    def test_acepta_excel_y_csv_en_latin1_con_punto_y_coma(self, equipo):
        api = cliente_de("super")
        latin = "Documento;Nombre\n45871236;José Núñez\n".encode("latin-1")
        r = subir(api, "clientes", SimpleUploadedFile("viejo.csv", latin), "importar")
        assert r.json()["creados"] == 1
        assert Cliente.objects.sin_ambito().get().nombre == "José Núñez"
