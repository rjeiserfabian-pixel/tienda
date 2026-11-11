"""Qué empresas puede operar un usuario ahora mismo."""

from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone

from apps.organizacion.models import Estado
from apps.seguridad.models import AccesoEmpresa, AccesoSucursal


@dataclass(frozen=True, slots=True)
class EmpresaHabilitada:
    id: int
    ruc: str
    razon_social: str
    nombre_comercial: str
    cargo: str
    sucursales: tuple[dict, ...] = field(default_factory=tuple)

    def como_dict(self) -> dict:
        return {
            "id": self.id,
            "ruc": self.ruc,
            "razon_social": self.razon_social,
            "nombre_comercial": self.nombre_comercial,
            "cargo": self.cargo,
            "sucursales": list(self.sucursales),
        }


def empresas_habilitadas(usuario) -> list[EmpresaHabilitada]:
    """Accesos vigentes (activos, no vencidos) a empresas activas de su organización.

    Son 2 consultas en total, sin importar cuántas empresas tenga el usuario.
    """
    if usuario.organizacion_id is None:
        return []
    ahora = timezone.now()
    accesos = list(
        AccesoEmpresa.objects.sin_ambito()
        .filter(
            Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gt=ahora),
            usuario=usuario,
            organizacion_id=usuario.organizacion_id,
            estado=Estado.ACTIVO,
            empresa__estado=Estado.ACTIVO,
            empresa__eliminado_en__isnull=True,
        )
        .select_related("empresa")
        .order_by("empresa_id")
    )
    sucursales_por_acceso: dict[int, list[dict]] = {}
    filas = (
        AccesoSucursal.objects.sin_ambito()
        .filter(acceso_empresa__in=[a.pk for a in accesos], sucursal__eliminado_en__isnull=True)
        .select_related("sucursal")
        .order_by("sucursal__codigo")
    )
    for fila in filas:
        sucursales_por_acceso.setdefault(fila.acceso_empresa_id, []).append(
            {
                "id": fila.sucursal_id,
                "nombre": fila.sucursal.nombre,
                "codigo": fila.sucursal.codigo,
            }
        )
    # Es la misma persona en todas sus empresas: sin cargo propio muestra el de otra empresa suya.
    cargo_comun = next((a.cargo for a in accesos if a.cargo), "")
    return [
        EmpresaHabilitada(
            id=a.empresa_id,
            ruc=a.empresa.ruc,
            razon_social=a.empresa.razon_social,
            nombre_comercial=a.empresa.nombre_comercial,
            cargo=a.cargo or cargo_comun,
            sucursales=tuple(sucursales_por_acceso.get(a.pk, ())),
        )
        for a in accesos
    ]
