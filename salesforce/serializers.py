# salesforce/serializers.py
from datetime import date

from rest_framework import serializers


class TextoSalesforce(serializers.CharField):
    """Conserva el texto original y convierte los marcadores del ETL en null."""

    def __init__(self, **kwargs):
        kwargs.setdefault("read_only", True)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def to_representation(self, valor):
        texto = super().to_representation(valor)
        if texto.strip().lower() in {"none", "nat", "nan"}:
            return None
        return texto


class OportunidadSerializer(serializers.Serializer):
    fecha_creacion = serializers.DateField(read_only=True, allow_null=True)
    origen = TextoSalesforce()
    propietario_oportunidad = TextoSalesforce()
    nombre_oportunidad = TextoSalesforce()
    etapa = TextoSalesforce()
    nombre_cuenta = TextoSalesforce()
    fecha_cierre = serializers.DateField(read_only=True, allow_null=True)
    importe = TextoSalesforce()
    duracion_etapa = TextoSalesforce()
    hobbies = TextoSalesforce()
    campana = TextoSalesforce(source="campaña")
    vin_vehiculo_facturado = TextoSalesforce()
    modelo_interes = TextoSalesforce()
    prueba_manejo = TextoSalesforce()
    descripcion = TextoSalesforce()
    loss_reason = TextoSalesforce()
    monto_enganche = TextoSalesforce()
    motivo_perdida = TextoSalesforce()
    cuenta_personal_origen = TextoSalesforce()
    fecha_promesa_entrega = TextoSalesforce()


class ProspectoSerializer(serializers.Serializer):
    nombre = TextoSalesforce(source="Nombre")
    apellidos = TextoSalesforce(source="Apellidos")
    estado_lead = TextoSalesforce(source="Estado_lead")
    cargo = TextoSalesforce(source="Cargo")
    compania = TextoSalesforce(source="Compania")
    email = TextoSalesforce(source="Email")
    origen = TextoSalesforce(source="Origen")
    calle = TextoSalesforce(source="Calle")
    valoracion = TextoSalesforce(source="Valoracion")
    propietario_lead = TextoSalesforce(source="Propietario_lead")
    tipo_solicitud = TextoSalesforce(source="Tipo_Solicitud")
    descripcion = TextoSalesforce(source="Descripcion")
    fecha_creacion = serializers.DateField(
        source="Fecha_creacion", read_only=True, allow_null=True
    )


class TareaSerializer(serializers.Serializer):
    fecha = serializers.DateTimeField(
        source="Fecha", read_only=True, allow_null=True
    )
    compania_cuenta = TextoSalesforce(source="Compañía_Cuenta")
    oportunidad = TextoSalesforce(source="Oportunidad")
    contacto = TextoSalesforce(source="Contacto")
    lead = TextoSalesforce(source="Lead")
    asunto = TextoSalesforce(source="Asunto")
    asignado = TextoSalesforce(source="Asignado")
    prioridad = TextoSalesforce(source="Prioridad")
    estado = TextoSalesforce(source="Estado")
    tarea = TextoSalesforce(source="Tarea")
    subtipo_de_evento = TextoSalesforce(source="Subtipo_de_evento")
    subtipo_de_tarea = TextoSalesforce(source="Subtipo_de_tarea")
    contacto_origen = TextoSalesforce(source="Contacto_Origen")
    etapa_de_la_oportunidad = TextoSalesforce(source="Etapa_de_la_oportunidad")
    nombre = TextoSalesforce(source="Nombre")
    comentarios_completos = TextoSalesforce(source="Comentarios_completos")
    comentarios = TextoSalesforce(source="Comentarios")
    origen_del_prospecto_de_la_oportunidad = TextoSalesforce(
        source="Origen_del_prospecto_de_la_oportunidad"
    )


class FiltrosConsultaSerializer(serializers.Serializer):
    """Valida los parámetros comunes antes de ejecutar SQL."""

    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=500, default=50)
    anio = serializers.IntegerField(min_value=1, max_value=9998, required=False)
    mes = serializers.IntegerField(min_value=1, max_value=12, required=False)
    fecha_desde = serializers.DateField(required=False)
    fecha_hasta = serializers.DateField(required=False)
    q = serializers.CharField(max_length=200, required=False)

    def validate(self, datos):
        if "mes" in datos and "anio" not in datos:
            raise serializers.ValidationError({
                "mes": "Debes indicar también el año mediante anio."
            })

        desde = datos.get("fecha_desde")
        hasta = datos.get("fecha_hasta")

        if desde and hasta and desde > hasta:
            raise serializers.ValidationError({
                "fecha_hasta": "Debe ser igual o posterior a fecha_desde."
            })

        if hasta == date.max:
            raise serializers.ValidationError({
                "fecha_hasta": "Debe ser anterior a 9999-12-31."
            })

        return datos
