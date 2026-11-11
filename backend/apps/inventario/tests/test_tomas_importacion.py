"""Toma de inventario físico (entrega 5): importar el conteo desde un Excel."""

import io
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import QuerySet
from django.utils import timezone
from openpyxl import Workbook

from apps.inventario import importacion_toma, tomas
from apps.inventario.exceptions import TomaEstadoInvalido
from apps.inventario.models import (
    ConteoToma,
    DetalleToma,
    EstadoToma,
    MovimientoInventario,
    TurnoToma,
)
from apps.mantenimiento.importacion import ErrorImportacion
from apps.mantenimiento.models import UnidadMedida
from apps.seguridad.tests.conftest import cliente_de

from .ayudas_api import BASE, cuerpo, registrar
from .conftest import comprar, vender

pytestmark = pytest.mark.django_db

D = Decimal
ENCABEZADO = [
    "codigo",
    "prod_descripcion",
    "prod_codigo_barra",
    "tpro_descripcion",
    "mar_descripcion",
    "precio_2",
    "precio_9",
    "precio_1",
    "precio_3",
    "stock",
    "unidad",
    "tipo",
    "prod_stockminimo",
    "STOCK INVENT.",
    "Diferencia",
    "Mensaje",
    "Importe Dife.",
    "FECHA",
    "TURNO",
    "HORA INICIO",
    "HORA FIN",
    "NOTA",
]


def fila(
    *,
    codigo="",
    descripcion="",
    barras="",
    conteo="",
    fecha="",
    turno="",
    inicio="",
    fin="",
    nota="",
):
    """Una fila del Excel de HRB Electro (las demás columnas no se usan)."""
    f = [""] * len(ENCABEZADO)
    f[0], f[1], f[2], f[13] = codigo, descripcion, barras, conteo
    f[17], f[18], f[19], f[20], f[21] = fecha, turno, inicio, fin, nota
    return f


def excel(filas, *, encabezado=ENCABEZADO, nombre="inventario.xlsx", titulo=True):
    libro = Workbook()
    hoja = libro.active
    if titulo:
        hoja.append(
            [
                "10011438534 HRB ELECTRO",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "14/10/2026",
            ]
        )
        hoja.append([])
    hoja.append(encabezado)
    for f in filas:
        hoja.append(f)
    buffer = io.BytesIO()
    libro.save(buffer)
    return SimpleUploadedFile(nombre, buffer.getvalue())


def _abrir(entorno):
    toma = tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk)
    toma = tomas.abrir_toma(toma.pk)
    time.sleep(0.02)
    return toma


def _detalle(toma, producto) -> DetalleToma:
    return DetalleToma.objects.get(toma=toma, producto=producto)


def _conteos():
    return ConteoToma.objects.sin_ambito().count()


@pytest.fixture
def montaje(entorno):
    """Dos productos con stock (uno con código de barras) y la toma ya abierta."""
    adaptador = entorno.producto("ADAPTADOR HDMI HEMBRA HEMBRA", codigo_barras="AD-1005")
    cable = entorno.producto("Cable UTP Cat6")
    for producto in (adaptador, cable):
        comprar(entorno, producto, 25, 10)
    return entorno, adaptador, cable, _abrir(entorno)


# ---------------------------------------------------------------------------
class TestImportar:
    def test_empareja_por_codigo_de_barras_y_por_nombre(self, montaje):
        entorno, adaptador, cable, toma = montaje
        archivo = excel(
            [
                fila(codigo="1890", descripcion="otro nombre", barras="ad-1005", conteo="24"),
                fila(
                    codigo="77",
                    descripcion="  CABLE utp   cat6 ",
                    conteo="25",
                    nota="Rollo completo",
                ),
            ]
        )
        informe = importacion_toma.importar(toma.pk, archivo)
        assert (informe.total, len(informe.items)) == (2, 2)
        assert tomas.TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.EN_CONTEO
        d = _detalle(toma, adaptador)
        assert (d.cantidad_contada, d.numero_conteos, d.diferencia) == (D("24"), 1, D("-1"))
        assert _detalle(toma, cable).nota == "Rollo completo"
        assert ConteoToma.objects.filter(importado=True).count() == 2

    def test_la_revision_no_guarda_nada(self, montaje):
        _, adaptador, _, toma = montaje
        archivo = excel([fila(descripcion="ADAPTADOR HDMI HEMBRA HEMBRA", conteo="24")])
        informe = importacion_toma.revisar(toma.pk, archivo)
        assert len(informe.items) == 1 and _conteos() == 0
        assert _detalle(toma, adaptador).cantidad_contada is None
        assert tomas.TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.ABIERTA

    def test_las_filas_sin_conteo_no_cuentan_y_los_ceros_quedan_pendientes(self, montaje):
        _, adaptador, cable, toma = montaje
        archivo = excel(
            [
                fila(descripcion="ADAPTADOR HDMI HEMBRA HEMBRA", conteo=""),  # sin contar
                fila(descripcion="Cable UTP Cat6", conteo="0"),  # ¿no lo encontró?
            ]
        )
        informe = importacion_toma.importar(toma.pk, archivo)
        assert (informe.sin_conteo, len(informe.items), len(informe.problemas["ceros"])) == (
            1,
            0,
            1,
        )
        assert _detalle(toma, cable).cantidad_contada is None  # sigue pendiente, no es «0»
        # Si se pide, el 0 se importa como «no hay».
        informe = importacion_toma.importar(toma.pk, archivo, importar_ceros=True)
        assert _detalle(toma, cable).cantidad_contada == 0 and len(informe.items) == 1

    def test_cada_motivo_de_omision_se_informa_con_su_fila(self, montaje):
        entorno, adaptador, cable, toma = montaje
        gemelo_a = entorno.producto("Gemelo")
        gemelo_b = entorno.producto("gemelo")  # mismo nombre normalizado
        for producto in (gemelo_a, gemelo_b):
            comprar(entorno, producto, 5, 10)
        sin_stock = entorno.producto("Sin stock")
        toma = _reabrir(entorno, toma)  # ahora los gemelos entran en la toma
        tomas.registrar_conteo(toma_id=toma.pk, producto_id=cable.pk, cantidad=D("25"))
        archivo = excel(
            [
                fila(descripcion="No existe en el sistema", conteo="3"),  # no encontrado
                fila(descripcion="Gemelo", conteo="3"),  # ambiguo
                fila(descripcion="Sin stock", conteo="3"),  # fuera de la toma
                fila(descripcion="Cable UTP Cat6", conteo="3"),  # ya contado
                fila(descripcion="ADAPTADOR HDMI HEMBRA HEMBRA", conteo="3"),  # duplicado (1/2)
                fila(barras="AD-1005", conteo="4"),  # duplicado (2/2)
                fila(descripcion="Gemelo", conteo="abc"),  # inválido
                fila(descripcion="Gemelo", conteo="-2"),  # inválido
            ]
        )
        informe = importacion_toma.revisar(toma.pk, archivo)
        p = informe.problemas
        assert [x["fila"] for x in p["no_encontrados"]] == [4]
        assert [x["fila"] for x in p["ambiguos"]] == [5]
        assert [x["fila"] for x in p["fuera_de_toma"]] == [6]
        assert [x["fila"] for x in p["ya_contados"]] == [7]
        assert sorted(x["fila"] for x in p["duplicados"]) == [8, 9]
        assert [x["fila"] for x in p["invalidos"]] == [10, 11]
        assert informe.items == []
        assert sin_stock.pk not in DetalleToma.objects.filter(toma=toma).values_list(
            "producto_id", flat=True
        )

    def test_una_unidad_por_pieza_rechaza_decimales_y_los_metros_los_aceptan(self, entorno):
        metro = UnidadMedida.objects.sin_ambito().create(
            organizacion=entorno.e.org_a, nombre="Metro", abreviatura="M", codigo_sunat="MTR"
        )
        pieza, cable = entorno.producto("Pieza"), entorno.producto("Cable en metros")
        cable.unidad = metro
        cable.save()
        for producto in (pieza, cable):
            comprar(entorno, producto, 100, 1)
        toma = _abrir(entorno)
        informe = importacion_toma.importar(
            toma.pk,
            excel(
                [
                    fila(descripcion="Pieza", conteo="2.5"),
                    fila(descripcion="Cable en metros", conteo="99,5"),
                ]
            ),
        )
        assert [x["fila"] for x in informe.problemas["invalidos"]] == [4]
        assert _detalle(toma, cable).cantidad_contada == D("99.5")

    def test_el_modo_codigo_empareja_por_el_codigo_sin_ceros_de_la_izquierda(self, montaje):
        _, adaptador, cable, toma = montaje
        numero = str(int(cable.codigo))  # Excel pierde los ceros: 000002 → 2
        archivo = excel([fila(codigo=numero, descripcion="no coincide", conteo="25")])
        assert (
            importacion_toma.revisar(toma.pk, archivo).items == []
        )  # automático: no hay coincidencia
        informe = importacion_toma.revisar(toma.pk, archivo, modo="codigo")
        assert [i.detalle.producto_id for i in informe.items] == [cable.pk]

    def test_un_conteo_con_diferencia_importante_queda_para_recontar(self, montaje):
        _, _, cable, toma = montaje
        importacion_toma.importar(toma.pk, excel([fila(descripcion="Cable UTP Cat6", conteo="10")]))
        assert _detalle(toma, cable).requiere_reconteo is True  # 15 de 25: 60 %

    def test_volver_a_importar_no_duplica_nada(self, montaje):
        _, _, _, toma = montaje
        archivo = excel([fila(descripcion="Cable UTP Cat6", conteo="25")])
        importacion_toma.importar(toma.pk, archivo)
        segundo = importacion_toma.importar(
            toma.pk, excel([fila(descripcion="Cable UTP Cat6", conteo="25")])
        )
        assert segundo.items == [] and len(segundo.problemas["ya_contados"]) == 1
        assert _conteos() == 1

    def test_todo_o_nada(self, montaje, monkeypatch):
        _, adaptador, cable, toma = montaje

        def falla(*args, **kwargs):
            raise RuntimeError("falla a medias")

        monkeypatch.setattr(tomas, "_poner_conteo", falla)
        archivo = excel([fila(descripcion="Cable UTP Cat6", conteo="25")])
        with pytest.raises(RuntimeError):
            importacion_toma.importar(toma.pk, archivo)
        assert _conteos() == 0 and _detalle(toma, cable).cantidad_contada is None
        assert tomas.TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.ABIERTA


class TestConLaFechaDelConteo:
    def test_sin_fecha_se_asume_que_se_conto_al_corte(self, montaje):
        _, _, cable, toma = montaje
        importacion_toma.importar(toma.pk, excel([fila(descripcion="Cable UTP Cat6", conteo="25")]))
        corte = tomas.TomaInventario.objects.get(pk=toma.pk).fecha_corte
        assert _detalle(toma, cable).contado_en == corte

    def test_un_conteo_de_dias_atras_descuenta_lo_que_se_vendio_despues(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        # La compra se registró hace 5 días; el conteo fue ayer; la venta de 2 se hizo después.
        hace_cinco = timezone.now() - timedelta(days=5)
        QuerySet.update(MovimientoInventario._base_manager.all(), creado_en=hace_cinco)
        vender(entorno, cemento, 2)  # el sistema baja a 8
        time.sleep(0.02)
        toma = _abrir(entorno)  # corte: stock 8
        ayer = (timezone.localdate() - timedelta(days=1)).strftime("%d/%m/%Y")
        archivo = excel(
            [
                fila(
                    descripcion=cemento.nombre,
                    conteo="10",
                    fecha=ayer,
                    turno="TARDE",
                    inicio="10:00",
                    fin="12:30",
                )
            ]
        )
        importacion_toma.importar(toma.pk, archivo)
        d = _detalle(toma, cemento)
        # Ayer había 10 y el conteo dio 10: no es un sobrante de 2 contra el stock de hoy.
        assert (d.diferencia, d.resultado, d.requiere_reconteo) == (D("0"), "CONFORME", False)
        assert timezone.localtime(d.contado_en).strftime("%d/%m/%Y %H:%M") == f"{ayer} 12:30"
        # Y al aprobar tampoco se ajusta nada.
        tomas.cerrar_toma(toma.pk, confirmar_pendientes=True)
        _, movimientos = tomas.aprobar_toma(toma.pk)
        assert movimientos == []

    def test_netos_antes_del_corte_tienen_el_signo_cambiado(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        time.sleep(0.02)
        antes = timezone.now()
        time.sleep(0.02)
        vender(entorno, cemento, 2)
        time.sleep(0.02)
        toma = _abrir(entorno)
        # Contado antes de la venta: el sistema debía tener 8 + 2.
        assert tomas.netos_hasta(toma, {cemento.pk: antes}) == {cemento.pk: D("2")}
        # Contado en el corte o después sin movimientos: nada que corregir.
        assert tomas.netos_hasta(toma, {cemento.pk: toma.fecha_corte}) == {}

    def test_una_fecha_futura_o_mal_escrita_se_rechaza_por_fila(self, montaje):
        _, _, _, toma = montaje
        manana = (timezone.localdate() + timedelta(days=1)).strftime("%d/%m/%Y")
        archivo = excel(
            [
                fila(descripcion="Cable UTP Cat6", conteo="25", fecha=manana, fin="10:00"),
                fila(descripcion="ADAPTADOR HDMI HEMBRA HEMBRA", conteo="25", fecha="31/02/2026"),
            ]
        )
        informe = importacion_toma.revisar(toma.pk, archivo)
        assert [x["fila"] for x in informe.problemas["invalidos"]] == [4, 5]

    def test_se_crea_un_turno_por_fecha_turno_y_horario(self, montaje):
        entorno, adaptador, cable, toma = montaje
        otro = entorno.producto("Tercero")
        comprar(entorno, otro, 5, 10)
        toma = _reabrir(entorno, toma)
        ayer = (timezone.localdate() - timedelta(days=1)).strftime("%d/%m/%Y")
        antes = (timezone.localdate() - timedelta(days=2)).strftime("%d/%m/%Y")
        archivo = excel(
            [
                fila(
                    descripcion=cable.nombre,
                    conteo="25",
                    fecha=ayer,
                    turno="TARDE",
                    inicio="16:00",
                    fin="19:00",
                ),
                fila(
                    descripcion=adaptador.nombre,
                    conteo="25",
                    fecha=ayer,
                    turno="Tarde",
                    inicio="16:00",
                    fin="19:00",
                ),
                fila(
                    descripcion=otro.nombre,
                    conteo="5",
                    fecha=antes,
                    turno="MAÑANA Y TARDE",
                    inicio="10:15",
                    fin="19:00",
                ),
            ]
        )
        importacion_toma.importar(toma.pk, archivo)
        turnos = list(TurnoToma.objects.filter(toma=toma).order_by("fecha"))
        assert [t.turno for t in turnos] == ["MANANA_Y_TARDE", "TARDE"]
        assert ConteoToma.objects.filter(turno=turnos[1]).count() == 2
        assert all(t.equipo == "Importado del Excel" for t in turnos)


def _reabrir(entorno, toma):
    """Anula la toma y abre otra (para que incluya productos que entraron después)."""
    tomas.anular_toma(toma.pk, motivo="Se agregaron productos")
    return _abrir(entorno)


# ---------------------------------------------------------------------------
class TestArchivoYEstado:
    def test_solo_se_importa_en_conteo(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        archivo = lambda: excel([fila(descripcion=cemento.nombre, conteo="10")])  # noqa: E731
        borrador = tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk)
        for funcion in (importacion_toma.revisar, importacion_toma.importar):
            with pytest.raises(TomaEstadoInvalido):
                funcion(borrador.pk, archivo())
        tomas.abrir_toma(borrador.pk)
        tomas.registrar_conteo(toma_id=borrador.pk, producto_id=cemento.pk, cantidad=D("5"))
        tomas.iniciar_reconteo(borrador.pk)
        with pytest.raises(TomaEstadoInvalido):  # en reconteo solo se recuenta a mano
            importacion_toma.importar(borrador.pk, archivo())

    def test_archivos_que_no_sirven(self, montaje):
        _, _, _, toma = montaje
        casos = {
            "csv": SimpleUploadedFile("conteo.csv", b"a,b\n1,2\n"),
            "sin encabezado": excel([["x", "y"]], encabezado=["algo", "otra cosa"]),
            "sin conteo": excel([], encabezado=["prod_descripcion", "stock"]),
            "vacío": excel([]),
            "pesado": SimpleUploadedFile("grande.xlsx", b"0" * (2 * 1024 * 1024 + 1)),
            "no es excel": SimpleUploadedFile("falso.xlsx", b"esto no es un zip"),
        }
        for nombre, archivo in casos.items():
            with pytest.raises(ErrorImportacion):
                importacion_toma.revisar(toma.pk, archivo)
            assert nombre  # (para que el fallo diga qué caso fue)

    def test_un_texto_que_parece_formula_es_solo_texto(self, montaje):
        _, _, _, toma = montaje
        informe = importacion_toma.revisar(
            toma.pk, excel([fila(descripcion='=HYPERLINK("http://x.test")', conteo="3")])
        )
        assert [x["fila"] for x in informe.problemas["no_encontrados"]] == [4]

    def test_el_encabezado_se_encuentra_aunque_haya_titulos_arriba_y_columnas_de_mas(self, montaje):
        _, _, _, toma = montaje
        informe = importacion_toma.revisar(
            toma.pk, excel([fila(descripcion="Cable UTP Cat6", conteo="25")])
        )
        assert "tpro_descripcion" in informe.ignoradas and informe.total == 1


# ---------------------------------------------------------------------------
TOMAS = f"{BASE}/tomas"


def _post(api, toma_id, archivo, **extra):
    return api.post(
        f"{TOMAS}/{toma_id}/importar/", {"archivo": archivo, **extra}, format="multipart"
    )


class TestApi:
    @pytest.fixture
    def abierta(self, mundo):
        cemento = mundo.producto()
        api = cliente_de("almacenero")
        assert registrar(api, cuerpo(mundo, cemento)).status_code == 201
        toma = api.post(
            f"{TOMAS}/", {"empresa": mundo.e1.pk, "almacen": mundo.alm[1].pk}, format="json"
        ).json()
        assert api.post(f"{TOMAS}/{toma['id']}/abrir/").status_code == 200
        return cemento, toma

    def test_revisar_e_importar_en_dos_pasos(self, mundo, abierta):
        cemento, toma = abierta
        api = cliente_de("almacenero")
        archivo = lambda: excel([fila(descripcion=cemento.nombre, conteo="9")])  # noqa: E731
        r = _post(api, toma["id"], archivo())
        assert r.status_code == 200, r.content
        datos = r.json()
        assert (datos["accion"], datos["a_importar"], datos["importados"]) == ("revisar", 1, 0)
        assert _conteos() == 0
        r = _post(api, toma["id"], archivo(), accion="importar")
        assert r.status_code == 200 and r.json()["importados"] == 1
        assert api.get(f"{TOMAS}/{toma['id']}/").json()["estado"] == "EN_CONTEO"
        # El informe de un segundo intento explica por qué no se repite.
        otra = _post(api, toma["id"], archivo(), accion="importar").json()
        assert otra["importados"] == 0 and otra["categorias"]["ya_contados"]["cantidad"] == 1

    def test_el_informe_no_revela_el_stock_del_sistema(self, mundo, abierta):
        cemento, toma = abierta
        r = _post(
            cliente_de("almacenero"),
            toma["id"],
            excel([fila(descripcion=cemento.nombre, conteo="9")]),
        )
        assert set(r.json()) == {
            "total",
            "con_conteo",
            "sin_conteo",
            "a_importar",
            "turnos",
            "columnas_ignoradas",
            "categorias",
            "accion",
            "importados",
        }  # solo cuentas y motivos de lo que trae el archivo, nunca el stock del sistema

    def test_sin_permiso_de_gestionar_no_se_importa(self, mundo, abierta):
        cemento, toma = abierta
        archivo = excel([fila(descripcion=cemento.nombre, conteo="9")])
        assert _post(cliente_de("vendedor"), toma["id"], archivo).status_code == 403
        assert _conteos() == 0

    def test_archivo_invalido_es_un_error_claro(self, mundo, abierta):
        _, toma = abierta
        r = _post(cliente_de("almacenero"), toma["id"], SimpleUploadedFile("a.csv", b"x"))
        assert r.status_code == 400 and "archivo" in str(r.json()).lower()

    def test_una_toma_en_borrador_responde_conflicto(self, mundo):
        api = cliente_de("super")
        toma = api.post(
            f"{TOMAS}/", {"empresa": mundo.e1.pk, "almacen": mundo.alm[1].pk}, format="json"
        ).json()
        r = _post(api, toma["id"], excel([fila(descripcion="x", conteo="1")]))
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "toma_estado_invalido"
