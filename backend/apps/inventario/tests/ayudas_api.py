"""Ayudas compartidas por las pruebas de la API de inventario."""

import itertools
from datetime import timedelta

from django.utils import timezone

BASE = "/api/v1/inventario"
_claves = itertools.count(1)


def clave():
    return f"clave-de-prueba-{next(_claves):06d}"


def cuerpo(mundo, producto, *, empresa=1, cantidad="10", precio="20", **extra):
    emp = mundo.e1 if empresa == 1 else mundo.e2
    return {
        "empresa": emp.pk,
        "almacen": mundo.alm[empresa].pk,
        "tipo": "ENTRADA",
        "origen": "COMPRA",
        "fecha": (timezone.localdate() - timedelta(days=2)).isoformat(),
        "lineas": [{"producto": producto.pk, "cantidad": cantidad, "precio_unitario": precio}],
        **extra,
    }


def registrar(api, datos, llave=None):
    return api.post(
        f"{BASE}/movimientos/", datos, format="json", HTTP_IDEMPOTENCY_KEY=llave or clave()
    )
