from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.exceptions import (
    ClaveIdempotenciaRequerida,
    ClaveIdempotenciaReutilizada,
    OperacionEnCurso,
)
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.models import RegistroIdempotencia
from apps.core.tenant import contexto_tenant

pytestmark = pytest.mark.django_db

CLAVE = "cobro-0001-abcdef"


@pytest.fixture
def ctx(escenario):
    with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk], escenario.usuario_id):
        yield


def _ejecutar(operacion, *, clave=CLAVE, cuerpo=b'{"total":"10.00"}'):
    return ejecutar_idempotente(
        clave=clave,
        metodo="POST",
        ruta="/api/v1/ventas/cobrar/",
        cuerpo=cuerpo,
        operacion=operacion,
    )


def test_repetir_la_peticion_no_ejecuta_dos_veces(ctx):
    llamadas = []

    def operacion():
        llamadas.append(1)
        return 201, {"venta": 1}

    primera = _ejecutar(operacion)
    segunda = _ejecutar(operacion)

    assert len(llamadas) == 1
    assert primera == (201, {"venta": 1}, False)
    assert segunda == (201, {"venta": 1}, True)
    assert RegistroIdempotencia.objects.count() == 1


def test_misma_clave_con_otro_cuerpo_se_rechaza(ctx):
    _ejecutar(lambda: (201, {}))
    with pytest.raises(ClaveIdempotenciaReutilizada):
        _ejecutar(lambda: (201, {}), cuerpo=b'{"total":"99.00"}')


def test_si_la_operacion_falla_se_puede_reintentar(ctx):
    def falla():
        raise RuntimeError("caída")

    with pytest.raises(RuntimeError):
        _ejecutar(falla)
    assert RegistroIdempotencia.objects.count() == 0
    assert _ejecutar(lambda: (201, {"ok": True}))[2] is False


def test_peticion_identica_en_proceso_devuelve_conflicto(escenario, ctx):
    _ejecutar(lambda: (201, {}))
    RegistroIdempotencia.objects.update(estado=RegistroIdempotencia.Estado.EN_PROCESO)
    with pytest.raises(OperacionEnCurso):
        _ejecutar(lambda: (201, {}))


def test_registro_abandonado_se_libera_y_reintenta(ctx):
    _ejecutar(lambda: (201, {"v": 1}))
    RegistroIdempotencia.objects.update(
        estado=RegistroIdempotencia.Estado.EN_PROCESO,
        creado_en=timezone.now() - timedelta(hours=1),
    )
    assert _ejecutar(lambda: (201, {"v": 2})) == (201, {"v": 2}, False)


def test_la_clave_es_independiente_por_organizacion(escenario, ctx):
    _ejecutar(lambda: (201, {"org": "A"}))
    with contexto_tenant(escenario.org_b.pk, [escenario.emp_b1.pk]):
        assert _ejecutar(lambda: (201, {"org": "B"})) == (201, {"org": "B"}, False)


@pytest.mark.parametrize("valor", ["", "corta", "con espacios invalidos", "x" * 200])
def test_cabecera_invalida_se_rechaza(rf, valor):
    request = rf.post("/", HTTP_IDEMPOTENCY_KEY=valor)
    with pytest.raises(ClaveIdempotenciaRequerida):
        clave_desde_request(request)


def test_cabecera_valida(rf):
    assert clave_desde_request(rf.post("/", HTTP_IDEMPOTENCY_KEY=CLAVE)) == CLAVE
