"""API de las órdenes de servicio: listado, ficha, recibir un equipo y consultar equipos."""

import json
from datetime import date, timedelta

from django.db.models import Count, Max, OuterRef, Prefetch, Q, Subquery, Sum
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import (
    Area,
    Cliente,
    EstadoRegistro,
    MedioPago,
    Personal,
)
from apps.organizacion.models import Empresa, Estado, Sucursal
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.servicio_tecnico import recepcion, servicios, trabajo
from apps.servicio_tecnico.capacidades import capacidades_de
from apps.servicio_tecnico.models import (
    AccesorioEquipo,
    AdelantoServicio,
    CategoriaServicio,
    Equipo,
    EstadoAdelanto,
    EstadoOrden,
    HistorialEstado,
    ItemChecklist,
    OrdenAccesorio,
    OrdenRevision,
    OrdenServicio,
    Prioridad,
    TipoEquipo,
    TipoServicio,
)
from apps.ventas.models import ComprobanteVenta

from .adelantos import AdelantosAcciones
from .garantia import GarantiaAcciones
from .presupuesto import PresupuestoAcciones
from .serializers import (
    AsignarEntrada,
    AvisoEntrada,
    CambiarEstadoEntrada,
    DiagnosticoEntrada,
    EquipoSerializer,
    OrdenDetalleSerializer,
    OrdenSerializer,
    RecibirEquipoEntrada,
)

TAG = ["servicio-tecnico"]
VER = "SERVICIOS.VER"
RECEPCIONAR = "SERVICIOS.RECEPCIONAR"
EJECUTAR = "SERVICIOS.EJECUTAR"
GESTIONAR = "SERVICIOS.GESTIONAR"


def _entero(params, nombre: str) -> int | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    if not str(valor).isdigit():
        raise ValidationError({nombre: "Debe ser un número entero."})
    return int(valor)


def _fecha(params, nombre: str) -> date | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({nombre: "Use el formato AAAA-MM-DD."}) from None


def _uno(modelo, pk, campo: str, mensaje: str, **filtros):
    """El registro con ese id dentro de lo permitido, o un error de ese campo (nunca otra org)."""
    if pk is None:
        return None
    objeto = modelo.objects.filter(pk=pk, **filtros).first()
    if objeto is None:
        raise ValidationError({campo: mensaje})
    return objeto


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


# ---------------------------------------------------------------------------
# Lo que la pantalla de ingreso necesita para armarse
# ---------------------------------------------------------------------------
class ConfiguracionView(APIView):
    """Catálogos activos, técnicos y sucursales de la empresa, en una sola llamada.

    Es una lista corta y completa a propósito (no se pagina): la pantalla la necesita entera.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = _empresa_activa(empresa_declarada(request, self))
        activos = {"estado": EstadoRegistro.ACTIVO}
        tecnicos = Personal.objects.filter(empresa=empresa, area=Area.TECNICO, **activos)
        sucursales = Sucursal.objects.filter(empresa=empresa, estado=Estado.ACTIVO)
        return Response(
            {
                "tipos_equipo": [
                    {"id": t.pk, "nombre": t.nombre}
                    for t in TipoEquipo.objects.filter(**activos).order_by("nombre")
                ],
                "accesorios": [
                    {"id": a.pk, "nombre": a.nombre}
                    for a in AccesorioEquipo.objects.filter(**activos).order_by("nombre")
                ],
                "revisiones": [
                    {"id": i.pk, "nombre": i.nombre, "tipo_equipo": i.tipo_equipo_id}
                    for i in ItemChecklist.objects.filter(**activos).order_by("orden", "nombre")
                ],
                "tipos_servicio": [
                    {
                        "id": s.pk,
                        "nombre": s.nombre,
                        "categoria": s.categoria,
                        "garantia_dias": s.garantia_dias,
                    }
                    for s in TipoServicio.objects.filter(**activos).order_by("nombre")
                ],
                "tecnicos": [
                    {"id": p.pk, "nombre": p.nombre_completo, "tiene_usuario": bool(p.usuario_id)}
                    for p in tecnicos.order_by("apellidos", "nombres")
                ],
                "sucursales": [
                    {"id": s.pk, "nombre": s.nombre} for s in sucursales.order_by("nombre")
                ],
                "medios_pago": [
                    {
                        "id": m.pk,
                        "nombre": m.nombre,
                        "tipo": m.tipo,
                        "requiere_referencia": m.requiere_referencia,
                    }
                    for m in MedioPago.objects.filter(**activos).order_by("nombre")
                ],
                "categorias_servicio": [
                    {"valor": v, "nombre": n} for v, n in CategoriaServicio.choices
                ],
            }
        )


# ---------------------------------------------------------------------------
# Equipos
# ---------------------------------------------------------------------------
class EquipoViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Equipos de la organización (``?empresa=ID`` obligatorio, por el permiso).

    Filtros: ``cliente``, ``serie`` (exacta, sin importar mayúsculas) y ``q`` (marca, modelo, serie
    o cliente). Cada equipo dice cuántas veces entró al taller.
    """

    serializer_class = EquipoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    permiso_requerido = RECEPCIONAR
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        params = self.request.query_params
        queryset = (
            Equipo.objects.select_related("tipo", "cliente")
            .annotate(
                n_ordenes=Count("ordenes", filter=Q(ordenes__eliminado_en__isnull=True)),
                ultimo_ingreso=Max("ordenes__fecha_ingreso"),
            )
            .order_by("-id")
        )
        if (cliente := _entero(params, "cliente")) is not None:
            queryset = queryset.filter(cliente_id=cliente)
        if serie := (params.get("serie") or "").strip():
            queryset = queryset.filter(numero_serie__iexact=serie)
        if q := (params.get("q") or "").strip():
            queryset = queryset.filter(
                Q(marca__icontains=q)
                | Q(modelo__icontains=q)
                | Q(numero_serie__icontains=q)
                | Q(cliente__nombre__icontains=q)
            )
        return queryset


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------
class OrdenServicioViewSet(
    AdelantosAcciones,
    GarantiaAcciones,
    PresupuestoAcciones,
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Órdenes de servicio de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``estado`` (uno, o ``abiertas`` para las que aún no se entregaron), ``tecnico``,
    ``prioridad``, ``desde`` y ``hasta`` (fecha de ingreso), ``atrasadas=1`` y ``q`` (número,
    cliente, documento, equipo o serie). Quien solo ve lo asignado ve solo las órdenes que tiene.
    """

    modelo = OrdenServicio
    serializer_class = OrdenSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    campo_asignado = "tecnico__usuario_id"
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": RECEPCIONAR,
        "clave": EJECUTAR,
        # Ver la orden alcanza para llegar aquí; lo que cada persona puede hacer lo decide
        # ``capacidades`` (el alcance de su permiso) antes de tocar nada.
        "cambiar_estado": VER,
        "diagnostico": VER,
        "avisos": VER,
        "asignar": GESTIONAR,
        "armar_presupuesto": VER,
        "aprobar": VER,
        "reservar": VER,
        "entregar": VER,
        "reingreso": VER,
        "recibir_adelanto": VER,
        "devolver_adelanto": VER,
        "anular_adelanto": VER,
    }
    acciones_de_ficha = (
        "retrieve",
        "cambiar_estado",
        "diagnostico",
        "avisos",
        "asignar",
        "armar_presupuesto",
        "aprobar",
        "reservar",
        "entregar",
        "reingreso",
        "recibir_adelanto",
        "devolver_adelanto",
        "anular_adelanto",
    )

    def get_serializer_class(self):
        return OrdenDetalleSerializer if self.action in self.acciones_de_ficha else OrdenSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "hoy": timezone.localdate()}

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                OrdenServicio.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("cliente", "equipo__tipo", "tecnico", "tipo_servicio", "empresa")
        )
        # Desde cuándo está la orden en su estado actual (para los equipos sin recoger).
        queryset = queryset.annotate(
            en_estado_desde=Subquery(
                HistorialEstado.objects.sin_ambito()
                .filter(orden=OuterRef("pk"), estado_nuevo=OuterRef("estado"))
                .order_by("-id")
                .values("creado_en")[:1]
            )
        )
        queryset = queryset.annotate(
            adelanto_disponible=Subquery(
                AdelantoServicio.objects.sin_ambito()
                .filter(orden=OuterRef("pk"), estado=EstadoAdelanto.VIGENTE)
                .filter(
                    Q(comprobante__isnull=True)
                    | Q(comprobante__estado=ComprobanteVenta.Estado.ANULADO)
                )
                .values("orden")
                .annotate(s=Sum("monto"))
                .values("s")
            )
        )
        if self.action in self.acciones_de_ficha:
            return queryset.select_related("sucursal", "reingreso_de").prefetch_related(
                Prefetch("accesorios", queryset=OrdenAccesorio.objects.order_by("id")),
                Prefetch("revisiones", queryset=OrdenRevision.objects.order_by("id")),
                "historial",
                "reingresos",
                "notificaciones",
                "adelantos",
                "avisos",
            )
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if params.get("mias") in ("1", "true"):
            # Las que me tocan a mí (por mi ficha de personal), aunque vea todas las de la empresa.
            queryset = queryset.filter(tecnico__usuario_id=self.request.user.pk)
        estado = params.get("estado")
        if estado == "abiertas":
            queryset = queryset.exclude(estado=EstadoOrden.ENTREGADO)
        elif estado in EstadoOrden.values:
            queryset = queryset.filter(estado=estado)
        elif estado:
            raise ValidationError({"estado": "Estado no válido."})
        if (tecnico := _entero(params, "tecnico")) is not None:
            queryset = queryset.filter(tecnico_id=tecnico)
        if (prioridad := params.get("prioridad")) in Prioridad.values:
            queryset = queryset.filter(prioridad=prioridad)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha_ingreso__date__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha_ingreso__date__lte=hasta)
        if params.get("sin_recoger") in ("1", "true"):
            limite = timezone.now() - timedelta(days=servicios.DIAS_PARA_ABANDONO)
            queryset = queryset.filter(
                estado=EstadoOrden.LISTO_ENTREGA, en_estado_desde__lte=limite
            )
        if params.get("garantia") in ("1", "true"):
            queryset = queryset.filter(es_garantia=True)
        if params.get("atrasadas") in ("1", "true"):
            queryset = queryset.filter(fecha_promesa__lt=timezone.localdate()).exclude(
                estado=EstadoOrden.ENTREGADO
            )
        q = (params.get("q") or "").strip()
        if q:
            condicion = (
                Q(cliente__nombre__icontains=q)
                | Q(cliente__numero_documento__icontains=q)
                | Q(equipo__marca__icontains=q)
                | Q(equipo__modelo__icontains=q)
                | Q(equipo__numero_serie__icontains=q)
            )
            digitos = (
                q.upper().removeprefix("OS-").lstrip("0") if q.upper().startswith("OS-") else q
            )
            if digitos.isdigit() and len(digitos) <= 9:
                condicion |= Q(numero=int(digitos))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha_ingreso", "-id")

    @extend_schema(
        tags=TAG,
        request=RecibirEquipoEntrada,
        responses={201: OrdenDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no registra dos veces.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = RecibirEquipoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        org = empresa.organizacion_id
        cliente = _uno(Cliente, v["cliente"], "cliente", "Elija un cliente.", organizacion_id=org)

        e = v["equipo"]
        equipo = recepcion.EquipoEntrada(
            existente=_uno(
                Equipo, e.get("id"), "equipo", "Elija un equipo de este cliente.", cliente=cliente
            ),
            tipo=_uno(
                TipoEquipo, e.get("tipo"), "equipo", "Elija un tipo de equipo.", organizacion_id=org
            ),
            marca=e.get("marca", ""),
            modelo=e.get("modelo", ""),
            numero_serie=e.get("numero_serie", ""),
            color=e.get("color", ""),
            descripcion=e.get("descripcion", ""),
        )
        accesorios = [
            recepcion.AccesorioEntrada(
                accesorio=_uno(
                    AccesorioEquipo,
                    a.get("accesorio"),
                    "accesorios",
                    "Hay accesorios que no existen.",
                    organizacion_id=org,
                ),
                nombre=a.get("nombre", ""),
                cantidad=a["cantidad"],
                detalle=a.get("detalle", ""),
            )
            for a in v.get("accesorios", [])
        ]
        revisiones = [
            recepcion.RevisionEntrada(
                item=_uno(
                    ItemChecklist,
                    r["item"],
                    "revisiones",
                    "Hay revisiones que no existen.",
                    organizacion_id=org,
                ),
                resultado=r["resultado"],
                observacion=r.get("observacion", ""),
            )
            for r in v.get("revisiones", [])
        ]
        tecnico = _uno(
            Personal,
            v.get("tecnico"),
            "tecnico",
            "Elija un técnico de esta empresa.",
            empresa=empresa,
        )
        sucursal = _uno(
            Sucursal,
            v.get("sucursal"),
            "sucursal",
            "Elija una sucursal de esta empresa.",
            empresa=empresa,
        )
        tipo_servicio = _uno(
            TipoServicio,
            v.get("tipo_servicio"),
            "tipo_servicio",
            "Elija un tipo de servicio.",
            organizacion_id=org,
        )

        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            orden = recepcion.recibir_equipo(
                empresa=empresa,
                cliente=cliente,
                equipo=equipo,
                falla_reportada=v["falla_reportada"],
                estado_fisico=v.get("estado_fisico", ""),
                clave_equipo=v.get("clave_equipo", ""),
                accesorios=accesorios,
                revisiones=revisiones,
                tecnico=tecnico,
                sucursal=sucursal,
                tipo_servicio=tipo_servicio,
                prioridad=v.get("prioridad", Prioridad.NORMAL),
                fecha_promesa=v.get("fecha_promesa"),
                acepta_whatsapp=v["acepta_whatsapp"],
            )
            nueva = self.get_queryset().get(pk=orden.pk)
            return 201, json.loads(
                json.dumps(
                    OrdenDetalleSerializer(nueva, context=self.get_serializer_context()).data,
                    default=str,
                )
            )

        codigo, contenido, repetida = ejecutar_idempotente(
            clave=clave,
            metodo=request.method,
            ruta=request.path,
            cuerpo=cuerpo,
            operacion=operacion,
        )
        respuesta = Response(contenido, status=codigo)
        if repetida:
            respuesta["Idempotency-Replayed"] = "true"
        return respuesta

    @extend_schema(tags=TAG)
    @action(
        detail=True, methods=["get"], url_path="clave", throttle_classes=[ApiAutenticadaThrottle]
    )
    def clave(self, request, pk=None):
        """La clave o patrón del equipo. Quien la pide queda en la auditoría."""
        orden = self.get_object()
        registrar(
            "servicio_tecnico.clave_consultada",
            recurso_tipo="orden_servicio",
            recurso_id=orden.pk,
            empresa_id=orden.empresa_id,
            resumen=f"Consultó la clave del equipo de {orden.codigo}",
        )
        respuesta = Response({"clave": orden.clave_equipo})
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    # -- trabajar la orden ---------------------------------------------------------------
    def _ficha(self, orden):
        """La orden ya actualizada, tal como la ve quien la pidió."""
        nueva = self.get_queryset().get(pk=orden.pk)
        return Response(self.get_serializer(nueva).data)

    @extend_schema(tags=TAG, request=CambiarEstadoEntrada, responses={200: OrdenDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="estado")
    def cambiar_estado(self, request, pk=None):
        """Pasa la orden a otro estado. Recepción mueve cualquiera; el técnico, solo los suyos."""
        orden = self.get_object()
        datos = CambiarEstadoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        poder = capacidades_de(request.user, orden)
        if not poder.cambia_estado:
            raise PermissionDenied("No tiene permiso para cambiar el estado de esta orden.")
        nuevo = datos.validated_data["estado"]
        if nuevo == EstadoOrden.ENTREGADO and not poder.entrega:
            raise PermissionDenied("No tiene permiso para entregar equipos.")
        servicios.cambiar_estado(
            orden,
            nuevo,
            motivo=datos.validated_data.get("motivo", ""),
            como_tecnico=not poder.recepcion,
        )
        return self._ficha(orden)

    @extend_schema(tags=TAG, request=DiagnosticoEntrada, responses={200: OrdenDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="diagnostico")
    def diagnostico(self, request, pk=None):
        """Guarda el diagnóstico, los trabajos a realizar, las horas y las notas. Es del técnico."""
        orden = self.get_object()
        if not capacidades_de(request.user, orden).trabaja:
            raise PermissionDenied("No tiene permiso para diagnosticar esta orden.")
        datos = DiagnosticoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        cambios = dict(datos.validated_data)
        tipo = _uno(
            TipoServicio,
            cambios.pop("tipo_servicio", None),
            "tipo_servicio",
            "Elija un tipo de servicio.",
            organizacion_id=orden.empresa.organizacion_id,
        )
        trabajo.registrar_diagnostico(orden, tipo_servicio=tipo, **cambios)
        return self._ficha(orden)

    @extend_schema(tags=TAG, request=AsignarEntrada, responses={200: OrdenDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="asignar")
    def asignar(self, request, pk=None):
        """Asigna el técnico de la orden (o la deja sin técnico con ``tecnico: null``)."""
        orden = self.get_object()
        datos = AsignarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        tecnico = _uno(
            Personal,
            datos.validated_data["tecnico"],
            "tecnico",
            "Elija un técnico de esta empresa.",
            empresa_id=orden.empresa_id,
        )
        trabajo.asignar_tecnico(orden, tecnico)
        return self._ficha(orden)

    @extend_schema(tags=TAG, request=AvisoEntrada, responses={200: OrdenDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="avisos")
    def avisos(self, request, pk=None):
        """Anota que se le avisó al cliente (por WhatsApp, llamada…) y qué se le dijo."""
        orden = self.get_object()
        if not capacidades_de(request.user, orden).recepcion:
            raise PermissionDenied("No tiene permiso para avisar al cliente.")
        datos = AvisoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        trabajo.registrar_aviso(
            orden, medio=datos.validated_data["medio"], mensaje=datos.validated_data["mensaje"]
        )
        return self._ficha(orden)
