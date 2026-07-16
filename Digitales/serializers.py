#volvo
# Digitales/serializers.py
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from citas.models import ClienteComercial, normaliza_tel_mx
from .models import ExpedienteDigital, MensajeWhatsApp

EDIT_WINDOW_MINUTES = 15


def absolute_backend_url(url_o_path: str) -> str:
    value = str(url_o_path or "").strip()

    if not value:
        return ""

    if value.startswith("http://") or value.startswith("https://"):
        return value.replace(" ", "%20")

    base = str(
        getattr(settings, "PUBLIC_API_BASE_URL", "")
        or "https://crmvolvo.grupoautomotrizryr.com"
    ).rstrip("/")

    if value.startswith("//"):
        return f"https:{value}".replace(" ", "%20")

    if not value.startswith("/"):
        value = f"/{value}"

    return f"{base}{value}".replace(" ", "%20")


def _safe_local_dt(dt):
    if not dt:
        return None

    if settings.USE_TZ and timezone.is_aware(dt):
        return timezone.localtime(dt)

    return dt


class WhatsAppMessageSerializer(serializers.ModelSerializer):
    mine = serializers.SerializerMethodField()
    text = serializers.CharField(source="body", read_only=True)
    time = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()
    edit_expires_at = serializers.SerializerMethodField()
    is_template = serializers.SerializerMethodField()
    is_media = serializers.SerializerMethodField()
    reply_to_message_id = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    origin_preview = serializers.SerializerMethodField()

    class Meta:
        model = MensajeWhatsApp
        fields = [
            "id",
            "telefono",
            "numero_asesor",
            "direction",
            "mine",
            "text",
            "body",
            "wa_message_id",
            "reply_to_message_id",
            "status",
            "raw",
            "created_at",
            "time",
            "editable",
            "edit_expires_at",
            "is_template",
            "is_media",
            "attachments",
            "origin_preview",
        ]

    def get_mine(self, obj):
        return obj.direction == MensajeWhatsApp.Direccion.OUT

    def get_time(self, obj):
        dt = _safe_local_dt(obj.created_at)
        if not dt:
            return ""
        return dt.strftime("%H:%M")

    def get_edit_expires_at(self, obj):
        if not obj.created_at:
            return None
        return (obj.created_at + timedelta(minutes=EDIT_WINDOW_MINUTES)).isoformat()

    def get_editable(self, obj):
        if obj.direction != MensajeWhatsApp.Direccion.OUT:
            return False
        if not obj.created_at:
            return False
        if self.get_is_template(obj) or self.get_is_media(obj):
            return False
        return timezone.now() <= (obj.created_at + timedelta(minutes=EDIT_WINDOW_MINUTES))

    def get_is_template(self, obj):
        body = (obj.body or "").strip()
        raw = obj.raw or {}
        return body.startswith("[TEMPLATE:") or bool(raw.get("template_name"))

    def get_is_media(self, obj):
        raw = obj.raw or {}
        if raw.get("meta_type") in ("image", "video", "audio", "document", "sticker"):
            return True
        if raw.get("type") in ("image", "video", "audio", "document", "sticker"):
            return True
        body = (obj.body or "").strip()
        return body.startswith("[FILE:") or "\n[FILE:" in body

    def get_reply_to_message_id(self, obj):
        raw = obj.raw or {}
        if not isinstance(raw, dict):
            return ""
        return str(raw.get("reply_to") or "").strip()

    def _media_proxy_url(self, media_id: str, obj):
        path = reverse("digitales-media-proxy", args=[media_id])
        numero_asesor = str(getattr(obj, "numero_asesor", "") or "").strip()

        if numero_asesor:
            path = f"{path}?numero_asesor={numero_asesor}"

        return absolute_backend_url(path)

    @staticmethod
    def _safe_dict(value):
        return value if isinstance(value, dict) else {}

    def get_origin_preview(self, obj):
        """
        Normaliza la referencia Click-to-WhatsApp para que el frontend pueda
        dibujar la tarjeta del anuncio dentro de la burbuja del primer mensaje.

        Se mantienen fallbacks porque algunos registros antiguos guardaron el
        último webhook dentro de raw["ultimo_webhook_payload"].
        """
        if obj.direction != MensajeWhatsApp.Direccion.IN:
            return None

        raw = self._safe_dict(obj.raw)
        ultimo_webhook = self._safe_dict(raw.get("ultimo_webhook_payload"))

        referral_candidates = [
            self._safe_dict(raw.get("referral")),
            self._safe_dict(self._safe_dict(raw.get("context")).get("referral")),
            self._safe_dict(ultimo_webhook.get("referral")),
            self._safe_dict(self._safe_dict(ultimo_webhook.get("context")).get("referral")),
        ]
        referral = next((item for item in referral_candidates if item), {})

        attribution_candidates = [
            self._safe_dict(raw.get("atribucion_meta")),
            self._safe_dict(ultimo_webhook.get("atribucion_meta")),
        ]
        atribucion = next((item for item in attribution_candidates if item), {})

        nombre_campana = str(
            atribucion.get("nombre_campana")
            or atribucion.get("campaign_name")
            or ""
        ).strip()
        nombre_anuncio = str(
            atribucion.get("nombre_anuncio")
            or referral.get("headline")
            or ""
        ).strip()
        sucursal = str(atribucion.get("sucursal") or "").strip()
        pauta = str(
            atribucion.get("pauta")
            or (f"{sucursal} - {nombre_campana}" if sucursal and nombre_campana else "")
            or nombre_campana
            or nombre_anuncio
            or ""
        ).strip()

        headline = str(
            referral.get("headline")
            or nombre_anuncio
            or nombre_campana
            or pauta
            or ""
        ).strip()
        body = str(
            referral.get("body")
            or atribucion.get("nombre_conjunto")
            or ""
        ).strip()
        source_url = str(referral.get("source_url") or "").strip()
        image_url = str(
            referral.get("image_url")
            or referral.get("thumbnail_url")
            or referral.get("video_thumbnail_url")
            or ""
        ).strip()

        if not any((pauta, headline, source_url, image_url)):
            return None

        return {
            "pauta": pauta or headline,
            "nombre_campana": nombre_campana,
            "nombre_anuncio": nombre_anuncio,
            "sucursal": sucursal,
            "headline": headline or pauta,
            "body": body,
            "source_url": source_url,
            "image_url": image_url,
            "media_type": str(referral.get("media_type") or "").strip(),
            "source_type": str(referral.get("source_type") or "").strip(),
            "source_id": str(referral.get("source_id") or "").strip(),
            "origen": str(atribucion.get("motivo") or "meta_ads").strip(),
            "referral": referral,
            "atribucion": atribucion,
        }

    def get_attachments(self, obj):
        raw = obj.raw or {}

        if not isinstance(raw, dict):
            return []

        # Media enviado desde el CRM, guardado con meta_upload/upload.
        upload = raw.get("meta_upload") or raw.get("upload") or {}
        kind = raw.get("meta_type") or raw.get("media_type") or raw.get("type") or ""
        kind = str(kind).lower()

        if upload and kind in ("image", "video", "audio", "document", "sticker"):
            media_id = upload.get("id") or raw.get("media_id") or ""
            media_url = raw.get("media_link") or raw.get("document_link") or raw.get("local_media_url") or ""

            if media_url:
                return [
                    {
                        "id": media_id or media_url,
                        "kind": "file" if kind == "document" else kind,
                        "url": absolute_backend_url(media_url),
                        "previewUrl": absolute_backend_url(media_url),
                        "mime": raw.get("content_type") or raw.get("mime_type") or "",
                        "name": raw.get("filename") or "",
                        "size": raw.get("size") or 0,
                    }
                ]

            if media_id:
                url = self._media_proxy_url(media_id, obj)
                return [
                    {
                        "id": media_id,
                        "kind": "file" if kind == "document" else kind,
                        "url": url,
                        "previewUrl": url,
                        "mime": raw.get("content_type") or raw.get("mime_type") or "",
                        "name": raw.get("filename") or "",
                        "size": raw.get("size") or 0,
                    }
                ]

        # Media entrante de webhook Meta. El raw es el msg original + metadata.
        message_type = str(raw.get("type") or "").lower()

        if message_type in ("image", "video", "audio", "document", "sticker"):
            payload = raw.get(message_type) or {}
            media_id = payload.get("id") or raw.get("media_id") or ""

            if media_id:
                url = self._media_proxy_url(media_id, obj)
                name = payload.get("filename") or raw.get("filename") or ""
                mime = payload.get("mime_type") or raw.get("mime_type") or raw.get("content_type") or ""

                return [
                    {
                        "id": media_id,
                        "kind": "file" if message_type == "document" else message_type,
                        "url": url,
                        "previewUrl": url,
                        "mime": mime,
                        "mime_type": mime,
                        "name": name,
                        "filename": name,
                        "size": payload.get("file_size") or raw.get("size") or 0,
                    }
                ]

        return []


# Alias para no romper imports viejos del proyecto Volvo.
MensajeWhatsAppSerializer = WhatsAppMessageSerializer


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
            "nombre",
            "telefono",
            "correo",
            "nombre_out",
            "telefono_out",
            "correo_out",
            "agencia",
            "business",
            "canal_contacto",
            "pauta",
            "estado",
            "motivo_descalificacion",
            "auto_interes",
            "enganche_monto",
            "presupuesto_mensual",
            "buro_estado",
            "forma_pago",
            "tipo_cliente",
            "plazo_compra",
            "uso_vehiculo",
            "comprobacion_ingresos",
            "id_cotizacion",
            "folio_solicitud_credito",
            "solicitud_credito_estado",
            "vin_facturado",
            "vin_estatus_entrega",
            "asesor_digital",
            "asesor_ventas",
            "comentarios",
            "resumen",
            "resumen_actualizado_at",
            "resumen_fuente",
            "primer_contacto_at",
            "ultimo_contacto_at",
            "last_read_at",
            "creado",
            "actualizado",
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

    def validate(self, attrs):
        estado_actual = getattr(self.instance, "estado", "") if self.instance else ""
        motivo_actual = getattr(self.instance, "motivo_descalificacion", "") if self.instance else ""

        estado = str(attrs.get("estado", estado_actual) or "").strip()
        motivo = str(attrs.get("motivo_descalificacion", motivo_actual) or "").strip()

        if estado.lower() == "descalificado":
            if not motivo:
                raise serializers.ValidationError({
                    "motivo_descalificacion": "Selecciona el motivo de descalificación."
                })
            attrs["motivo_descalificacion"] = motivo
        else:
            # Evita conservar un motivo antiguo si el prospecto vuelve a otro estado.
            attrs["motivo_descalificacion"] = ""

        for campo in (
            "id_cotizacion",
            "folio_solicitud_credito",
            "solicitud_credito_estado",
            "vin_facturado",
            "vin_estatus_entrega",
        ):
            if campo in attrs:
                attrs[campo] = str(attrs.get(campo) or "").strip()

        if "vin_facturado" in attrs:
            attrs["vin_facturado"] = attrs["vin_facturado"].upper()

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["nombre"] = data.pop("nombre_out", "") or ""
        data["telefono"] = data.pop("telefono_out", "") or ""
        data["correo"] = data.pop("correo_out", "") or ""
        return data

    def _get_or_create_cliente(self, telefono, nombre="", correo=""):
        telefono = normaliza_tel_mx(telefono)

        if not telefono:
            raise serializers.ValidationError(
                {"telefono": "Teléfono inválido. Debe tener 10 dígitos o formato 52XXXXXXXXXX."}
            )

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

        if nombre_limpio and (cliente.nombre or "").strip() != nombre_limpio:
            cliente.nombre = nombre_limpio
            cambios.append("nombre")

        if correo is not None and (cliente.correo or "").strip() != correo_limpio:
            cliente.correo = correo_limpio
            cambios.append("correo")

        if cambios:
            cambios.append("actualizado_en")
            cliente.save(update_fields=list(dict.fromkeys(cambios)))

        return cliente

    def create(self, validated_data):
        nombre = validated_data.pop("nombre", "")
        telefono = validated_data.pop("telefono", "")
        correo = validated_data.pop("correo", "")

        cliente = self._get_or_create_cliente(telefono=telefono, nombre=nombre, correo=correo)

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
                raise serializers.ValidationError(
                    {"telefono": "Teléfono inválido. Debe tener 10 dígitos o formato 52XXXXXXXXXX."}
                )

            if telefono_normalizado != cliente.telefono:
                existe = (
                    ClienteComercial.objects
                    .filter(telefono=telefono_normalizado)
                    .exclude(id_cliente=cliente.id_cliente)
                    .exists()
                )
                if existe:
                    raise serializers.ValidationError({"telefono": "Ya existe otro prospecto con este teléfono."})

                cliente.telefono = telefono_normalizado
                cambios_cliente.append("telefono")

        if nombre is not None:
            nombre_limpio = (nombre or "").strip()
            if nombre_limpio and (cliente.nombre or "").strip() != nombre_limpio:
                cliente.nombre = nombre_limpio
                cambios_cliente.append("nombre")

        if correo is not None:
            correo_limpio = (correo or "").strip()
            if (cliente.correo or "").strip() != correo_limpio:
                cliente.correo = correo_limpio
                cambios_cliente.append("correo")

        if cambios_cliente:
            cambios_cliente.append("actualizado_en")
            cliente.save(update_fields=list(dict.fromkeys(cambios_cliente)))

        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)

        instance.save()
        return instance
w