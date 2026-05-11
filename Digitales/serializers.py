# Digitales/serializers.py
from rest_framework import serializers
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.urls import reverse
from .models import ExpedienteDigital, MensajeWhatsApp
from citas.models import ClienteComercial, normaliza_tel_mx

EDIT_WINDOW_MINUTES = 15

def tel_normalizado_valido(tel: str) -> bool:
    tel = "".join(c for c in str(tel or "") if c.isdigit())
    return len(tel) == 12 and tel.startswith("52")

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

    #def get_time(self, obj):
    #    if not obj.created_at:
    #        return ""
    #    dt = timezone.localtime(obj.created_at)
    #    return dt.strftime("%I:%M %p").lower()
    
    def get_time(self, obj):
        if not obj.created_at:
            return ""
        dt = obj.created_at
        if settings.USE_TZ and timezone.is_aware(dt):
            dt = timezone.localtime(dt)
        return dt.strftime("%I:%M %p").lower()
    
    def get_is_template(self, obj):
        b = (obj.body or "").strip()
        return b.startswith("[TEMPLATE:")

    def get_is_media(self, obj):
        raw = obj.raw or {}
        if raw.get("meta_type") in ("image", "video", "audio", "document", "sticker"):
            return True
        b = (obj.body or "").strip()
        return b.startswith("[FILE:") or "\n[FILE:" in b

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

        # 1) Saliente por media_id (tu enviar_media_view guarda raw.upload.id, raw.meta_type, filename, content_type)
        if isinstance(raw, dict) and raw.get("upload") and raw.get("meta_type"):
            media_id = (raw.get("upload") or {}).get("id") or ""
            if media_id:
                kind = raw.get("meta_type")
                url = self._media_proxy_url(media_id, obj)
                return [{
                    "id": media_id,
                    "kind": "file" if kind == "document" else kind,
                    "url": url,
                    "mime": raw.get("content_type") or "",
                    "name": raw.get("filename") or "",
                    "size": 0,
                }]

        # 2) Saliente por link publico (IA envia ficha o imagen por URL)
        if isinstance(raw, dict) and raw.get("meta_type") in ("image", "document"):
            kind = raw.get("meta_type")
            media_url = raw.get("media_link") or raw.get("document_link") or ""
            if media_url:
                return [{
                    "id": raw.get("wa_message_id") or raw.get("filename") or media_url,
                    "kind": "file" if kind == "document" else kind,
                    "url": media_url,
                    "mime": raw.get("content_type") or ("application/pdf" if kind == "document" else "image/jpeg"),
                    "name": raw.get("filename") or "",
                    "size": 0,
                }]

        # 3) Entrante (webhook)
        if isinstance(raw, dict):
            t = (raw.get("type") or "").lower()
            if t in ("image", "video", "audio", "document", "sticker"):
                payload = raw.get(t) or {}
                media_id = payload.get("id") or ""
                if media_id:
                    url = self._media_proxy_url(media_id, obj)
                    name = payload.get("filename") or ""
                    mime = payload.get("mime_type") or ""
                    return [{
                        "id": media_id,
                        "kind": "sticker" if t == "sticker" else ("file" if t == "document" else t),
                        "url": url,
                        "mime": mime,
                        "name": name,
                        "size": 0,
                    }]

        return []

class ProspectoSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(write_only=True, required=False, allow_blank=True)
    telefono = serializers.CharField(write_only=True, required=True)
    correo = serializers.EmailField(write_only=True, required=False, allow_blank=True)

    nombre_out = serializers.CharField(source="cliente.nombre", read_only=True)
    telefono_out = serializers.CharField(source="cliente.telefono", read_only=True)
    correo_out = serializers.EmailField(source="cliente.correo", read_only=True)

    cliente_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ExpedienteDigital
        fields = [
            "id",
            "cliente_id",
            "nombre", "telefono", "correo",
            "nombre_out", "telefono_out", "correo_out",
            "agencia", "business", "canal_contacto", "pauta", "estado",
            "asesor_digital", "asesor_ventas",
            "auto_interes", "comentarios",
            "resumen", "resumen_actualizado_at", "resumen_fuente",
            "primer_contacto_at", "ultimo_contacto_at", "last_read_at",
            "creado", "actualizado",
            "ultima_cita_agendada",
            "asistencia",
            "ultima_cita",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["nombre"] = data.pop("nombre_out", "") or ""
        data["telefono"] = data.pop("telefono_out", "") or ""
        data["correo"] = data.pop("correo_out", "") or ""
        return data

    def _get_or_create_cliente(self, tel, nombre="", correo=""):
        tel = normaliza_tel_mx(tel)
        if not tel:
            raise serializers.ValidationError({"telefono": "Teléfono inválido"})

        cli, _ = ClienteComercial.objects.get_or_create(
            telefono=tel,
            defaults={"nombre": (nombre or "").strip(), "correo": (correo or "").strip()},
        )

        changed = False
        if nombre and nombre.strip() and (cli.nombre or "").strip() != nombre.strip():
            cli.nombre = nombre.strip()
            changed = True
        if correo is not None and (cli.correo or "").strip() != (correo or "").strip():
            cli.correo = (correo or "").strip()
            changed = True
        if changed:
            cli.save(update_fields=["nombre", "correo", "actualizado_en"])
        return cli

    def create(self, validated_data):
        nombre = validated_data.pop("nombre", "")
        telefono = validated_data.pop("telefono", "")
        correo = validated_data.pop("correo", "")

        cli = self._get_or_create_cliente(telefono, nombre, correo)

        exp, created = ExpedienteDigital.objects.get_or_create(
            cliente=cli,
            defaults=validated_data,
        )
        if not created:
            for k, v in validated_data.items():
                if v is None:
                    continue
                if isinstance(v, str) and not v.strip():
                    continue
                setattr(exp, k, v)
            exp.save()
        return exp

    def update(self, instance, validated_data):
        nombre = validated_data.pop("nombre", None)
        telefono = validated_data.pop("telefono", None)
        correo = validated_data.pop("correo", None)

        if telefono is not None:
            new_tel = normaliza_tel_mx(telefono)
            old_tel = instance.cliente.telefono

            if not new_tel:
                raise serializers.ValidationError({"telefono": "Teléfono inválido. Debe ser de 10 dígitos."})

            if new_tel != old_tel:
                if tel_normalizado_valido(old_tel):
                    raise serializers.ValidationError(
                        {"telefono": "No se permite cambiar un teléfono válido desde aquí. Solo corrección de teléfonos inválidos."}
                    )

                instance.cliente.telefono = new_tel
                instance.cliente.save(update_fields=["telefono", "actualizado_en"])

        if nombre is not None or correo is not None:
            cli = instance.cliente
            changed = False
            if nombre is not None and nombre.strip():
                cli.nombre = nombre.strip()
                changed = True
            if correo is not None:
                cli.correo = (correo or "").strip()
                changed = True
            if changed:
                cli.save(update_fields=["nombre", "correo", "actualizado_en"])

        for k, v in validated_data.items():
            setattr(instance, k, v)

        instance.save()
        return instance