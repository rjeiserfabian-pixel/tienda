"""API de la ficha laboral y los contratos de los trabajadores (por empresa).

Qué ve cada quien:

* ``RRHH.TRABAJADORES.VER``: la ficha, los datos laborales y los contratos (sin sueldos ni cuentas).
* ``RRHH.SUELDOS.VER``: además los sueldos, su historial y los últimos dígitos de la cuenta.
* ``RRHH.TRABAJADORES.EDITAR``: editar la ficha y los contratos; ``RRHH.SUELDOS.EDITAR``: cambiar
  sueldos y cuentas bancarias. La cuenta completa nunca sale por la API.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Exists, OuterRef, Prefetch, Q
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import Banco, Personal
from apps.rrhh import trabajadores
from apps.rrhh.models import (
    CategoriaTrabajador,
    ContratoLaboral,
    EstadoContrato,
    MetodoPago,
    NombreAfp,
    RegimenLaboral,
    Sexo,
    SistemaPension,
    TipoComision,
    TipoContrato,
)
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

TAG = ["rrhh"]
CENTAVO = Decimal("0.01")
VER = "RRHH.TRABAJADORES.VER"
EDITAR = "RRHH.TRABAJADORES.EDITAR"
SUELDOS_VER = "RRHH.SUELDOS.VER"
SUELDOS_EDITAR = "RRHH.SUELDOS.EDITAR"


def _entero(params, nombre: str) -> int | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    if not str(valor).isdigit():
        raise ValidationError({nombre: "Debe ser un número entero."})
    return int(valor)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class DatosLaboralesEntrada(serializers.Serializer):
    """Todo es opcional: solo se cambia lo que se envía. La cuenta vacía = no cambia."""

    sexo = serializers.ChoiceField(choices=Sexo.choices, required=False, allow_blank=True)
    nacionalidad = serializers.CharField(max_length=40, required=False)
    sistema_pension = serializers.ChoiceField(choices=SistemaPension.choices, required=False)
    afp = serializers.ChoiceField(choices=NombreAfp.choices, required=False, allow_blank=True)
    tipo_comision = serializers.ChoiceField(
        choices=TipoComision.choices, required=False, allow_blank=True
    )
    cuspp = serializers.CharField(max_length=12, required=False, allow_blank=True)
    asignacion_familiar = serializers.BooleanField(required=False)
    paga_renta_5ta = serializers.BooleanField(required=False)
    subsidio_descanso_medico = serializers.BooleanField(required=False)
    metodo_pago = serializers.ChoiceField(choices=MetodoPago.choices, required=False)
    banco = serializers.ChoiceField(choices=Banco.choices, required=False, allow_blank=True)
    numero_cuenta = serializers.CharField(max_length=30, required=False, allow_blank=True)
    cci = serializers.CharField(max_length=20, required=False, allow_blank=True)


class ContratoEntrada(serializers.Serializer):
    regimen = serializers.IntegerField(min_value=1)
    tipo_contrato = serializers.ChoiceField(choices=TipoContrato.choices, required=False)
    categoria = serializers.ChoiceField(choices=CategoriaTrabajador.choices, required=False)
    cargo = serializers.CharField(max_length=100)
    fecha_inicio = serializers.DateField()
    fecha_fin = serializers.DateField(required=False, allow_null=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    sueldo = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=CENTAVO)


class ContratoEdicion(serializers.Serializer):
    regimen = serializers.IntegerField(min_value=1, required=False)
    tipo_contrato = serializers.ChoiceField(choices=TipoContrato.choices, required=False)
    categoria = serializers.ChoiceField(choices=CategoriaTrabajador.choices, required=False)
    cargo = serializers.CharField(max_length=100, required=False)
    fecha_fin = serializers.DateField(required=False, allow_null=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)


class FinalizarEntrada(serializers.Serializer):
    fecha_cese = serializers.DateField()
    motivo = serializers.CharField(max_length=200)


class SueldoEntrada(serializers.Serializer):
    monto = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=CENTAVO)
    vigente_desde = serializers.DateField()
    motivo = serializers.CharField(max_length=100, required=False, allow_blank=True)


# ---------------------------------------------------------------------------
# Salida (armada a mano para ocultar sueldos y cuentas a quien no corresponde)
# ---------------------------------------------------------------------------
def _contrato_json(contrato: ContratoLaboral, *, ver_sueldos: bool, hoy) -> dict:
    datos = {
        "id": contrato.pk,
        "regimen": contrato.regimen_id,
        "regimen_nombre": contrato.regimen.nombre,
        "tipo_contrato": contrato.tipo_contrato,
        "tipo_nombre": contrato.get_tipo_contrato_display(),
        "categoria": contrato.categoria,
        "categoria_nombre": contrato.get_categoria_display(),
        "cargo": contrato.cargo,
        "fecha_inicio": contrato.fecha_inicio,
        "fecha_fin": contrato.fecha_fin,
        "estado": contrato.estado,
        "fecha_cese": contrato.fecha_cese,
        "motivo_cese": contrato.motivo_cese,
        "observacion": contrato.observacion,
        "dias_para_vencer": trabajadores.dias_para_vencer(contrato, hoy),
    }
    if ver_sueldos:
        cambios = list(contrato.cambios_sueldo.all())  # ya viene ordenado, el último primero
        datos["sueldo_actual"] = trabajadores.sueldo_vigente(contrato, hoy)
        datos["cambios_sueldo"] = [
            {"id": c.pk, "monto": c.monto, "vigente_desde": c.vigente_desde, "motivo": c.motivo}
            for c in cambios
        ]
    return datos


def _datos_json(datos, *, ver_sueldos: bool) -> dict | None:
    if datos is None:
        return None
    salida = {
        "sexo": datos.sexo,
        "nacionalidad": datos.nacionalidad,
        "sistema_pension": datos.sistema_pension,
        "afp": datos.afp,
        "tipo_comision": datos.tipo_comision,
        "cuspp": datos.cuspp,
        "asignacion_familiar": datos.asignacion_familiar,
        "paga_renta_5ta": datos.paga_renta_5ta,
        "subsidio_descanso_medico": datos.subsidio_descanso_medico,
        "metodo_pago": datos.metodo_pago,
    }
    if ver_sueldos:
        # La cuenta completa nunca sale: solo se sabe si está puesta y cómo termina.
        salida |= {
            "banco": datos.banco,
            "cuenta_puesta": bool(datos.numero_cuenta),
            "cuenta_final": (datos.numero_cuenta or "")[-4:],
            "cci_puesto": bool(datos.cci),
            "cci_final": (datos.cci or "")[-4:],
        }
    return salida


def _personal_json(p: Personal) -> dict:
    return {
        "id": p.pk,
        "empresa": p.empresa_id,
        "nombres": p.nombres,
        "apellidos": p.apellidos,
        "nombre_completo": p.nombre_completo,
        "tipo_documento": p.tipo_documento,
        "numero_documento": p.numero_documento,
        "area": p.area,
        "cargo": p.cargo,
        "fecha_nacimiento": p.fecha_nacimiento,
        "fecha_ingreso": p.fecha_ingreso,
        "direccion": p.direccion,
        "telefono": p.telefono,
        "correo": p.correo,
        "estado": p.estado,
    }


def _resumen_contrato(contrato, hoy) -> dict | None:
    if contrato is None:
        return None
    return {
        "id": contrato.pk,
        "regimen_nombre": contrato.regimen.nombre,
        "tipo_contrato": contrato.tipo_contrato,
        "tipo_nombre": contrato.get_tipo_contrato_display(),
        "cargo": contrato.cargo,
        "fecha_inicio": contrato.fecha_inicio,
        "fecha_fin": contrato.fecha_fin,
        "dias_para_vencer": trabajadores.dias_para_vencer(contrato, hoy),
    }


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------
class _PorEmpresa:
    """Lo común: la empresa sale del propio registro, o se declara al listar."""

    requiere_empresa = True
    _modelo_de_pk = None

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                self._modelo_de_pk.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]


class TrabajadorViewSet(
    _PorEmpresa,
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Trabajadores de una empresa (``?empresa=ID``) con su contrato vigente y lo que les falta.

    Filtros: ``q``, ``estado`` y ``contrato`` (``vigente``, ``sin_contrato``, ``por_vencer`` o
    ``vencido``). Los trabajadores se registran en Mantenimiento › Personal.
    """

    modelo = Personal
    _modelo_de_pk = Personal
    campo_propio = None
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "patch", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "datos_laborales": EDITAR,
        "contratos": EDITAR,
    }

    def get_queryset(self):
        queryset = super().get_queryset().select_related("datos_laborales", "empresa")
        if self.action == "retrieve":
            return queryset.prefetch_related(
                Prefetch(
                    "contratos",
                    queryset=ContratoLaboral.objects.select_related("regimen").prefetch_related(
                        "cambios_sueldo"
                    ),
                )
            )
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if q := " ".join((params.get("q") or "").split()):
            queryset = queryset.filter(
                Q(nombres__icontains=q)
                | Q(apellidos__icontains=q)
                | Q(numero_documento__icontains=q)
                | Q(cargo__icontains=q)
            )
        hoy = timezone.localdate()
        vigentes = ContratoLaboral.objects.filter(
            personal=OuterRef("pk"), estado=EstadoContrato.VIGENTE
        )
        filtro = params.get("contrato", "")
        if filtro == "vigente":
            queryset = queryset.filter(Exists(vigentes))
        elif filtro == "sin_contrato":
            queryset = queryset.filter(~Exists(vigentes))
        elif filtro == "por_vencer":
            limite = hoy + timedelta(days=trabajadores.AVISO_VENCIMIENTO)
            queryset = queryset.filter(
                Exists(
                    vigentes.filter(
                        fecha_fin__isnull=False, fecha_fin__gte=hoy, fecha_fin__lte=limite
                    )
                )
            )
        elif filtro == "vencido":
            queryset = queryset.filter(Exists(vigentes.filter(fecha_fin__lt=hoy)))
        elif filtro:
            raise ValidationError({"contrato": "Use vigente, sin_contrato, por_vencer o vencido."})
        return queryset.prefetch_related(
            Prefetch(
                "contratos",
                queryset=ContratoLaboral.objects.filter(
                    estado=EstadoContrato.VIGENTE
                ).select_related("regimen"),
                to_attr="vigentes",
            )
        ).order_by("apellidos", "nombres", "id")

    # -- lectura -------------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("q", str),
            OpenApiParameter("estado", str),
            OpenApiParameter(
                "contrato", str, enum=["vigente", "sin_contrato", "por_vencer", "vencido"]
            ),
        ],
        responses={200: dict},
    )
    def list(self, request, *args, **kwargs):
        pagina = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        hoy = timezone.localdate()
        filas = []
        for p in pagina:
            contrato = p.vigentes[0] if p.vigentes else None
            datos = getattr(p, "datos_laborales", None)
            filas.append(
                {
                    **_personal_json(p),
                    "contrato": _resumen_contrato(contrato, hoy),
                    "faltantes": trabajadores.faltantes_ficha(p, datos, contrato),
                }
            )
        return self.get_paginated_response(filas)

    def retrieve(self, request, *args, **kwargs):
        return Response(self._ficha(self.get_object()))

    def _ficha(self, personal: Personal) -> dict:
        """La ficha completa; los sueldos y la cuenta solo si el usuario tiene el permiso."""
        ver = motor.tiene_permiso(self.request.user, SUELDOS_VER, personal.empresa_id)
        hoy = timezone.localdate()
        # Se vuelve a leer: después de una edición los datos cacheados quedarían viejos.
        personal = (
            Personal.objects.select_related("datos_laborales", "empresa")
            .prefetch_related(
                Prefetch(
                    "contratos",
                    queryset=ContratoLaboral.objects.select_related("regimen").prefetch_related(
                        "cambios_sueldo"
                    ),
                )
            )
            .get(pk=personal.pk)
        )
        contratos = list(personal.contratos.all())
        vigente = next((c for c in contratos if c.vigente), None)
        datos = getattr(personal, "datos_laborales", None)
        return {
            "personal": _personal_json(personal),
            "datos_laborales": _datos_json(datos, ver_sueldos=ver),
            "contratos": [_contrato_json(c, ver_sueldos=ver, hoy=hoy) for c in contratos],
            "faltantes": trabajadores.faltantes_ficha(personal, datos, vigente),
            "permisos": {
                "editar": motor.tiene_permiso(self.request.user, EDITAR, personal.empresa_id),
                "ver_sueldos": ver,
                "editar_sueldos": motor.tiene_permiso(
                    self.request.user, SUELDOS_EDITAR, personal.empresa_id
                ),
            },
        }

    # -- escritura -----------------------------------------------------------------
    @extend_schema(tags=TAG, request=DatosLaboralesEntrada, responses={200: dict})
    @action(detail=True, methods=["patch"], url_path="datos-laborales")
    def datos_laborales(self, request, pk=None):
        personal = self.get_object()
        entrada = DatosLaboralesEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        puede = motor.tiene_permiso(request.user, SUELDOS_EDITAR, personal.empresa_id)
        trabajadores.guardar_datos_laborales(
            personal, dict(entrada.validated_data), puede_cuenta=puede
        )
        return Response(self._ficha(personal))

    @extend_schema(tags=TAG, request=ContratoEntrada, responses={201: dict})
    @action(detail=True, methods=["post"], url_path="contratos")
    def contratos(self, request, pk=None):
        personal = self.get_object()
        # El sueldo inicial es un dato sensible: exige su propio permiso.
        motor.exigir_permiso(request.user, SUELDOS_EDITAR, personal.empresa_id)
        entrada = ContratoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = dict(entrada.validated_data)
        regimen = RegimenLaboral.objects.filter(pk=v["regimen"]).first()
        if regimen is None:
            raise ValidationError({"regimen": "Elija un régimen de la lista."})
        contrato, avisos = trabajadores.crear_contrato(
            personal,
            regimen=regimen,
            tipo_contrato=v.get("tipo_contrato", TipoContrato.INDETERMINADO),
            categoria=v.get("categoria", CategoriaTrabajador.EMPLEADO),
            cargo=v["cargo"],
            fecha_inicio=v["fecha_inicio"],
            fecha_fin=v.get("fecha_fin"),
            sueldo=v["sueldo"],
            observacion=v.get("observacion", ""),
        )
        return Response(
            {**self._ficha(personal), "contrato_creado": contrato.pk, "avisos": avisos}, status=201
        )


class ContratoViewSet(_PorEmpresa, ScopedQuerysetMixin, viewsets.GenericViewSet):
    """Acciones sobre un contrato: corregirlo, finalizarlo y cambiarle el sueldo."""

    modelo = ContratoLaboral
    _modelo_de_pk = ContratoLaboral
    campo_propio = None
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    http_method_names = ["patch", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    permisos_por_accion = {
        "partial_update": EDITAR,
        "finalizar": EDITAR,
        "sueldos": SUELDOS_EDITAR,
    }

    def get_queryset(self):
        return super().get_queryset().select_related("regimen", "personal")

    def _ficha(self, contrato: ContratoLaboral, extra: dict | None = None) -> Response:
        vista = TrabajadorViewSet()
        vista.request = self.request
        return Response({**vista._ficha(contrato.personal), **(extra or {})})

    @extend_schema(tags=TAG, request=ContratoEdicion, responses={200: dict})
    def partial_update(self, request, pk=None):
        contrato = self.get_object()
        entrada = ContratoEdicion(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        if "regimen" in datos:
            regimen = RegimenLaboral.objects.filter(pk=datos["regimen"]).first()
            if regimen is None:
                raise ValidationError({"regimen": "Elija un régimen de la lista."})
            datos["regimen"] = regimen
        if datos:
            trabajadores.actualizar_contrato(contrato, datos)
        return self._ficha(contrato)

    @extend_schema(tags=TAG, request=FinalizarEntrada, responses={200: dict})
    @action(detail=True, methods=["post"])
    def finalizar(self, request, pk=None):
        contrato = self.get_object()
        entrada = FinalizarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        trabajadores.finalizar_contrato(
            contrato,
            fecha_cese=entrada.validated_data["fecha_cese"],
            motivo=entrada.validated_data["motivo"],
        )
        return self._ficha(contrato)

    @extend_schema(tags=TAG, request=SueldoEntrada, responses={200: dict})
    @action(detail=True, methods=["post"])
    def sueldos(self, request, pk=None):
        contrato = self.get_object()
        entrada = SueldoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        _, avisos = trabajadores.registrar_cambio_sueldo(
            contrato, monto=v["monto"], vigente_desde=v["vigente_desde"], motivo=v.get("motivo", "")
        )
        return self._ficha(contrato, {"avisos": avisos})
