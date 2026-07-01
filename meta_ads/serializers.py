# meta_ads/serializers.py
from rest_framework import serializers

from .models import CampanaMeta


class CampanaMetaListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampanaMeta
        fields = (
            "id_campana",
            "id_concesionaria",
            "sucursal",
            "inicio_informe",
            "fin_informe",
            "nombre_campana",
            "estado_campana",
            "objetivo_campana",
            "inicio_campana",
            "fin_campana",
            "total_resultados",
            "alcance",
            "impresiones",
            "presupuesto_anuncio",
            "coste_resultados",
            "importe_gastado",
        )


class CampanaMetaSerializer(serializers.ModelSerializer):
    """
    Serializer completo solo para detalle o uso administrativo.
    """

    class Meta:
        model = CampanaMeta
        fields = "__all__"