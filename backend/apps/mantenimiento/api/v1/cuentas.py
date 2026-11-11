"""API de las cajas y cuentas (efectivo, bancos y billeteras digitales) de cada empresa."""

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Estado, Sucursal
from apps.seguridad.services import permisos_engine as motor

from .views import MaestroViewSet, _permisos, _PorEmpresaMixin

EDITAR = "CAJA.CUENTAS.EDITAR"


class CuentaFinancieraSerializer(serializers.ModelSerializer):
    """El número de cuenta y el CCI solo los ve quien puede editar; los demás, los últimos 4."""

    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)
    moneda_nombre = serializers.CharField(source="get_moneda_display", read_only=True)
    sucursal_nombre = serializers.CharField(source="sucursal.nombre", default=None, read_only=True)

    class Meta:
        model = CuentaFinanciera
        fields = (
            "id",
            "empresa",
            "nombre",
            "tipo",
            "tipo_nombre",
            "moneda",
            "moneda_nombre",
            "sucursal",
            "sucursal_nombre",
            "banco",
            "numero_cuenta",
            "cci",
            "saldo_inicial",
            "fecha_saldo_inicial",
            "rol_caja",
            "fondo_inicial",
            "exige_sesion",
            "permite_saldo_negativo",
            "saldo_minimo",
            "cuenta_contable",
            "codigo_entidad",
            "estado",
            "creado_en",
        )
        read_only_fields = fields

    def _ve_datos(self, empresa_id: int) -> bool:
        # Una consulta por empresa, no por fila (``ver_datos`` la arma la vista con caché).
        return self.context["ver_datos"](empresa_id)

    def to_representation(self, instancia):
        datos = super().to_representation(instancia)
        if not self._ve_datos(instancia.empresa_id):
            numero = instancia.numero_cuenta
            datos["numero_cuenta"] = f"••••{numero[-4:]}" if numero else ""
            datos["cci"] = ""
        return datos


class CuentaFinancieraEntrada(serializers.Serializer):
    """``empresa`` y ``moneda`` no cambian después de crear; el ``tipo`` sí (``_cambiar_tipo``)."""

    empresa = serializers.IntegerField(min_value=1, required=False)
    nombre = serializers.CharField(max_length=80)
    tipo = serializers.ChoiceField(choices=CuentaFinanciera.Tipo.choices, required=False)
    moneda = serializers.ChoiceField(choices=CuentaFinanciera.Moneda.choices, required=False)
    sucursal = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    banco = serializers.CharField(max_length=60, required=False, allow_blank=True)
    numero_cuenta = serializers.CharField(max_length=40, required=False, allow_blank=True)
    cci = serializers.CharField(max_length=30, required=False, allow_blank=True)
    saldo_inicial = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=0, required=False
    )
    fecha_saldo_inicial = serializers.DateField(required=False, allow_null=True)
    rol_caja = serializers.ChoiceField(
        choices=CuentaFinanciera.RolCaja.choices, required=False, allow_blank=True
    )
    fondo_inicial = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=0, required=False
    )
    exige_sesion = serializers.BooleanField(required=False)
    permite_saldo_negativo = serializers.BooleanField(required=False)
    saldo_minimo = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    cuenta_contable = serializers.CharField(max_length=20, required=False, allow_blank=True)
    codigo_entidad = serializers.CharField(max_length=2, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class CuentaFinancieraViewSet(_PorEmpresaMixin, MaestroViewSet):
    """Cajas y cuentas de cada empresa (``?empresa=ID`` obligatorio al crear).

    Filtros: ``?tipo=``, ``?moneda=``, ``?sucursal=``, ``?estado=``, ``?q=`` (nombre o banco).
    Una por tienda: con ``sucursal`` es de esa tienda; sin ella sirve a toda la empresa.
    """

    modelo = CuentaFinanciera
    campo_empresa = "empresa_id"
    serializer_class = CuentaFinancieraSerializer
    entrada = CuentaFinancieraEntrada
    recurso = "cuenta_financiera"
    duplicado = "La empresa ya tiene una caja o cuenta con ese nombre."
    campo_duplicado = "nombre"
    permisos_por_accion = _permisos("CAJA.CUENTAS")
    campos_busqueda = ("nombre", "banco")
    filtros_exactos = ("estado", "tipo", "moneda", "sucursal")
    ordenes = {"nombre": ("nombre",), "tipo": ("tipo", "nombre")}
    orden_por_defecto = ("tipo", "nombre")

    def get_queryset(self):
        return super().get_queryset().select_related("sucursal")

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        permitidas: dict[int, bool] = {}

        def ver_datos(empresa_id: int) -> bool:
            if empresa_id not in permitidas:
                permitidas[empresa_id] = motor.tiene_permiso(self.request.user, EDITAR, empresa_id)
            return permitidas[empresa_id]

        contexto["ver_datos"] = ver_datos
        return contexto

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

    @staticmethod
    def _cambiar_tipo(instancia, nuevo: str, validados: dict) -> None:
        """Pasa de caja a banco o billetera (o al revés) limpiando lo que ya no corresponde.

        Una caja que ya tuvo sesiones no deja de ser caja: su historial son turnos con arqueo.
        """
        from apps.caja.models import SesionCaja

        Tipo = CuentaFinanciera.Tipo
        if instancia.tipo == Tipo.CAJA:
            if SesionCaja.objects.sin_ambito().filter(cuenta=instancia).exists():
                raise ValidationError(
                    {"tipo": "Esta caja ya tuvo sesiones: no puede dejar de ser caja de efectivo."}
                )
            validados.update(rol_caja="", fondo_inicial=0, exige_sesion=False)
        if nuevo == Tipo.CAJA:
            validados.update(
                banco="", numero_cuenta="", cci="", codigo_entidad="", permite_saldo_negativo=False
            )

    def datos_de_alta(self, validados: dict) -> dict:
        empresa = self._empresa_activa(validados)
        if "tipo" not in validados:
            raise ValidationError({"tipo": "Elija si es caja, banco o billetera."})
        if "sucursal" in validados:
            validados["sucursal"] = self._sucursal(validados["sucursal"], empresa.pk)
        validados.setdefault("estado", EstadoRegistro.ACTIVO)
        return {**validados, "empresa": empresa}

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        self._empresa_inmutable(instancia, validados)
        if validados.pop("moneda", instancia.moneda) != instancia.moneda:
            raise ValidationError(
                {"moneda": "No se puede cambiar la moneda: crea otra caja o cuenta."}
            )
        nuevo = validados.get("tipo", instancia.tipo)
        if nuevo != instancia.tipo:
            self._cambiar_tipo(instancia, nuevo, validados)
        if "sucursal" in validados:
            validados["sucursal"] = self._sucursal(validados["sucursal"], instancia.empresa_id)
        return validados
