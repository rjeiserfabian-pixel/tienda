"""Arma el JSON de cada documento tal como lo pide la API de facturación.

Las formas del JSON salen de la documentación de la API (``post.php`` para factura, boleta y nota
de crédito; el bloque de la guía de remisión remitente). Aquí NO se envía nada: son funciones que
reciben el documento y devuelven un diccionario. Lo que lleva las claves SOL (``bloque_empresa``)
se arma aparte para poder mostrar una vista previa con las claves ocultas.

Lo que la documentación no define (cuotas del crédito, transportista público) NO se inventa: el
documento no se puede enviar y se dice por qué (``DocumentoNoEnviable``).
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.mantenimiento.models import Ubigeo
from apps.organizacion.models import ConfiguracionEmpresa, Empresa

from .exceptions import DocumentoNoEnviable

OCULTO = "********"
# Una boleta de MÁS de este monto (en soles) lleva los datos del cliente (regla de SUNAT).
BOLETA_SIN_DATOS_HASTA = Decimal("700")
_TIPO_ENTIDAD = {"RUC": "6", "DNI": "1", "CE": "4", "PASAPORTE": "7"}
_MONEDA = {"PEN": 1, "USD": 2}
_FORMA_PAGO = {"CONTADO": 1, "CREDITO": 2}
UNIDAD_POR_DEFECTO = "NIU"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _num(valor, decimales: int = 2) -> float | None:
    """Número JSON con los decimales pedidos (la API recibe números, no textos)."""
    if valor is None:
        return None
    paso = Decimal(1).scaleb(-decimales)
    return float(Decimal(valor).quantize(paso, rounding=ROUND_HALF_UP))


def _opcional(valor) -> float | None:
    """Un total que no aplica va como ``null``, no como 0."""
    return None if not valor else _num(valor)


def _hora(instante: datetime) -> str:
    return timezone.localtime(instante).strftime("%H:%M:%S")


def _numero(valor: int) -> str:
    return f"{valor:08d}"


def _quitar_guion(placa: str) -> str:
    return (placa or "").replace("-", "").replace(" ", "").upper()


def _partir_nombre(completo: str) -> tuple[str, str]:
    """«Jeiser Fabian Rojas Diaz» → («Jeiser Fabian», «Rojas Diaz»): dos apellidos al final."""
    palabras = (completo or "").split()
    if len(palabras) <= 1:
        return (palabras[0] if palabras else "", "")
    corte = len(palabras) - 2 if len(palabras) >= 3 else 1
    return " ".join(palabras[:corte]), " ".join(palabras[corte:])


# ---------------------------------------------------------------------------
# Empresa
# ---------------------------------------------------------------------------
def faltantes(
    empresa: Empresa, config: ConfiguracionEmpresa | None, *, guia: bool = False
) -> list[str]:
    """Lo que falta configurar para poder enviar (vacío = todo listo)."""
    if config is None:
        return ["Configuración de la empresa"]
    falta = []
    if not config.sunat_usuario_sol:
        falta.append("Usuario secundario de la Clave SOL")
    if not config.sunat_clave_sol:
        falta.append("Clave del usuario secundario SOL")
    if not empresa.direccion_fiscal:
        falta.append("Dirección fiscal de la empresa")
    if not config.ubigeo_fiscal:
        falta.append("Ubigeo del domicilio fiscal")
    elif not Ubigeo.objects.filter(codigo=config.ubigeo_fiscal).exists():
        falta.append("Ubigeo del domicilio fiscal (el código no existe)")
    if guia:
        if not config.sunat_gre_client_id:
            falta.append("Client ID de la guía de remisión")
        if not config.sunat_gre_client_secret:
            falta.append("Client secret de la guía de remisión")
    return falta


def bloque_empresa(
    empresa: Empresa, config: ConfiguracionEmpresa, *, credenciales: bool, guia: bool = False
) -> dict:
    """El bloque ``empresa`` del JSON. Con ``credenciales=False`` las claves salen ocultas."""
    ubigeo = Ubigeo.objects.filter(codigo=config.ubigeo_fiscal).first()
    modo = 1 if config.modo_sunat == ConfiguracionEmpresa.ModoSunat.PRODUCCION else 0
    bloque = {
        "ruc": empresa.ruc,
        "razon_social": empresa.razon_social,
        "nombre_comercial": empresa.nombre_comercial or empresa.razon_social,
        "domicilio_fiscal": empresa.direccion_fiscal,
        "ubigeo": config.ubigeo_fiscal,
        "urbanizacion": config.urbanizacion,
        "departamento": ubigeo.departamento if ubigeo else "",
        "provincia": ubigeo.provincia if ubigeo else "",
        "distrito": ubigeo.distrito if ubigeo else "",
        "modo": str(modo) if guia else modo,  # la guía lo recibe como texto
        "usu_secundario_produccion_user": config.sunat_usuario_sol if credenciales else OCULTO,
        "usu_secundario_produccion_password": config.sunat_clave_sol if credenciales else OCULTO,
    }
    if guia:
        bloque["gre_client_id"] = config.sunat_gre_client_id if credenciales else OCULTO
        bloque["gre_client_secret"] = config.sunat_gre_client_secret if credenciales else OCULTO
    else:
        bloque["cuenta_detraccion"] = ""
    return bloque


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------
def _cliente(venta) -> dict:
    tipo = _TIPO_ENTIDAD.get(venta.cliente_tipo_documento or "", "0")
    documento = venta.cliente_documento or ""
    if tipo == "0":
        documento = documento or "00000000"
    direccion = ""
    if venta.cliente_id and venta.cliente is not None:
        direccion = venta.cliente.direccion
    return {
        "codigo_tipo_entidad": tipo,
        "numero_documento": documento,
        "razon_social_nombres": venta.cliente_nombre or "CLIENTES VARIOS",
        "cliente_direccion": direccion or "-",
    }


def _exigir_cliente(tipo_documento: str, venta, total: Decimal) -> None:
    cliente = _cliente(venta)
    if tipo_documento == "01" and cliente["codigo_tipo_entidad"] != "6":
        raise DocumentoNoEnviable("La factura necesita un cliente con RUC.")
    if (
        tipo_documento == "03"
        and cliente["codigo_tipo_entidad"] == "0"
        and venta.moneda == "PEN"
        and total > BOLETA_SIN_DATOS_HASTA
    ):
        raise DocumentoNoEnviable(
            f"Una boleta de más de S/ {BOLETA_SIN_DATOS_HASTA} necesita el documento del cliente."
        )


def _codigo_sunat(producto, config: ConfiguracionEmpresa) -> str:
    codigo = producto.codigo_sunat or config.codigo_sunat_defecto
    if not codigo:
        raise DocumentoNoEnviable(
            f"«{producto.nombre}» no tiene código SUNAT. Póngale uno al producto, o indique un "
            "código por defecto en la configuración de la facturación electrónica."
        )
    return codigo


def _unidad(producto) -> str:
    return (
        (producto.unidad.codigo_sunat or UNIDAD_POR_DEFECTO)
        if producto.unidad_id
        else UNIDAD_POR_DEFECTO
    )


# ---------------------------------------------------------------------------
# Factura y boleta (01, 03)
# ---------------------------------------------------------------------------
def armar_comprobante(comprobante, empresa_json: dict, config: ConfiguracionEmpresa) -> dict:
    tipo = comprobante.tipo_comprobante.codigo
    venta = comprobante.venta
    if venta.forma_pago == "CREDITO":
        raise DocumentoNoEnviable(
            "Las ventas a crédito todavía no se pueden enviar: falta definir el formato de las "
            "cuotas de la API."
        )
    _exigir_cliente(tipo, venta, comprobante.total)
    lineas = comprobante.lineas.select_related("producto__unidad", "afectacion").order_by("orden")
    return {
        "empresa": empresa_json,
        "cliente": _cliente(venta),
        "venta": {
            "tipo_documento_codigo": tipo,
            "serie": comprobante.serie,
            "numero": _numero(comprobante.numero),
            "fecha_emision": comprobante.fecha.isoformat(),
            "hora_emision": _hora(comprobante.creado_en),
            "moneda_id": _MONEDA[venta.moneda],
            "forma_pago_id": _FORMA_PAGO[venta.forma_pago],
            "total_gravada": _num(comprobante.op_gravada),
            "total_igv": _num(comprobante.igv),
            "total_exonerada": _opcional(comprobante.op_exonerada),
            "total_inafecta": _opcional(comprobante.op_inafecta),
            "total_gratuita": None,
            "total_gratuita_igv": None,
            "total_bolsa": None,
            "nota": venta.observacion,
        },
        "items": [
            {
                "codigo_producto": linea.producto.codigo,
                "producto": linea.descripcion,
                "codigo_sunat": _codigo_sunat(linea.producto, config),
                "cantidad": _num(linea.cantidad, 3),
                "codigo_unidad": _unidad(linea.producto),
                "precio_base": _num(linea.precio_unitario, 6),
                "tipo_igv_codigo": linea.afectacion.codigo,
                "descuento_precio_base": 0,
                "bolsa": False,
            }
            for linea in lineas
        ],
        "cuotas": [],
        "guias_adjuntas": [],
        "anticipos": [],
    }


# ---------------------------------------------------------------------------
# Nota de crédito (07)
# ---------------------------------------------------------------------------
def armar_nota_credito(nota, empresa_json: dict, config: ConfiguracionEmpresa) -> dict:
    venta = nota.venta
    comprobante = nota.comprobante
    lineas = nota.lineas.select_related(
        "linea_venta__producto__unidad", "linea_venta__afectacion"
    ).order_by("orden")
    return {
        "empresa": empresa_json,
        "cliente": _cliente(venta),
        "venta": {
            "tipo_documento_codigo": nota.tipo_comprobante.codigo,
            "serie": nota.serie,
            "numero": _numero(nota.numero),
            "fecha_emision": nota.fecha.isoformat(),
            "hora_emision": _hora(nota.creado_en),
            "moneda_id": _MONEDA[venta.moneda],
            "forma_pago_id": 1,
            "total_gravada": _num(nota.op_gravada),
            "total_igv": _num(nota.igv),
            "total_exonerada": _opcional(nota.op_exonerada),
            "total_inafecta": _opcional(nota.op_inafecta),
            "relacionado_serie": comprobante.serie,
            "relacionado_numero": _numero(comprobante.numero),
            "relacionado_tipo_documento": comprobante.tipo_comprobante.codigo,
            "relacionado_motivo_codigo": nota.motivo,
            "nota": nota.descripcion,
        },
        "items": [
            {
                "codigo_producto": linea.linea_venta.producto.codigo,
                "producto": linea.linea_venta.descripcion,
                "codigo_sunat": _codigo_sunat(linea.linea_venta.producto, config),
                "cantidad": _num(linea.cantidad, 3),
                "codigo_unidad": _unidad(linea.linea_venta.producto),
                "precio_base": _num(linea.linea_venta.precio_unitario, 6),
                "tipo_igv_codigo": linea.linea_venta.afectacion.codigo,
            }
            for linea in lineas
        ],
        "cuotas": [],
        "guias_adjuntas": [],
        "anticipos": [],
    }


# ---------------------------------------------------------------------------
# Guía de remisión remitente (09)
# ---------------------------------------------------------------------------
def _producto_de(linea):
    return linea.producto or (linea.linea_venta.producto if linea.linea_venta_id else None)


def armar_guia(guia, empresa_json: dict, config: ConfiguracionEmpresa) -> dict:
    if guia.modalidad == "01":
        raise DocumentoNoEnviable(
            "Las guías con transporte público todavía no se pueden enviar: falta definir el "
            "formato del transportista de la API."
        )
    empresa = guia.empresa
    vehiculos, conductores = [], []
    if not guia.traslado_m1_l:
        if guia.placa:
            vehiculos.append({"placa": _quitar_guion(guia.placa), "principal": True})
            vehiculos += [
                {"placa": _quitar_guion(p), "principal": False} for p in guia.placas_secundarias
            ]
        if guia.conductor_nombre:
            nombres, apellidos = _partir_nombre(guia.conductor_nombre)
            conductores.append(
                {
                    "tipo_documento": "1",
                    "numero_documento": guia.conductor_documento,
                    "nombres": nombres,
                    "apellidos": apellidos,
                    "licencia": guia.conductor_licencia,
                    "principal": True,
                }
            )
    lineas = guia.lineas.select_related(
        "producto__unidad", "linea_venta__producto__unidad"
    ).order_by("orden")
    relacionados = []
    if guia.comprobante_id:
        relacionados.append(
            {
                "tipo_documento": guia.comprobante.tipo_comprobante.codigo,
                "serie": guia.comprobante.serie,
                "numero": _numero(guia.comprobante.numero),
                "ruc_emisor": empresa.ruc,
            }
        )
    return {
        "empresa": empresa_json,
        "remitente": {
            "codigo_tipo_entidad": "6",
            "numero_documento": empresa.ruc,
            "razon_social_nombres": empresa.razon_social,
        },
        "destinatario": {
            "codigo_tipo_entidad": _TIPO_ENTIDAD.get(guia.destinatario_tipo_documento, "0"),
            "numero_documento": guia.destinatario_documento or "00000000",
            "razon_social_nombres": guia.destinatario_nombre,
        },
        "guia": {
            "tipo_documento_codigo": guia.tipo_comprobante.codigo,
            "serie": guia.serie,
            "numero": _numero(guia.numero),
            "fecha_emision": guia.fecha_emision.isoformat(),
            "hora_emision": _hora(guia.creado_en),
            "fecha_entrega_bienes_transportista": guia.fecha_traslado.isoformat(),
            "fecha_inicio_traslado": guia.fecha_traslado.isoformat(),
            "motivo_traslado_codigo": guia.motivo,
            "peso_total": _num(guia.peso_kg, 3),
            "unidad_peso": "KGM",
            "cantidad_bultos": guia.bultos,
            "direccion_partida": guia.punto_partida,
            "ubigeo_partida": guia.ubigeo_partida,
            "direccion_llegada": guia.punto_llegada,
            "ubigeo_llegada": guia.ubigeo_llegada,
            "transporte_publico": False,
            "observacion": guia.observacion,
        },
        "transportista": {},
        "vehiculos": vehiculos,
        "conductores": conductores,
        "items": [
            {
                "codigo_producto": (_producto_de(linea).codigo if _producto_de(linea) else ""),
                "producto": linea.descripcion,
                "codigo_sunat": (
                    _codigo_sunat(_producto_de(linea), config) if _producto_de(linea) else ""
                ),
                "cantidad": _num(linea.cantidad, 3),
                "codigo_unidad": (
                    _unidad(_producto_de(linea)) if _producto_de(linea) else UNIDAD_POR_DEFECTO
                ),
            }
            for linea in lineas
        ],
        "documentos_relacionados": relacionados,
        "evento": {},
    }
