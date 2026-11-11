"""API del propio trabajador: sus boletas, su saldo de vacaciones y lo que debe de adelantos.

* ``RRHH.AUTOSERVICIO.VER``: ver SOLO lo propio. El trabajador se reconoce por el vínculo entre su
  usuario y su ficha de «Personal» en la empresa; nunca se acepta un id de trabajador del cliente.
* Solo se ven planillas cerradas (las que están en revisión todavía pueden cambiar).
"""

from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import EstadoRegistro, Personal
from apps.rrhh import adelantos, pagos, vacaciones
from apps.rrhh.models import (
    AdelantoPersonal,
    EstadoAdelanto,
    EstadoPago,
    EstadoPlanilla,
    PagoPlanilla,
    PlanillaTrabajador,
)
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

TAG = ["rrhh"]
VER = "RRHH.AUTOSERVICIO.VER"
MAX_BOLETAS = 36


class _Mi(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER}
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @staticmethod
    def _personal(request) -> Personal:
        personal = Personal.objects.filter(
            usuario=request.user,
            empresa_id=empresa_declarada(request, None),
            estado=EstadoRegistro.ACTIVO,
        ).first()
        if personal is None:
            raise PermissionDenied("Tu usuario no está vinculado a un trabajador de esta empresa.")
        return personal


class MiResumenView(_Mi):
    """Mis boletas (planillas cerradas), mi saldo de vacaciones y mis adelantos por descontar."""

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        personal = self._personal(request)
        detalles = list(
            PlanillaTrabajador.objects.filter(
                personal=personal, planilla__estado=EstadoPlanilla.CERRADA
            )
            .select_related("planilla")
            .order_by("-planilla__periodo")[:MAX_BOLETAS]
        )
        pagados = {
            p.detalle_id: p
            for p in PagoPlanilla.objects.filter(detalle__in=detalles, estado=EstadoPago.PAGADO)
        }
        saldo = vacaciones.saldos_de([personal.pk]).get(personal.pk)
        pendientes = []
        for a in AdelantoPersonal.objects.filter(
            personal=personal, estado=EstadoAdelanto.VIGENTE
        ).order_by("-fecha"):
            falta = adelantos.saldo_pendiente(a)
            if falta > 0:
                pendientes.append(
                    {
                        "numero": a.numero,
                        "tipo_nombre": a.get_tipo_display(),
                        "fecha": a.fecha,
                        "monto": str(a.monto),
                        "pendiente": str(falta),
                    }
                )
        respuesta = Response(
            {
                "nombre_completo": personal.nombre_completo,
                "boletas": [
                    {
                        "planilla": d.planilla_id,
                        "periodo": d.planilla.periodo,
                        "total_ingresos": str(d.total_ingresos),
                        "total_descuentos": str(d.total_descuentos),
                        "neto": str(d.neto),
                        "fecha_pago": pagados[d.pk].fecha if d.pk in pagados else None,
                    }
                    for d in detalles
                ],
                "vacaciones": None
                if saldo is None
                else {
                    "ganados": str(saldo["ganados"]),
                    "tomados": saldo["tomados"],
                    "saldo": str(saldo["saldo"]),
                },
                "adelantos": pendientes,
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class MiBoletaView(_Mi):
    """Mi boleta de un mes cerrado, lista para imprimir."""

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request, planilla_id):
        personal = self._personal(request)
        detalle = (
            PlanillaTrabajador.objects.filter(
                personal=personal,
                planilla_id=planilla_id,
                planilla__estado=EstadoPlanilla.CERRADA,
            )
            .select_related("planilla__empresa", "personal")
            .prefetch_related("conceptos")
            .first()
        )
        if detalle is None:
            raise Http404
        respuesta = Response(pagos.boleta(detalle.planilla, detalle))
        respuesta["Cache-Control"] = "no-store"
        return respuesta
