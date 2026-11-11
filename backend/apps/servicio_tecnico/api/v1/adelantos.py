"""API de los adelantos de una orden: recibirlos, devolverlos y anular un recibo por error."""

from decimal import Decimal

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.mantenimiento.models import MedioPago
from apps.seguridad.services import permisos_engine as motor
from apps.servicio_tecnico import adelantos
from apps.servicio_tecnico.models import AdelantoServicio

TAG = ["servicio-tecnico"]
ADELANTOS = "SERVICIOS.ADELANTOS.GESTIONAR"


class AdelantoEntrada(serializers.Serializer):
    monto = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("99999.99")
    )
    medio_pago = serializers.IntegerField(min_value=1)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)


class AccionSobreAdelanto(serializers.Serializer):
    adelanto = serializers.IntegerField(min_value=1)
    motivo = serializers.CharField(max_length=250)


def adelantos_de(orden) -> dict:
    """Los recibos de la orden y cuánto hay por descontar, aplicado y devuelto."""
    libres = {a.pk for a in adelantos.disponibles(orden)}
    filas = []
    for a in orden.adelantos.select_related("medio_pago", "comprobante").all():
        aplicado = a.pk not in libres and a.estado == "VIGENTE"
        filas.append(
            {
                "id": a.pk,
                "codigo": a.codigo,
                "monto": str(a.monto),
                "medio_nombre": a.medio_pago.nombre,
                "referencia": a.referencia,
                "fecha": a.fecha,
                "estado": a.estado,
                "estado_nombre": (
                    "Descontado del comprobante"
                    if aplicado
                    else "Por devolver"
                    if a.pk in libres
                    else a.get_estado_display()
                ),
                "aplicado": aplicado,
                "disponible": a.pk in libres,
                "comprobante": a.comprobante.numero_completo if aplicado else "",
                "devolucion_motivo": a.devolucion_motivo,
                "anulacion_motivo": a.anulacion_motivo,
            }
        )
    r = adelantos.resumen(orden)
    tope = adelantos.tope(orden)
    return {
        "recibos": filas,
        "resumen": {k: str(v) for k, v in r.items()},
        "tope": str(tope) if tope is not None else None,
    }


class AdelantosAcciones:
    """Recibir, devolver y anular adelantos. Hace falta ``SERVICIOS.ADELANTOS.GESTIONAR``."""

    def _exigir_adelantos(self, request, orden) -> None:
        if not motor.tiene_permiso(request.user, ADELANTOS, orden.empresa_id):
            raise PermissionDenied("No tiene permiso para manejar adelantos.")

    @extend_schema(tags=TAG, request=AdelantoEntrada)
    @action(detail=True, methods=["post"], url_path="adelantos")
    def recibir_adelanto(self, request, pk=None):
        """Recibe un adelanto del cliente: da el recibo interno y el dinero entra a la caja."""
        orden = self.get_object()
        self._exigir_adelantos(request, orden)
        datos = AdelantoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        medio = MedioPago.objects.filter(
            pk=v["medio_pago"], organizacion_id=orden.empresa.organizacion_id
        ).first()
        if medio is None:
            raise ValidationError({"medio_pago": "Elija un método de pago que exista."})
        adelantos.registrar_adelanto(
            orden, monto=v["monto"], medio_pago=medio, referencia=v.get("referencia", "")
        )
        return self._ficha(orden)

    def _adelanto_de(self, orden, id_: int) -> AdelantoServicio:
        adelanto = AdelantoServicio.objects.filter(pk=id_, orden=orden).first()
        if adelanto is None:
            raise NotFound("No existe ese recibo en esta orden.")
        return adelanto

    @extend_schema(tags=TAG, request=AccionSobreAdelanto)
    @action(detail=True, methods=["post"], url_path="adelantos/devolver")
    def devolver_adelanto(self, request, pk=None):
        """Devuelve un adelanto al cliente (sale de la caja). Sin nota de crédito: no se facturó."""
        orden = self.get_object()
        self._exigir_adelantos(request, orden)
        datos = AccionSobreAdelanto(data=request.data)
        datos.is_valid(raise_exception=True)
        adelantos.devolver(
            self._adelanto_de(orden, datos.validated_data["adelanto"]),
            motivo=datos.validated_data["motivo"],
        )
        return self._ficha(orden)

    @extend_schema(tags=TAG, request=AccionSobreAdelanto)
    @action(detail=True, methods=["post"], url_path="adelantos/anular")
    def anular_adelanto(self, request, pk=None):
        """Anula un recibo emitido por error: el ingreso a la caja se deshace."""
        orden = self.get_object()
        self._exigir_adelantos(request, orden)
        datos = AccionSobreAdelanto(data=request.data)
        datos.is_valid(raise_exception=True)
        adelantos.anular(
            self._adelanto_de(orden, datos.validated_data["adelanto"]),
            motivo=datos.validated_data["motivo"],
        )
        return self._ficha(orden)
