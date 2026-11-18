"""Eventos de riesgo: lo primero que debería mirar quien revisa la bitácora.

Cada CATEGORÍA agrupa acciones de la bitácora que merecen atención (accesos sospechosos, cambios de
permisos, anulaciones…). Si en el periodo que se mira ocurren al menos ``umbral`` eventos de una
categoría, se enciende su ALERTA. Los umbrales son una guía inicial: se ajustan aquí.
"""

from dataclasses import dataclass

from django.db.models import Count, Max, Q


@dataclass(frozen=True, slots=True)
class Categoria:
    clave: str
    nombre: str
    gravedad: str  # ALTA | MEDIA
    descripcion: str
    umbral: int
    acciones: tuple[str, ...] = ()  # acciones exactas
    contiene: tuple[str, ...] = ()  # o que contengan este texto

    def filtro(self) -> Q:
        condicion = Q(accion__in=self.acciones) if self.acciones else Q(pk__in=[])
        for texto in self.contiene:
            condicion |= Q(accion__icontains=texto)
        return condicion


CATEGORIAS: tuple[Categoria, ...] = (
    Categoria(
        "acceso",
        "Intentos de acceso sospechosos",
        "ALTA",
        "Contraseñas o códigos fallidos, cuentas bloqueadas y sesiones reutilizadas.",
        10,
        acciones=(
            "sesion.login_fallido",
            "sesion.login_bloqueado",
            "mfa.intento_fallido",
            "sesion.refresh_reutilizado",
        ),
    ),
    Categoria(
        "permisos",
        "Cambios de permisos y accesos",
        "ALTA",
        "Permisos, roles o accesos dados o quitados; contraseñas y segundo factor restablecidos.",
        1,
        acciones=(
            "rol.permisos_modificados",
            "usuario.rol_asignado",
            "usuario.rol_quitado",
            "usuario.excepcion_otorgada",
            "usuario.acceso_establecido",
            "usuario.acceso_quitado",
            "usuario.desactivado",
            "usuario.reactivado",
            "password.restablecida_admin",
            "mfa.desactivado",
            "mfa.restablecido",
        ),
    ),
    Categoria(
        "reaperturas",
        "Cierres reabiertos",
        "ALTA",
        "Periodos, planillas, cajas o conciliaciones ya cerrados que se abrieron de nuevo.",
        1,
        acciones=(
            "inventario.periodo_reabierto",
            "rrhh.planilla_reabierta",
            "caja.sesion_reabierta",
            "caja.conciliacion_reabierta",
        ),
    ),
    Categoria(
        "precios",
        "Ventas fuera de lo normal",
        "MEDIA",
        "Ventas por debajo del precio mínimo o con el tipo de cambio puesto a mano.",
        3,
        acciones=("ventas.venta_bajo_minimo", "ventas.tipo_cambio_manual"),
    ),
    Categoria(
        "anulaciones",
        "Anulaciones y devoluciones",
        "MEDIA",
        "Comprobantes, cobros, compras, gastos y movimientos anulados, y dinero devuelto.",
        5,
        acciones=(
            "ventas.comprobante_anulado",
            "ventas.nota_credito_emitida",
            "ventas.guia_anulada",
            "ventas.proforma_anulada",
            "caja.movimiento_anulado",
            "caja.transferencia_anulada",
            "compras.compra_anulada",
            "compras.pago_anulado",
            "compras.devolucion_registrada",
            "gastos.gasto_anulado",
            "inventario.movimiento_anulado",
            "servicio_tecnico.adelanto_anulado",
            "tienda.reembolso_aprobado",
            "rrhh.pago_planilla_anulado",
        ),
    ),
    Categoria(
        "eliminaciones",
        "Registros eliminados",
        "MEDIA",
        "Clientes, productos, catálogos y otros datos que se dieron de baja.",
        1,
        contiene=(".eliminad",),
    ),
    Categoria(
        "sensibles",
        "Datos delicados consultados o cambiados",
        "MEDIA",
        "Claves de equipos consultadas, sueldos cambiados y equipos entregados sin cobrar.",
        1,
        acciones=(
            "servicio_tecnico.clave_consultada",
            "servicio_tecnico.entregado_sin_cobro",
            "rrhh.sueldo_cambiado",
        ),
    ),
    Categoria(
        "exportaciones",
        "Descargas de reportes",
        "MEDIA",
        "Reportes y libros exportados (llevan información fuera del sistema).",
        10,
        contiene=("exportad",),
    ),
)

POR_CLAVE = {c.clave: c for c in CATEGORIAS}


def resumen(eventos, desde, *, nombres_de_usuario) -> dict:
    """Cuántos eventos de cada categoría hubo desde ``desde``, quién los hizo y cuáles fueron."""
    desde_filtro = eventos.filter(creado_en__gte=desde)
    categorias = []
    for c in CATEGORIAS:
        mios = desde_filtro.filter(c.filtro())
        agregados = mios.aggregate(total=Count("id"), ultimo=Max("creado_en"))
        total = agregados["total"] or 0
        por_usuario = list(
            mios.exclude(usuario_id__isnull=True)
            .values("usuario_id")
            .annotate(n=Count("id"))
            .order_by("-n")[:3]
        )
        categorias.append(
            {
                "clave": c.clave,
                "nombre": c.nombre,
                "gravedad": c.gravedad,
                "descripcion": c.descripcion,
                "umbral": c.umbral,
                "total": total,
                "alerta": total >= c.umbral,
                "ultimo": agregados["ultimo"],
                "top_usuarios": [
                    {
                        "usuario_id": str(f["usuario_id"]),
                        "nombre": nombres_de_usuario(f["usuario_id"]),
                        "n": f["n"],
                    }
                    for f in por_usuario
                ],
            }
        )
    return {
        "categorias": categorias,
        "alertas": sum(1 for c in categorias if c["alerta"]),
    }


def filtrar_por_riesgo(eventos, clave: str):
    """Los eventos de una categoría de riesgo (o ninguno si la clave no existe)."""
    categoria = POR_CLAVE.get(clave)
    if categoria is None:
        return eventos.none()
    return eventos.filter(categoria.filtro())
