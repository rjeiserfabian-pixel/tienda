"""Emisión simultánea contra la base real: la numeración no se repite ni se salta."""

import threading

import pytest
from django.db import connection

from apps.core.tenant import establecer_contexto
from apps.mantenimiento import series
from apps.mantenimiento.models import SerieComprobante, TipoComprobante

pytestmark = pytest.mark.django_db(transaction=True)


def _en_paralelo(escenario, tareas):
    """Cada tarea corre en su propio hilo (y su propia conexión), todas a la vez."""
    salida = [None] * len(tareas)
    barrera = threading.Barrier(len(tareas))

    def correr(posicion, tarea):
        e = escenario
        establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
        try:
            barrera.wait(timeout=10)
            salida[posicion] = tarea()
        except Exception as error:  # noqa: BLE001 - se devuelve para que la prueba lo revise
            salida[posicion] = error
        finally:
            connection.close()

    hilos = [threading.Thread(target=correr, args=(i, t)) for i, t in enumerate(tareas)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    return salida


def _serie(escenario, empresa, codigo="F001"):
    tipo = TipoComprobante.objects.sin_ambito().get(organizacion=escenario.org_a, codigo="01")
    return SerieComprobante.objects.sin_ambito().create(
        empresa=empresa, tipo_comprobante=tipo, serie=codigo
    )


def test_varias_cajas_emitiendo_a_la_vez_no_repiten_ni_saltan_numeros(escenario):
    serie = _serie(escenario, escenario.emp_a1)

    resultados = _en_paralelo(
        escenario,
        [lambda: series.siguiente_numero(escenario.emp_a1, serie.pk) for _ in range(12)],
    )

    assert all(isinstance(r, tuple) for r in resultados), resultados
    assert sorted(numero for _, numero in resultados) == list(range(1, 13))
    serie.refresh_from_db()
    assert (serie.ultimo_numero, serie.emitidos) == (12, 12)


def test_dos_empresas_emiten_a_la_vez_cada_una_con_su_numeracion(escenario):
    uno = _serie(escenario, escenario.emp_a1, "F001")
    dos = _serie(escenario, escenario.emp_a2, "F002")
    tareas = [lambda: series.siguiente_numero(escenario.emp_a1, uno.pk) for _ in range(5)]
    tareas += [lambda: series.siguiente_numero(escenario.emp_a2, dos.pk) for _ in range(5)]

    resultados = _en_paralelo(escenario, tareas)

    assert all(isinstance(r, tuple) for r in resultados), resultados
    de_uno = sorted(n for s, n in resultados if s == "F001")
    de_dos = sorted(n for s, n in resultados if s == "F002")
    assert de_uno == de_dos == [1, 2, 3, 4, 5]
