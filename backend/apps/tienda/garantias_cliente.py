"""Las garantías de lo que el cliente compró en la tienda (para «Mis pedidos» y «Mis garantías»).

La serie y el enlace de consulta salen igual que la serie del pedido: solo cuando el equipo ya va
hacia el cliente (enviado, listo para recoger o entregado); antes la unidad todavía puede cambiar.
"""

from apps.garantias import publico
from apps.garantias.models import Garantia

from . import series_pedido
from .models import PedidoTienda


def _salida(g: Garantia, *, visible: bool) -> dict:
    situacion = publico.situacion_de(g)
    return {
        "producto": g.producto.nombre,
        "cantidad": 1 if g.numero_serie else int(g.cantidad),
        "numero_serie": g.numero_serie if visible else "",
        "meses": g.meses,
        "desde": g.fecha_inicio.isoformat(),
        "hasta": g.vence_el.isoformat(),
        "situacion": situacion,
        "texto": publico.TEXTO_SITUACION[situacion],
        "vigente": g.vigente(),
        "dias_restantes": g.dias_restantes(),
        # Ruta dentro de la tienda: la página pública de la garantía (con el código secreto).
        "enlace": f"/garantia/{g.token_publico}" if visible else "",
    }


def _consulta(venta_ids):
    return (
        Garantia.objects.sin_ambito()
        .filter(comprobante__venta_id__in=venta_ids)
        .select_related("producto", "comprobante")
        .order_by("id")
    )


def de_pedido(p: PedidoTienda) -> list[dict]:
    """Las garantías de un pedido pagado (vacío si aún no tiene venta o nada lleva garantía)."""
    if not p.venta_id:
        return []
    visible = p.estado in series_pedido.ESTADOS_VISIBLES
    return [_salida(g, visible=visible) for g in _consulta([p.venta_id])]


def de_cuenta(cuenta) -> list[dict]:
    """Todas las garantías de los pedidos de la cuenta que ya van hacia el cliente."""
    pedidos = list(
        PedidoTienda.objects.sin_ambito()
        .filter(
            organizacion_id=cuenta.organizacion_id,
            cuenta=cuenta,
            venta__isnull=False,
            estado__in=series_pedido.ESTADOS_VISIBLES,
        )
        .values("numero", "venta_id", "creado_en")
    )
    por_venta = {p["venta_id"]: p for p in pedidos}
    filas = []
    for g in _consulta(list(por_venta)):
        pedido = por_venta[g.comprobante.venta_id]
        filas.append({**_salida(g, visible=True), "pedido": pedido["numero"]})
    # Lo que vence primero, arriba.
    filas.sort(key=lambda f: (not f["vigente"], f["hasta"]))
    return filas
