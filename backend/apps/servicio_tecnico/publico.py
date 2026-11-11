"""Lo que el cliente puede ver de su orden sin iniciar sesión (con el enlace o el QR de su hoja).

Solo sale lo que no compromete a nadie: el código, el equipo (sin número de serie), en qué paso va,
cuándo se prometió, el mensaje que el taller dejó para el cliente y la garantía. NUNCA salen
precios, el diagnóstico técnico, las notas internas, la clave del equipo ni datos del cliente.
"""

import re

from django.db.models import Prefetch

from .models import EstadoOrden, HistorialEstado, OrdenServicio

# Cómo se le cuenta al cliente cada estado: título corto y una frase sin tecnicismos.
ETAPAS: dict[str, tuple[str, str]] = {
    EstadoOrden.RECIBIDO: ("Equipo recibido", "Recibimos tu equipo y lo registramos."),
    EstadoOrden.PENDIENTE_DIAGNOSTICO: (
        "En espera de revisión",
        "Tu equipo espera su turno para ser revisado.",
    ),
    EstadoOrden.EN_DIAGNOSTICO: ("En revisión", "Nuestro técnico está revisando tu equipo."),
    EstadoOrden.DIAGNOSTICADO: (
        "Revisión terminada",
        "Terminamos la revisión y estamos preparando el presupuesto.",
    ),
    EstadoOrden.PENDIENTE_APROBACION: (
        "Presupuesto por aprobar",
        "Tienes un presupuesto esperando tu respuesta. Comunícate con nosotros para confirmarlo.",
    ),
    EstadoOrden.APROBADO: ("Servicio aprobado", "Aprobaste el servicio y lo estamos programando."),
    EstadoOrden.EN_MANTENIMIENTO: (
        "En mantenimiento",
        "Estamos realizando el mantenimiento de tu equipo.",
    ),
    EstadoOrden.EN_REPARACION: ("En reparación", "Estamos reparando tu equipo."),
    EstadoOrden.PENDIENTE_REPUESTO: (
        "Esperando un repuesto",
        "El trabajo está detenido hasta que llegue un repuesto.",
    ),
    EstadoOrden.EN_PRUEBAS: ("En pruebas", "Estamos comprobando que todo funcione bien."),
    EstadoOrden.TERMINADO: ("Servicio terminado", "Terminamos el trabajo de tu equipo."),
    EstadoOrden.LISTO_ENTREGA: (
        "Listo para recoger",
        "Tu equipo está listo. Puedes pasar a recogerlo.",
    ),
    EstadoOrden.ENTREGADO: ("Entregado", "Tu equipo fue entregado. ¡Gracias por tu confianza!"),
    EstadoOrden.NO_APROBADO: (
        "Servicio no realizado",
        "El servicio no se realizó. Tu equipo está disponible para recoger.",
    ),
    EstadoOrden.SIN_SOLUCION: (
        "Sin solución",
        "No fue posible repararlo. Tu equipo está disponible para recoger.",
    ),
    EstadoOrden.ABANDONADO: (
        "Equipo sin recoger",
        "Tu equipo sigue en el taller. Comunícate con nosotros.",
    ),
}

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,40}$")


def orden_por_token(token: str) -> OrdenServicio | None:
    """La orden de ese enlace, o ``None`` (un token mal escrito no toca la base de datos)."""
    if not _TOKEN.fullmatch(token or ""):
        return None
    return (
        OrdenServicio.objects.sin_ambito()
        .select_related("empresa", "equipo__tipo")
        # Sin sesión no hay ámbito activo: el historial se lee a propósito sin él.
        .prefetch_related(
            Prefetch("historial", queryset=HistorialEstado.objects.sin_ambito().order_by("id"))
        )
        .filter(token_publico=token)
        .first()
    )


def estado_publico(orden: OrdenServicio) -> dict:
    titulo, descripcion = ETAPAS[orden.estado]
    e = orden.empresa
    equipo = orden.equipo
    entregado = orden.estado == EstadoOrden.ENTREGADO
    garantia = None
    if entregado and orden.garantia_dias > 0 and orden.garantia_hasta:
        garantia = {"dias": orden.garantia_dias, "hasta": orden.garantia_hasta}
    return {
        "codigo": orden.codigo,
        "empresa": {
            "nombre": e.nombre_comercial or e.razon_social,
            "telefono": e.telefono,
            "direccion": e.direccion_fiscal,
        },
        "equipo": " ".join(p for p in (equipo.tipo.nombre, equipo.marca, equipo.modelo) if p),
        "estado": {"clave": orden.estado, "titulo": titulo, "descripcion": descripcion},
        "fecha_ingreso": orden.fecha_ingreso,
        "fecha_promesa": None if entregado else orden.fecha_promesa,
        "fecha_entrega": orden.fecha_entrega,
        "mensaje_del_taller": orden.nota_cliente,
        "es_garantia": orden.es_garantia,
        "garantia": garantia,
        "linea_de_tiempo": [
            {"titulo": ETAPAS[h.estado_nuevo][0], "fecha": h.creado_en}
            for h in orden.historial.all()
        ],
    }
