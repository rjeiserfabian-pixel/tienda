"""API del tablero por estado, los reportes del taller y las comisiones de los técnicos.

Los importes (lo cobrado, el costo de los repuestos, la utilidad y la comisión) salen solo para
quien tiene ``VENTAS.VER_UTILIDAD`` en la empresa; el resto ve cantidades y tiempos.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import OuterRef, Subquery
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import Personal
from apps.seguridad.mixins import filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor
from apps.servicio_tecnico import reportes, servicios
from apps.servicio_tecnico.flujo import ESTADOS_QUE_ESPERAN
from apps.servicio_tecnico.models import EstadoOrden, HistorialEstado, OrdenServicio

TAG = ["servicio-tecnico"]
VER = "SERVICIOS.VER"
REPORTES = "SERVICIOS.REPORTES.VER"
COMISIONES = "SERVICIOS.COMISIONES.GESTIONAR"
UTILIDAD = "VENTAS.VER_UTILIDAD"

TARJETAS_POR_COLUMNA = 15
# Las columnas del tablero, en el orden del proceso (lo entregado ya no está en el taller).
COLUMNAS = [e for e in EstadoOrden.values if e != EstadoOrden.ENTREGADO]


def _periodo(params) -> reportes.Periodo:
    def fecha(nombre: str) -> date | None:
        valor = params.get(nombre)
        if not valor:
            return None
        try:
            return date.fromisoformat(valor)
        except ValueError:
            raise ValidationError({nombre: "Use el formato AAAA-MM-DD."}) from None

    try:
        return reportes.Periodo.validar(fecha("desde"), fecha("hasta"))
    except ValueError as error:
        raise ValidationError({"desde": str(error)}) from None


class _VistaDeEmpresa(APIView):
    """Base: la empresa se declara (``?empresa=``) y se verifica el permiso en ella."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]


# ---------------------------------------------------------------------------
# Tablero
# ---------------------------------------------------------------------------
class TableroView(_VistaDeEmpresa):
    """Las órdenes abiertas por estado: cuántas hay y las primeras de cada columna.

    Filtros: ``tecnico``, ``prioridad``, ``mias=1``. Quien solo ve lo asignado ve solo lo suyo.
    """

    permiso_requerido = VER

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = empresa_declarada(request, self)
        params = request.query_params
        base = (
            filtrar_por_alcance(
                OrdenServicio.objects.filter(empresa_id=empresa),
                request.user,
                VER,
                campo_asignado="tecnico__usuario_id",
            )
            .exclude(estado=EstadoOrden.ENTREGADO)
            .select_related("cliente", "equipo__tipo", "tecnico")
        )
        if params.get("mias") in ("1", "true"):
            base = base.filter(tecnico__usuario_id=request.user.pk)
        if (tecnico := params.get("tecnico")) not in (None, ""):
            if not str(tecnico).isdigit():
                raise ValidationError({"tecnico": "Debe ser un número entero."})
            base = base.filter(tecnico_id=int(tecnico))
        if params.get("prioridad") in ("NORMAL", "URGENTE"):
            base = base.filter(prioridad=params["prioridad"])
        desde = Subquery(
            HistorialEstado.objects.sin_ambito()
            .filter(orden=OuterRef("pk"), estado_nuevo=OuterRef("estado"))
            .order_by("-id")
            .values("creado_en")[:1]
        )
        base = base.annotate(en_estado_desde=desde)
        hoy = timezone.localdate()
        ahora = timezone.now()
        columnas = []
        for estado in COLUMNAS:
            ordenes = base.filter(estado=estado)
            tarjetas = []
            for o in ordenes.order_by("-prioridad", "fecha_promesa", "id")[:TARJETAS_POR_COLUMNA]:
                dias = max((ahora - o.en_estado_desde).days, 0) if o.en_estado_desde else None
                tarjetas.append(
                    {
                        "id": o.pk,
                        "codigo": o.codigo,
                        "cliente": o.cliente.nombre,
                        "equipo": str(o.equipo),
                        "tecnico": o.tecnico.nombre_completo if o.tecnico_id else "",
                        "prioridad": o.prioridad,
                        "es_garantia": o.es_garantia,
                        "fecha_promesa": o.fecha_promesa,
                        "atrasada": bool(o.fecha_promesa and o.fecha_promesa < hoy),
                        "dias_en_estado": dias,
                        "por_abandonar": bool(
                            dias is not None
                            and dias >= servicios.DIAS_PARA_ABANDONO
                            and estado in ESTADOS_QUE_ESPERAN
                        ),
                    }
                )
            columnas.append(
                {
                    "estado": estado,
                    "nombre": EstadoOrden(estado).label,
                    "cantidad": ordenes.count(),
                    "tarjetas": tarjetas,
                }
            )
        respuesta = Response({"columnas": columnas, "tarjetas_por_columna": TARJETAS_POR_COLUMNA})
        respuesta["Cache-Control"] = "no-store"
        return respuesta


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------
class ResumenReporteView(_VistaDeEmpresa):
    """Cómo va el taller en un periodo: cantidades, tiempos, técnicos y equipos que más vuelven."""

    permiso_requerido = REPORTES

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = empresa_declarada(request, self)
        p = _periodo(request.query_params)
        con_importes = motor.tiene_permiso(request.user, UTILIDAD, empresa)
        datos = {
            "periodo": {"desde": p.desde, "hasta": p.hasta},
            "con_importes": con_importes,
            "resumen": reportes.resumen(empresa, p),
            "tiempos": reportes.tiempos_por_estado(empresa, p),
            "tecnicos": reportes.tecnicos(empresa, p, con_importes=con_importes),
            "repetidos": reportes.equipos_mas_reparados(empresa, p),
        }
        if con_importes:
            datos["utilidad"] = reportes.utilidad_resumen(empresa, p)
        respuesta = Response(datos)
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class UtilidadReporteView(_VistaDeEmpresa):
    """Lo cobrado, lo que costaron los repuestos y lo que dejó cada orden (paginado)."""

    permiso_requerido = REPORTES

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = empresa_declarada(request, self)
        if not motor.tiene_permiso(request.user, UTILIDAD, empresa):
            raise PermissionDenied("No tiene permiso para ver el costo y la utilidad.")
        p = _periodo(request.query_params)
        paginador = PaginaEstandar()
        pagina = paginador.paginate_queryset(reportes.utilidad_ordenes(empresa, p), request, self)
        filas = [
            {
                "orden": f.orden_id,
                "codigo": f.orden.codigo,
                "fecha_entrega": f.orden.fecha_entrega,
                "cliente": f.orden.cliente.nombre,
                "equipo": str(f.orden.equipo),
                "tipo_servicio": f.orden.tipo_servicio.nombre if f.orden.tipo_servicio_id else "",
                "tecnico": f.orden.tecnico.nombre_completo if f.orden.tecnico_id else "",
                "ingreso": str(f.ingreso),
                "costo_repuestos": str(f.costo_repuestos),
                "comision": str(f.comision),
                "utilidad": str(f.utilidad),
            }
            for f in pagina
        ]
        return paginador.get_paginated_response(filas)


# ---------------------------------------------------------------------------
# Comisiones
# ---------------------------------------------------------------------------
class ComisionEntrada(serializers.Serializer):
    porcentaje = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100")
    )


class ComisionesView(_VistaDeEmpresa):
    """Los técnicos de la empresa y su porcentaje de comisión."""

    permiso_requerido = COMISIONES

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = empresa_declarada(request, self)
        return Response({"tecnicos": reportes.comisiones_configuradas(empresa)})


class ComisionDetalleView(_VistaDeEmpresa):
    """Fija el porcentaje de un técnico: vale para las entregas que se hagan desde ahora."""

    permiso_requerido = COMISIONES

    @extend_schema(
        tags=TAG,
        request=ComisionEntrada,
        parameters=[OpenApiParameter("empresa", int, required=True)],
    )
    def put(self, request, personal_id: int):
        empresa = empresa_declarada(request, self)
        personal = Personal.objects.filter(pk=personal_id, empresa_id=empresa).first()
        if personal is None:
            raise NotFound("No existe ese técnico en la empresa.")
        datos = ComisionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        anterior = reportes.comisiones_configuradas(empresa)
        antes = next((t["porcentaje"] for t in anterior if t["id"] == personal.pk), "0")
        try:
            fila = reportes.fijar_comision(personal, datos.validated_data["porcentaje"])
        except InvalidOperation:
            raise ValidationError({"porcentaje": "Escriba un porcentaje válido."}) from None
        except ValueError as error:
            raise ValidationError({"porcentaje": str(error)}) from None
        registrar(
            "servicio_tecnico.comision_fijada",
            recurso_tipo="personal",
            recurso_id=personal.pk,
            empresa_id=empresa,
            resumen=f"Comisión de {personal.nombre_completo}: {antes}% → {fila.porcentaje}%",
            detalle={"antes": antes, "despues": str(fila.porcentaje)},
        )
        return Response({"id": personal.pk, "porcentaje": str(fila.porcentaje)})
