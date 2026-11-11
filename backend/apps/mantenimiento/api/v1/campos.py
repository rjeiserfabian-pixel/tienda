"""Campos de entrada reutilizables de la API."""

from rest_framework import serializers

from apps.mantenimiento.models import Ubigeo


class CampoUbigeo(serializers.CharField):
    """El ubigeo (código INEI de 6 dígitos) de una dirección: opcional, pero debe existir."""

    default_error_messages = {"inexistente": "Ese ubigeo no está en la lista del INEI."}

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("max_length", 6)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        valor = super().to_internal_value(data)
        if valor and not Ubigeo.objects.filter(codigo=valor).exists():
            self.fail("inexistente")
        return valor
