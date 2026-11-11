"""Intercambia los IDs de dos empresas (sin crear registros nuevos).

Uso (desde la carpeta backend, con el entorno virtual activo):

    python scripts/intercambiar_ids_empresas.py 10011438534 20610589317           # simulacro
    python scripts/intercambiar_ids_empresas.py 10011438534 20610589317 --aplicar  # ejecuta

El primer RUC pasa a tener el ID del segundo y viceversa. Todas las tablas que
referencian a la empresa (claves foráneas y auditoría) se actualizan en la misma
transacción; si algo falla, no se cambia nada.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection, transaction  # noqa: E402

from apps.organizacion.models import Empresa  # noqa: E402


def columnas_que_apuntan_a_empresa() -> list[tuple[str, str]]:
    """(tabla, columna) de toda FK a Empresa más las columnas sin FK de auditoría."""
    destinos = []
    for modelo in apps.get_models(include_auto_created=True):
        for campo in modelo._meta.concrete_fields:
            if campo.is_relation and campo.related_model is Empresa:
                destinos.append((modelo._meta.db_table, campo.column))
    # La auditoría guarda el ID de empresa sin clave foránea.
    destinos.append((apps.get_model("auditoria", "AuditoriaEvento")._meta.db_table, "empresa_id"))
    return destinos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ruc_a")
    parser.add_argument("ruc_b")
    parser.add_argument("--aplicar", action="store_true", help="ejecuta el cambio")
    args = parser.parse_args()

    a = Empresa._base_manager.get(ruc=args.ruc_a, eliminado_en__isnull=True)
    b = Empresa._base_manager.get(ruc=args.ruc_b, eliminado_en__isnull=True)
    print(f"{a.razon_social} ({a.ruc}): ID {a.pk} -> {b.pk}")
    print(f"{b.razon_social} ({b.ruc}): ID {b.pk} -> {a.pk}")

    destinos = columnas_que_apuntan_a_empresa()
    q = connection.ops.quote_name
    with connection.cursor() as cursor:
        for tabla, col in destinos:
            cursor.execute(
                f"SELECT COUNT(*) FROM {q(tabla)} WHERE {q(col)} IN (%s, %s)", [a.pk, b.pk]
            )
            print(f"  {tabla}.{col}: {cursor.fetchone()[0]} filas")

    if not args.aplicar:
        print("\nSimulacro: no se cambió nada. Agregue --aplicar para ejecutar.")
        return

    temporal = -1  # ID que no existe, para evitar choque de llave primaria
    pasos = [(a.pk, temporal), (b.pk, a.pk), (temporal, b.pk)]
    tabla_empresa = q(Empresa._meta.db_table)
    with transaction.atomic(), connection.cursor() as cursor:
        # Las FK de Django son DEFERRABLE: se validan al final, con todo ya consistente.
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        for viejo, nuevo in pasos:
            cursor.execute(f"UPDATE {tabla_empresa} SET id = %s WHERE id = %s", [nuevo, viejo])
            for tabla, col in destinos:
                cursor.execute(
                    f"UPDATE {q(tabla)} SET {q(col)} = %s WHERE {q(col)} = %s", [nuevo, viejo]
                )
    print("\nListo. IDs intercambiados.")


if __name__ == "__main__":
    main()
