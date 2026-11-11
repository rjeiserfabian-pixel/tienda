import json
from datetime import date
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.caja.models import SesionCaja
from apps.core.exceptions import ErrorDominio
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import MostradorThrottle
from apps.inventario.series import mas_antiguas
from apps.mantenimiento import fiscal
from apps.mantenimiento import series as numeracion
from apps.mantenimiento import tipo_cambio as servicio_tipo_cambio
from apps.mantenimiento.models import (
    AfectacionIGV,
    Almacen,
    Categoria,
    Cliente,
    EstadoRegistro,
    ListaPrecio,
    MedioPago,
    Periodicidad,
    Producto,
    SerieComprobante,
    TipoComprobante,
)
from apps.organizacion.models import Empresa, Estado, Sucursal
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.models import Usuario
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor
from apps.ventas import catalogo, credito, proformas, servicios, ventas_internas
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import (
    AbonoVenta,
    ComprobanteVenta,
    DocumentoInterno,
    FormaPago,
    LineaVenta,
    Proforma,
    Venta,
)

from .serializers import (
    AnulacionVentaEntrada,
    CarritoEntrada,
    VentaDetalleSerializer,
    VentaEntrada,
    VentaSerializer,
)

TAG = ["ventas"]
VER = "VENTAS.VER"
VENDER = "VENTAS.VENDER"
ANULAR = "VENTAS.ANULAR"
DESCUENTO = "VENTAS.DESCUENTO"
PRECIO_TECNICO = "VENTAS.PRECIO_TECNICO"
BAJO_MINIMO = "VENTAS.VENDER_BAJO_MINIMO"
OTRA_EMPRESA = "VENTAS.VENDER_STOCK_OTRA_EMPRESA"
VENTA_INTERNA = "VENTAS.VENTA_INTERNA"
ELEGIR_VENDEDOR = "VENTAS.ELEGIR_VENDEDOR"
CAMBIAR_TC = "VENTAS.CAMBIAR_TIPO_CAMBIO"
CREDITO = "VENTAS.CREDITO"
CREDITO_EXCEDER = "VENTAS.CREDITO_EXCEDER"
COBRAR = "VENTAS.COBRAR"


def _nombre_empresa(empresa: Empresa) -> str:
    return empresa.nombre_comercial or empresa.razon_social


def _nombre_usuario(usuario) -> str:
    return (usuario.get_full_name() or usuario.username).strip()


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


def _empresas_del_carrito(request, view) -> list[int]:
    """El mostrador y cada empresa que surte una línea: se exige el permiso en todas."""
    empresas = [empresa_declarada(request, view)]
    facturar_por = request.data.get("facturar_por") if hasattr(request.data, "get") else None
    if str(facturar_por).isdigit():
        empresas.append(int(facturar_por))
    lineas = request.data.get("lineas") if hasattr(request.data, "get") else None
    if isinstance(lineas, list):
        for linea in lineas:
            valor = linea.get("empresa") if isinstance(linea, dict) else None
            if str(valor).isdigit():
                empresas.append(int(valor))
    return list(dict.fromkeys(empresas))


def _empresas_que_venden(usuario, org_id: int) -> list[Empresa]:
    """Las empresas del usuario desde las que puede vender, la principal primero."""
    ids = motor.empresas_ids_de(usuario)
    empresas = Empresa.objects.filter(pk__in=ids, estado=Estado.ACTIVO, organizacion_id=org_id)
    return [
        e
        for e in empresas.order_by("-es_principal", "id")
        if motor.tiene_permiso(usuario, VENDER, e.pk)
    ]


def _permisos_de_venta(usuario, empresa: Empresa) -> dict[str, bool]:
    return {
        "descuento": motor.tiene_permiso(usuario, DESCUENTO, empresa.pk),
        "precio_tecnico": motor.tiene_permiso(usuario, PRECIO_TECNICO, empresa.pk),
        "bajo_minimo": motor.tiene_permiso(usuario, BAJO_MINIMO, empresa.pk),
        "otra_empresa": motor.tiene_permiso(usuario, OTRA_EMPRESA, empresa.pk),
        "venta_interna": motor.tiene_permiso(usuario, VENTA_INTERNA, empresa.pk),
        "elegir_vendedor": motor.tiene_permiso(usuario, ELEGIR_VENDEDOR, empresa.pk),
        "cambiar_tipo_cambio": motor.tiene_permiso(usuario, CAMBIAR_TC, empresa.pk),
        "credito": motor.tiene_permiso(usuario, CREDITO, empresa.pk),
        "credito_exceder": motor.tiene_permiso(usuario, CREDITO_EXCEDER, empresa.pk),
        "cobrar": motor.tiene_permiso(usuario, COBRAR, empresa.pk),
    }


def _cobro_disponible(empresa: Empresa, medio: MedioPago, sucursal, moneda: str) -> dict:
    """¿Entra este método a alguna caja o cuenta de la empresa? Si no, dice por qué."""
    try:
        cuenta = servicios.resolver_cuenta(empresa, medio, sucursal, moneda)
    except ErrorDominio as error:
        return {"ok": False, "motivo": error.mensaje}
    if (
        cuenta.exige_sesion
        and not SesionCaja.objects.filter(cuenta=cuenta, estado=SesionCaja.Estado.ABIERTA).exists()
    ):
        return {"ok": False, "motivo": f"Abra la sesión de «{cuenta.nombre}» para cobrar."}
    return {"ok": True, "cuenta": cuenta.nombre}


class ConfiguracionView(APIView):
    """Todo lo que la pantalla de venta necesita para armarse (``?empresa=`` es el mostrador)."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VENDER
    requiere_empresa = True
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("empresa", int, required=True)],
        responses={200: dict},
    )
    def get(self, request):
        mostrador = _empresa_activa(empresa_declarada(request, self))
        org = mostrador.organizacion_id
        permisos = _permisos_de_venta(request.user, mostrador)
        empresas = _empresas_que_venden(request.user, org)
        hoy = timezone.localdate()

        con_series = {}
        series_de = {}
        for x in (
            SerieComprobante.objects.sin_ambito()
            .filter(
                empresa__in=empresas,
                estado=EstadoRegistro.ACTIVO,
                tipo_comprobante__codigo__in=servicios.TIPOS_DE_VENTA,
            )
            .select_related("tipo_comprobante")
            .order_by("tipo_comprobante__codigo", "serie")
        ):
            con_series.setdefault(x.empresa_id, set()).add(x.tipo_comprobante.codigo)
            series_de.setdefault(x.empresa_id, []).append(
                {
                    "id": x.pk,
                    "tipo": x.tipo_comprobante.codigo,
                    "serie": x.serie,
                    "nombre": x.nombre,
                    "sucursal": x.sucursal_id,
                    "proximo": numeracion.formatear(x.serie, x.proximo_numero),
                }
            )
        almacenes = {}
        for a in (
            Almacen.objects.sin_ambito()
            .filter(empresa__in=empresas, estado=EstadoRegistro.ACTIVO, permite_venta=True)
            .order_by("codigo", "id")
        ):
            almacenes.setdefault(a.empresa_id, []).append({"id": a.pk, "nombre": a.nombre})
        medios = list(
            MedioPago.objects.filter(organizacion_id=org, estado=EstadoRegistro.ACTIVO).order_by(
                "id"
            )
        )
        sucursal = _uno(
            Sucursal,
            _entero(request.query_params, "sucursal"),
            "sucursal",
            "Elija una sucursal.",
            empresa=mostrador,
        )
        cobros = {
            moneda: {
                str(e.pk): {str(m.pk): _cobro_disponible(e, m, sucursal, moneda) for m in medios}
                for e in empresas
            }
            for moneda in ("PEN", "USD")
        }
        cambio = servicio_tipo_cambio.vigente(org, hoy)
        listas = ListaPrecio.objects.filter(organizacion_id=org, estado=EstadoRegistro.ACTIVO)
        usos_permitidos = {
            "DESCUENTO": permisos["descuento"],
            "TECNICO": permisos["precio_tecnico"],
            "CREDITO": False,  # la lista de crédito se usa sola al vender a crédito
        }
        vendedores = []
        if permisos["elegir_vendedor"]:
            for u in Usuario.objects.filter(organizacion_id=org, is_active=True).order_by(
                "first_name", "username"
            ):
                if motor.tiene_permiso(u, VENDER, mostrador.pk):
                    vendedores.append({"id": str(u.pk), "nombre": _nombre_usuario(u)})
        igv = fiscal.tasa_vigente(org, AfectacionIGV.Impuesto.IGV)
        respuesta = Response(
            {
                "mostrador": mostrador.pk,
                "sucursales": [
                    {"id": s.pk, "nombre": s.nombre, "codigo": s.codigo}
                    for s in Sucursal.objects.filter(
                        empresa=mostrador, estado=Estado.ACTIVO
                    ).order_by("codigo", "id")
                ],
                "igv_porcentaje": f"{igv:.2f}",
                "tope_boleta": f"{servicios.TOPE_BOLETA_SIN_IDENTIFICAR:.2f}",
                "afectaciones": [
                    {"codigo": a.codigo, "nombre": a.nombre}
                    for a in AfectacionIGV.objects.sin_ambito()
                    .filter(
                        organizacion_id=org,
                        estado=EstadoRegistro.ACTIVO,
                        aplica_ventas=True,
                        gratuita=False,
                    )
                    .order_by("codigo")
                ],
                "empresas": [
                    {
                        "id": e.pk,
                        "nombre": _nombre_empresa(e),
                        "ruc": e.ruc,
                        "es_principal": e.es_principal,
                        "letra": "AB"[i] if i < 2 else str(i + 1),
                        "almacenes": almacenes.get(e.pk, []),
                        "tipos": sorted(con_series.get(e.pk, ())),
                        "series": series_de.get(e.pk, []),
                        "series_proforma": proformas.series_de_proforma(e.pk),
                    }
                    for i, e in enumerate(empresas)
                ],
                "listas": [
                    {
                        "id": lista.pk,
                        "nombre": lista.nombre,
                        "uso": lista.uso,
                        "es_principal": lista.es_principal,
                        "permitida": usos_permitidos.get(lista.uso, True),
                    }
                    for lista in listas.order_by("orden", "id")
                ],
                "tipos_comprobante": [
                    {"codigo": t.codigo, "nombre": t.nombre}
                    for t in TipoComprobante.objects.filter(
                        organizacion_id=org,
                        codigo__in=servicios.TIPOS_DE_VENTA,
                        estado=EstadoRegistro.ACTIVO,
                        aplica_ventas=True,
                    ).order_by("codigo")
                ],
                "medios_pago": [
                    {
                        "id": m.pk,
                        "nombre": m.nombre,
                        "tipo": m.tipo,
                        "requiere_referencia": m.requiere_referencia,
                    }
                    for m in medios
                ],
                "cobros": cobros,
                "categorias": [
                    {"id": c.pk, "nombre": c.nombre}
                    for c in Categoria.objects.filter(
                        organizacion_id=org, estado=EstadoRegistro.ACTIVO
                    ).order_by("nombre")
                ],
                "tipo_cambio": (
                    {"fecha": str(cambio.fecha), "compra": str(cambio.compra)} if cambio else None
                ),
                "permisos": permisos,
                "venta_interna": {
                    "documentos": [
                        {
                            "codigo": codigo,
                            "nombre": nombre,
                            "motivo": ventas_internas.documento_no_disponible(codigo),
                        }
                        for codigo, nombre in DocumentoInterno.choices
                    ],
                },
                "credito": {
                    "cuotas_maximas": servicios.MAX_CUOTAS,
                    "lista": next(
                        (
                            lista.pk
                            for lista in listas.filter(uso="CREDITO").order_by("orden", "id")
                        ),
                        None,
                    ),
                    "periodicidades": [
                        {"id": p.pk, "nombre": p.nombre, "unidad": p.unidad, "cantidad": p.cantidad}
                        for p in Periodicidad.objects.filter(
                            organizacion_id=org, estado=EstadoRegistro.ACTIVO
                        ).order_by("id")
                    ],
                },
                "vendedor": {"id": str(request.user.pk), "nombre": _nombre_usuario(request.user)},
                "vendedores": vendedores,
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class CatalogoView(APIView):
    """Productos para vender: ``?q=`` busca, ``?categoria=`` filtra, ``?pagina=`` recorre."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VENDER
    requiere_empresa = True
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("empresa", int, required=True)],
        responses={200: dict},
    )
    def get(self, request):
        mostrador = _empresa_activa(empresa_declarada(request, self))
        empresas = _empresas_que_venden(request.user, mostrador.organizacion_id)
        fichas, exacto, hay_mas = catalogo.buscar(
            empresas,
            q=request.query_params.get("q", ""),
            categoria=_entero(request.query_params, "categoria"),
            pagina=_entero(request.query_params, "pagina") or 1,
        )
        respuesta = Response({"results": fichas, "exacto": exacto, "hay_mas": hay_mas})
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class SeriesSugeridasView(APIView):
    """Las series más antiguas de un producto en el almacén que surte (primero en entrar, primero
    en salir), para que el punto de venta las proponga. ``?empresa=`` es el mostrador;
    ``surte`` y ``almacen`` son los de la línea. Es solo una propuesta: se puede elegir otra.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VENDER
    requiere_empresa = True
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("empresa", int, required=True)],
        responses={200: dict},
    )
    def get(self, request):
        mostrador = _empresa_activa(empresa_declarada(request, self))
        params = request.query_params
        surte_id, almacen_id = _entero(params, "surte"), _entero(params, "almacen")
        producto_id, cantidad = _entero(params, "producto"), _entero(params, "cantidad")
        if not (surte_id and almacen_id and producto_id and cantidad):
            raise ValidationError("Indique surte, almacen, producto y cantidad.")
        if surte_id not in {
            e.pk for e in _empresas_que_venden(request.user, mostrador.organizacion_id)
        }:
            raise PermissionDenied("No puede vender desde esa empresa.")
        if not Almacen.objects.sin_ambito().filter(pk=almacen_id, empresa_id=surte_id).exists():
            raise ValidationError({"almacen": "El almacén no es de esa empresa."})
        if not Producto.objects.filter(
            pk=producto_id, organizacion_id=mostrador.organizacion_id, lleva_serie=True
        ).exists():
            raise ValidationError({"producto": "Ese producto no lleva serie."})
        series = mas_antiguas(producto_id, surte_id, almacen_id, min(cantidad, 200))
        respuesta = Response({"series": [s.numero for s in series]})
        respuesta["Cache-Control"] = "no-store"
        return respuesta


def _carrito_de(request, v: dict, *, estricto: bool = True) -> dict:
    """Los datos validados del cuerpo pasan a objetos y a los permisos de quien vende."""
    empresa = _empresa_activa(v["empresa"])
    org = empresa.organizacion_id
    permisos = _permisos_de_venta(request.user, empresa)
    cliente = _uno(Cliente, v.get("cliente"), "cliente", "Elija un cliente.", organizacion_id=org)
    lista = _uno(
        ListaPrecio, v.get("lista"), "lista", "Elija una lista de precios.", organizacion_id=org
    )
    sucursal = _uno(Sucursal, v.get("sucursal"), "sucursal", "Elija una sucursal.", empresa=empresa)
    if v.get("tipo_cambio") is not None and not permisos["cambiar_tipo_cambio"]:
        raise PermissionDenied("No tiene permiso para cambiar el tipo de cambio.")
    forma_pago = v.get("forma_pago", FormaPago.CONTADO)
    if forma_pago == FormaPago.CREDITO and not permisos["credito"]:
        raise PermissionDenied("No tiene permiso para vender a crédito.")
    cuotas = None
    if v.get("cuotas"):
        c = v["cuotas"]
        periodicidad = _uno(
            Periodicidad,
            c["periodicidad"],
            "cuotas",
            "Elija cada cuánto vencen las cuotas.",
            organizacion_id=org,
        )
        cuotas = servicios.CuotasEntrada(c["cantidad"], c["primera_fecha"], periodicidad)
    ids = [ln["producto"] for ln in v["lineas"]]
    productos = {p.pk: p for p in Producto.objects.filter(pk__in=ids, organizacion_id=org)}
    empresas = {
        e.pk: e
        for e in Empresa.objects.filter(
            pk__in={ln["empresa"] for ln in v["lineas"]}, organizacion_id=org
        )
    }
    almacenes = {
        a.pk: a
        for a in Almacen.objects.sin_ambito().filter(
            pk__in={ln["almacen"] for ln in v["lineas"] if ln.get("almacen")}
        )
    }
    lineas = []
    for ln in v["lineas"]:
        if ln["producto"] not in productos or ln["empresa"] not in empresas:
            raise ValidationError({"lineas": "Hay productos o empresas que no existen."})
        if ln.get("almacen") and ln["almacen"] not in almacenes:
            raise ValidationError({"lineas": "Hay almacenes que no existen."})
        lineas.append(
            servicios.LineaEntrada(
                producto=productos[ln["producto"]],
                cantidad=ln["cantidad"],
                empresa=empresas[ln["empresa"]],
                almacen=almacenes.get(ln.get("almacen")),
                precio_unitario=ln.get("precio_unitario"),
                series=tuple(ln.get("series", ())),
                afectacion=ln.get("afectacion", ""),
            )
        )
    return {
        "empresa": empresa,
        "fecha": timezone.localdate(),
        "tipo_comprobante": v["tipo_comprobante"],
        "lineas": lineas,
        "cliente": cliente,
        "moneda": v.get("moneda", "PEN"),
        "tipo_cambio": v.get("tipo_cambio"),
        "lista": lista,
        "sucursal": sucursal,
        "puede_descontar": permisos["descuento"],
        "puede_precio_tecnico": permisos["precio_tecnico"],
        "puede_vender_bajo_minimo": permisos["bajo_minimo"],
        "puede_vender_stock_otra_empresa": permisos["otra_empresa"],
        "forma_pago": forma_pago,
        "cuotas": cuotas,
        "puede_credito": permisos["credito"],
        "series": {int(k): v for k, v in (v.get("serie_por_empresa") or {}).items()} or None,
    }


def _venta_interna_de(request, v: dict, argumentos: dict) -> dict:
    """Lo que la venta interna le pide a ``registrar_venta`` (vacío si no se pidió).

    El permiso se exige en TODAS las empresas que intervienen: la del mostrador, la que factura y
    las que surten alguna línea. Quien lo tiene puede vender el stock de la otra empresa: es
    justo lo que autoriza.
    """
    pedida = v.get("facturar_por")
    if pedida is None:
        return {}
    mostrador = argumentos["empresa"]
    facturadora = _uno(
        Empresa,
        pedida,
        "facturar_por",
        "Elija una empresa activa que facture.",
        organizacion_id=mostrador.organizacion_id,
        estado=Estado.ACTIVO,
    )
    intervienen = {mostrador.pk, facturadora.pk, *(ln.empresa.pk for ln in argumentos["lineas"])}
    for empresa_id in sorted(intervienen):
        if not motor.tiene_permiso(request.user, VENTA_INTERNA, empresa_id):
            raise PermissionDenied("No tiene permiso para hacer una venta interna entre empresas.")
    almacenes = {}
    for origen_id, destino_id in (v.get("almacenes_internos") or {}).items():
        destino = Almacen.objects.sin_ambito().filter(pk=destino_id, empresa=facturadora).first()
        if destino is None:
            raise ValidationError(
                {"almacenes_internos": "Elija un almacén de la empresa que factura."}
            )
        almacenes[int(origen_id)] = destino
    return {
        "facturar_por": facturadora,
        "documento_interno": v.get("documento_interno", DocumentoInterno.INTERNO),
        "puede_venta_interna": True,
        "almacenes_internos": almacenes or None,
    }


def _situacion(cliente) -> dict:
    """Límite, deuda y disponible del cliente (en soles), listos para mostrar."""
    datos = credito.situacion(cliente)
    return {
        clave: (valor if isinstance(valor, bool) or valor is None else f"{valor:.2f}")
        for clave, valor in datos.items()
    }


class PrevisualizarView(APIView):
    """Totales de cada empresa para el carrito actual, sin guardar nada."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VENDER
    requiere_empresa = True
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        return _empresas_del_carrito(request, self)

    @staticmethod
    def _con_venta_interna(argumentos: dict, interna: dict):
        """El carrito como quedaría con un solo comprobante, y qué impide hacerlo (sin escribir).

        Lo que impide la venta interna se avisa, no falla: la persona puede estar armando el
        carrito. Devuelve (argumentos, resumen para la pantalla o ``None``, avisos).
        """
        facturadora, lineas = interna["facturar_por"], argumentos["lineas"]
        avisos = []
        if motivo := ventas_internas.documento_no_disponible(interna["documento_interno"]):
            avisos.append(motivo)
        try:
            revisadas = ventas_internas.revisar(lineas, facturadora, interna["almacenes_internos"])
        except VentaInvalida as error:
            return argumentos, None, [*avisos, error.mensaje]
        problemas = [p for r in revisadas for p in r.problemas]
        if any(r.almacen_destino is None for r in revisadas):
            # Sin saber dónde recibe no se puede mostrar el comprobante único.
            return argumentos, None, [*avisos, *problemas]
        resumen = {
            "facturar_por": facturadora.pk,
            "documento": interna["documento_interno"],
            "problemas": problemas,
            "entregan": sorted({r.linea.empresa.pk for r in revisadas}),
        }
        nuevas = ventas_internas.lineas_de_la_facturadora(lineas, facturadora, revisadas)
        argumentos = {**argumentos, "lineas": nuevas, "puede_vender_stock_otra_empresa": True}
        return argumentos, resumen, [*avisos, *problemas]

    @extend_schema(tags=TAG, request=CarritoEntrada, responses={200: dict})
    def post(self, request):
        datos = CarritoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        argumentos = _carrito_de(request, datos.validated_data)
        interna = _venta_interna_de(request, datos.validated_data, argumentos)
        resumen_interno, avisos_internos = None, []
        if interna:
            argumentos, resumen_interno, avisos_internos = self._con_venta_interna(
                argumentos, interna
            )
        preparada = servicios.preparar_venta(
            **argumentos,
            inicial=datos.validated_data.get("inicial", Decimal("0")),
            estricto=False,
            revisar_series=resumen_interno is None,
        )
        preparada.avisos.extend(avisos_internos)
        puesto = {id(entrada): i for i, entrada in enumerate(argumentos["lineas"])}
        comprobantes = []
        for posicion, c in enumerate(preparada.comprobantes):
            t = c.totales
            comprobantes.append(
                {
                    "empresa": c.empresa.pk,
                    "serie": c.serie.serie,
                    "op_gravada": str(t.op_gravada),
                    "op_exonerada": str(t.op_exonerada),
                    "op_inafecta": str(t.op_inafecta),
                    "igv": str(t.igv),
                    "total": str(t.total),
                    "credito": str(preparada.creditos[posicion]) if preparada.creditos else None,
                    "cuotas": [
                        {"numero": q.numero, "fecha": str(q.fecha), "monto": str(q.monto)}
                        for q in (preparada.cronogramas[posicion] if preparada.cronogramas else [])
                    ],
                    "lineas": [
                        {
                            "indice": puesto[id(ln.entrada)],
                            "afectacion": ln.afectacion.nombre,
                            "tasa_igv": str(ln.tasa),
                            "precio_lista": str(ln.precio_lista),
                            "precio": str(ln.precio),
                            "minimo": None if ln.minimo_oculto else str(ln.minimo),
                            "estado_precio": ln.estado_precio,
                            "valor_venta": str(ln.importes.valor_venta),
                            "igv": str(ln.importes.igv),
                            "total": str(ln.importes.total),
                        }
                        for ln in c.lineas
                    ],
                }
            )
        respuesta = Response(
            {
                "moneda": preparada.moneda,
                "tipo_cambio": str(preparada.cambio),
                "lista": preparada.lista.pk,
                "total": str(preparada.total),
                "avisos": preparada.avisos,
                "venta_interna": resumen_interno,
                "forma_pago": preparada.forma_pago,
                "cliente_credito": _situacion(preparada.cliente) if preparada.cliente else None,
                "comprobantes": comprobantes,
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class VentaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Ventas del mostrador de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``desde``, ``hasta``, ``estado``, ``vendedor`` (nombre) y ``q`` (número de venta,
    cliente, documento o número de comprobante).
    """

    modelo = Venta
    serializer_class = VentaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": VENDER,
        "anular": ANULAR,
        "anular_comprobante": ANULAR,
    }

    def get_serializer_class(self):
        return VentaDetalleSerializer if self.action == "retrieve" else VentaSerializer

    def empresas_de_la_operacion(self, request):
        if self.action == "create":
            return _empresas_del_carrito(request, self)
        if "pk" in self.kwargs:
            venta = Venta.objects.sin_ambito().filter(pk=self.kwargs["pk"]).first()
            if venta is None:
                raise Http404
            empresas = [venta.empresa_id]
            empresas += list(
                ComprobanteVenta.objects.sin_ambito()
                .filter(venta=venta)
                .values_list("empresa_id", flat=True)
            )
            empresas = list(dict.fromkeys(empresas))
            propias = set(motor.empresas_ids_de(request.user))
            if not request.user.es_admin_plataforma and not propias.intersection(empresas):
                raise Http404  # una venta de otra organización no existe para esta persona
            if self.action in ("anular", "anular_comprobante"):
                # Anular exige el permiso en TODAS las empresas de la venta, también en la que
                # entregó mercadería si fue una venta interna (su stock vuelve a ella).
                return list(
                    dict.fromkeys([*empresas, *ventas_internas.empresas_que_entregaron(venta.pk)])
                )
            # Ver: alcanza con poder ver una de ellas (el serializador oculta las demás).
            for e in empresas:
                if motor.tiene_permiso(request.user, VER, e):
                    return [e]
            return [venta.empresa_id]
        return [empresa_declarada(request, self)]

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        usuario = self.request.user
        if not usuario.es_admin_plataforma:
            contexto["empresas_visibles"] = {
                e for e in motor.empresas_ids_de(usuario) if motor.tiene_permiso(usuario, VER, e)
            }
        if self.action == "list":
            contexto["empresa_vista"] = _entero(self.request.query_params, "empresa")
        return contexto

    @staticmethod
    def _consulta(origen, detalle: bool):
        queryset = origen.select_related(
            "lista", "empresa", "sucursal", *(("cliente",) if detalle else ())
        ).prefetch_related(
            Prefetch(
                "comprobantes",
                # Todos los comprobantes de la venta: el serializador deja solo los que la persona
                # puede ver y avisa que la venta es parcial (si no, no sabría que faltan).
                queryset=ComprobanteVenta.objects.sin_ambito()
                .select_related("empresa", "tipo_comprobante")
                .order_by("id"),
            )
        )
        if detalle:
            queryset = queryset.prefetch_related(
                Prefetch(
                    "comprobantes__lineas",
                    queryset=LineaVenta.objects.select_related(
                        "producto__unidad", "afectacion"
                    ).order_by("orden"),
                ),
                "comprobantes__cobros__medio_pago",
                "comprobantes__cobros__cuenta",
                "comprobantes__cuotas",
                "comprobantes__notas_credito",
                "ventas_internas__empresa",
                "ventas_internas__empresa_destino",
                "ventas_internas__lineas",
                "ventas_internas__devoluciones",
                Prefetch(
                    "comprobantes__abonos",
                    queryset=AbonoVenta.objects.select_related("medio_pago", "cuenta")
                    .prefetch_related("aplicaciones__cuota")
                    .order_by("id"),
                ),
            )
        return queryset

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        usuario = self.request.user
        # Sin ámbito a propósito: la venta hecha en el mostrador de otra empresa la ve quien
        # tiene un comprobante en ella. El aislamiento lo da el alcance por empresa, que solo
        # considera las empresas de la persona (la plataforma sigue con el ámbito de siempre).
        origen = Venta.objects.all() if usuario.es_admin_plataforma else Venta.objects.sin_ambito()
        comprobantes = (
            ComprobanteVenta.objects.all()
            if usuario.es_admin_plataforma
            else ComprobanteVenta.objects.sin_ambito()
        )
        base = self._consulta(origen, detalle=self.action == "retrieve")
        # Una venta la ve quien puede ver el mostrador donde se hizo O el comprobante de alguna
        # de sus empresas: cada empresa ve lo que facturó, aunque otra haya hecho la venta.
        por_mostrador = filtrar_por_alcance(origen, usuario, codigo)
        por_comprobante = filtrar_por_alcance(comprobantes, usuario, codigo)
        queryset = base.filter(
            Q(pk__in=por_mostrador.values("pk")) | Q(pk__in=por_comprobante.values("venta_id"))
        )
        if self.action != "list":
            return queryset
        params = self.request.query_params
        empresa_pedida = _entero(params, "empresa")
        queryset = queryset.filter(
            Q(empresa_id=empresa_pedida) | Q(comprobantes__empresa_id=empresa_pedida)
        ).distinct()
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if params.get("forma_pago") in FormaPago.values:
            queryset = queryset.filter(forma_pago=params["forma_pago"])
        if vendedor := (params.get("vendedor") or "").strip():
            queryset = queryset.filter(vendedor_nombre__icontains=vendedor)
        q = (params.get("q") or "").strip()
        if q:
            condicion = (
                Q(cliente_nombre__icontains=q)
                | Q(cliente_documento__icontains=q)
                | Q(comprobantes__numero__icontains=q)
                | Q(comprobantes__serie__icontains=q)
            )
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion).distinct()
        return queryset.order_by("-fecha", "-id")

    def _vendedor(self, request, empresa: Empresa, pedido):
        """Quién vende: la propia persona, o la que un administrador elige."""
        if pedido is None or pedido == request.user.pk:
            return request.user.pk, _nombre_usuario(request.user)
        if not motor.tiene_permiso(request.user, ELEGIR_VENDEDOR, empresa.pk):
            raise PermissionDenied("Solo puede vender a su propio nombre.")
        elegido = Usuario.objects.filter(
            pk=pedido, organizacion_id=empresa.organizacion_id, is_active=True
        ).first()
        if elegido is None or not motor.tiene_permiso(elegido, VENDER, empresa.pk):
            raise ValidationError({"vendedor": "Elija a una persona que pueda vender."})
        return elegido.pk, _nombre_usuario(elegido)

    @extend_schema(
        tags=TAG,
        request=VentaEntrada,
        responses={201: VentaDetalleSerializer},
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
        datos = VentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        argumentos = _carrito_de(request, v)
        empresa = argumentos["empresa"]
        interna = _venta_interna_de(request, v, argumentos)
        if interna:
            # Quien puede hacer una venta interna puede vender el stock de la otra empresa.
            argumentos = {**argumentos, "puede_vender_stock_otra_empresa": True}
        vendedor_id, vendedor_nombre = self._vendedor(request, empresa, v.get("vendedor"))
        proforma = _uno(
            Proforma,
            v.get("proforma"),
            "proforma",
            "Elija una proforma de esta empresa.",
            empresa=empresa,
        )
        medios = {
            m.pk: m
            for m in MedioPago.objects.filter(
                pk__in={c["medio_pago"] for c in v.get("cobros", [])},
                organizacion_id=empresa.organizacion_id,
            )
        }
        cobros = []
        for c in v.get("cobros", []):
            if c["medio_pago"] not in medios:
                raise ValidationError({"cobros": "Hay métodos de pago que no existen."})
            cobros.append(
                servicios.CobroEntrada(
                    medio_pago=medios[c["medio_pago"]],
                    monto=c["monto"],
                    referencia=c.get("referencia", ""),
                    recibido=c.get("recibido"),
                )
            )

        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            venta = servicios.registrar_venta(
                **argumentos,
                **interna,
                cobros_entrada=cobros,
                vendedor_id=vendedor_id,
                vendedor_nombre=vendedor_nombre,
                observacion=v.get("observacion", ""),
                proforma=proforma,
                puede_exceder_limite=_permisos_de_venta(request.user, empresa)["credito_exceder"],
            )
            return 201, self._detalle(venta.pk)

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

    def _detalle(self, pk: int):
        venta = self._consulta(Venta.objects.all(), detalle=True).get(pk=pk)
        return json.loads(json.dumps(VentaDetalleSerializer(venta).data, default=str))

    @extend_schema(tags=TAG, request=AnulacionVentaEntrada, responses={200: VentaDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula la venta entera: vuelve el stock y el dinero de cada empresa."""
        venta = self.get_object()
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicios.anular_venta(venta, motivo=datos.validated_data["motivo"])
        return Response(self._detalle(venta.pk))

    @extend_schema(tags=TAG, request=AnulacionVentaEntrada, responses={200: VentaDetalleSerializer})
    @action(detail=True, methods=["post"], url_path=r"comprobantes/(?P<comprobante_id>\d+)/anular")
    def anular_comprobante(self, request, pk=None, comprobante_id=None):
        """Anula el comprobante de una sola empresa; los demás de la venta siguen vigentes."""
        venta = self.get_object()
        comprobante = ComprobanteVenta.objects.filter(venta=venta, pk=comprobante_id).first()
        if comprobante is None:
            raise Http404
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicios.anular_comprobante(comprobante, motivo=datos.validated_data["motivo"])
        return Response(self._detalle(venta.pk))
