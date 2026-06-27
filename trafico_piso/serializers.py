#trafico_piso/serializers.py
from decimal import Decimal
from rest_framework import serializers
from .models import TraficoPiso

class DecimalFlexibleField(serializers.DecimalField):
    def to_internal_value(self, data):
        if data in ("", None):
            return Decimal("0")
        return super().to_internal_value(data)


class IntegerFlexibleField(serializers.IntegerField):
    def to_internal_value(self, data):
        if data in ("", None):
            return 0
        return super().to_internal_value(data)


class TraficoPisoSerializer(serializers.ModelSerializer):
    presupuesto_estimado = DecimalFlexibleField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    enganche_presupuestado = DecimalFlexibleField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    mensualidades_presupuestadas = IntegerFlexibleField(
        required=False,
        allow_null=True,
    )
    edad = IntegerFlexibleField(
        required=False,
        allow_null=True,
    )
    cantidad_hijos = IntegerFlexibleField(
        required=False,
        allow_null=True,
    )

    class Meta:
        model = TraficoPiso
        fields = "__all__"
        read_only_fields = [
            "id_trafico",
            "creado_por",
            "creado_en",
            "actualizado_en",
        ]