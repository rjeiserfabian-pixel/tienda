"""Operaciones simultáneas contra la base real: los bloqueos impiden vender dos veces lo mismo."""

import threading

import pytest
from django.db import connection

from apps.core.tenant import establecer_contexto
from apps.inventario.exceptions import StockInsuficiente
from apps.inventario.models import MovimientoInventario

from .conftest import comprar, saldo_de, vender

pytestmark = pytest.mark.django_db(transaction=True)


def en_paralelo(entorno, tareas):
    """Ejecuta cada tarea en su propio hilo (y su propia conexión), todas a la vez."""
    salida = [None] * len(tareas)
    barrera = threading.Barrier(len(tareas))

    def correr(posicion, tarea):
        e = entorno.e
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


def test_dos_ventas_de_la_ultima_unidad_solo_dejan_pasar_una(entorno):
    cemento = entorno.producto()
    comprar(entorno, cemento, 1, 20, dias=2)

    resultados = en_paralelo(entorno, [lambda: vender(entorno, cemento, 1) for _ in range(2)])

    exitos = [r for r in resultados if isinstance(r, MovimientoInventario)]
    fallos = [r for r in resultados if isinstance(r, StockInsuficiente)]
    assert len(exitos) == 1 and len(fallos) == 1, resultados
    saldo = saldo_de(entorno, cemento)
    assert (saldo.cantidad, saldo.costo_total) == (0, 0)


def test_varias_compras_simultaneas_no_repiten_numero_ni_pierden_unidades(entorno):
    cemento = entorno.producto()

    resultados = en_paralelo(entorno, [lambda: comprar(entorno, cemento, 1, 20) for _ in range(8)])

    assert all(isinstance(r, MovimientoInventario) for r in resultados), resultados
    assert sorted(r.numero for r in resultados) == list(range(1, 9))
    saldo = saldo_de(entorno, cemento)
    assert (saldo.cantidad, saldo.costo_total) == (8, 160)
