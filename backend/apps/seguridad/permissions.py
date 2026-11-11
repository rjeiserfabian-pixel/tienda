"""Clase de permiso de DRF basada en el motor RBAC.

La vista DECLARA qué permiso exige y de dónde sale la empresa::

    class VentaViewSet(ScopedQuerysetMixin, ModelViewSet):
        permission_classes = [IsAuthenticated, PermisoRBAC]
        permisos_por_accion = {"list": "VENTAS.VER", "create": "VENTAS.VENDER"}
        requiere_empresa = True            # la empresa viaja en el cuerpo ("empresa")

        def empresas_de_la_operacion(self, request):   # operación mixta: una por línea
            return [linea["empresa"] for linea in request.data["lineas"]]

Si la vista no declara permiso para la acción, se DENIEGA (fail-closed).
"""

from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission

from apps.seguridad.exceptions import PermisoDenegado
from apps.seguridad.services import permisos_engine as motor


def _entero(valor, nombre: str) -> int | None:
    if valor in (None, ""):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValidationError({nombre: "Debe ser un número entero."}) from None


def empresa_declarada(request, view) -> int | None:
    """Empresa que indica el cliente (query o cuerpo). Nunca se asume una por defecto."""
    valor = request.query_params.get("empresa")
    if valor in (None, "") and hasattr(request.data, "get"):
        valor = request.data.get("empresa")
    empresa_id = _entero(valor, "empresa")
    if empresa_id is None and getattr(view, "requiere_empresa", False):
        raise ValidationError({"empresa": "Debe indicar la empresa de la operación."})
    return empresa_id


def codigo_requerido(view, request) -> str | None:
    por_accion = getattr(view, "permisos_por_accion", None) or {}
    accion = getattr(view, "action", None) or request.method.lower()
    return por_accion.get(accion) or getattr(view, "permiso_requerido", None)


class PermisoRBAC(BasePermission):
    """Verifica el permiso por CADA empresa distinta de la operación; todo o nada."""

    def has_permission(self, request, view) -> bool:
        usuario = request.user
        if not usuario or not usuario.is_authenticated:
            return False
        codigo = codigo_requerido(view, request)
        if codigo is None:
            raise PermisoDenegado("La operación no tiene un permiso asociado.")
        resolver = getattr(view, "empresas_de_la_operacion", None)
        empresas = resolver(request) if resolver else [empresa_declarada(request, view)]
        # Si una sola empresa falla se rechaza TODO, antes de guardar nada.
        request.alcances_permiso = motor.exigir_permiso_en_empresas(usuario, codigo, empresas)
        return True
