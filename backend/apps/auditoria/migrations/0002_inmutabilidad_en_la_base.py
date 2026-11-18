"""La bitácora no se puede editar ni borrar NI SIQUIERA desde la base de datos.

Un disparador de PostgreSQL rechaza todo UPDATE y todo DELETE de ``auditoria_auditoriaevento``. La
única salida es la purga por retención, que avisa con ``SET LOCAL app.auditoria_purga = 'on'`` dentro
de su propia transacción. Así el rastro aguanta aunque alguien use el shell, un script o un cliente
SQL con el usuario de la aplicación. (Un superusuario de la base todavía puede quitar el disparador:
ese acceso se cuida aparte, ver ``docs/DESPLIEGUE_VPS.md``.)
"""

from django.db import migrations

CREAR = """
CREATE OR REPLACE FUNCTION auditoria_proteger() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Los eventos de auditoría no se modifican.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF current_setting('app.auditoria_purga', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Los eventos de auditoría no se eliminan; use la purga por retención.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS auditoria_inmutable ON auditoria_auditoriaevento;
CREATE TRIGGER auditoria_inmutable
    BEFORE UPDATE OR DELETE ON auditoria_auditoriaevento
    FOR EACH ROW EXECUTE FUNCTION auditoria_proteger();
"""

QUITAR = """
DROP TRIGGER IF EXISTS auditoria_inmutable ON auditoria_auditoriaevento;
DROP FUNCTION IF EXISTS auditoria_proteger();
"""


def _crear(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREAR)


def _quitar(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(QUITAR)


class Migration(migrations.Migration):
    dependencies = [("auditoria", "0001_initial")]

    operations = [migrations.RunPython(_crear, _quitar)]
