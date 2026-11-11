"""Prepara la base de datos de la demostración (sin tocar la base de desarrollo).

Qué hace, y solo si falta:
  1. Crea la base de datos indicada en DB_NAME (por seguridad su nombre debe contener «demo»).
  2. Aplica las migraciones y sincroniza los permisos.
  3. Crea una organización con su empresa de ejemplo y un usuario administrador con una
     contraseña generada, que guarda en demo/credenciales-demo.txt (ese archivo no se sube).

Se ejecuta desde la carpeta backend con el Python de su entorno virtual y las variables de la
demostración ya puestas (lo hace demo/iniciar-demo.ps1).
"""

import os
import secrets
import sys
from pathlib import Path

import django
import psycopg
from psycopg import sql

RAIZ = Path(__file__).resolve().parent
ARCHIVO_CREDENCIALES = RAIZ / "credenciales-demo.txt"
USUARIO = "demo"
EMAIL = "demo@example.com"


def digito_ruc(base10: str) -> str:
    """Dígito verificador de un RUC peruano a partir de sus 10 primeros dígitos."""
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    resto = sum(int(d) * p for d, p in zip(base10, pesos, strict=True)) % 11
    return str((11 - resto) % 10)


def crear_base_si_falta(config: dict) -> bool:
    nombre = config["NAME"]
    if "demo" not in nombre.lower():
        sys.exit(f"Por seguridad la base de la demostración debe llamarse «…demo…» (es «{nombre}»).")
    with psycopg.connect(
        dbname="postgres",
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"],
        autocommit=True,
    ) as conexion:
        existe = conexion.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)).fetchone()
        if existe:
            return False
        conexion.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
        return True


def main() -> None:
    sys.path.insert(0, str(RAIZ.parent / "backend"))  # para importar «config» y «apps»
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    from apps.organizacion.models import Empresa, Organizacion
    from apps.organizacion.services.creacion import crear_organizacion_con_empresa
    from apps.seguridad.models import Usuario

    config = settings.DATABASES["default"]
    print(f"Base de la demostración: {config['NAME']}")
    if crear_base_si_falta(config):
        print("  - base creada")

    call_command("migrate", interactive=False, verbosity=0)
    call_command("sync_permisos", verbosity=0)
    print("  - migraciones y permisos al día")

    organizacion = Organizacion.objects.first()
    if organizacion is None:
        base = "2010000011"
        creada = crear_organizacion_con_empresa(
            nombre_organizacion="Empresa Demo",
            razon_social="EMPRESA DEMO S.A.C.",
            ruc=base + digito_ruc(base),
            nombre_comercial="Empresa Demo",
            codigo_sucursal="001",
        )
        organizacion = creada.organizacion
        print("  - organización y empresa de ejemplo creadas")
        call_command("sync_permisos", verbosity=0)  # roles de la organización nueva

    if Usuario.objects.filter(username=USUARIO).exists():
        print(f"  - el usuario «{USUARIO}» ya existe (sus datos están en {ARCHIVO_CREDENCIALES.name})")
        return

    empresas = list(
        Empresa.objects.sin_ambito()
        .filter(organizacion=organizacion)
        .values_list("pk", flat=True)
    )
    password = secrets.token_urlsafe(10) + "aA1!"
    os.environ["USUARIO_PASSWORD"] = password
    argumentos = [
        "--organizacion-id", str(organizacion.pk),
        "--username", USUARIO,
        "--email", EMAIL,
        "--nombres", "Usuario",
        "--apellidos", "Demostración",
        "--rol", "SUPERADMIN",
    ]  # fmt: skip
    for pk in empresas:
        argumentos += ["--empresa-id", str(pk)]
    call_command("crear_usuario", *argumentos, verbosity=0)
    ARCHIVO_CREDENCIALES.write_text(
        f"Usuario: {USUARIO}\nContraseña: {password}\n", encoding="utf-8"
    )
    print(f"  - usuario «{USUARIO}» creado; contraseña guardada en {ARCHIVO_CREDENCIALES.name}")


if __name__ == "__main__":
    main()
