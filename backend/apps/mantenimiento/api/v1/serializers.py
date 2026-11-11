from decimal import Decimal

from rest_framework import serializers

from apps.mantenimiento.models import (
    Almacen,
    Area,
    Banco,
    CampoEspecificacion,
    Categoria,
    CentroCosto,
    Cliente,
    EstadoRegistro,
    Familia,
    FotoProducto,
    ListaPrecio,
    Marca,
    Personal,
    PrecioProducto,
    Producto,
    Proveedor,
    TipoAlmacen,
    TipoCambio,
    TipoDocumento,
    TipoProducto,
    Ubicacion,
    UnidadMedida,
    UsoLista,
    ZonaFiscal,
)
from apps.mantenimiento.productos import margen_de_utilidad

from .campos import CampoUbigeo

_COMUNES = (
    "id",
    "tipo_documento",
    "numero_documento",
    "direccion",
    "telefono",
    "correo",
    "estado",
    "creado_en",
)


# --------------------------------------------------------------------------- salida
class ClienteSerializer(serializers.ModelSerializer):
    asesor_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = (
            *_COMUNES,
            "ubigeo",
            "nombre",
            "nombre_comercial",
            "zona",
            "limite_credito",
            "credito_sin_limite",
            "asesor",
            "asesor_nombre",
        )
        read_only_fields = fields

    def get_asesor_nombre(self, obj) -> str | None:
        a = obj.asesor
        if a is None:
            return None
        return f"{a.first_name} {a.last_name}".strip() or a.username


class ProveedorSerializer(serializers.ModelSerializer):
    """La cuenta bancaria solo la ve quien puede editar (``ver_cuenta`` en el contexto)."""

    class Meta:
        model = Proveedor
        fields = (
            *_COMUNES,
            "ubigeo",
            "nombre",
            "nombre_comercial",
            "zona",
            "ciudad",
            "contacto",
            "banco",
            "cuenta_bancaria",
            "productos_referencia",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        datos = super().to_representation(instance)
        if not self.context.get("ver_cuenta", False):
            datos["cuenta_bancaria"] = None
            datos["banco"] = ""
        return datos


class PersonalSerializer(serializers.ModelSerializer):
    usuario_username = serializers.CharField(
        source="usuario.username", default=None, read_only=True
    )

    class Meta:
        model = Personal
        fields = (
            *_COMUNES,
            "empresa",
            "nombres",
            "apellidos",
            "nombre_completo",
            "area",
            "cargo",
            "fecha_nacimiento",
            "fecha_ingreso",
            "usuario",
            "usuario_username",
        )
        read_only_fields = fields


class FamiliaSerializer(serializers.ModelSerializer):
    n_categorias = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Familia
        fields = ("id", "nombre", "slug", "estado", "n_categorias", "creado_en")
        read_only_fields = fields


class CategoriaSerializer(serializers.ModelSerializer):
    familia_nombre = serializers.CharField(source="familia.nombre", read_only=True)
    n_campos = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Categoria
        fields = (
            "id",
            "familia",
            "familia_nombre",
            "nombre",
            "slug",
            "estado",
            "n_campos",
            "creado_en",
        )
        read_only_fields = fields


class MarcaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Marca
        fields = ("id", "nombre", "slug", "estado", "creado_en")
        read_only_fields = fields


class AlmacenSerializer(serializers.ModelSerializer):
    sucursal_nombre = serializers.CharField(source="sucursal.nombre", read_only=True)
    responsable_nombre = serializers.CharField(
        source="responsable.nombre_completo", default=None, read_only=True
    )

    class Meta:
        model = Almacen
        fields = (
            "id",
            "empresa",
            "codigo",
            "nombre",
            "sucursal",
            "sucursal_nombre",
            "tipo",
            "permite_venta",
            "direccion",
            "ubigeo",
            "responsable",
            "responsable_nombre",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class UbicacionSerializer(serializers.ModelSerializer):
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    n_productos = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Ubicacion
        fields = (
            "id",
            "empresa",
            "almacen",
            "almacen_nombre",
            "codigo",
            "nombre",
            "n_productos",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class CentroCostoSerializer(serializers.ModelSerializer):
    padre_nombre = serializers.CharField(source="padre.nombre", default=None, read_only=True)
    n_hijos = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = CentroCosto
        fields = (
            "id",
            "codigo",
            "nombre",
            "padre",
            "padre_nombre",
            "n_hijos",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class TipoCambioSerializer(serializers.ModelSerializer):
    fuente_nombre = serializers.CharField(source="get_fuente_display", read_only=True)
    es_manual = serializers.BooleanField(read_only=True)

    class Meta:
        model = TipoCambio
        fields = (
            "id",
            "fecha",
            "moneda",
            "fuente",
            "fuente_nombre",
            "compra",
            "venta",
            "es_manual",
            "creado_en",
        )
        read_only_fields = fields


# -------------------------------------------------------------------------- entrada
class _EntradaBase(serializers.Serializer):
    tipo_documento = serializers.ChoiceField(choices=TipoDocumento.choices)
    numero_documento = serializers.CharField(max_length=30)
    direccion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)
    correo = serializers.EmailField(required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class _EntradaNombre(_EntradaBase):
    nombre = serializers.CharField(max_length=250)
    nombre_comercial = serializers.CharField(max_length=250, required=False, allow_blank=True)


class ClienteEntrada(_EntradaNombre):
    """``asesor`` solo lo respeta quien puede asignar asesores; para los demás es quien registra."""

    ubigeo = CampoUbigeo()
    asesor = serializers.UUIDField(required=False, allow_null=True)
    zona = serializers.ChoiceField(choices=ZonaFiscal.choices, required=False, allow_blank=True)
    # Solo lo respeta quien tiene VENTAS.LIMITE_CREDITO; para los demás se ignora.
    limite_credito = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False
    )
    credito_sin_limite = serializers.BooleanField(required=False)


class ProveedorEntrada(_EntradaNombre):
    ubigeo = CampoUbigeo()
    zona = serializers.ChoiceField(choices=ZonaFiscal.choices, required=False, allow_blank=True)
    ciudad = serializers.CharField(max_length=80, required=False, allow_blank=True)
    contacto = serializers.CharField(max_length=150, required=False, allow_blank=True)
    banco = serializers.ChoiceField(choices=Banco.choices, required=False, allow_blank=True)
    cuenta_bancaria = serializers.CharField(max_length=40, required=False, allow_blank=True)
    productos_referencia = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class PersonalEntrada(_EntradaBase):
    """``empresa`` solo se envía al crear: el personal no cambia de empresa."""

    empresa = serializers.IntegerField(min_value=1, required=False)
    nombres = serializers.CharField(max_length=150)
    apellidos = serializers.CharField(max_length=150)
    area = serializers.ChoiceField(choices=Area.choices, required=False)
    cargo = serializers.CharField(max_length=100, required=False, allow_blank=True)
    fecha_nacimiento = serializers.DateField(required=False, allow_null=True)
    fecha_ingreso = serializers.DateField(required=False, allow_null=True)
    usuario = serializers.UUIDField(required=False, allow_null=True)


class CatalogoEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=100)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class CategoriaEntrada(CatalogoEntrada):
    """``familia`` es obligatoria al crear; al editar sirve para mover la categoría."""

    familia = serializers.IntegerField(min_value=1)


class AlmacenEntrada(serializers.Serializer):
    """``empresa`` solo se envía al crear: un almacén no cambia de empresa."""

    empresa = serializers.IntegerField(min_value=1, required=False)
    codigo = serializers.CharField(max_length=20)
    nombre = serializers.CharField(max_length=100)
    sucursal = serializers.IntegerField(min_value=1)
    tipo = serializers.ChoiceField(choices=TipoAlmacen.choices, required=False)
    permite_venta = serializers.BooleanField(required=False)
    direccion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    ubigeo = CampoUbigeo()
    responsable = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class UbicacionEntrada(serializers.Serializer):
    """``empresa`` y ``almacen`` solo se envían al crear: una ubicación no cambia de almacén."""

    empresa = serializers.IntegerField(min_value=1, required=False)
    almacen = serializers.IntegerField(min_value=1, required=False)
    codigo = serializers.CharField(max_length=20)
    nombre = serializers.CharField(max_length=100)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


class CentroCostoEntrada(CatalogoEntrada):
    codigo = serializers.CharField(max_length=20)
    padre = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class TipoCambioEntrada(serializers.Serializer):
    """Solo los tipos de cambio manuales se cargan o editan a mano."""

    fecha = serializers.DateField()
    compra = serializers.DecimalField(max_digits=10, decimal_places=4, min_value=0)
    venta = serializers.DecimalField(max_digits=10, decimal_places=4, min_value=0)


class ActualizarTipoCambioEntrada(serializers.Serializer):
    fecha = serializers.DateField(required=False)
    fuentes = serializers.ListField(
        child=serializers.ChoiceField(choices=["SUNAT", "SBS", "SBS_CONTABLE"]),
        required=False,
        allow_empty=False,
    )
    forzar = serializers.BooleanField(required=False, default=False)


# --------------------------------------------------------------------------- productos
class UnidadMedidaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnidadMedida
        fields = ("id", "nombre", "abreviatura", "codigo_sunat", "estado", "creado_en")
        read_only_fields = fields


class UnidadMedidaEntrada(CatalogoEntrada):
    abreviatura = serializers.CharField(max_length=10)
    codigo_sunat = serializers.CharField(max_length=5, required=False, allow_blank=True)


class ListaPrecioSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListaPrecio
        fields = ("id", "nombre", "orden", "es_principal", "uso", "estado", "creado_en")
        read_only_fields = fields


class ListaPrecioEntrada(CatalogoEntrada):
    orden = serializers.IntegerField(min_value=1, max_value=99, required=False)
    uso = serializers.ChoiceField(choices=UsoLista.choices, required=False)


class CampoEspecificacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampoEspecificacion
        fields = (
            "id",
            "clave",
            "nombre",
            "tipo",
            "unidad",
            "opciones",
            "seccion",
            "orden",
            "es_filtro",
            "en_tarjeta",
            "estado",
        )
        read_only_fields = fields


class CampoEspecificacionEntrada(serializers.Serializer):
    id = serializers.IntegerField(min_value=1, required=False)
    nombre = serializers.CharField(max_length=80)
    tipo = serializers.ChoiceField(choices=CampoEspecificacion.Tipo.choices, default="TEXTO")
    unidad = serializers.CharField(max_length=20, required=False, allow_blank=True)
    opciones = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, max_length=40
    )
    seccion = serializers.CharField(max_length=60, required=False, allow_blank=True)
    es_filtro = serializers.BooleanField(required=False)
    en_tarjeta = serializers.BooleanField(required=False)


class EspecificacionesEntrada(serializers.Serializer):
    campos = CampoEspecificacionEntrada(many=True, max_length=80)


class PlantillaEntrada(serializers.Serializer):
    plantilla = serializers.CharField(max_length=40)


class OrdenFotosEntrada(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=20)


class FotoProductoSerializer(serializers.ModelSerializer):
    class Meta:
        model = FotoProducto
        fields = ("id", "es_principal", "orden", "nombre_original")
        read_only_fields = fields


class PrecioProductoSerializer(serializers.ModelSerializer):
    lista_nombre = serializers.CharField(source="lista.nombre", read_only=True)
    margen = serializers.SerializerMethodField()

    class Meta:
        model = PrecioProducto
        fields = ("lista", "lista_nombre", "precio", "utilidad", "margen")
        read_only_fields = fields

    def get_margen(self, fila) -> str | None:
        """Margen sobre el precio, derivado de la utilidad guardada."""
        margen = margen_de_utilidad(fila.utilidad)
        return None if margen is None else f"{margen:.2f}"


class ProductoSerializer(serializers.ModelSerializer):
    """Salida de un producto. ``costo`` y ``utilidad`` solo se ven con permiso de precios."""

    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    familia = serializers.IntegerField(source="categoria.familia_id", read_only=True)
    familia_nombre = serializers.CharField(source="categoria.familia.nombre", read_only=True)
    marca_nombre = serializers.CharField(source="marca.nombre", default=None, read_only=True)
    unidad_abreviatura = serializers.CharField(source="unidad.abreviatura", read_only=True)
    unidad_nombre = serializers.CharField(source="unidad.nombre", read_only=True)
    afectacion_igv_nombre = serializers.CharField(
        source="afectacion_igv.nombre", default=None, read_only=True
    )
    codigo_barras_efectivo = serializers.CharField(read_only=True)
    foto_principal = serializers.SerializerMethodField()
    precios = serializers.SerializerMethodField()
    presentaciones = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = (
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "tipo",
            "familia",
            "familia_nombre",
            "categoria",
            "categoria_nombre",
            "marca",
            "marca_nombre",
            "unidad",
            "unidad_nombre",
            "unidad_abreviatura",
            "codigo_fabricante",
            "codigo_barras",
            "codigo_barras_efectivo",
            "codigo_sunat",
            "stock_minimo",
            "controla_stock",
            "lleva_serie",
            "precio_editable",
            "afectacion_igv",
            "afectacion_igv_nombre",
            "costo",
            "estado",
            "foto_principal",
            "precios",
            "presentaciones",
            "especificaciones",
            "publicado_web",
            "destacado",
            "es_nuevo",
            "descripcion_web",
            "puntos_destacados",
            "slug",
            "garantia_meses",
            "peso_kg",
            "largo_cm",
            "ancho_cm",
            "alto_cm",
            "creado_en",
        )
        read_only_fields = fields

    def _ve_precios(self) -> bool:
        return bool(self.context.get("ve_costos"))

    def to_representation(self, instancia):
        datos = super().to_representation(instancia)
        if not self._ve_precios():
            datos.pop("costo", None)
        return datos

    def get_foto_principal(self, producto) -> int | None:
        # ``fotos`` viene precargado (ordenado: la principal primero); no consulta por fila.
        fotos = list(producto.fotos.all())
        return fotos[0].pk if fotos else None

    def get_presentaciones(self, producto) -> list[dict]:
        from .presentaciones import PresentacionProductoSerializer  # evita un import circular

        return PresentacionProductoSerializer(
            producto.presentaciones.all(), many=True, context=self.context
        ).data

    def get_precios(self, producto) -> list[dict]:
        ve = self._ve_precios()
        filas = []
        for fila in producto.precios.all():
            dato = PrecioProductoSerializer(fila).data
            if not ve:
                dato.pop("utilidad", None)
                dato.pop("margen", None)
            filas.append(dato)
        return filas


class PrecioEntrada(serializers.Serializer):
    lista = serializers.IntegerField(min_value=1)
    precio = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=0, required=False, allow_null=True
    )
    utilidad = serializers.DecimalField(
        max_digits=9, decimal_places=2, min_value=-100, required=False, allow_null=True
    )
    # Alternativa a la utilidad: ganancia como parte del precio de venta (menor que 100).
    margen = serializers.DecimalField(
        max_digits=9,
        decimal_places=2,
        min_value=Decimal("-1000"),
        max_value=Decimal("99.99"),
        required=False,
        allow_null=True,
    )


class ProductoEntrada(serializers.Serializer):
    nombre = serializers.CharField(max_length=200)
    descripcion = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    tipo = serializers.ChoiceField(choices=TipoProducto.choices, required=False)
    categoria = serializers.IntegerField(min_value=1)
    marca = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    unidad = serializers.IntegerField(min_value=1)
    codigo_fabricante = serializers.CharField(max_length=60, required=False, allow_blank=True)
    codigo_barras = serializers.CharField(max_length=40, required=False, allow_blank=True)
    codigo_sunat = serializers.RegexField(r"^\d{8}$", required=False, allow_blank=True)
    stock_minimo = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=0, required=False
    )
    controla_stock = serializers.BooleanField(required=False)
    lleva_serie = serializers.BooleanField(required=False)
    precio_editable = serializers.BooleanField(required=False)
    afectacion_igv = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    costo = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=0, required=False)
    estado = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)
    precios = PrecioEntrada(many=True, required=False)
    # Para la tienda
    especificaciones = serializers.DictField(required=False)
    publicado_web = serializers.BooleanField(required=False)
    destacado = serializers.BooleanField(required=False)
    es_nuevo = serializers.BooleanField(required=False)
    descripcion_web = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    puntos_destacados = serializers.ListField(
        child=serializers.CharField(max_length=120, allow_blank=True), required=False, max_length=8
    )
    slug = serializers.CharField(max_length=200, required=False, allow_blank=True)
    garantia_meses = serializers.IntegerField(
        min_value=0, max_value=240, required=False, allow_null=True
    )
    peso_kg = serializers.DecimalField(
        max_digits=8, decimal_places=3, min_value=0, required=False, allow_null=True
    )
    largo_cm = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    ancho_cm = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    alto_cm = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=0, required=False, allow_null=True
    )
