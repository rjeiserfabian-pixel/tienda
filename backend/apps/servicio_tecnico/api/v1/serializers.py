"""Entradas y salidas de la API de órdenes de servicio y equipos."""

from django.utils import timezone
from rest_framework import serializers

from apps.seguridad.models import Usuario
from apps.seguridad.services import permisos_engine as motor
from apps.servicio_tecnico import garantia, notificaciones
from apps.servicio_tecnico.capacidades import capacidades_de, destinos_para
from apps.servicio_tecnico.flujo import ESTADOS_QUE_ESPERAN
from apps.servicio_tecnico.models import (
    AvisoCliente,
    Equipo,
    EstadoOrden,
    MedioAviso,
    OrdenAccesorio,
    OrdenRevision,
    OrdenServicio,
    Prioridad,
    ResultadoRevision,
)
from apps.servicio_tecnico.servicios import DIAS_PARA_ABANDONO


def nombre_empresa(empresa) -> str:
    return empresa.nombre_comercial or empresa.razon_social


def nombre_usuario(usuario) -> str:
    return (usuario.get_full_name() or usuario.username).strip()


# ---------------------------------------------------------------------------
# Entrada: recibir un equipo
# ---------------------------------------------------------------------------
class EquipoEntradaSerializer(serializers.Serializer):
    """Un equipo ya registrado (``id``) o los datos de uno nuevo."""

    id = serializers.IntegerField(min_value=1, required=False)
    tipo = serializers.IntegerField(min_value=1, required=False)
    marca = serializers.CharField(max_length=60, required=False, allow_blank=True)
    modelo = serializers.CharField(max_length=80, required=False, allow_blank=True)
    numero_serie = serializers.CharField(max_length=80, required=False, allow_blank=True)
    color = serializers.CharField(max_length=40, required=False, allow_blank=True)
    descripcion = serializers.CharField(max_length=250, required=False, allow_blank=True)

    def validate(self, datos):
        if "id" not in datos and "tipo" not in datos:
            raise serializers.ValidationError("Elija un equipo registrado o indique su tipo.")
        return datos


class AccesorioEntradaSerializer(serializers.Serializer):
    accesorio = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    nombre = serializers.CharField(max_length=80, required=False, allow_blank=True)
    cantidad = serializers.IntegerField(min_value=1, max_value=99, default=1)
    detalle = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def validate(self, datos):
        if not datos.get("accesorio") and not datos.get("nombre", "").strip():
            raise serializers.ValidationError("Elija el accesorio o escriba su nombre.")
        return datos


class RevisionEntradaSerializer(serializers.Serializer):
    item = serializers.IntegerField(min_value=1)
    resultado = serializers.ChoiceField(choices=ResultadoRevision.choices)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)


class RecibirEquipoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    # El cliente aceptó recibir avisos de su orden por WhatsApp.
    acepta_whatsapp = serializers.BooleanField(required=False, default=False)
    cliente = serializers.IntegerField(min_value=1)
    equipo = EquipoEntradaSerializer()
    falla_reportada = serializers.CharField(max_length=1000)
    estado_fisico = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    clave_equipo = serializers.CharField(max_length=100, required=False, allow_blank=True)
    accesorios = AccesorioEntradaSerializer(many=True, required=False, max_length=30)
    revisiones = RevisionEntradaSerializer(many=True, required=False, max_length=60)
    tecnico = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    sucursal = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    tipo_servicio = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    prioridad = serializers.ChoiceField(choices=Prioridad.choices, required=False)
    fecha_promesa = serializers.DateField(required=False, allow_null=True)


# ---------------------------------------------------------------------------
# Entrada: trabajar la orden
# ---------------------------------------------------------------------------
class CambiarEstadoEntrada(serializers.Serializer):
    estado = serializers.ChoiceField(choices=EstadoOrden.choices)
    motivo = serializers.CharField(max_length=500, required=False, allow_blank=True)


class DiagnosticoEntrada(serializers.Serializer):
    """Solo se envía lo que cambia: lo que no viene se deja como está."""

    diagnostico = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    trabajos_a_realizar = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    horas_estimadas = serializers.DecimalField(
        max_digits=4, decimal_places=1, min_value=0, required=False, allow_null=True
    )
    nota_interna = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    nota_cliente = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    tipo_servicio = serializers.IntegerField(min_value=1, required=False)


class AsignarEntrada(serializers.Serializer):
    tecnico = serializers.IntegerField(min_value=1, allow_null=True)


class AvisoEntrada(serializers.Serializer):
    medio = serializers.ChoiceField(choices=MedioAviso.choices)
    mensaje = serializers.CharField(max_length=500)


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class EquipoSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source="tipo.nombre", read_only=True)
    cliente_nombre = serializers.CharField(source="cliente.nombre", read_only=True)
    n_ordenes = serializers.IntegerField(read_only=True, default=0)
    ultimo_ingreso = serializers.DateTimeField(read_only=True, default=None)

    class Meta:
        model = Equipo
        fields = (
            "id",
            "cliente",
            "cliente_nombre",
            "tipo",
            "tipo_nombre",
            "marca",
            "modelo",
            "numero_serie",
            "color",
            "descripcion",
            "n_ordenes",
            "ultimo_ingreso",
        )
        read_only_fields = fields


class OrdenSerializer(serializers.ModelSerializer):
    """La orden como se ve en el listado."""

    codigo = serializers.CharField(read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    prioridad_nombre = serializers.CharField(source="get_prioridad_display", read_only=True)
    cliente_nombre = serializers.CharField(source="cliente.nombre", read_only=True)
    cliente_documento = serializers.SerializerMethodField()
    equipo_descripcion = serializers.CharField(source="equipo.__str__", read_only=True)
    tipo_equipo_nombre = serializers.CharField(source="equipo.tipo.nombre", read_only=True)
    tecnico_nombre = serializers.SerializerMethodField()
    tipo_servicio_nombre = serializers.CharField(
        source="tipo_servicio.nombre", default="", read_only=True
    )
    atrasada = serializers.SerializerMethodField()
    adelanto_disponible = serializers.SerializerMethodField()
    dias_en_estado = serializers.SerializerMethodField()
    por_abandonar = serializers.SerializerMethodField()
    reingreso_de_codigo = serializers.CharField(
        source="reingreso_de.codigo", default="", read_only=True
    )

    class Meta:
        model = OrdenServicio
        fields = (
            "id",
            "empresa",
            "numero",
            "codigo",
            "estado",
            "estado_nombre",
            "estado_previo",
            "prioridad",
            "prioridad_nombre",
            "cliente",
            "cliente_nombre",
            "cliente_documento",
            "equipo",
            "equipo_descripcion",
            "tipo_equipo_nombre",
            "tecnico",
            "tecnico_nombre",
            "tipo_servicio_nombre",
            "falla_reportada",
            "fecha_ingreso",
            "fecha_promesa",
            "fecha_entrega",
            "atrasada",
            "adelanto_disponible",
            "dias_en_estado",
            "por_abandonar",
            "es_garantia",
            "reingreso_de",
            "reingreso_de_codigo",
        )
        read_only_fields = fields

    def get_cliente_documento(self, orden) -> str:
        return f"{orden.cliente.tipo_documento} {orden.cliente.numero_documento}"

    def get_tecnico_nombre(self, orden) -> str:
        return orden.tecnico.nombre_completo if orden.tecnico_id else ""

    def get_adelanto_disponible(self, orden) -> str:
        """Lo que el cliente dejó por adelantado y todavía no se descontó ni se le devolvió."""
        return f"{getattr(orden, 'adelanto_disponible', None) or 0:.2f}"

    def get_dias_en_estado(self, orden) -> int | None:
        desde = getattr(orden, "en_estado_desde", None)
        return max((timezone.now() - desde).days, 0) if desde else None

    def get_por_abandonar(self, orden) -> bool:
        """Espera tanto una respuesta o un retiro que ya se puede dar por abandonado."""
        dias = self.get_dias_en_estado(orden)
        return bool(
            dias is not None and dias >= DIAS_PARA_ABANDONO and orden.estado in ESTADOS_QUE_ESPERAN
        )

    def get_atrasada(self, orden) -> bool:
        """Pasó la fecha prometida y el equipo sigue sin entregarse."""
        hoy = self.context.get("hoy")
        return bool(
            hoy
            and orden.fecha_promesa
            and orden.fecha_promesa < hoy
            and orden.estado != EstadoOrden.ENTREGADO
        )


class AccesorioSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrdenAccesorio
        fields = ("id", "nombre", "cantidad", "detalle")
        read_only_fields = fields


class RevisionSerializer(serializers.ModelSerializer):
    resultado_nombre = serializers.CharField(source="get_resultado_display", read_only=True)

    class Meta:
        model = OrdenRevision
        fields = ("id", "nombre", "resultado", "resultado_nombre", "observacion")
        read_only_fields = fields


class AvisoSerializer(serializers.ModelSerializer):
    medio_nombre = serializers.CharField(source="get_medio_display", read_only=True)
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = AvisoCliente
        fields = ("id", "medio", "medio_nombre", "mensaje", "creado_en", "usuario_nombre")
        read_only_fields = fields

    def get_usuario_nombre(self, aviso) -> str:
        return self.context.get("nombres_avisos", {}).get(aviso.creado_por_id, "")


class OrdenDetalleSerializer(OrdenSerializer):
    equipo_datos = serializers.SerializerMethodField()
    n_ingresos_equipo = serializers.SerializerMethodField()
    sucursal_nombre = serializers.CharField(source="sucursal.nombre", default="", read_only=True)
    tiene_clave = serializers.SerializerMethodField()
    accesorios = AccesorioSerializer(many=True, read_only=True)
    revisiones = RevisionSerializer(many=True, read_only=True)
    historial = serializers.SerializerMethodField()
    recibido_por = serializers.SerializerMethodField()
    emisor = serializers.SerializerMethodField()
    cliente_telefono = serializers.CharField(source="cliente.telefono", read_only=True)
    cliente_direccion = serializers.CharField(source="cliente.direccion", read_only=True)
    tipo_servicio_categoria = serializers.CharField(
        source="tipo_servicio.categoria", default="", read_only=True
    )
    avisos = serializers.SerializerMethodField()
    destinos = serializers.SerializerMethodField()
    permite = serializers.SerializerMethodField()
    presupuesto = serializers.SerializerMethodField()
    entrega = serializers.SerializerMethodField()
    garantia = serializers.SerializerMethodField()
    reingresos = serializers.SerializerMethodField()
    abandono = serializers.SerializerMethodField()
    url_publica = serializers.SerializerMethodField()
    adelantos = serializers.SerializerMethodField()
    whatsapp = serializers.SerializerMethodField()
    notificaciones = serializers.SerializerMethodField()

    class Meta(OrdenSerializer.Meta):
        fields = (
            *OrdenSerializer.Meta.fields,
            "cliente_telefono",
            "cliente_direccion",
            "equipo_datos",
            "n_ingresos_equipo",
            "sucursal",
            "sucursal_nombre",
            "estado_fisico",
            "tiene_clave",
            "accesorios",
            "revisiones",
            "historial",
            "recibido_por",
            "emisor",
            "tipo_servicio",
            "tipo_servicio_categoria",
            "diagnostico",
            "trabajos_a_realizar",
            "horas_estimadas",
            "nota_interna",
            "nota_cliente",
            "avisos",
            "destinos",
            "permite",
            "presupuesto",
            "entrega",
            "recogio_nombre",
            "recogio_documento",
            "recogio_es_titular",
            "garantia",
            "reingresos",
            "abandono",
            "acepta_whatsapp",
            "url_publica",
            "adelantos",
            "whatsapp",
            "notificaciones",
        )
        read_only_fields = fields

    def _nombres(self, orden) -> dict:
        """Nombres de quienes recibieron y movieron la orden (una consulta para todos)."""
        if not hasattr(self, "_cache_nombres"):
            self._cache_nombres = {}
        if orden.pk not in self._cache_nombres:
            ids = {
                orden.creado_por_id,
                *(h.creado_por_id for h in orden.historial.all()),
                *(a.creado_por_id for a in orden.avisos.all()),
            }
            ids.discard(None)
            usuarios = Usuario.objects.filter(pk__in=ids)
            self._cache_nombres[orden.pk] = {u.pk: nombre_usuario(u) for u in usuarios}
        return self._cache_nombres[orden.pk]

    def get_equipo_datos(self, orden) -> dict:
        e = orden.equipo
        return {
            "id": e.pk,
            "tipo": e.tipo.nombre,
            "marca": e.marca,
            "modelo": e.modelo,
            "numero_serie": e.numero_serie,
            "color": e.color,
            "descripcion": e.descripcion,
        }

    def get_n_ingresos_equipo(self, orden) -> int:
        """Cuántas veces entró este equipo al taller (esta orden incluida)."""
        return OrdenServicio.objects.filter(equipo_id=orden.equipo_id).count()

    def get_tiene_clave(self, orden) -> bool:
        return bool(orden.clave_equipo)

    def get_historial(self, orden) -> list[dict]:
        nombres = self._nombres(orden)
        return [
            {
                "id": h.pk,
                "estado_anterior": h.estado_anterior,
                "estado_nuevo": h.estado_nuevo,
                "estado_nuevo_nombre": EstadoOrden(h.estado_nuevo).label,
                "motivo": h.motivo,
                "fecha": h.creado_en,
                "usuario_nombre": nombres.get(h.creado_por_id, ""),
            }
            for h in orden.historial.all()
        ]

    def get_recibido_por(self, orden) -> str:
        return self._nombres(orden).get(orden.creado_por_id, "")

    def get_emisor(self, orden) -> dict:
        e = orden.empresa
        return {
            "empresa": e.pk,
            "tiene_logo": bool(e.logo),
            "nombre": nombre_empresa(e),
            "ruc": e.ruc,
            "direccion": e.direccion_fiscal,
            "telefono": e.telefono,
            "correo": e.correo,
        }

    def get_avisos(self, orden) -> list[dict]:
        nombres = self._nombres(orden)
        return AvisoSerializer(
            orden.avisos.all(), many=True, context={**self.context, "nombres_avisos": nombres}
        ).data

    def _usuario(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_destinos(self, orden) -> list[dict]:
        """Los pasos que esta persona puede dar ahora con la orden."""
        usuario = self._usuario()
        return destinos_para(usuario, orden) if usuario else []

    def get_permite(self, orden) -> dict:
        """Qué botones le sirven a esta persona en la ficha."""
        usuario = self._usuario()
        if not usuario or orden.estado == EstadoOrden.ENTREGADO:
            # Entregada: solo queda reingresarla por garantía, mientras esta siga vigente.
            reingreso = bool(
                usuario
                and capacidades_de(usuario, orden).recibe
                and not orden.es_garantia
                and garantia.estado_de(orden).vigente
                and not any(r.estado != EstadoOrden.ENTREGADO for r in orden.reingresos.all())
            )
            return {
                "diagnosticar": False,
                "asignar": False,
                "avisar": False,
                "presupuestar": False,
                "aprobar": False,
                "reservar": False,
                "reingreso": reingreso,
                "adelantos": False,
            }
        from .presupuesto import permisos_de_presupuesto

        poder = capacidades_de(usuario, orden)
        return {
            "diagnosticar": poder.trabaja,
            "asignar": poder.asigna,
            "avisar": poder.recepcion,
            "adelantos": (
                motor.tiene_permiso(usuario, "SERVICIOS.ADELANTOS.GESTIONAR", orden.empresa_id)
                and not orden.es_garantia
            ),
            "reingreso": (
                poder.recibe
                and orden.estado == EstadoOrden.ENTREGADO
                and garantia.estado_de(orden).vigente
                and not orden.es_garantia
            ),
            **permisos_de_presupuesto(orden, usuario, self._presupuesto(orden)),
        }

    def _presupuesto(self, orden) -> dict | None:
        """El presupuesto vigente (se arma una sola vez por orden y petición)."""
        from .presupuesto import presupuesto_de

        usuario = self._usuario()
        if not usuario:
            return None
        if not hasattr(self, "_cache_presupuesto"):
            self._cache_presupuesto = {}
        if orden.pk not in self._cache_presupuesto:
            self._cache_presupuesto[orden.pk] = presupuesto_de(orden, usuario)
        return self._cache_presupuesto[orden.pk]

    def get_adelantos(self, orden) -> dict:
        from .adelantos import adelantos_de

        return adelantos_de(orden)

    def get_url_publica(self, orden) -> str:
        return notificaciones.url_publica(orden)

    def get_whatsapp(self, orden) -> dict:
        """Para escribirle al cliente a mano: su número para WhatsApp y un mensaje sugerido."""
        return {
            "numero": notificaciones.normalizar_telefono(orden.cliente.telefono),
            "mensaje": notificaciones.mensaje_manual(orden),
        }

    def get_notificaciones(self, orden) -> list[dict]:
        return [
            {
                "id": n.pk,
                "evento": n.evento,
                "evento_nombre": n.get_evento_display(),
                "estado": n.estado,
                "estado_nombre": n.get_estado_display(),
                "detalle": n.detalle,
                "fecha": n.enviado_en or n.creado_en,
            }
            for n in orden.notificaciones.all()
        ]

    def get_garantia(self, orden) -> dict:
        g = garantia.estado_de(orden)
        return {
            "dias": g.dias,
            "hasta": g.hasta,
            "vigente": g.vigente,
            "dias_restantes": g.dias_restantes,
        }

    def get_reingresos(self, orden) -> list[dict]:
        return [
            {
                "id": r.pk,
                "codigo": r.codigo,
                "estado": r.estado,
                "estado_nombre": r.get_estado_display(),
            }
            for r in orden.reingresos.order_by("id")
        ]

    def get_abandono(self, orden) -> dict:
        """Lo que falta para poder dar por abandonado un equipo que no se recoge."""
        dias = self.get_dias_en_estado(orden) or 0
        avisos = len(orden.avisos.all())
        return {
            "aplica": orden.estado in ESTADOS_QUE_ESPERAN,
            "dias": dias,
            "dias_requeridos": DIAS_PARA_ABANDONO,
            "avisos": avisos,
            "puede": dias >= DIAS_PARA_ABANDONO and avisos > 0,
        }

    def get_entrega(self, orden) -> dict | None:
        """Lo que pide la entrega del equipo (solo a quien puede entregarlo)."""
        from .presupuesto import entrega_de

        usuario = self._usuario()
        return entrega_de(orden, usuario) if usuario else None

    def get_presupuesto(self, orden) -> dict | None:
        return self._presupuesto(orden)
