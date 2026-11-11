"""API de las series de comprobantes que emite cada empresa y su numeración."""

from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.mantenimiento import series, services
from apps.mantenimiento.exceptions import RegistroEnUso
from apps.mantenimiento.models import EstadoRegistro, SerieComprobante, TipoComprobante
from apps.organizacion.models import Estado, Sucursal

from .views import MaestroViewSet, _permisos, _PorEmpresaMixin


class SerieComprobanteSerializer(serializers.ModelSerializer):
    tipo_codigo = serializers.CharField(source="tipo_comprobante.codigo", read_only=True)
    tipo_nombre = serializers.CharField(source="tipo_comprobante.nombre", read_only=True)
    sucursal_nombre = serializers.CharField(source="sucursal.nombre", default=None, read_only=True)
    proximo = serializers.SerializerMethodField()
    usada = serializers.SerializerMethodField()

    class Meta:
        model = SerieComprobante
        fields = (
            "id",
            "empresa",
            "tipo_comprobante",
            "tipo_codigo",
            "tipo_nombre",
            "serie",
            "nombre",
            "sucursal",
            "sucursal_nombre",
            "es_electronica",
            "ultimo_numero",
            "proximo",
            "emitidos",
            "usada",
            "estado",
            "creado_en",
        )
        read_only_fields = fields

    def get_proximo(self, serie) -> str:
        """El comprobante que saldría ahora, por ejemplo ``F001-00000001``."""
        return series.formatear(serie.serie, serie.proximo_numero)

    def get_usada(self, serie) -> bool:
        return serie.emitidos > 0


class SerieComprobanteEntrada(serializers.Serializer):
    """``empresa`` y ``tipo_comprobante`` se envían al crear; después solo si la serie no emitió."""

    empresa = serializers.IntegerField(min_value=1, required=False)
    tipo_comprobante = serializers.IntegerField(min_value=1, required=False)
    serie = serializers.CharField(max_length=12)  # el modelo limpia y exige hasta 4
    nombre = serializers.CharField(max_length=80, required=False, allow_blank=True)
    sucursal = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    es_electronica = serializers.BooleanField(required=False)
    ultimo_numero = serializers.IntegerField(
        min_value=0, max_value=SerieComprobante.MAXIMO_NUMERO, required=False
    )
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)

    def validate_serie(self, valor: str) -> str:
        """Sin espacios y en mayúsculas, antes de que el modelo revise el largo."""
        return "".join(valor.split()).upper()


class SerieComprobanteViewSet(_PorEmpresaMixin, MaestroViewSet):
    """Series de comprobantes de venta de cada empresa (``?empresa=ID`` obligatorio al crear).

    Filtros: ``?tipo_comprobante=``, ``?sucursal=``, ``?es_electronica=``, ``?estado=``, ``?q=``.
    ``ultimo_numero`` se puede ajustar: libre mientras la serie no haya emitido nada; después solo
    hacia arriba. Una serie que ya emitió no cambia de tipo ni de código y no se elimina.
    """

    modelo = SerieComprobante
    campo_empresa = "empresa_id"
    serializer_class = SerieComprobanteSerializer
    entrada = SerieComprobanteEntrada
    recurso = "serie_comprobante"
    duplicado = "Esa empresa ya tiene esa serie para ese tipo de comprobante."
    campo_duplicado = "serie"
    permisos_por_accion = _permisos("MANTENIMIENTO.SERIES")
    campos_busqueda = ("serie", "nombre", "tipo_comprobante__nombre")
    filtros_exactos = ("estado", "tipo_comprobante", "sucursal", "es_electronica")
    ordenes = {"serie": ("serie",), "tipo": ("tipo_comprobante__codigo", "serie")}
    orden_por_defecto = ("tipo_comprobante__codigo", "serie")

    def get_queryset(self):
        return super().get_queryset().select_related("tipo_comprobante", "sucursal")

    # -- ayudas ---------------------------------------------------------------
    @staticmethod
    def _tipo(tipo_id: int) -> TipoComprobante:
        tipo = TipoComprobante.objects.filter(
            pk=tipo_id, estado=EstadoRegistro.ACTIVO, aplica_ventas=True
        ).first()
        if tipo is None:
            raise ValidationError(
                {"tipo_comprobante": "Elija un tipo de comprobante activo que se use en ventas."}
            )
        return tipo

    @staticmethod
    def _sucursal(sucursal_id: int | None, empresa_id: int) -> Sucursal | None:
        if sucursal_id is None:
            return None
        sucursal = Sucursal.objects.filter(
            pk=sucursal_id, empresa_id=empresa_id, estado=Estado.ACTIVO
        ).first()
        if sucursal is None:
            raise ValidationError({"sucursal": "Elija una sucursal activa de la empresa."})
        return sucursal

    # -- escritura ------------------------------------------------------------
    def datos_de_alta(self, validados: dict) -> dict:
        empresa = self._empresa_activa(validados)
        if "tipo_comprobante" not in validados:
            raise ValidationError({"tipo_comprobante": "Elija el tipo de comprobante."})
        validados["tipo_comprobante"] = self._tipo(validados["tipo_comprobante"])
        if "sucursal" in validados:
            validados["sucursal"] = self._sucursal(validados["sucursal"], empresa.pk)
        validados.setdefault("estado", EstadoRegistro.ACTIVO)
        return {**validados, "empresa": empresa}

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        self._empresa_inmutable(instancia, validados)
        ya_emitio = instancia.emitidos > 0
        if "tipo_comprobante" in validados:
            if validados["tipo_comprobante"] == instancia.tipo_comprobante_id:
                del validados["tipo_comprobante"]
            elif ya_emitio:
                raise ValidationError(
                    {"tipo_comprobante": "Esta serie ya emitió: no cambia de tipo de comprobante."}
                )
            else:
                validados["tipo_comprobante"] = self._tipo(validados["tipo_comprobante"])
        if ya_emitio and validados.get("serie", instancia.serie).upper() != instancia.serie:
            raise ValidationError({"serie": "Esta serie ya emitió: su código no se cambia."})
        if ya_emitio and validados.get("es_electronica", instancia.es_electronica) != (
            instancia.es_electronica
        ):
            raise ValidationError({"es_electronica": "Esta serie ya emitió: no cambia de tipo."})
        if "sucursal" in validados:
            validados["sucursal"] = self._sucursal(validados["sucursal"], instancia.empresa_id)
        if "ultimo_numero" in validados:
            series.validar_correlativo(instancia, validados["ultimo_numero"])
        return validados

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        if instancia.emitidos > 0:
            raise RegistroEnUso(
                "Esta serie ya emitió comprobantes. Desactívala en lugar de borrarla."
            )
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)
