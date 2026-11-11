from datetime import date

from django.db.models import Count, Max, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ConsultaDocumentoThrottle, ImportacionThrottle
from apps.mantenimiento import (
    consultas,
    cuota,
    especificaciones,
    importacion,
    productos,
    services,
    tipo_cambio,
)
from apps.mantenimiento import fotos as servicio_fotos
from apps.mantenimiento.exceptions import (
    CentroConHijos,
    FamiliaConCategorias,
    ImagenInvalida,
    RegistroEnUso,
    TipoCambioOficial,
    UsuarioYaVinculado,
)
from apps.mantenimiento.models import (
    AfectacionIGV,
    Almacen,
    Categoria,
    CentroCosto,
    Cliente,
    EstadoRegistro,
    Familia,
    FotoProducto,
    FuenteTipoCambio,
    ListaPrecio,
    Marca,
    Personal,
    PrecioPresentacion,
    PrecioProducto,
    PresentacionProducto,
    Producto,
    Proveedor,
    TipoCambio,
    Ubicacion,
    UnidadMedida,
)
from apps.organizacion.models import Empresa, Estado, Sucursal
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.models import Usuario
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import (
    ActualizarTipoCambioEntrada,
    AlmacenEntrada,
    AlmacenSerializer,
    CampoEspecificacionSerializer,
    CatalogoEntrada,
    CategoriaEntrada,
    CategoriaSerializer,
    CentroCostoEntrada,
    CentroCostoSerializer,
    ClienteEntrada,
    ClienteSerializer,
    EspecificacionesEntrada,
    FamiliaSerializer,
    FotoProductoSerializer,
    ListaPrecioEntrada,
    ListaPrecioSerializer,
    MarcaSerializer,
    OrdenFotosEntrada,
    PersonalEntrada,
    PersonalSerializer,
    PlantillaEntrada,
    ProductoEntrada,
    ProductoSerializer,
    ProveedorEntrada,
    ProveedorSerializer,
    TipoCambioEntrada,
    TipoCambioSerializer,
    UbicacionEntrada,
    UbicacionSerializer,
    UnidadMedidaEntrada,
    UnidadMedidaSerializer,
)

TAG = ["mantenimiento"]
ASIGNAR_ASESOR = "MANTENIMIENTO.CLIENTES.ASIGNAR_ASESOR"
LIMITE_CREDITO = "VENTAS.LIMITE_CREDITO"
CAMBIAR_PRECIO = "MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO"


def _permisos(prefijo: str) -> dict[str, str]:
    """Acciones del viewset → permiso (VER, CREAR, EDITAR, ELIMINAR)."""
    return {
        "list": f"{prefijo}.VER",
        "retrieve": f"{prefijo}.VER",
        "create": f"{prefijo}.CREAR",
        "partial_update": f"{prefijo}.EDITAR",
        "destroy": f"{prefijo}.ELIMINAR",
        "plantilla": f"{prefijo}.IMPORTAR",
        "importar": f"{prefijo}.IMPORTAR",
        "actualizar": f"{prefijo}.CREAR",
        "resumen": f"{prefijo}.VER",
        "sembrar": f"{prefijo}.CREAR",
        "fotos": f"{prefijo}.VER",
        "foto_imagen": f"{prefijo}.VER",
        "subir_foto": f"{prefijo}.EDITAR",
        "foto_principal": f"{prefijo}.EDITAR",
        "eliminar_foto": f"{prefijo}.EDITAR",
        "orden_fotos": f"{prefijo}.EDITAR",
        "plantillas": f"{prefijo}.VER",
        "especificaciones": f"{prefijo}.VER",
        "guardar_especificaciones": f"{prefijo}.EDITAR",
        "cargar_plantilla": f"{prefijo}.EDITAR",
    }


class MaestroViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Base de los maestros: listado paginado con búsqueda, alta, edición y baja lógica.

    Cada recurso declara su modelo, sus serializers, su permiso base y sus filtros.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    lookup_value_regex = r"\d+"

    recurso: str = ""
    duplicado: str = "Ya existe un registro con ese documento."
    campo_duplicado: str = "numero_documento"  # campo al que se atribuye el error de duplicado
    entrada = None
    campos_busqueda: tuple[str, ...] = ()
    filtros_exactos: tuple[str, ...] = ("estado",)
    ordenes: dict[str, tuple[str, ...]] = {}
    orden_por_defecto: tuple[str, ...] = ("-id",)

    def empresas_de_la_operacion(self, request):
        return [None]  # recurso de la organización

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        for campo in self.filtros_exactos:
            valor = params.get(campo)
            if valor:
                queryset = queryset.filter(**{campo: valor})
        q = (params.get("q") or "").strip()
        if q:
            condicion = Q()
            for campo in self.campos_busqueda:
                condicion |= Q(**{f"{campo}__icontains": q})
            queryset = queryset.filter(condicion)
        orden = self.ordenes.get((params.get("orden") or "").strip(), self.orden_por_defecto)
        return queryset.order_by(*orden, "id")

    # -- escritura ---------------------------------------------------------------
    def datos_de_alta(self, validados: dict) -> dict:
        return {**validados, "organizacion_id": self.request.user.organizacion_id}

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        return validados

    @extend_schema(tags=TAG)
    def create(self, request, *args, **kwargs):
        datos = self.entrada(data=request.data)
        datos.is_valid(raise_exception=True)
        creado = services.crear(
            self.modelo,
            recurso=self.recurso,
            duplicado=self.duplicado,
            campo_duplicado=self.campo_duplicado,
            **self.datos_de_alta(dict(datos.validated_data)),
        )
        return Response(self.get_serializer(creado).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=TAG)
    def partial_update(self, request, *args, **kwargs):
        instancia = self.get_object()
        datos = self.entrada(data=request.data, partial=True)
        datos.is_valid(raise_exception=True)
        services.actualizar(
            instancia,
            recurso=self.recurso,
            duplicado=self.duplicado,
            campo_duplicado=self.campo_duplicado,
            **self.datos_de_edicion(instancia, dict(datos.validated_data)),
        )
        return Response(self.get_serializer(instancia).data)

    @extend_schema(tags=TAG)
    def destroy(self, request, *args, **kwargs):
        services.eliminar(self.get_object(), recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClienteViewSet(MaestroViewSet):
    """Clientes de la organización (``?q=``, ``?estado=``, ``?tipo_documento=``, ``?orden=``)."""

    modelo = Cliente
    campo_empresa = None
    serializer_class = ClienteSerializer
    entrada = ClienteEntrada
    recurso = "cliente"
    duplicado = "Ya existe un cliente con ese documento."
    permisos_por_accion = _permisos("MANTENIMIENTO.CLIENTES")
    campos_busqueda = ("nombre", "nombre_comercial", "numero_documento", "correo")
    filtros_exactos = ("estado", "tipo_documento", "asesor")
    campo_propio = "asesor_id"  # el alcance «propio» de un cliente es el que atiende el asesor
    con_asesor = True
    especificacion = importacion.especificacion_clientes()
    ordenes = {
        "nombre": ("nombre",),
        "-nombre": ("-nombre",),
        "documento": ("numero_documento",),
        "reciente": ("-creado_en",),
    }
    orden_por_defecto = ("nombre",)

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.select_related("asesor") if self.con_asesor else queryset

    @action(detail=False, methods=["get"], url_path="plantilla")
    def plantilla(self, request):
        """Plantilla CSV con los encabezados y una fila de ejemplo."""
        respuesta = HttpResponse(
            importacion.plantilla_csv(self.especificacion), content_type="text/csv; charset=utf-8"
        )
        respuesta["Content-Disposition"] = (
            f'attachment; filename="plantilla_{self.especificacion.plural}.csv"'
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    @action(
        detail=False,
        methods=["post"],
        url_path="importar",
        parser_classes=[MultiPartParser, FormParser],
        throttle_classes=[*APIView.throttle_classes, ImportacionThrottle],
    )
    def importar(self, request):
        """``modo=validar`` informa sin guardar; ``modo=importar`` crea las válidas."""
        archivo = request.FILES.get("archivo")
        if archivo is None:
            raise ValidationError({"archivo": "Adjunta el archivo."})
        modo = request.data.get("modo", "validar")
        if modo not in ("validar", "importar"):
            raise ValidationError({"modo": "Use «validar» o «importar»."})
        datos = {
            "organizacion_id": request.user.organizacion_id,
            "asesor": request.user,
        }
        try:
            if modo == "validar":
                informe, creados = importacion.validar(self.especificacion, archivo, **datos), 0
            else:
                informe, creados = importacion.importar(self.especificacion, archivo, **datos)
        except importacion.ErrorImportacion as error:
            raise ValidationError({"archivo": str(error)}) from None
        return Response({**informe.como_dict(), "modo": modo, "creados": creados})

    def _puede_asignar(self) -> bool:
        return motor.alcance_de(self.request.user, ASIGNAR_ASESOR, None) is not None

    def _sin_limite_si_no_puede(self, datos: dict) -> dict:
        """El límite de crédito solo lo fija quien tiene ese permiso; a los demás se les ignora."""
        if motor.alcance_de(self.request.user, LIMITE_CREDITO, None) is None:
            datos.pop("limite_credito", None)
            datos.pop("credito_sin_limite", None)
        return datos

    def _asesor(self, usuario_id):
        usuario = Usuario.objects.filter(
            pk=usuario_id, organizacion_id=self.request.user.organizacion_id, is_active=True
        ).first()
        if usuario is None:
            raise ValidationError({"asesor": "Elija un usuario activo de la organización."})
        return usuario

    def datos_de_alta(self, validados: dict) -> dict:
        datos = self._sin_limite_si_no_puede(super().datos_de_alta(validados))
        if self.con_asesor:
            elegido = datos.pop("asesor", None)
            # Quien no puede asignar queda como asesor de lo que registra, sin importar lo enviado.
            datos["asesor"] = (
                self._asesor(elegido) if elegido and self._puede_asignar() else self.request.user
            )
        return datos

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        datos = self._sin_limite_si_no_puede(super().datos_de_edicion(instancia, validados))
        if self.con_asesor:
            elegido = datos.pop("asesor", None)
            if elegido and elegido != instancia.asesor_id and self._puede_asignar():
                datos["asesor"] = self._asesor(elegido)
        return datos


class ProveedorViewSet(ClienteViewSet):
    con_asesor = False
    especificacion = importacion.especificacion_proveedores()
    filtros_exactos = ("estado", "tipo_documento")
    campo_propio = "creado_por_id"
    modelo = Proveedor
    serializer_class = ProveedorSerializer
    entrada = ProveedorEntrada
    recurso = "proveedor"
    duplicado = "Ya existe un proveedor con ese documento."
    permisos_por_accion = _permisos("MANTENIMIENTO.PROVEEDORES")

    def get_serializer_context(self):
        # Dato financiero: solo para quien puede editar proveedores (quien solo consulta no lo ve).
        puede = motor.alcance_de(self.request.user, "MANTENIMIENTO.PROVEEDORES.EDITAR", None)
        return {**super().get_serializer_context(), "ver_cuenta": puede is not None}

    campos_busqueda = (
        "nombre",
        "nombre_comercial",
        "numero_documento",
        "correo",
        "contacto",
        "ciudad",
        "productos_referencia",
    )


class _PorEmpresaMixin:
    """Maestros de cada empresa: la empresa va en la URL (listar) o en el cuerpo (crear)."""

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                self.modelo.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        if self.action == "create":
            self.requiere_empresa = True  # la empresa es obligatoria y explícita al crear
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset()
        valor = self.request.query_params.get("empresa")  # solo la URL: el cuerpo no filtra
        if valor:
            if not valor.isdigit():
                raise ValidationError({"empresa": "Debe ser un número entero."})
            queryset = queryset.filter(empresa_id=int(valor))
        return queryset

    def _empresa_activa(self, validados: dict) -> Empresa:
        empresa = Empresa.objects.filter(
            pk=validados.pop("empresa", None), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        return empresa

    def _empresa_inmutable(self, instancia, validados: dict) -> None:
        if validados.pop("empresa", instancia.empresa_id) != instancia.empresa_id:
            raise ValidationError({"empresa": "No se puede pasar a otra empresa."})


class PersonalViewSet(_PorEmpresaMixin, MaestroViewSet):
    """Personal de cada empresa (``?empresa=ID`` obligatorio al crear)."""

    modelo = Personal
    campo_empresa = "empresa_id"
    serializer_class = PersonalSerializer
    entrada = PersonalEntrada
    recurso = "personal"
    duplicado = "Ya existe una persona con ese documento en la empresa."
    permisos_por_accion = _permisos("MANTENIMIENTO.PERSONAL")
    campos_busqueda = ("nombres", "apellidos", "numero_documento", "cargo", "correo")
    filtros_exactos = ("estado", "area", "tipo_documento")
    ordenes = {
        "nombre": ("apellidos", "nombres"),
        "-nombre": ("-apellidos", "-nombres"),
        "ingreso": ("fecha_ingreso",),
        "-ingreso": ("-fecha_ingreso",),
    }
    orden_por_defecto = ("apellidos", "nombres")

    def get_queryset(self):
        return super().get_queryset().select_related("usuario")

    def _resolver_usuario(self, validados: dict, instancia=None) -> None:
        """Valida el vínculo con un usuario: de la misma organización y libre."""
        if "usuario" not in validados or validados["usuario"] is None:
            return
        # Vincular expone la lista de usuarios: exige poder verlos.
        motor.exigir_permiso(self.request.user, "SEGURIDAD.USUARIOS.VER", None)
        usuario = Usuario.objects.filter(
            pk=validados["usuario"], organizacion_id=self.request.user.organizacion_id
        ).first()
        if usuario is None:
            raise ValidationError({"usuario": "Elija un usuario válido."})
        ocupado = Personal.objects.sin_ambito().filter(usuario=usuario)
        if instancia is not None:
            ocupado = ocupado.exclude(pk=instancia.pk)
        if ocupado.exists():
            raise UsuarioYaVinculado()
        validados["usuario"] = usuario

    def datos_de_alta(self, validados: dict) -> dict:
        self._resolver_usuario(validados)
        empresa = self._empresa_activa(validados)
        validados.setdefault("estado", EstadoRegistro.ACTIVO)
        return {**validados, "empresa": empresa}

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        self._empresa_inmutable(instancia, validados)
        self._resolver_usuario(validados, instancia)
        return validados


class ConsultaDocumentoView(APIView):
    """``GET /consultas/{dni,ruc}/<numero>/``: datos públicos para autocompletar formularios."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = "MANTENIMIENTO.CONSULTAS.USAR"
    throttle_classes = [*APIView.throttle_classes, ConsultaDocumentoThrottle]

    def empresas_de_la_operacion(self, request):
        return [None]

    @extend_schema(tags=TAG)
    def get(self, request, tipo, numero):
        if tipo not in ("dni", "ruc"):
            raise Http404
        datos = consultas.consultar(tipo, numero)
        # Quién consultó qué número queda registrado (son datos de personas).
        registrar(
            "documento.consultado",
            recurso_tipo=tipo,
            recurso_id=numero,
            resumen=f"Consulta de {tipo.upper()} en el servicio externo",
        )
        respuesta = Response(datos)
        respuesta["Cache-Control"] = "no-store"
        return respuesta


# --------------------------------------------------------------------------- catálogos
class _CatalogoViewSet(MaestroViewSet):
    """Catálogos simples de la organización (los comparten todas sus empresas)."""

    campo_empresa = None
    campo_propio = "creado_por_id"
    entrada = CatalogoEntrada
    campo_duplicado = "nombre"
    campos_busqueda = ("nombre",)
    ordenes = {"nombre": ("nombre",), "-nombre": ("-nombre",), "reciente": ("-creado_en",)}
    orden_por_defecto = ("nombre",)


class _ProtegeEnUso:
    """No deja eliminar un catálogo que algún producto usa: se desactiva en su lugar."""

    relaciones_en_uso: tuple[str, ...] = ()
    mensaje_en_uso = "Hay productos que la usan. Desactívala en lugar de eliminarla."

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        if any(getattr(instancia, relacion).exists() for relacion in self.relaciones_en_uso):
            raise RegistroEnUso(self.mensaje_en_uso)
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FamiliaViewSet(_CatalogoViewSet):
    """Familias de productos (``?q=``, ``?estado=``); ``n_categorias`` cuenta sus categorías."""

    modelo = Familia
    serializer_class = FamiliaSerializer
    recurso = "familia"
    duplicado = "Ya existe una familia con ese nombre."
    permisos_por_accion = _permisos("MANTENIMIENTO.CLASIFICACION")

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(
                n_categorias=Count("categorias", filter=Q(categorias__eliminado_en__isnull=True))
            )
        )

    def destroy(self, request, *args, **kwargs):
        familia = self.get_object()
        if Categoria.objects.filter(familia=familia).exists():
            raise FamiliaConCategorias()
        services.eliminar(familia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CategoriaViewSet(_ProtegeEnUso, _CatalogoViewSet):
    """Categorías (``?familia=ID``, ``?q=``, ``?estado=``). Cada una pertenece a una familia."""

    modelo = Categoria
    serializer_class = CategoriaSerializer
    entrada = CategoriaEntrada
    recurso = "categoria"
    duplicado = "Ya existe una categoría con ese nombre en la familia."
    permisos_por_accion = _permisos("MANTENIMIENTO.CLASIFICACION")
    campos_busqueda = ("nombre", "familia__nombre")
    ordenes = {**_CatalogoViewSet.ordenes, "familia": ("familia__nombre", "nombre")}
    relaciones_en_uso = ("productos",)

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("familia")
            .annotate(
                n_campos=Count(
                    "campos_especificacion",
                    filter=Q(campos_especificacion__estado=EstadoRegistro.ACTIVO),
                )
            )
        )
        familia = self.request.query_params.get("familia")
        if familia:
            if not familia.isdigit():
                raise ValidationError({"familia": "Debe ser un número entero."})
            queryset = queryset.filter(familia_id=int(familia))
        return queryset

    def _familia(self, familia_id):
        familia = Familia.objects.filter(pk=familia_id, estado=EstadoRegistro.ACTIVO).first()
        if familia is None:
            raise ValidationError({"familia": "Elija una familia activa."})
        return familia

    def datos_de_alta(self, validados: dict) -> dict:
        validados["familia"] = self._familia(validados["familia"])
        return super().datos_de_alta(validados)

    # -- especificaciones técnicas de la categoría --------------------------------
    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=False, methods=["get"], url_path="plantillas-especificaciones")
    def plantillas(self, request):
        """Las plantillas de ejemplo que se pueden cargar en una categoría."""
        return Response(especificaciones.plantillas_disponibles())

    @extend_schema(tags=TAG, responses={200: CampoEspecificacionSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="especificaciones")
    def especificaciones(self, request, pk=None):
        """Los campos que se piden a los productos de esta categoría (también los inactivos)."""
        categoria = self.get_object()
        lista = especificaciones.campos_de(categoria)
        return Response(CampoEspecificacionSerializer(lista, many=True).data)

    @especificaciones.mapping.post
    @extend_schema(
        tags=TAG,
        request=EspecificacionesEntrada,
        responses={200: CampoEspecificacionSerializer(many=True)},
    )
    def guardar_especificaciones(self, request, pk=None):
        """Guarda la lista completa de campos, en el orden enviado."""
        categoria = self.get_object()
        entrada = EspecificacionesEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        especificaciones.guardar_campos(
            categoria, [dict(c) for c in entrada.validated_data["campos"]]
        )
        todos = especificaciones.campos_de(categoria)
        return Response(CampoEspecificacionSerializer(todos, many=True).data)

    @extend_schema(
        tags=TAG,
        request=PlantillaEntrada,
        responses={200: CampoEspecificacionSerializer(many=True)},
    )
    @action(detail=True, methods=["post"], url_path="especificaciones/plantilla")
    def cargar_plantilla(self, request, pk=None):
        """Suma a la categoría los campos de una plantilla de ejemplo (laptop, mouse, monitor…)."""
        categoria = self.get_object()
        entrada = PlantillaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        campos = especificaciones.cargar_plantilla(categoria, entrada.validated_data["plantilla"])
        return Response(CampoEspecificacionSerializer(campos, many=True).data)

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if "familia" in validados:
            if validados["familia"] == instancia.familia_id:
                del validados["familia"]
            else:
                validados["familia"] = self._familia(validados["familia"])  # la mueve de familia
        return validados


class MarcaViewSet(_ProtegeEnUso, _CatalogoViewSet):
    modelo = Marca
    serializer_class = MarcaSerializer
    recurso = "marca"
    duplicado = "Ya existe una marca con ese nombre."
    permisos_por_accion = _permisos("MANTENIMIENTO.MARCAS")
    relaciones_en_uso = ("productos",)


class AlmacenViewSet(_PorEmpresaMixin, MaestroViewSet):
    """Almacenes de cada empresa (``?empresa=ID``, ``?tipo=``, ``?estado=``, ``?q=``)."""

    modelo = Almacen
    campo_empresa = "empresa_id"
    serializer_class = AlmacenSerializer
    entrada = AlmacenEntrada
    recurso = "almacen"
    duplicado = "Ya existe un almacén con ese código o nombre en la empresa."
    campo_duplicado = "codigo"
    permisos_por_accion = _permisos("MANTENIMIENTO.ALMACENES")
    campos_busqueda = ("codigo", "nombre", "direccion")
    filtros_exactos = ("estado", "tipo")
    ordenes = {"codigo": ("codigo",), "nombre": ("nombre",), "-nombre": ("-nombre",)}
    orden_por_defecto = ("codigo",)

    def get_queryset(self):
        return super().get_queryset().select_related("sucursal", "responsable")

    def _sucursal(self, sucursal_id, empresa_id):
        sucursal = Sucursal.objects.filter(
            pk=sucursal_id, empresa_id=empresa_id, estado=Estado.ACTIVO
        ).first()
        if sucursal is None:
            raise ValidationError({"sucursal": "Elija una sucursal activa de la empresa."})
        return sucursal

    def _responsable(self, personal_id, empresa_id):
        if personal_id is None:
            return None  # sin responsable
        responsable = Personal.objects.filter(pk=personal_id, empresa_id=empresa_id).first()
        if responsable is None:
            raise ValidationError({"responsable": "Elija a alguien del personal de la empresa."})
        return responsable

    def datos_de_alta(self, validados: dict) -> dict:
        empresa = self._empresa_activa(validados)
        validados["sucursal"] = self._sucursal(validados["sucursal"], empresa.pk)
        if "responsable" in validados:
            validados["responsable"] = self._responsable(validados["responsable"], empresa.pk)
        validados.setdefault("estado", EstadoRegistro.ACTIVO)
        return {**validados, "empresa": empresa}

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        self._empresa_inmutable(instancia, validados)
        if "sucursal" in validados:
            if validados["sucursal"] == instancia.sucursal_id:
                del validados["sucursal"]
            else:
                validados["sucursal"] = self._sucursal(validados["sucursal"], instancia.empresa_id)
        if "responsable" in validados:
            validados["responsable"] = self._responsable(
                validados["responsable"], instancia.empresa_id
            )
        return validados


class UbicacionViewSet(_PorEmpresaMixin, MaestroViewSet):
    """Ubicaciones de un almacén (``?empresa=ID``, ``?almacen=ID``, ``?estado=``, ``?q=``).

    ``n_productos`` cuenta los productos asignados. Una ubicación en uso no se elimina: se
    desactiva.
    """

    modelo = Ubicacion
    campo_empresa = "empresa_id"
    serializer_class = UbicacionSerializer
    entrada = UbicacionEntrada
    recurso = "ubicacion"
    duplicado = "Ya existe una ubicación con ese código en el almacén."
    campo_duplicado = "codigo"
    permisos_por_accion = _permisos("MANTENIMIENTO.UBICACIONES")
    campos_busqueda = ("codigo", "nombre")
    filtros_exactos = ("estado",)
    ordenes = {"codigo": ("codigo",), "nombre": ("nombre",)}
    orden_por_defecto = ("almacen__codigo", "codigo")

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("almacen")
            .annotate(
                n_productos=Count("productos", filter=Q(productos__eliminado_en__isnull=True))
            )
        )
        almacen = self.request.query_params.get("almacen")
        if almacen:
            if not almacen.isdigit():
                raise ValidationError({"almacen": "Debe ser un número entero."})
            queryset = queryset.filter(almacen_id=int(almacen))
        return queryset

    def _almacen(self, almacen_id, empresa_id) -> Almacen:
        almacen = Almacen.objects.filter(
            pk=almacen_id, empresa_id=empresa_id, estado=EstadoRegistro.ACTIVO
        ).first()
        if almacen is None:
            raise ValidationError({"almacen": "Elija un almacén activo de la empresa."})
        return almacen

    def datos_de_alta(self, validados: dict) -> dict:
        empresa = self._empresa_activa(validados)
        if "almacen" not in validados:
            raise ValidationError({"almacen": "Elija el almacén."})
        validados["almacen"] = self._almacen(validados["almacen"], empresa.pk)
        validados.setdefault("estado", EstadoRegistro.ACTIVO)
        return {**validados, "empresa": empresa}

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        self._empresa_inmutable(instancia, validados)
        if validados.pop("almacen", instancia.almacen_id) != instancia.almacen_id:
            raise ValidationError({"almacen": "No se puede pasar a otro almacén."})
        return validados

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        if instancia.productos.exists():
            raise RegistroEnUso("Hay productos asignados a esta ubicación. Desactívala.")
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CentroCostoViewSet(_CatalogoViewSet):
    """Centros de costo de la organización, en dos niveles (``?q=``, ``?estado=``, ``?padre=``)."""

    modelo = CentroCosto
    serializer_class = CentroCostoSerializer
    entrada = CentroCostoEntrada
    recurso = "centro_costo"
    duplicado = "Ya existe un centro de costo con ese código o nombre."
    campo_duplicado = "codigo"
    permisos_por_accion = _permisos("MANTENIMIENTO.CENTROS_COSTO")
    campos_busqueda = ("codigo", "nombre")
    ordenes = {"codigo": ("codigo",), "nombre": ("nombre",), "-nombre": ("-nombre",)}
    orden_por_defecto = ("codigo",)

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("padre")
            .annotate(n_hijos=Count("hijos", filter=Q(hijos__eliminado_en__isnull=True)))
        )
        padre = self.request.query_params.get("padre")
        if padre == "ninguno":  # solo los de primer nivel (candidatos a grupo)
            queryset = queryset.filter(padre__isnull=True)
        elif padre:
            if not padre.isdigit():
                raise ValidationError({"padre": "Debe ser un número entero o «ninguno»."})
            queryset = queryset.filter(padre_id=int(padre))
        return queryset

    def _padre(self, padre_id):
        if padre_id is None:
            return None
        padre = CentroCosto.objects.filter(pk=padre_id, estado=EstadoRegistro.ACTIVO).first()
        if padre is None:
            raise ValidationError({"padre": "Elija un centro de costo activo como grupo."})
        return padre

    def datos_de_alta(self, validados: dict) -> dict:
        if "padre" in validados:
            validados["padre"] = self._padre(validados["padre"])
        return super().datos_de_alta(validados)

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if "padre" in validados:
            validados["padre"] = self._padre(validados["padre"])
        return validados

    def destroy(self, request, *args, **kwargs):
        centro = self.get_object()
        if CentroCosto.objects.filter(padre=centro).exists():
            raise CentroConHijos()
        services.eliminar(centro, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TipoCambioViewSet(MaestroViewSet):
    """Tipo de cambio por fecha (``?fuente=``, ``?desde=``, ``?hasta=``).

    Las filas de SUNAT y SBS son oficiales: solo se traen con ``actualizar``. Los usuarios
    cargan, editan y eliminan únicamente las manuales.
    """

    modelo = TipoCambio
    campo_empresa = None
    campo_propio = "creado_por_id"
    serializer_class = TipoCambioSerializer
    entrada = TipoCambioEntrada
    recurso = "tipo_cambio"
    duplicado = "Ya hay un tipo de cambio manual para esa fecha."
    campo_duplicado = "fecha"
    permisos_por_accion = _permisos("MANTENIMIENTO.TIPO_CAMBIO")
    filtros_exactos = ("fuente",)
    ordenes = {"fecha": ("fecha",), "-fecha": ("-fecha",)}
    orden_por_defecto = ("-fecha", "fuente")

    def get_queryset(self):
        queryset = super().get_queryset()
        for parametro, filtro in (("desde", "fecha__gte"), ("hasta", "fecha__lte")):
            valor = self.request.query_params.get(parametro)
            if valor:
                try:
                    queryset = queryset.filter(**{filtro: date.fromisoformat(valor)})
                except ValueError:
                    raise ValidationError({parametro: "Use el formato AAAA-MM-DD."}) from None
        return queryset

    def datos_de_alta(self, validados: dict) -> dict:
        return {
            **super().datos_de_alta(validados),
            "fuente": FuenteTipoCambio.MANUAL,
            "moneda": "USD",
        }

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if not instancia.es_manual:
            raise TipoCambioOficial()
        return validados

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        if not instancia.es_manual:
            raise TipoCambioOficial()
        services.eliminar(instancia, recurso=self.recurso)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="resumen")
    def resumen(self, request):
        """La tasa más reciente de cada fuente (lo que aplica hoy)."""
        hoy = timezone.localdate()
        filas = []
        for fuente in FuenteTipoCambio.values:
            fila = tipo_cambio.vigente(request.user.organizacion_id, hoy, fuente)
            if fila is not None:
                filas.append(self.get_serializer(fila).data)
        return Response({"hoy": hoy.isoformat(), "fuentes": filas, "uso": cuota.estado()})

    @action(
        detail=False,
        methods=["post"],
        url_path="actualizar",
        throttle_classes=[*APIView.throttle_classes, ConsultaDocumentoThrottle],
    )
    def actualizar(self, request):
        """Trae el tipo de cambio de SUNAT y SBS ahora (consume la cuota de Decolecta)."""
        datos = ActualizarTipoCambioEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        resultados = tipo_cambio.sincronizar(
            request.user.organizacion_id,
            fecha=datos.validated_data.get("fecha"),
            fuentes=datos.validated_data.get("fuentes", [FuenteTipoCambio.SUNAT]),
            actor_id=request.user.pk,
            forzar=datos.validated_data.get("forzar", False),
        )
        return Response({"resultados": resultados, "uso": cuota.estado()})


class UsoConsultasView(APIView):
    """``GET /consultas/uso/``: cuántas consultas al servicio externo se gastaron este mes."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = "MANTENIMIENTO.CONSULTAS.USAR"

    def empresas_de_la_operacion(self, request):
        return [None]

    @extend_schema(tags=TAG)
    def get(self, request):
        return Response(cuota.estado())


# --------------------------------------------------------------------------- productos
class UnidadMedidaViewSet(_ProtegeEnUso, _CatalogoViewSet):
    """Unidades de medida (``?q=``, ``?estado=``). ``POST sembrar`` carga las más comunes."""

    modelo = UnidadMedida
    serializer_class = UnidadMedidaSerializer
    entrada = UnidadMedidaEntrada
    recurso = "unidad_medida"
    duplicado = "Ya existe una unidad con ese nombre o abreviatura."
    permisos_por_accion = _permisos("MANTENIMIENTO.UNIDADES")
    campos_busqueda = ("nombre", "abreviatura")
    relaciones_en_uso = ("productos", "presentaciones")

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=False, methods=["post"])
    def sembrar(self, request):
        creadas = productos.sembrar_unidades(request.user.organizacion_id)
        return Response({"creadas": creadas})


class ListaPrecioViewSet(_ProtegeEnUso, _CatalogoViewSet):
    """Listas de precios (Público, Descuento…); sus nombres los define cada negocio."""

    modelo = ListaPrecio
    serializer_class = ListaPrecioSerializer
    entrada = ListaPrecioEntrada
    recurso = "lista_precio"
    duplicado = "Ya existe una lista de precios con ese nombre."
    permisos_por_accion = _permisos("MANTENIMIENTO.LISTAS_PRECIO")
    ordenes = {**_CatalogoViewSet.ordenes, "orden": ("orden", "nombre")}
    orden_por_defecto = ("orden", "nombre")
    relaciones_en_uso = ("precios", "precios_presentacion")
    mensaje_en_uso = "Hay productos con precio en esta lista. Desactívala en lugar de eliminarla."

    def datos_de_alta(self, validados: dict) -> dict:
        if "orden" not in validados:
            ultimo = ListaPrecio.objects.aggregate(m=Max("orden"))["m"] or 0
            validados["orden"] = min(ultimo + 1, 99)
        # La primera lista que se crea es la principal (la de venta normal).
        validados["es_principal"] = not ListaPrecio.objects.filter(es_principal=True).exists()
        return super().datos_de_alta(validados)

    def datos_de_edicion(self, instancia, validados: dict) -> dict:
        if instancia.es_principal and validados.get("estado") == EstadoRegistro.INACTIVO:
            raise ValidationError({"estado": "La lista principal no se puede desactivar."})
        return validados

    def destroy(self, request, *args, **kwargs):
        if self.get_object().es_principal:
            raise RegistroEnUso("La lista principal no se puede eliminar.")
        return super().destroy(request, *args, **kwargs)

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=False, methods=["post"])
    def sembrar(self, request):
        creadas = productos.sembrar_listas(request.user.organizacion_id)
        return Response({"creadas": creadas})


class ProductoViewSet(MaestroViewSet):
    """Productos y servicios de la organización.

    Filtros: ``?q=`` (nombre, código, barras), ``?estado=``, ``?tipo=``, ``?familia=``,
    ``?categoria=``, ``?marca=``. El costo y la utilidad solo los ve quien puede cambiar precios.
    """

    modelo = Producto
    campo_empresa = None
    serializer_class = ProductoSerializer
    entrada = ProductoEntrada
    recurso = "producto"
    permisos_por_accion = _permisos("MANTENIMIENTO.PRODUCTOS")
    campos_busqueda = ("nombre", "codigo", "codigo_barras", "codigo_fabricante")
    filtros_exactos = ("estado", "tipo")
    ordenes = {
        "nombre": ("nombre",),
        "-nombre": ("-nombre",),
        "codigo": ("codigo",),
        "reciente": ("-creado_en",),
    }
    orden_por_defecto = ("nombre",)

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["ve_costos"] = self._puede_cambiar_precio()
        return contexto

    def _puede_cambiar_precio(self) -> bool:
        cache = getattr(self.request, "_puede_cambiar_precio", None)
        if cache is None:
            cache = motor.tiene_permiso(self.request.user, CAMBIAR_PRECIO)
            self.request._puede_cambiar_precio = cache
        return cache

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("categoria__familia", "marca", "unidad", "afectacion_igv")
            .prefetch_related(
                "fotos",
                Prefetch("precios", queryset=PrecioProducto.objects.select_related("lista")),
                Prefetch(
                    "presentaciones",
                    queryset=PresentacionProducto.objects.select_related("unidad").prefetch_related(
                        Prefetch(
                            "precios", queryset=PrecioPresentacion.objects.select_related("lista")
                        )
                    ),
                ),
            )
        )
        params = self.request.query_params
        for parametro, campo in (
            ("familia", "categoria__familia_id"),
            ("categoria", "categoria_id"),
            ("marca", "marca_id"),
        ):
            valor = params.get(parametro)
            if valor:
                if not valor.isdigit():
                    raise ValidationError({parametro: "Debe ser un número entero."})
                queryset = queryset.filter(**{campo: int(valor)})
        publicado = params.get("publicado")
        if publicado in ("1", "true", "True"):
            queryset = queryset.filter(publicado_web=True)
        elif publicado in ("0", "false", "False"):
            queryset = queryset.filter(publicado_web=False)
        return queryset

    # -- escritura ---------------------------------------------------------------
    def _activo(self, modelo, pk, campo: str, etiqueta: str):
        objeto = modelo.objects.filter(pk=pk, estado=EstadoRegistro.ACTIVO).first()
        if objeto is None:
            raise ValidationError({campo: f"Elija {etiqueta} activa."})
        return objeto

    def _relaciones(self, validados: dict, instancia=None) -> None:
        """Convierte los ids de categoría, marca, unidad e IGV en objetos de la organización."""
        for campo, modelo, etiqueta in (
            ("categoria", Categoria, "una categoría"),
            ("unidad", UnidadMedida, "una unidad de medida"),
            ("marca", Marca, "una marca"),
            ("afectacion_igv", AfectacionIGV, "una afectación del IGV"),
        ):
            if campo not in validados:
                continue
            pk = validados[campo]
            if pk is None:
                continue  # la marca y la afectación del IGV pueden quedar vacías
            elif instancia is not None and pk == getattr(instancia, f"{campo}_id"):
                del validados[campo]  # no cambió: no se exige que siga activa
            else:
                validados[campo] = self._activo(modelo, pk, campo, etiqueta)

    def _exigir_precios(self, validados: dict, instancia=None) -> None:
        """Poner o cambiar costo y precios requiere el permiso de cambiar precios."""
        cambia_costo = "costo" in validados and (
            instancia is None or validados["costo"] != instancia.costo
        )
        if (cambia_costo or "precios" in validados) and not self._puede_cambiar_precio():
            motor.exigir_permiso(self.request.user, CAMBIAR_PRECIO)  # lanza PermisoDenegado
        if instancia is not None and not cambia_costo:
            validados.pop("costo", None)

    @extend_schema(tags=TAG)
    def create(self, request, *args, **kwargs):
        entrada = self.entrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        validados = dict(entrada.validated_data)
        self._exigir_precios(validados)
        precios = validados.pop("precios", None)
        self._relaciones(validados)
        creado = productos.crear_producto(
            organizacion_id=request.user.organizacion_id, datos=validados, precios=precios
        )
        creado = self.get_queryset().get(pk=creado.pk)
        return Response(self.get_serializer(creado).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=TAG)
    def partial_update(self, request, *args, **kwargs):
        instancia = self.get_object()
        entrada = self.entrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        validados = dict(entrada.validated_data)
        self._exigir_precios(validados, instancia)
        precios = validados.pop("precios", None)
        self._relaciones(validados, instancia)
        productos.actualizar_producto(instancia, datos=validados, precios=precios)
        return Response(self.get_serializer(self.get_queryset().get(pk=instancia.pk)).data)

    # -- fotos --------------------------------------------------------------------
    def _foto(self, producto, foto_id) -> FotoProducto:
        foto = FotoProducto.objects.filter(producto=producto, pk=foto_id).first()
        if foto is None:
            raise Http404
        return foto

    @action(
        detail=True,
        methods=["get"],
        url_path="fotos",
        parser_classes=[MultiPartParser, FormParser],
    )
    @extend_schema(tags=TAG, responses={200: FotoProductoSerializer(many=True)})
    def fotos(self, request, pk=None):
        producto = self.get_object()
        lista = FotoProducto.objects.filter(producto=producto)
        return Response(FotoProductoSerializer(lista, many=True).data)

    @fotos.mapping.post
    @extend_schema(
        tags=TAG, request={"multipart/form-data": dict}, responses={201: FotoProductoSerializer}
    )
    def subir_foto(self, request, pk=None):
        producto = self.get_object()
        archivo = request.FILES.get("imagen")
        if archivo is None:
            raise ImagenInvalida("Elige una foto para subir.")
        foto = servicio_fotos.agregar(producto, archivo)
        return Response(FotoProductoSerializer(foto).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=TAG, responses={(200, "image/webp"): bytes})
    @action(detail=True, methods=["get"], url_path=r"fotos/(?P<foto_id>\d+)/imagen")
    def foto_imagen(self, request, pk=None, foto_id=None):
        """La imagen (o su miniatura con ``?tam=mini``); solo con sesión y permiso."""
        foto = self._foto(self.get_object(), foto_id)
        campo = foto.miniatura if request.query_params.get("tam") == "mini" else foto.imagen
        try:
            archivo = campo.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404 from None
        respuesta = FileResponse(archivo, content_type="image/webp")
        respuesta["Cache-Control"] = "private, max-age=3600"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta

    @extend_schema(tags=TAG, request=None, responses={200: FotoProductoSerializer})
    @action(detail=True, methods=["post"], url_path=r"fotos/(?P<foto_id>\d+)/principal")
    def foto_principal(self, request, pk=None, foto_id=None):
        foto = servicio_fotos.hacer_principal(self._foto(self.get_object(), foto_id))
        return Response(FotoProductoSerializer(foto).data)

    @extend_schema(
        tags=TAG, request=OrdenFotosEntrada, responses={200: FotoProductoSerializer(many=True)}
    )
    @action(detail=True, methods=["post"], url_path="fotos/orden")
    def orden_fotos(self, request, pk=None):
        """Ordena las fotos: se envían todas sus ids y la primera queda como principal."""
        producto = self.get_object()
        entrada = OrdenFotosEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        lista = servicio_fotos.reordenar(producto, entrada.validated_data["ids"])
        return Response(FotoProductoSerializer(lista, many=True).data)

    @extend_schema(tags=TAG, request=None, responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"fotos/(?P<foto_id>\d+)")
    def eliminar_foto(self, request, pk=None, foto_id=None):
        servicio_fotos.eliminar(self._foto(self.get_object(), foto_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
