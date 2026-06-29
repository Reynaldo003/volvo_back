# Digitales/serializers.py
from django.utils import timezone
from rest_framework import serializers

from .models import ExpedienteDigital, MensajeWhatsApp
from citas.models import ClienteComercial, normaliza_tel_mx


class ProspectoSerializer(serializers.ModelSerializer):
    # Campos planos que recibe/envía el frontend
    nombre = serializers.CharField(write_only=True, required=False, allow_blank=True)
    telefono = serializers.CharField(write_only=True, required=True)
    correo = serializers.EmailField(write_only=True, required=False, allow_blank=True)

    # Campos reales desde ClienteComercial
    nombre_out = serializers.CharField(source="cliente.nombre", read_only=True)
    telefono_out = serializers.CharField(source="cliente.telefono", read_only=True)
    correo_out = serializers.EmailField(source="cliente.correo", read_only=True)

    cliente_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ExpedienteDigital
        fields = [
            "id",
            "cliente_id",

            # Entrada manual
            "nombre",
            "telefono",
            "correo",

            # Salida desde cliente
            "nombre_out",
            "telefono_out",
            "correo_out",

            # Datos comerciales
            "agencia",
            "business",
            "canal_contacto",
            "pauta",
            "estado",
            "auto_interes",
            "enganche_monto",
            "presupuesto_mensual",
            "buro_estado",
            "forma_pago",
            "tipo_cliente",
            "plazo_compra",
            "uso_vehiculo",
            "comprobacion_ingresos",
            "asesor_digital",
            "asesor_ventas",
            "comentarios",

            # Resumen / IA
            "resumen",
            "resumen_actualizado_at",
            "resumen_fuente",

            # Fechas / auditoría
            "primer_contacto_at",
            "ultimo_contacto_at",
            "last_read_at",
            "creado",
            "actualizado",

            # Cita relacionada
            "ultima_cita",
            "ultima_cita_agendada",
            "asistencia",
        ]

        read_only_fields = [
            "id",
            "cliente_id",
            "nombre_out",
            "telefono_out",
            "correo_out",
            "creado",
            "actualizado",
            "ultima_cita",
            "ultima_cita_agendada",
            "asistencia",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)

        data["nombre"] = data.pop("nombre_out", "") or ""
        data["telefono"] = data.pop("telefono_out", "") or ""
        data["correo"] = data.pop("correo_out", "") or ""

        return data

    def _get_or_create_cliente(self, telefono, nombre="", correo=""):
        telefono = normaliza_tel_mx(telefono)

        if not telefono:
            raise serializers.ValidationError({
                "telefono": "Teléfono inválido. Debe tener 10 dígitos o 12 dígitos iniciando con 52."
            })

        cliente, _ = ClienteComercial.objects.get_or_create(
            telefono=telefono,
            defaults={
                "nombre": (nombre or "").strip(),
                "correo": (correo or "").strip(),
            },
        )

        cambios = []

        nombre_limpio = (nombre or "").strip()
        correo_limpio = (correo or "").strip()

        if nombre_limpio and cliente.nombre != nombre_limpio:
            cliente.nombre = nombre_limpio
            cambios.append("nombre")

        if correo is not None and cliente.correo != correo_limpio:
            cliente.correo = correo_limpio
            cambios.append("correo")

        if cambios:
            cambios.append("actualizado_en")
            cliente.save(update_fields=cambios)

        return cliente

    def create(self, validated_data):
        nombre = validated_data.pop("nombre", "")
        telefono = validated_data.pop("telefono", "")
        correo = validated_data.pop("correo", "")

        cliente = self._get_or_create_cliente(
            telefono=telefono,
            nombre=nombre,
            correo=correo,
        )

        if not validated_data.get("canal_contacto"):
            validated_data["canal_contacto"] = "Manual"

        if not validated_data.get("estado"):
            validated_data["estado"] = "Nuevo"

        expediente, creado = ExpedienteDigital.objects.get_or_create(
            cliente=cliente,
            defaults=validated_data,
        )

        if not creado:
            for campo, valor in validated_data.items():
                setattr(expediente, campo, valor)

            expediente.save()

        return expediente

    def update(self, instance, validated_data):
        nombre = validated_data.pop("nombre", None)
        telefono = validated_data.pop("telefono", None)
        correo = validated_data.pop("correo", None)

        cliente = instance.cliente
        cambios_cliente = []

        if telefono is not None:
            telefono_normalizado = normaliza_tel_mx(telefono)

            if not telefono_normalizado:
                raise serializers.ValidationError({
                    "telefono": "Teléfono inválido. Debe tener 10 dígitos o 12 dígitos iniciando con 52."
                })

            if telefono_normalizado != cliente.telefono:
                telefono_ocupado = (
                    ClienteComercial.objects
                    .filter(telefono=telefono_normalizado)
                    .exclude(id_cliente=cliente.id_cliente)
                    .exists()
                )

                if telefono_ocupado:
                    raise serializers.ValidationError({
                        "telefono": "Ya existe otro prospecto con este teléfono."
                    })

                cliente.telefono = telefono_normalizado
                cambios_cliente.append("telefono")

        if nombre is not None:
            nombre_limpio = nombre.strip()

            if nombre_limpio and cliente.nombre != nombre_limpio:
                cliente.nombre = nombre_limpio
                cambios_cliente.append("nombre")

        if correo is not None:
            correo_limpio = (correo or "").strip()

            if cliente.correo != correo_limpio:
                cliente.correo = correo_limpio
                cambios_cliente.append("correo")

        if cambios_cliente:
            cambios_cliente.append("actualizado_en")
            cliente.save(update_fields=cambios_cliente)

        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)

        instance.save()

        return instance


class MensajeWhatsAppSerializer(serializers.ModelSerializer):
    """
    Serializer para mensajes del chat.

    Importante:
    - id siempre es el ID local bigint de PostgreSQL.
    - wa_message_id es el ID real de Meta.
    - El UUID del frontend no se guarda aquí.
    """

    id = serializers.IntegerField(read_only=True)
    cliente_id = serializers.IntegerField(source="cliente.id_cliente", read_only=True)

    mine = serializers.SerializerMethodField()
    text = serializers.SerializerMethodField()
    time = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = MensajeWhatsApp
        fields = [
            "id",
            "telefono",
            "numero_asesor",
            "cliente_id",
            "direction",
            "mine",
            "body",
            "text",
            "wa_message_id",
            "status",
            "raw",
            "created_at",
            "time",
            "attachments",
        ]

        read_only_fields = [
            "id",
            "cliente_id",
            "mine",
            "text",
            "created_at",
            "time",
            "attachments",
        ]

    def get_mine(self, obj):
        return obj.direction == MensajeWhatsApp.Direccion.OUT

    def get_text(self, obj):
        return obj.body or ""

    def get_time(self, obj):
        if not obj.created_at:
            return ""

        return timezone.localtime(obj.created_at).strftime("%H:%M")

    def get_attachments(self, obj):
        """
        Se deja listo para que el frontend no truene.
        Si manejas archivos/media, lo recomendable es seguir usando
        _attachments_from_raw() desde views.py porque necesita request.build_absolute_uri().
        """
        return []

    def validate_telefono(self, value):
        telefono = normaliza_tel_mx(value)

        if not telefono:
            raise serializers.ValidationError("Teléfono inválido.")

        return telefono

    def validate_numero_asesor(self, value):
        numero_asesor = normaliza_tel_mx(value)

        if not numero_asesor:
            raise serializers.ValidationError("Número asesor inválido.")

        return numero_asesor

    def validate_wa_message_id(self, value):
        return str(value or "")[:255]

    def validate_status(self, value):
        return str(value or "sent")[:50]