from rest_framework import serializers

from .models import MatrizPresupuesto, MatrizPresupuestoRef


def campos_modelo(modelo):
    return [
        campo.name
        for campo in modelo._meta.fields
        if campo.name != "pk"
    ]


class MatrizPresupuestoSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatrizPresupuesto
        fields = campos_modelo(MatrizPresupuesto)


class MatrizPresupuestoRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatrizPresupuestoRef
        fields = campos_modelo(MatrizPresupuestoRef)