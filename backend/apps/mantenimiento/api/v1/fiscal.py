"""API fiscal: comprobantes, afectaciones y tasas del IGV, régimen por empresa y sugerencia."""

from datetime import date, timedelta

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import diferencia, registrar
from apps.mantenimiento import fiscal, services
from apps.mantenimiento.exceptions import RegistroEnUso
from apps.mantenimiento.models import (
    AfectacionIGV,
    Cliente,
    EstadoRegistro,
    Producto,
    Proveedor,
    TasaImpuesto,
    TipoComprobante,
    ZonaFiscal,
)
from apps.organizacion.models import ConfiguracionEmpresa, Empresa, RegimenIgv
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

from .views import MaestroViewSet, _permisos

TAG = ["fiscal"]
VER_IGV = "MANTENIMIENTO.IGV.VER"
EDITAR_IGV = "MANTENIMIENTO.IGV.EDITAR"
# Sin estas dos afectaciones el sistema no puede proponer el IGV de una operación.
AFECTACIONES_BASE = frozenset({"10", "20"})


def _booleano(params, nombre: str) -> bool | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    if valor not in ("0", "1"):
        raise ValidationError({nombre: "Use 1 o 0."})
    return valor == "1"


# ---------------------------------------------------------------------------
# Tipos de comprobante
# ---------------------------------------------------------------------------
class TipoComprobanteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoComprobante
        fields = (
            "id",
            "codigo",
            "nombre",
            "abreviatura",
            "es_electronico",
            "aplica_compras",
            "aplica_ventas",
            "lleva_igv",
            "ejemplo_serie",
            "patron_serie",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class TipoComprobanteEntrada(serializers.Serializer):
    codigo = serializers.RegexField(r"^\d{2}$", required=False)
    nombre = serializers.CharField(max_length=80)
    abreviatura = serializers.CharField(max_length=10)
    es_electronico = serializers.BooleanField(required=False)
    aplica_compras = serializers.BooleanField(required=False)
    aplica_ventas = serializers.BooleanField(required=False)
    lleva_igv = serializers.BooleanField(required=False)
    ejemplo_serie = serializers.CharField(max_length=10, required=False, allow_blank=True)
    patron_serie = serializers.CharField(max_length=60, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class TipoComprobanteViewSet(MaestroViewSet):
    """Tipos de comprobante de la organización (``?q=``, ``?estado=``, ``?aplica_compras=1``).

    Un tipo que ya usó algún movimiento no se elimina: se desactiva. El código SUNAT no cambia.
    """

    modelo = TipoComprobante
    campo_empresa = None
    serializer_class = TipoComprobanteSerializer
    entrada = TipoComprobanteEntrada
    recurso = "tipo_comprobante"
    duplicado = "Ya existe un tipo de comprobante con ese código."
    campo_duplicado = "codigo"
    permisos_por_accion = _permisos("MANTENIMIENTO.COMPROBANTES")
    campos_busqueda = ("codigo", "nombre", "abreviatura")
    ordenes = {"codigo": ("codigo",), "nombre": ("nombre",)}
    orden_por_defecto = ("codigo",)

    def get_queryset(self):
        queryset = super().get_queryset()
        for campo in ("aplica_compras", "aplica_ventas", "es_electronico"):
            valor = _booleano(self.request.query_params, campo)
            if valor is not None:
                queryset = queryset.filter(**{campo: valor})
        return queryset

    def datos_de_alta(self, validados: dict) -> dict:
        if "codigo" not in validados:
            raise ValidationError({"codigo": "Ingrese el código SUNAT (2 números)."})
        validados.setdefault("estado", EstadoRegistro.ACTIVO)
        return super().datos_de_alta(validados)

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if validados.pop("codigo", instancia.codigo) != instancia.codigo:
            raise ValidationError({"codigo": "El código SUNAT no se puede cambiar."})
        return validados

    def destroy(self, request, *args, **kwargs):
        from apps.inventario.models import MovimientoInventario

        instancia = self.get_object()
        usado = (
            MovimientoInventario.objects.sin_ambito()
            .filter(empresa__organizacion_id=instancia.organizacion_id)
            .filter(comprobante_tipo=instancia.codigo)
            .exists()
        )
        if usado:
            raise RegistroEnUso("Ya hay movimientos con este comprobante. Desactívalo.")
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Afectaciones del IGV (catálogo 07 de SUNAT): se ajustan, no se crean ni se borran
# ---------------------------------------------------------------------------
class AfectacionIGVSerializer(serializers.ModelSerializer):
    grupo_nombre = serializers.CharField(source="get_grupo_display", read_only=True)
    impuesto_nombre = serializers.CharField(source="get_impuesto_display", read_only=True)

    class Meta:
        model = AfectacionIGV
        fields = (
            "id",
            "codigo",
            "nombre",
            "grupo",
            "grupo_nombre",
            "impuesto",
            "impuesto_nombre",
            "gratuita",
            "aplica_compras",
            "aplica_ventas",
            "estado",
        )
        read_only_fields = fields


class AfectacionIGVEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=100, required=False)
    aplica_compras = serializers.BooleanField(required=False)
    aplica_ventas = serializers.BooleanField(required=False)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class AfectacionIGVViewSet(MaestroViewSet):
    """Afectaciones del IGV (``?q=``, ``?estado=``, ``?grupo=``, ``?aplica_compras=1``)."""

    modelo = AfectacionIGV
    campo_empresa = None
    serializer_class = AfectacionIGVSerializer
    entrada = AfectacionIGVEntrada
    recurso = "afectacion_igv"
    duplicado = "Ya existe una afectación con ese código."
    campo_duplicado = "codigo"
    http_method_names = ["get", "patch", "head", "options"]
    permisos_por_accion = _permisos("MANTENIMIENTO.IGV")
    campos_busqueda = ("codigo", "nombre")
    filtros_exactos = ("estado", "grupo")
    ordenes = {"codigo": ("codigo",)}
    orden_por_defecto = ("codigo",)

    def get_queryset(self):
        queryset = super().get_queryset()
        for campo in ("aplica_compras", "aplica_ventas"):
            valor = _booleano(self.request.query_params, campo)
            if valor is not None:
                queryset = queryset.filter(**{campo: valor})
        return queryset

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        base = instancia.codigo in AFECTACIONES_BASE
        if base and validados.get("estado") == EstadoRegistro.INACTIVO:
            raise ValidationError(
                {"estado": "Gravado y Exonerado son la base del sistema: no se desactivan."}
            )
        if base and (
            validados.get("aplica_compras") is False or validados.get("aplica_ventas") is False
        ):
            raise ValidationError(
                {"aplica_compras": "Gravado y Exonerado deben ofrecerse en compras y ventas."}
            )
        return validados


# ---------------------------------------------------------------------------
# Tasas de impuesto con vigencia: solo se agregan; las ya iniciadas no se tocan
# ---------------------------------------------------------------------------
class TasaImpuestoSerializer(serializers.ModelSerializer):
    impuesto_nombre = serializers.CharField(source="get_impuesto_display", read_only=True)
    vigente_hasta = serializers.SerializerMethodField()
    situacion = serializers.SerializerMethodField()

    class Meta:
        model = TasaImpuesto
        fields = (
            "id",
            "impuesto",
            "impuesto_nombre",
            "porcentaje",
            "vigente_desde",
            "vigente_hasta",
            "situacion",
            "creado_en",
        )
        read_only_fields = fields

    def _siguiente(self, tasa) -> date | None:
        # Las tasas del mismo impuesto, de la más antigua a la más nueva (las precarga la vista).
        fechas = self.context.get("fechas", {}).get(tasa.impuesto, [])
        posteriores = [f for f in fechas if f > tasa.vigente_desde]
        return posteriores[0] if posteriores else None

    def get_vigente_hasta(self, tasa) -> date | None:
        siguiente = self._siguiente(tasa)
        return siguiente - timedelta(days=1) if siguiente else None

    def get_situacion(self, tasa) -> str:
        """``FUTURA`` aún no empieza; ``VIGENTE`` rige hoy; ``ANTERIOR`` ya fue reemplazada."""
        hoy = timezone.localdate()
        if tasa.vigente_desde > hoy:
            return "FUTURA"
        siguiente = self._siguiente(tasa)
        return "VIGENTE" if siguiente is None or siguiente > hoy else "ANTERIOR"


class TasaImpuestoEntrada(serializers.Serializer):
    impuesto = serializers.ChoiceField(choices=TasaImpuesto.Impuesto.choices)
    porcentaje = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100
    )
    vigente_desde = serializers.DateField()

    def validate_vigente_desde(self, valor: date) -> date:
        hoy = timezone.localdate()
        if valor < date(2000, 1, 1):
            raise serializers.ValidationError("La fecha no puede ser anterior al año 2000.")
        if valor > hoy + timedelta(days=730):
            raise serializers.ValidationError("La fecha no puede pasar de dos años desde hoy.")
        return valor


class TasaImpuestoViewSet(MaestroViewSet):
    """Tasas del IGV y del IVAP (``?impuesto=``).

    Cuando la ley cambia el porcentaje se agrega una tasa nueva desde su fecha. Para corregir un
    error se edita el porcentaje o la fecha, pero solo mientras ningún documento haya usado esa
    tasa; si ya la usó, queda como historia. Solo se elimina una tasa futura.
    """

    modelo = TasaImpuesto
    campo_empresa = None
    serializer_class = TasaImpuestoSerializer
    entrada = TasaImpuestoEntrada
    recurso = "tasa_impuesto"
    duplicado = "Ya hay una tasa de ese impuesto desde esa fecha."
    campo_duplicado = "vigente_desde"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permisos_por_accion = _permisos("MANTENIMIENTO.IGV")
    campos_busqueda = ()
    filtros_exactos = ("impuesto",)
    ordenes = {"fecha": ("-vigente_desde",)}
    orden_por_defecto = ("impuesto", "-vigente_desde")

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        fechas: dict[str, list[date]] = {}
        todas = TasaImpuesto.objects.values_list("impuesto", "vigente_desde").order_by(
            "vigente_desde"
        )
        for impuesto, desde in todas:
            fechas.setdefault(impuesto, []).append(desde)
        contexto["fechas"] = fechas
        return contexto

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if validados.pop("impuesto", instancia.impuesto) != instancia.impuesto:
            raise ValidationError({"impuesto": "El impuesto de una tasa no se puede cambiar."})
        nueva_fecha = validados.get("vigente_desde", instancia.vigente_desde)
        hoy = timezone.localdate()
        fechas = {instancia.vigente_desde, nueva_fecha}
        for desde in sorted(fechas):
            ya_rige = desde <= hoy and (desde == instancia.vigente_desde or nueva_fecha <= hoy)
            if ya_rige and fiscal.tasa_en_uso(
                instancia.organizacion_id, instancia.impuesto, desde, excluir_pk=instancia.pk
            ):
                raise RegistroEnUso(
                    "Ya hay documentos registrados con esta tasa. Para el cambio, agrega una "
                    "tasa nueva desde su fecha: así lo anterior no se altera."
                )
        return validados

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        if instancia.vigente_desde <= timezone.localdate():
            raise RegistroEnUso(
                "Una tasa que ya empezó queda como historia. Agrega una nueva desde la fecha "
                "del cambio."
            )
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Régimen del IGV de una empresa
# ---------------------------------------------------------------------------
class ConfiguracionIgvEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    regimen_igv = serializers.ChoiceField(choices=RegimenIgv.choices, required=False)
    igv_compras_al_costo = serializers.BooleanField(required=False)


def _configuracion_de(empresa_id: int) -> tuple[Empresa, ConfiguracionEmpresa]:
    # El gestor de empresas ya limita a la organización de la sesión.
    empresa = Empresa.objects.filter(pk=empresa_id).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa."})
    configuracion = ConfiguracionEmpresa.objects.sin_ambito().filter(empresa=empresa).first()
    if configuracion is None:
        configuracion = ConfiguracionEmpresa.objects.sin_ambito().create(empresa=empresa)
    return empresa, configuracion


def _config_json(configuracion: ConfiguracionEmpresa) -> dict:
    return {
        "empresa": configuracion.empresa_id,
        "regimen_igv": configuracion.regimen_igv,
        "regimen_nombre": configuracion.get_regimen_igv_display(),
        "igv_compras_al_costo": configuracion.igv_compras_al_costo,
    }


class ConfiguracionIgvView(APIView):
    """Régimen del IGV de una empresa (``?empresa=ID``): ver y cambiar."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER_IGV, "patch": EDITAR_IGV}
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        _, configuracion = _configuracion_de(empresa_declarada(request, self))
        return Response(_config_json(configuracion))

    @extend_schema(tags=TAG, request=ConfiguracionIgvEntrada)
    def patch(self, request):
        datos = ConfiguracionIgvEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        validados = dict(datos.validated_data)
        empresa, configuracion = _configuracion_de(validados.pop("empresa"))
        antes = _config_json(configuracion)
        for campo, valor in validados.items():
            setattr(configuracion, campo, valor)
        if validados:
            configuracion.save(update_fields=list(validados))
            registrar(
                "empresa.igv_configurado",
                recurso_tipo="empresa",
                recurso_id=empresa.pk,
                empresa_id=empresa.pk,
                resumen=f"Se cambió el régimen del IGV de {empresa.razon_social}",
                detalle=diferencia(antes, _config_json(configuracion)),
            )
        return Response(_config_json(configuracion))


# ---------------------------------------------------------------------------
# Sugerencia de afectación para una compra o venta
# ---------------------------------------------------------------------------
class SugerenciaIgvView(APIView):
    """Qué afectación del IGV corresponde a una línea (``empresa`` y ``operacion`` obligatorias).

    Parámetros opcionales: ``proveedor`` o ``cliente`` (su zona), ``zona`` (si no se manda el
    tercero), ``producto`` (puede tener su propia afectación) y ``fecha`` (para la tasa).
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER_IGV
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @staticmethod
    def _entero(params, nombre: str) -> int | None:
        valor = params.get(nombre)
        if valor in (None, ""):
            return None
        if not str(valor).isdigit():
            raise ValidationError({nombre: "Debe ser un número entero."})
        return int(valor)

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("operacion", str, required=True, enum=["COMPRA", "VENTA"]),
            OpenApiParameter("proveedor", int),
            OpenApiParameter("cliente", int),
            OpenApiParameter("zona", str, enum=ZonaFiscal.values),
            OpenApiParameter("producto", int),
            OpenApiParameter("fecha", str, description="AAAA-MM-DD"),
        ],
        responses={200: dict},
    )
    def get(self, request):
        p = request.query_params
        operacion = p.get("operacion")
        if operacion not in (fiscal.COMPRA, fiscal.VENTA):
            raise ValidationError({"operacion": "Use COMPRA o VENTA."})
        empresa = Empresa.objects.filter(pk=empresa_declarada(request, self)).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa."})

        zona = p.get("zona", "")
        if zona and zona not in ZonaFiscal.values:
            raise ValidationError({"zona": "Use DENTRO o FUERA."})
        proveedor, cliente = self._entero(p, "proveedor"), self._entero(p, "cliente")
        tercero = None
        if proveedor is not None:
            tercero = Proveedor.objects.filter(pk=proveedor).first()
        elif cliente is not None:
            tercero = Cliente.objects.filter(pk=cliente).first()
        if (proveedor is not None or cliente is not None) and tercero is None:
            raise ValidationError({"proveedor" if proveedor else "cliente": "No existe."})
        if tercero is not None:
            zona = tercero.zona

        producto = None
        if (producto_id := self._entero(p, "producto")) is not None:
            producto = (
                Producto.objects.select_related("afectacion_igv").filter(pk=producto_id).first()
            )
            if producto is None:
                raise ValidationError({"producto": "No existe."})
        fecha = None
        if p.get("fecha"):
            try:
                fecha = date.fromisoformat(p["fecha"])
            except ValueError:
                raise ValidationError({"fecha": "Use el formato AAAA-MM-DD."}) from None

        sugerencia = fiscal.sugerir_afectacion(
            empresa=empresa, operacion=operacion, zona=zona, producto=producto, fecha=fecha
        )
        configuracion = ConfiguracionEmpresa.objects.sin_ambito().filter(empresa=empresa).first()
        a = sugerencia.afectacion
        return Response(
            {
                "afectacion": {
                    "id": a.pk,
                    "codigo": a.codigo,
                    "nombre": a.nombre,
                    "grupo": a.grupo,
                    "impuesto": a.impuesto,
                },
                "porcentaje": str(sugerencia.porcentaje),
                "motivo": sugerencia.motivo,
                "zona": zona,
                "igv_compras_al_costo": bool(configuracion and configuracion.igv_compras_al_costo),
            }
        )
