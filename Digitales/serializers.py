# Digitales/serializers.py
from rest_framework import serializers
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.urls import reverse

from .models import ExpedienteDigital, MensajeWhatsApp
from citas.models import ClienteComercial, normaliza_tel_mx

EDIT_WINDOW_MINUTES = 15


class WhatsAppMessageSerializer(serializers.ModelSerializer):
    mine = serializers.SerializerMethodField()
    text = serializers.CharField(source="body", read_only=True)
    time = serializers.SerializerMethodField()

    editable = serializers.SerializerMethodField()
    edit_expires_at = serializers.SerializerMethodField()
    is_template = serializers.SerializerMethodField()
    is_media = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = MensajeWhatsApp
        fields = [
            "id",
            "telefono",
            "direction",
            "mine",
            "text",
            "body",
            "wa_message_id",
            "status",
            "raw",
            "created_at",
            "time",
            "editable",
            "edit_expires_at",
            "is_template",
            "is_media",
            "attachments",
        ]

    def get_mine(self, obj):
        return obj.direction == "out"

    def get_time(self, obj):
        if not obj.created_at:
            return ""

        dt = obj.created_at

        if settings.USE_TZ and timezone.is_aware(dt):
            dt = timezone.localtime(dt)

        return dt.strftime("%I:%M %p").lower()

    def get_is_template(self, obj):
        return str(obj.body or "").strip().startswith("[TEMPLATE:")

    def get_is_media(self, obj):
        raw = obj.raw or {}

        if raw.get("meta_type") in ("image", "video", "audio", "document", "sticker"):
            return True

        body = str(obj.body or "").strip()

        return body.startswith("[FILE:") or "\n[FILE:" in body

    def get_edit_expires_at(self, obj):
        if not obj.created_at:
            return None

        return (obj.created_at + timedelta(minutes=EDIT_WINDOW_MINUTES)).isoformat()

    def get_editable(self, obj):
        if obj.direction != "out":
            return False

        if not obj.created_at:
            return False

        if self.get_is_template(obj):
            return False

        if self.get_is_media(obj):
            return False

        return timezone.now() <= (obj.created_at + timedelta(minutes=EDIT_WINDOW_MINUTES))

    def _media_proxy_url(self, media_id: str, obj):
        req = self.context.get("request")
        path = reverse("digitales-media-proxy", args=[media_id])

        numero_asesor = str(getattr(obj, "numero_asesor", "") or "").strip()

        if numero_asesor:
            path = f"{path}?numero_asesor={numero_asesor}"

        return req.build_absolute_uri(path) if req else path

    def get_attachments(self, obj):
        raw = obj.raw or {}

        local_url = (
            raw.get("local_media_url")
            or raw.get("media_link")
            or raw.get("document_link")
        )

        if local_url:
            kind = str(raw.get("meta_type") or raw.get("type") or "file").lower()

            return [
                {
                    "id": raw.get("media_id") or raw.get("wa_message_id") or local_url,
                    "kind": "file" if kind == "document" else kind,
                    "url": local_url,
                    "mime": raw.get("content_type") or "",
                    "name": raw.get("filename") or "",
                    "size": raw.get("size") or 0,
                }
            ]

        if isinstance(raw, dict) and raw.get("upload") and raw.get("meta_type"):
            media_id = (raw.get("upload") or {}).get("id") or ""

            if media_id:
                kind = raw.get("meta_type")

                return [
                    {
                        "id": media_id,
                        "kind": "file" if kind == "document" else kind,
                        "url": self._media_proxy_url(media_id, obj),
                        "mime": raw.get("content_type") or "",
                        "name": raw.get("filename") or "",
                        "size": 0,
                    }
                ]

        message_type = str(raw.get("type") or "").lower()

        if message_type in ("image", "video", "audio", "document", "sticker"):
            payload = raw.get(message_type) or {}
            media_id = payload.get("id") or ""

            if media_id:
                return [
                    {
                        "id": media_id,
                        "kind": "sticker" if message_type == "sticker" else (
                            "file" if message_type == "document" else message_type
                        ),
                        "url": self._media_proxy_url(media_id, obj),
                        "mime": payload.get("mime_type") or "",
                        "name": payload.get("filename") or "",
                        "size": 0,
                    }
                ]

        return []

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