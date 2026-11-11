"""API de cotizaciones: permisos, flujo completo, importación desde Excel y adjudicación."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from openpyxl import load_workbook

from apps.compras.models import OrdenCompra, RespuestaCotizacion
from apps.mantenimiento.models import Proveedor
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)
from .test_api import clave, datos  # noqa: F401

pytestmark = pytest.mark.django_db

BASE = "/api/v1/compras/cotizaciones"


@pytest.fixture
def otro(datos):
    """Un segundo proveedor, para tener con quién comparar."""
    return Proveedor.objects.sin_ambito().create(
        organizacion=datos.mundo.e.org_a,
        tipo_documento="RUC",
        numero_documento=ruc_valido("2010000031"),
        nombre="Ferretería Norte",
    )


def cuerpo_cotizacion(datos, otro, **extra):
    p1, p2 = datos.mundo.producto("Cemento"), datos.mundo.producto("Fierro")
    base = {
        "empresa": datos.mundo.e1.pk,
        "almacen": datos.mundo.alm[1].pk,
        "fecha": timezone.localdate().isoformat(),
        "proveedores": [datos.proveedor.pk, otro.pk],
        "lineas": [
            {"producto": p1.pk, "cantidad": "10"},
            {"producto": p2.pk, "cantidad": "5"},
        ],
    }
    return {**base, **extra}


def crear(datos, otro, usuario="almacenero", llave=None, **extra):
    return cliente_de(usuario).post(
        f"{BASE}/",
        cuerpo_cotizacion(datos, otro, **extra),
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or clave(),
    )


def nueva(datos, otro, usuario="almacenero", **extra):
    r = crear(datos, otro, usuario, **extra)
    assert r.status_code == 201, r.content
    return r.json()


def responder(usuario, sid, cuerpo):
    return cliente_de(usuario).post(f"{BASE}/{sid}/respuesta/", cuerpo, format="json")


def respuesta_de(c, proveedor_id):
    return next(p for p in c["proveedores"] if p["proveedor"] == proveedor_id)["respuesta"]


def precios_de(c, *valores):
    return [
        {"linea": ln["id"], "precio_unitario": v}
        for ln, v in zip(c["lineas"], valores, strict=True)
        if v is not None
    ]


class TestPermisos:
    def test_el_almacenero_crea_y_el_vendedor_ni_la_ve(self, datos, otro):
        assert crear(datos, otro, "almacenero").status_code == 201
        assert crear(datos, otro, "vendedor").status_code == 403
        r = cliente_de("vendedor").get(f"{BASE}/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 403

    def test_el_contador_ve_pero_no_crea(self, datos, otro):
        assert crear(datos, otro, "contador").status_code == 403
        r = cliente_de("contador").get(f"{BASE}/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 200

    def test_el_almacenero_no_adjudica(self, datos, otro):
        c = nueva(datos, otro)
        a = respuesta_de(c, datos.proveedor.pk)
        responder("almacenero", c["id"], {"respuesta": a, "precios": precios_de(c, "10", "20")})
        r = cliente_de("almacenero").post(
            f"{BASE}/{c['id']}/adjudicar/",
            {"asignaciones": [{"linea": c["lineas"][0]["id"], "respuesta": a}]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=clave(),
        )
        assert r.status_code == 403

    def test_otra_organizacion_no_la_ve(self, datos, otro):
        c = nueva(datos, otro)
        assert cliente_de("otra_org").get(f"{BASE}/{c['id']}/").status_code in (403, 404)


class TestCrear:
    def test_crea_en_borrador_con_sus_proveedores_y_el_comparativo_vacio(self, datos, otro):
        c = nueva(datos, otro)
        assert (c["codigo"], c["estado"], c["moneda"]) == ("COT-000001", "BORRADOR", "PEN")
        assert len(c["lineas"]) == 2 and len(c["proveedores"]) == 2
        assert c["lineas"][0]["cantidad"] == "10.000"
        assert c["comparativo"]["mejor_total"] is None
        assert {p["estado"] for p in c["proveedores"]} == {"PENDIENTE"}

    def test_reintento_con_la_misma_clave_no_duplica(self, datos, otro):
        llave = clave()
        p = datos.mundo.producto("Unico")
        extra = {"lineas": [{"producto": p.pk, "cantidad": "1"}]}
        a = crear(datos, otro, llave=llave, **extra)
        b = crear(datos, otro, llave=llave, **extra)
        assert (a.status_code, b.status_code) == (201, 201)
        assert b.json() == a.json() and b["Idempotency-Replayed"] == "true"

    def test_se_lista_con_conteos_y_filtros(self, datos, otro):
        c = nueva(datos, otro)
        r = cliente_de("almacenero").get(
            f"{BASE}/", {"empresa": datos.mundo.e1.pk, "q": "COT-000001"}
        )
        assert r.status_code == 200
        fila = r.json()["results"][0]
        assert (fila["id"], fila["lineas"], fila["proveedores"], fila["respondidas"]) == (
            c["id"],
            2,
            2,
            0,
        )
        vacio = cliente_de("almacenero").get(
            f"{BASE}/", {"empresa": datos.mundo.e1.pk, "estado": "ADJUDICADA"}
        )
        assert vacio.json()["results"] == []

    def test_un_producto_repetido_da_400(self, datos, otro):
        p = datos.mundo.producto("Repetido")
        r = crear(
            datos,
            otro,
            lineas=[{"producto": p.pk, "cantidad": "1"}, {"producto": p.pk, "cantidad": "2"}],
        )
        assert r.status_code == 400

    def test_se_edita_en_borrador(self, datos, otro):
        c = nueva(datos, otro)
        cuerpo = cuerpo_cotizacion(datos, otro, proveedores=[datos.proveedor.pk])
        cuerpo.pop("empresa")
        r = cliente_de("almacenero").post(f"{BASE}/{c['id']}/editar/", cuerpo, format="json")
        assert r.status_code == 200, r.content
        assert len(r.json()["proveedores"]) == 1

    def test_se_suma_y_se_quita_un_proveedor(self, datos, otro):
        c = nueva(datos, otro, proveedores=[datos.proveedor.pk])
        api = cliente_de("almacenero")
        r = api.post(f"{BASE}/{c['id']}/proveedores/", {"proveedor": otro.pk}, format="json")
        assert r.status_code == 200 and len(r.json()["proveedores"]) == 2
        quitar = respuesta_de(r.json(), otro.pk)
        r = api.post(f"{BASE}/{c['id']}/quitar-proveedor/", {"respuesta": quitar}, format="json")
        assert r.status_code == 200 and len(r.json()["proveedores"]) == 1


class TestResponder:
    def test_a_mano_abre_la_cotizacion_y_arma_el_comparativo(self, datos, otro):
        c = nueva(datos, otro)
        a, b = respuesta_de(c, datos.proveedor.pk), respuesta_de(c, otro.pk)
        r = responder(
            "almacenero",
            c["id"],
            {"respuesta": a, "precios": precios_de(c, "10", "20"), "plazo_entrega_dias": 2},
        )
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "ABIERTA"
        r = responder("almacenero", c["id"], {"respuesta": b, "precios": precios_de(c, "9", "25")})
        comp = r.json()["comparativo"]
        assert comp["mejor_total"] == "200.00"
        assert [p["total"] for p in comp["proveedores"]] == ["200.00", "215.00"]
        assert comp["lineas"][0]["mejor_precio"] == "9.000000"
        assert comp["lineas"][0]["ofertas"][1]["es_mejor"] is True

    def test_un_precio_con_mas_de_seis_decimales_da_400(self, datos, otro):
        c = nueva(datos, otro)
        a = respuesta_de(c, datos.proveedor.pk)
        r = responder(
            "almacenero", c["id"], {"respuesta": a, "precios": precios_de(c, "1.1234567", "2")}
        )
        assert r.status_code == 400

    def test_un_proveedor_que_no_cotiza(self, datos, otro):
        c = nueva(datos, otro)
        b = respuesta_de(c, otro.pk)
        r = cliente_de("almacenero").post(
            f"{BASE}/{c['id']}/declinar/", {"respuesta": b, "motivo": "Sin stock"}, format="json"
        )
        assert r.status_code == 200
        assert (
            next(p for p in r.json()["proveedores"] if p["respuesta"] == b)["estado"] == "DECLINADA"
        )

    def test_la_respuesta_de_otra_cotizacion_da_400(self, datos, otro):
        c, otra = nueva(datos, otro), nueva(datos, otro)
        ajena = respuesta_de(otra, datos.proveedor.pk)
        r = responder(
            "almacenero", c["id"], {"respuesta": ajena, "precios": precios_de(c, "1", "1")}
        )
        assert r.status_code == 400


def excel(respuesta_json, c, usuario="almacenero"):
    r = cliente_de(usuario).get(f"{BASE}/{c['id']}/plantilla/", {"respuesta": respuesta_json})
    assert r.status_code == 200, r.content
    return r


def con_precios(contenido: bytes, valores: dict, condiciones: dict | None = None) -> bytes:
    """Abre la plantilla descargada, llena precios por N° y condiciones, y la devuelve."""
    libro = load_workbook(io.BytesIO(contenido))
    hoja = libro.active
    for fila in hoja.iter_rows():
        rotulo = str(fila[0].value or "")
        if condiciones:
            for etiqueta, valor in condiciones.items():
                if rotulo.startswith(etiqueta):
                    fila[1].value = valor
        if isinstance(fila[0].value, int) and fila[0].value in valores:
            fila[5].value = valores[fila[0].value]
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def subir(usuario, c, respuesta, contenido, accion="revisar", nombre="resp.xlsx"):
    return cliente_de(usuario).post(
        f"{BASE}/{c['id']}/importar/",
        {
            "respuesta": respuesta,
            "accion": accion,
            "archivo": SimpleUploadedFile(
                nombre, contenido, content_type="application/octet-stream"
            ),
        },
        format="multipart",
    )


class TestImportar:
    def test_la_plantilla_trae_los_productos_y_cantidades(self, datos, otro):
        c = nueva(datos, otro)
        r = excel(respuesta_de(c, datos.proveedor.pk), c)
        assert r["Content-Type"].startswith("application/vnd.openxmlformats")
        hoja = load_workbook(io.BytesIO(r.content)).active
        filas = [[x.value for x in f] for f in hoja.iter_rows() if isinstance(f[0].value, int)]
        assert [(f[0], f[2], f[4]) for f in filas] == [(1, "Cemento", 10), (2, "Fierro", 5)]

    def test_revisar_no_guarda_y_aplicar_si(self, datos, otro):
        c = nueva(datos, otro)
        a = respuesta_de(c, datos.proveedor.pk)
        contenido = con_precios(
            excel(a, c).content,
            {1: 10.5, 2: 20},
            {"Forma de pago": "Crédito", "Plazo de crédito": 30, "Plazo de entrega": 4},
        )
        r = subir("almacenero", c, a, contenido, "revisar")
        assert r.status_code == 200, r.content
        informe = r.json()["informe"]
        assert (informe["cotizados"], informe["errores"], informe["se_puede_aplicar"]) == (
            2,
            0,
            True,
        )
        assert informe["condiciones"]["forma_pago"] == "CREDITO"
        assert (
            RespuestaCotizacion.objects.sin_ambito().get(pk=a).estado == "PENDIENTE"
        )  # nada se guardó

        r = subir("almacenero", c, a, contenido, "aplicar")
        assert r.status_code == 200, r.content
        cot = r.json()["cotizacion"]
        assert cot["estado"] == "ABIERTA"
        fila = next(p for p in cot["comparativo"]["proveedores"] if p["respuesta"] == a)
        assert (
            fila["origen"],
            fila["forma_pago"],
            fila["plazo_dias"],
            fila["plazo_entrega_dias"],
        ) == (
            "ARCHIVO",
            "CREDITO",
            30,
            4,
        )
        assert fila["total"] == "205.00"  # 10,5*10 + 20*5

    def test_un_precio_vacio_es_no_cotiza_y_un_error_bloquea_todo(self, datos, otro):
        c = nueva(datos, otro)
        a = respuesta_de(c, datos.proveedor.pk)
        base = excel(a, c).content
        r = subir("almacenero", c, a, con_precios(base, {1: 10}), "revisar")
        informe = r.json()["informe"]
        assert (informe["cotizados"], informe["sin_precio"], informe["se_puede_aplicar"]) == (
            1,
            1,
            True,
        )

        malo = con_precios(base, {1: "abc", 2: 5})
        r = subir("almacenero", c, a, malo, "revisar")
        assert (
            r.json()["informe"]["errores"] == 1 and r.json()["informe"]["se_puede_aplicar"] is False
        )
        r = subir("almacenero", c, a, malo, "aplicar")
        assert r.status_code == 400
        assert RespuestaCotizacion.objects.sin_ambito().get(pk=a).estado == "PENDIENTE"

    def test_un_archivo_de_otra_cotizacion_se_detecta_por_el_codigo(self, datos, otro):
        c = nueva(datos, otro)
        a = respuesta_de(c, datos.proveedor.pk)
        libro = load_workbook(io.BytesIO(excel(a, c).content))
        hoja = libro.active
        for fila in hoja.iter_rows():
            if fila[0].value == 1:
                fila[1].value = "OTRO-CODIGO"
                fila[5].value = 10
        salida = io.BytesIO()
        libro.save(salida)
        r = subir("almacenero", c, a, salida.getvalue(), "revisar")
        assert r.json()["informe"]["errores"] == 1

    def test_solo_se_aceptan_archivos_xlsx(self, datos, otro):
        c = nueva(datos, otro)
        a = respuesta_de(c, datos.proveedor.pk)
        r = subir("almacenero", c, a, b"no es excel", "revisar", nombre="resp.txt")
        assert r.status_code == 400
        r = subir("almacenero", c, a, b"no es excel", "revisar", nombre="resp.xlsx")
        assert r.status_code == 400

    def test_el_contador_no_importa(self, datos, otro):
        c = nueva(datos, otro)
        a = respuesta_de(c, datos.proveedor.pk)
        r = subir("contador", c, a, excel(a, c).content, "revisar")
        assert r.status_code == 403


class TestAdjudicar:
    def _lista(self, datos, otro):
        c = nueva(datos, otro)
        a, b = respuesta_de(c, datos.proveedor.pk), respuesta_de(c, otro.pk)
        responder("almacenero", c["id"], {"respuesta": a, "precios": precios_de(c, "10", "20")})
        responder("almacenero", c["id"], {"respuesta": b, "precios": precios_de(c, "9", "25")})
        return c, a, b

    def test_el_administrador_divide_entre_proveedores_y_se_crean_dos_ordenes(self, datos, otro):
        c, a, b = self._lista(datos, otro)
        l1, l2 = (ln["id"] for ln in c["lineas"])
        r = cliente_de("admin").post(
            f"{BASE}/{c['id']}/adjudicar/",
            {
                "asignaciones": [
                    {"linea": l1, "respuesta": b},
                    {"linea": l2, "respuesta": a, "cantidad": "3"},
                ]
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=clave(),
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "ADJUDICADA"
        assert d["comparativo"]["ahorro"] == "25.00"  # (10-9)*10 + (25-20)*3
        ordenes = OrdenCompra.objects.sin_ambito().filter(cotizacion_id=c["id"])
        assert ordenes.count() == 2
        assert all(o.estado == "BORRADOR" for o in ordenes)
        assert {p["orden_codigo"] for p in d["proveedores"]} == {"OC-000001", "OC-000002"}

    def test_el_reintento_no_crea_las_ordenes_dos_veces(self, datos, otro):
        c, a, _b = self._lista(datos, otro)
        cuerpo = {"asignaciones": [{"linea": c["lineas"][0]["id"], "respuesta": a}]}
        llave = clave()
        api = cliente_de("admin")
        r1 = api.post(
            f"{BASE}/{c['id']}/adjudicar/", cuerpo, format="json", HTTP_IDEMPOTENCY_KEY=llave
        )
        r2 = api.post(
            f"{BASE}/{c['id']}/adjudicar/", cuerpo, format="json", HTTP_IDEMPOTENCY_KEY=llave
        )
        assert (r1.status_code, r2.status_code) == (200, 200)
        assert OrdenCompra.objects.sin_ambito().filter(cotizacion_id=c["id"]).count() == 1

    def test_una_adjudicada_no_se_anula(self, datos, otro):
        c, a, _b = self._lista(datos, otro)
        cliente_de("admin").post(
            f"{BASE}/{c['id']}/adjudicar/",
            {"asignaciones": [{"linea": c["lineas"][0]["id"], "respuesta": a}]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=clave(),
        )
        r = cliente_de("admin").post(
            f"{BASE}/{c['id']}/anular/", {"motivo": "Ya no"}, format="json"
        )
        assert r.status_code == 409

    def test_se_anula_con_motivo(self, datos, otro):
        c = nueva(datos, otro)
        api = cliente_de("almacenero")
        assert (
            api.post(f"{BASE}/{c['id']}/anular/", {"motivo": ""}, format="json").status_code == 400
        )
        r = api.post(f"{BASE}/{c['id']}/anular/", {"motivo": "Ya no se necesita"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "ANULADA"
