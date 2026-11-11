"""«Arma tu PC»: configuración, reglas de compatibilidad y API pública."""

# ruff: noqa: F811

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import Categoria
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import armador
from apps.tienda.models import ConfiguracionArmador

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/armador/"
PUBLICO = "/api/v1/tienda/armador"
VALIDAR = "/api/v1/tienda/armador/validar"
OPCIONES = "/api/v1/tienda/armador/opciones"
ESPACIOS = [
    "procesador",
    "placa",
    "ram",
    "almacenamiento",
    "video",
    "fuente",
    "gabinete",
    "refrigeracion",
]


def anonimo() -> APIClient:
    return APIClient(HTTP_X_REQUESTED_WITH="tienda")


def contexto(tienda):
    e = tienda.e
    establecer_contexto(tienda.org.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)


@pytest.fixture
def pc(tienda):
    """Una categoría por espacio, el armador configurado y activo, y un helper para crear piezas."""
    contexto(tienda)
    categorias = {
        esp: Categoria.objects.sin_ambito().create(
            organizacion=tienda.org, familia=tienda.familia, nombre=f"Cat {esp}"
        )
        for esp in ESPACIOS
    }
    for esp, cat in categorias.items():
        from apps.mantenimiento.especificaciones import generar_slug  # noqa: F401

        Categoria.objects.sin_ambito().filter(pk=cat.pk).update(slug=f"cat-{esp}")
    ConfiguracionArmador.objects.sin_ambito().create(
        organizacion=tienda.org,
        activo=True,
        espacios=[{"clave": e, "categorias": [categorias[e].pk]} for e in ESPACIOS],
    )
    cache.clear()

    def pieza(espacio, nombre, precio=100, stock=5, **specs):
        contexto(tienda)  # cada llamada a la API limpia el contexto de la prueba
        return tienda.publicar(
            nombre,
            categoria=categorias[espacio],
            precio=precio,
            stock=stock,
            especificaciones=specs,
        )

    tienda.categorias = categorias
    tienda.pieza = pieza
    return tienda


def lineas(*pares):
    return {"lineas": [{"producto": p.pk, "cantidad": c} for p, c in pares]}


def validar(*pares):
    r = anonimo().post(VALIDAR, lineas(*pares), format="json")
    assert r.status_code == 200, r.content
    return r.json()


def estado(resultado, regla, indice=0):
    return [c for c in resultado["compatibilidades"] if c["regla"] == regla][indice]["estado"]


class TestReglas:
    def test_socket_igual_es_compatible_y_distinto_no(self, pc):
        cpu = pc.pieza("procesador", "Ryzen 5", socket="AM5")
        placa_am5 = pc.pieza("placa", "Placa B650", socket="AM5")
        placa_lga = pc.pieza("placa", "Placa Z790", socket="LGA1700")
        assert estado(validar((cpu, 1), (placa_am5, 1)), "socket") == "COMPATIBLE"
        r = validar((cpu, 1), (placa_lga, 1))
        assert estado(r, "socket") == "INCOMPATIBLE"
        assert r["puede_agregar"] is False and r["incompatibles"] == 1

    def test_sin_dato_no_se_afirma_compatibilidad(self, pc):
        cpu = pc.pieza("procesador", "Ryzen", socket="AM5")
        placa = pc.pieza("placa", "Placa sin socket")
        r = validar((cpu, 1), (placa, 1))
        assert estado(r, "socket") == "NO_VERIFICABLE"
        assert "No pudimos verificar" in r["compatibilidades"][0]["mensaje"]
        assert r["puede_agregar"] is True  # no verificable avisa pero no bloquea

    def test_normaliza_mayusculas_espacios_y_guiones(self, pc):
        placa = pc.pieza("placa", "Placa", **{"factor-de-forma": "Micro-ATX"})
        caja = pc.pieza(
            "gabinete", "Caja", **{"factores-de-forma-compatibles": "ATX, micro atx, Mini-ITX"}
        )
        assert estado(validar((placa, 1), (caja, 1)), "factor_forma") == "COMPATIBLE"
        atx = pc.pieza("placa", "Placa ATX", **{"factor-de-forma": "ATX"})
        mini = pc.pieza("gabinete", "Caja mini", **{"factores-de-forma-compatibles": "Mini-ITX"})
        assert estado(validar((atx, 1), (mini, 1)), "factor_forma") == "INCOMPATIBLE"

    def test_tipo_de_memoria_y_sodimm(self, pc):
        placa = pc.pieza("placa", "Placa", **{"tipo-de-ram": "DDR5"})
        ddr5 = pc.pieza("ram", "RAM DDR5", tipo="DDR5", formato="DIMM (PC de escritorio)")
        ddr4 = pc.pieza("ram", "RAM DDR4", tipo="DDR4", formato="DIMM (PC de escritorio)")
        laptop = pc.pieza("ram", "RAM laptop", tipo="DDR5", formato="SODIMM (laptop)")
        assert estado(validar((placa, 1), (ddr5, 1)), "tipo_ram") == "COMPATIBLE"
        assert estado(validar((placa, 1), (ddr4, 1)), "tipo_ram") == "INCOMPATIBLE"
        r = validar((laptop, 1))
        assert estado(r, "ram_escritorio") == "INCOMPATIBLE" and r["puede_agregar"] is False

    def test_ranuras_y_maximo_de_memoria(self, pc):
        placa = pc.pieza("placa", "Placa", **{"ranuras-de-memoria": 2, "maximo-de-memoria": 64})
        kit = pc.pieza("ram", "Kit 2x16", capacidad=32, **{"numero-de-modulos": "2 módulos (kit)"})
        r = validar((placa, 1), (kit, 1))
        assert estado(r, "ram_ranuras") == "COMPATIBLE" and estado(r, "ram_maximo") == "COMPATIBLE"
        r = validar((placa, 1), (kit, 2))  # 4 módulos y 64 GB
        assert (
            estado(r, "ram_ranuras") == "INCOMPATIBLE" and estado(r, "ram_maximo") == "COMPATIBLE"
        )
        r = validar((placa, 1), (kit, 3))
        assert estado(r, "ram_maximo") == "INCOMPATIBLE"

    def test_cooler_largo_y_altura(self, pc):
        cpu = pc.pieza("procesador", "CPU", socket="AM5")
        aire = pc.pieza(
            "refrigeracion", "Cooler", **{"sockets-compatibles": "AM4, AM5", "altura": 160}
        )
        caja = pc.pieza(
            "gabinete",
            "Caja",
            **{"altura-maxima-del-cooler": 150, "largo-maximo-de-tarjeta-de-video": 300},
        )
        gpu = pc.pieza("video", "GPU", largo=320)
        r = validar((cpu, 1), (aire, 1), (caja, 1), (gpu, 1))
        assert estado(r, "cooler_socket") == "COMPATIBLE"
        assert estado(r, "cooler_altura") == "INCOMPATIBLE"
        assert estado(r, "gpu_largo") == "INCOMPATIBLE"

    def test_potencia_de_la_fuente(self, pc):
        cpu = pc.pieza("procesador", "CPU", **{"potencia-turbo-maxima": 140})
        gpu = pc.pieza("video", "GPU", **{"consumo-tgp": 220})
        chica = pc.pieza("fuente", "Fuente 450", potencia=450)
        grande = pc.pieza("fuente", "Fuente 650", potencia=650)
        assert estado(validar((cpu, 1), (gpu, 1), (chica, 1)), "fuente_potencia") == "INCOMPATIBLE"
        r = validar((cpu, 1), (gpu, 1), (grande, 1))
        assert estado(r, "fuente_potencia") == "COMPATIBLE"
        # sin dato de consumo de la tarjeta no se afirma
        sin = pc.pieza("video", "GPU sin dato")
        assert (
            estado(validar((cpu, 1), (sin, 1), (grande, 1)), "fuente_potencia") == "NO_VERIFICABLE"
        )

    def test_discos_m2_y_sata_contra_la_placa(self, pc):
        placa = pc.pieza("placa", "Placa", **{"ranuras-m2": 1, "puertos-sata": 2})
        m2 = pc.pieza("almacenamiento", "NVMe", formato="M.2 2280")
        sata = pc.pieza("almacenamiento", "SATA", formato="2.5 pulgadas SATA")
        assert estado(validar((placa, 1), (m2, 1)), "ssd_m2") == "COMPATIBLE"
        assert estado(validar((placa, 1), (m2, 2)), "ssd_m2") == "INCOMPATIBLE"
        assert estado(validar((placa, 1), (sata, 2)), "ssd_sata") == "COMPATIBLE"
        assert estado(validar((placa, 1), (sata, 3)), "ssd_sata") == "INCOMPATIBLE"

    def test_una_regla_apagada_no_se_evalua_y_las_claves_se_pueden_cambiar(self, pc):
        cpu = pc.pieza("procesador", "CPU", socket="AM5", zocalo="LGA1700")
        placa = pc.pieza("placa", "Placa", socket="LGA1700")
        assert estado(validar((cpu, 1), (placa, 1)), "socket") == "INCOMPATIBLE"
        admin = cliente_de("admin")
        r = admin.patch(
            ADMIN,
            {"reglas": {"socket": {"activa": True, "claves": {"a": "zocalo"}}}},
            format="json",
        )
        assert r.status_code == 200, r.content
        cache.clear()
        assert estado(validar((cpu, 1), (placa, 1)), "socket") == "COMPATIBLE"
        admin.patch(ADMIN, {"reglas": {"socket": {"activa": False}}}, format="json")
        cache.clear()
        assert not [
            c for c in validar((cpu, 1), (placa, 1))["compatibilidades"] if c["regla"] == "socket"
        ]


class TestValidar:
    def test_total_faltantes_y_completo(self, pc):
        cpu = pc.pieza("procesador", "CPU", precio=500)
        r = validar((cpu, 1))
        assert r["completo"] is False and {f["clave"] for f in r["faltantes"]} >= {
            "placa",
            "ram",
            "fuente",
            "gabinete",
        }
        assert "video" not in {f["clave"] for f in r["faltantes"]}  # opcional
        assert float(r["subtotal"]) >= 500 and r["lineas"][0]["espacio"] == "procesador"

    def test_problemas_de_stock_bloquean_agregar(self, pc):
        agotado = pc.pieza("procesador", "CPU agotada", stock=0)
        r = validar((agotado, 1))
        assert r["problemas"] == 1 and r["puede_agregar"] is False

    def test_limites_por_espacio(self, pc):
        a = pc.pieza("procesador", "CPU A")
        b = pc.pieza("procesador", "CPU B")
        ram = pc.pieza("ram", "RAM", stock=50)
        mal = anonimo().post(VALIDAR, lineas((a, 1), (b, 1)), format="json")
        assert mal.status_code == 400 and "solo puedes elegir una pieza" in str(mal.json())
        assert anonimo().post(VALIDAR, lineas((ram, 5)), format="json").status_code == 400
        assert anonimo().post(VALIDAR, lineas((ram, 4)), format="json").status_code == 200

    def test_una_pieza_que_no_es_del_armador_se_rechaza(self, pc):
        mouse = pc.publicar("Mouse suelto", precio=20, stock=5)
        assert anonimo().post(VALIDAR, lineas((mouse, 1)), format="json").status_code == 400

    def test_lo_que_ya_no_se_vende_se_quita(self, pc):
        oculta = pc.pieza("procesador", "Oculta")
        from apps.mantenimiento.models import Producto

        Producto.objects.sin_ambito().filter(pk=oculta.pk).update(publicado_web=False)
        cache.clear()
        r = validar((oculta, 1))
        assert r["quitados"] == [oculta.pk] and r["lineas"] == []

    @pytest.mark.parametrize(
        "cuerpo",
        [
            {"lineas": [{"producto": 0, "cantidad": 1}]},
            {"lineas": [{"producto": 1, "cantidad": 100}]},
            {"lineas": [{"producto": "x"}]},
            {"lineas": [{"producto": i} for i in range(1, 40)]},
        ],
    )
    def test_rechaza_entradas_mal_formadas(self, pc, cuerpo):
        assert anonimo().post(VALIDAR, cuerpo, format="json").status_code == 400

    def test_pide_la_cabecera_anti_csrf(self, pc):
        assert APIClient().post(VALIDAR, {"lineas": []}, format="json").status_code == 403

    def test_sin_armador_activo_responde_error_claro(self, pc):
        ConfiguracionArmador.objects.sin_ambito().update(activo=False)
        cache.clear()
        assert anonimo().post(VALIDAR, {"lineas": []}, format="json").status_code == 400


class TestOpciones:
    def test_solo_compatibles_por_defecto_y_con_todas_se_marcan(self, pc):
        cpu = pc.pieza("procesador", "CPU AM5", socket="AM5")
        buena = pc.pieza("placa", "Placa AM5", socket="AM5")
        mala = pc.pieza("placa", "Placa LGA", socket="LGA1700")
        incierta = pc.pieza("placa", "Placa sin dato")
        r = anonimo().get(OPCIONES, {"espacio": "placa", "p": str(cpu.pk)}).json()
        nombres = [p["nombre"] for p in r["results"]]
        assert "Placa LGA" not in nombres and nombres[:2] == ["Placa AM5", "Placa sin dato"]
        estados = {p["nombre"]: p["compatibilidad"]["estado"] for p in r["results"]}
        assert estados == {"Placa AM5": "COMPATIBLE", "Placa sin dato": "NO_VERIFICABLE"}
        todas = anonimo().get(OPCIONES, {"espacio": "placa", "p": str(cpu.pk), "todas": "1"}).json()
        assert [p["nombre"] for p in todas["results"]][-1] == "Placa LGA"
        assert {p["nombre"]: p["compatibilidad"]["estado"] for p in todas["results"]}[
            "Placa LGA"
        ] == "INCOMPATIBLE"
        assert buena and mala and incierta

    def test_sin_nada_elegido_todo_queda_libre(self, pc):
        pc.pieza("placa", "Placa A", socket="AM5")
        r = anonimo().get(OPCIONES, {"espacio": "placa"}).json()
        assert r["results"][0]["compatibilidad"]["estado"] == "LIBRE"

    def test_cambiar_una_pieza_unica_evalua_contra_el_resto(self, pc):
        cpu = pc.pieza("procesador", "CPU", socket="AM5")
        actual = pc.pieza("placa", "Placa actual", socket="AM5")
        pc.pieza("placa", "Placa otra", socket="LGA1700")
        r = (
            anonimo()
            .get(OPCIONES, {"espacio": "placa", "p": f"{cpu.pk},{actual.pk}", "todas": "1"})
            .json()
        )
        estados = {p["nombre"]: p["compatibilidad"]["estado"] for p in r["results"]}
        assert estados["Placa actual"] == "COMPATIBLE" and estados["Placa otra"] == "INCOMPATIBLE"
        assert [p["elegido"] for p in r["results"] if p["nombre"] == "Placa actual"] == [True]

    def test_paginacion_y_espacio_invalido(self, pc):
        for i in range(5):
            pc.pieza("ram", f"RAM {i}", tipo="DDR5")
        r = anonimo().get(OPCIONES, {"espacio": "ram", "page_size": 2, "page": 2}).json()
        assert r["count"] == 5 and r["page"] == 2 and len(r["results"]) == 2 and r["paginas"] == 3
        assert anonimo().get(OPCIONES, {"espacio": "nada"}).status_code == 400

    def test_no_filtra_costos(self, pc):
        pc.pieza("ram", "RAM", tipo="DDR5")
        texto = anonimo().get(OPCIONES, {"espacio": "ram"}).content.decode()
        for prohibido in ("costo", "utilidad", "almacen"):
            assert prohibido not in texto


class TestConfiguracion:
    def test_publica_solo_los_espacios_con_categorias(self, pc):
        r = anonimo().get(PUBLICO).json()
        assert r["activo"] is True and [e["clave"] for e in r["espacios"]] == ESPACIOS
        assert r["espacios"][0]["categorias"][0]["slug"] == "cat-procesador"
        assert "monitor" not in [e["clave"] for e in r["espacios"]]

    def test_inactivo_o_sin_categorias_responde_activo_false(self, tienda):
        assert anonimo().get(PUBLICO).json() == {"activo": False}
        cliente_de("admin")
        ConfiguracionArmador.objects.sin_ambito().create(
            organizacion=tienda.org, activo=True, espacios=[]
        )
        cache.clear()
        assert anonimo().get(PUBLICO).json() == {"activo": False}

    def test_el_panel_guarda_valida_y_audita(self, tienda):
        contexto(tienda)
        cat = Categoria.objects.sin_ambito().create(
            organizacion=tienda.org, familia=tienda.familia, nombre="Placas"
        )
        otra = Categoria.objects.sin_ambito().create(
            organizacion=tienda.org, familia=tienda.familia, nombre="CPUs"
        )
        admin = cliente_de("admin")
        assert admin.get(ADMIN).json()["activo"] is False
        # no se puede activar sin categorías
        assert admin.patch(ADMIN, {"activo": True}, format="json").status_code == 400
        ok = admin.patch(
            ADMIN,
            {
                "activo": True,
                "espacios": [
                    {"clave": "placa", "categorias": [cat.pk], "max_unidades": 1},
                    {"clave": "procesador", "categorias": [otra.pk], "obligatorio": False},
                ],
            },
            format="json",
        )
        assert ok.status_code == 200 and ok.json()["listo"] is True
        proc = next(e for e in ok.json()["espacios"] if e["clave"] == "procesador")
        assert proc["obligatorio"] is False and proc["categorias"] == [otra.pk]
        # una categoría no puede llenar dos espacios
        dup = admin.patch(
            ADMIN,
            {
                "espacios": [
                    {"clave": "placa", "categorias": [cat.pk]},
                    {"clave": "ram", "categorias": [cat.pk]},
                ]
            },
            format="json",
        )
        assert dup.status_code == 400 and "solo puede llenar un espacio" in str(dup.json())

    @pytest.mark.parametrize(
        "cuerpo",
        [
            {"espacios": [{"clave": "nave", "categorias": []}]},
            {"espacios": [{"clave": "ram", "categorias": [999999]}]},
            {"espacios": [{"clave": "ram", "max_unidades": 0}]},
            {"reglas": {"inventada": {"activa": True}}},
            {"reglas": {"socket": {"claves": {"zzz": "socket"}}}},
            {"reglas": {"socket": {"claves": {"a": "Con Espacios!"}}}},
        ],
    )
    def test_rechaza_configuracion_invalida(self, tienda, cuerpo):
        assert cliente_de("admin").patch(ADMIN, cuerpo, format="json").status_code == 400

    def test_permisos_y_otra_organizacion(self, tienda):
        assert cliente_de("vendedor").get(ADMIN).status_code == 403
        assert cliente_de("vendedor").patch(ADMIN, {}, format="json").status_code == 403
        assert APIClient().get(ADMIN).status_code == 401
        assert cliente_de("otra_org").get(ADMIN).json()["activo"] is False

    def test_el_panel_avisa_que_campos_faltan_en_las_categorias(self, pc):
        regla = next(
            r for r in cliente_de("admin").get(ADMIN).json()["reglas"] if r["id"] == "socket"
        )
        assert regla["claves"]["a"]["existe"] is False  # las categorías de prueba no tienen campos
        assert regla["claves"]["a"]["espacio_configurado"] is True

    def test_las_plantillas_traen_las_claves_que_usan_las_reglas(self, tienda):
        from apps.mantenimiento.especificaciones import PLANTILLAS, _clave_libre

        claves = {
            plantilla: {_clave_libre(c["nombre"], set()) for c in datos["campos"]}
            for plantilla, datos in PLANTILLAS.items()
        }
        espacio_plantilla = {
            "procesador": "procesador", "placa": "placa-base", "ram": "memoria-ram",
            "almacenamiento": "ssd", "video": "tarjeta-de-video", "fuente": "fuente-de-poder",
            "gabinete": "gabinete", "refrigeracion": "refrigeracion",
        }  # fmt: skip
        for regla in armador.REGLAS:
            for alias, (espacio, clave) in regla.claves.items():
                assert clave in claves[espacio_plantilla[espacio]], (regla.id, alias, clave)
