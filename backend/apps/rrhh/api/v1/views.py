"""API de los parámetros y catálogos de RR.HH. (de la organización: los comparten sus empresas)."""

from datetime import date

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.mantenimiento import services
from apps.mantenimiento.api.v1.views import MaestroViewSet, _permisos
from apps.mantenimiento.models import EstadoRegistro
from apps.rrhh import catalogos
from apps.rrhh.models import (
    DETALLE_PARAMETROS,
    ConceptoPlanilla,
    Feriado,
    ParametroLaboral,
    RegimenLaboral,
    TasaAfp,
    TipoAsistencia,
    TramoRenta5,
)

from .serializers import (
    ConceptoEntrada,
    ConceptoSerializer,
    FeriadoEntrada,
    FeriadoSerializer,
    ParametroEntrada,
    ParametroSerializer,
    RegimenEntrada,
    RegimenSerializer,
    TasaAfpEntrada,
    TasaAfpSerializer,
    TipoAsistenciaEntrada,
    TipoAsistenciaSerializer,
    TramoRenta5Entrada,
    TramoRenta5Serializer,
)

TAG = ["rrhh"]
PERMISO = "RRHH.PARAMETROS"


class _CatalogoRrhh(MaestroViewSet):
    """Base: catálogo de la organización, con el permiso de parámetros laborales."""

    campo_empresa = None
    campo_propio = "creado_por_id"
    permisos_por_accion = _permisos(PERMISO)


def _fecha(valor: str | None, nombre: str = "fecha") -> date:
    if not valor:
        return date.today()
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({nombre: "Use el formato AAAA-MM-DD."}) from None


# ---------------------------------------------------------------------------
class RegimenViewSet(_CatalogoRrhh):
    """Regímenes laborales (general, pequeña empresa…). ``?q=``, ``?estado=``."""

    modelo = RegimenLaboral
    serializer_class = RegimenSerializer
    entrada = RegimenEntrada
    recurso = "regimen_laboral"
    campo_duplicado = "codigo"
    duplicado = "Ya existe un régimen con ese código."
    campos_busqueda = ("codigo", "nombre")
    ordenes = {"nombre": ("nombre",)}
    orden_por_defecto = ("nombre",)

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=False, methods=["post"])
    def sembrar(self, request):
        return Response({"creadas": catalogos.sembrar_regimenes(request.user.organizacion_id)})


class ParametroViewSet(_CatalogoRrhh):
    """Valores legales con fecha de vigencia. ``?codigo=``, ``?estado=``."""

    modelo = ParametroLaboral
    serializer_class = ParametroSerializer
    entrada = ParametroEntrada
    recurso = "parametro_laboral"
    campo_duplicado = "vigente_desde"
    duplicado = "Ya hay un valor de ese parámetro con esa fecha de vigencia."
    filtros_exactos = ("estado", "codigo")
    campos_busqueda = ("codigo", "nota")
    ordenes = {"reciente": ("-vigente_desde",)}
    orden_por_defecto = ("codigo", "-vigente_desde")

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if "codigo" in validados and validados["codigo"] != instancia.codigo:
            raise ValidationError({"codigo": "El parámetro no se cambia: registra otro valor."})
        return validados

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("fecha", str, description="AAAA-MM-DD (por defecto, hoy)")],
        responses={200: dict},
    )
    @action(detail=False, methods=["get"])
    def resumen(self, request):
        """El valor vigente de cada parámetro en una fecha y cuáles todavía no se cargaron."""
        fecha = _fecha(request.query_params.get("fecha"))
        organizacion = request.user.organizacion_id
        filas = []
        for codigo, (unidad, para_que) in DETALLE_PARAMETROS.items():
            valor = catalogos.valor_vigente(organizacion, codigo, fecha)
            filas.append(
                {
                    "codigo": codigo,
                    "nombre": dict(ParametroLaboral._meta.get_field("codigo").choices)[codigo],
                    "unidad": unidad,
                    "para_que": para_que,
                    "valor": None if valor is None else str(valor),
                    "falta": valor is None,
                }
            )
        return Response(
            {
                "fecha": fecha.isoformat(),
                "parametros": filas,
                "faltan": sum(f["falta"] for f in filas),
            }
        )


class TasaAfpViewSet(_CatalogoRrhh):
    """Tasas de cada AFP con su fecha de vigencia. ``?afp=``, ``?estado=``."""

    modelo = TasaAfp
    serializer_class = TasaAfpSerializer
    entrada = TasaAfpEntrada
    recurso = "tasa_afp"
    campo_duplicado = "vigente_desde"
    duplicado = "Esa AFP ya tiene tasas con esa fecha."
    filtros_exactos = ("estado", "afp")
    campos_busqueda = ("afp", "nota")
    orden_por_defecto = ("afp", "-vigente_desde")

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if "afp" in validados and validados["afp"] != instancia.afp:
            raise ValidationError({"afp": "La AFP no se cambia: registra otras tasas."})
        return validados


class TramoRenta5ViewSet(_CatalogoRrhh):
    """Tramos de la escala de renta de 5.ª categoría, con su vigencia. ``?estado=``."""

    modelo = TramoRenta5
    serializer_class = TramoRenta5Serializer
    entrada = TramoRenta5Entrada
    recurso = "tramo_renta5"
    campo_duplicado = "orden"
    duplicado = "Ya hay un tramo con ese orden en esa escala."
    campos_busqueda = ()
    orden_por_defecto = ("-vigente_desde", "orden")


class TipoAsistenciaViewSet(_CatalogoRrhh):
    """Los códigos de la asistencia diaria. ``?q=``, ``?categoria=``, ``?estado=``."""

    modelo = TipoAsistencia
    serializer_class = TipoAsistenciaSerializer
    entrada = TipoAsistenciaEntrada
    recurso = "tipo_asistencia"
    campo_duplicado = "codigo"
    duplicado = "Ya existe un tipo con ese código."
    filtros_exactos = ("estado", "categoria")
    campos_busqueda = ("codigo", "nombre")
    orden_por_defecto = ("codigo",)

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=False, methods=["post"])
    def sembrar(self, request):
        return Response(
            {"creadas": catalogos.sembrar_tipos_asistencia(request.user.organizacion_id)}
        )


class FeriadoViewSet(_CatalogoRrhh):
    """Los feriados del calendario. ``?anio=2026``, ``?q=``."""

    modelo = Feriado
    serializer_class = FeriadoSerializer
    entrada = FeriadoEntrada
    recurso = "feriado"
    campo_duplicado = "fecha"
    duplicado = "Ya hay un feriado en esa fecha."
    campos_busqueda = ("nombre",)
    orden_por_defecto = ("-fecha",)

    def get_queryset(self):
        queryset = super().get_queryset()
        anio = self.request.query_params.get("anio")
        if anio:
            if not anio.isdigit() or not 1900 <= int(anio) <= 2100:
                raise ValidationError({"anio": "Indique un año válido."})
            queryset = queryset.filter(fecha__year=int(anio))
        return queryset


class ConceptoViewSet(_CatalogoRrhh):
    """Los conceptos de la planilla. ``?q=``, ``?tipo=``, ``?estado=``."""

    modelo = ConceptoPlanilla
    serializer_class = ConceptoSerializer
    entrada = ConceptoEntrada
    recurso = "concepto_planilla"
    campo_duplicado = "codigo"
    duplicado = "Ya existe un concepto con ese código."
    filtros_exactos = ("estado", "tipo")
    campos_busqueda = ("codigo", "nombre", "codigo_plame")
    orden_por_defecto = ("tipo", "orden", "nombre")

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if instancia.es_del_sistema:
            for campo in ("codigo", "tipo"):
                if campo in validados and validados[campo] != getattr(instancia, campo):
                    raise ValidationError(
                        {campo: "Lo usa el cálculo de la planilla: no se puede cambiar."}
                    )
            if validados.get("estado") == EstadoRegistro.INACTIVO:
                raise ValidationError({"estado": "Lo usa la planilla: no se puede desactivar."})
        return validados

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        if instancia.es_del_sistema:
            raise ValidationError("Lo usa el cálculo de la planilla: no se puede eliminar.")
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=False, methods=["post"])
    def sembrar(self, request):
        return Response({"creadas": catalogos.sembrar_conceptos(request.user.organizacion_id)})
