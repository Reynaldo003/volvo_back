# Digitales/serializers.py
from rest_framework import serializers

from .models import ExpedienteDigital
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
            "auto_interes","enganche_monto",
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

            # Campos de resumen se dejan por compatibilidad,
            # aunque ahorita no uses IA.
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

        if nombre and nombre.strip() and cliente.nombre != nombre.strip():
            cliente.nombre = nombre.strip()
            cambios.append("nombre")

        if correo is not None and cliente.correo != (correo or "").strip():
            cliente.correo = (correo or "").strip()
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

        if nombre is not None and nombre.strip() and cliente.nombre != nombre.strip():
            cliente.nombre = nombre.strip()
            cambios_cliente.append("nombre")

        if correo is not None and cliente.correo != (correo or "").strip():
            cliente.correo = (correo or "").strip()
            cambios_cliente.append("correo")

        if cambios_cliente:
            cambios_cliente.append("actualizado_en")
            cliente.save(update_fields=cambios_cliente)

        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)

        instance.save()

        return instance