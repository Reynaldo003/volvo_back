# Digitales/views.py
import json
import logging
import mimetypes
import os
import threading
import uuid
from datetime import timedelta

from django.core.files.storage import default_storage
from django.db import close_old_connections
from django.db.models import Q
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from citas.models import ClienteComercial, normaliza_tel_mx

from .models import CampanaMeta, ExpedienteDigital, LecturaWhatsApp, MensajeWhatsApp
from .serializers import ProspectoSerializer
from .sett import WHATSAPP_LINES, token as VERIFY_TOKEN

from . import contacto as contacto_api


logger = logging.getLogger(__name__)

EDIT_WINDOW_MINUTES = 15


# ============================================================
# Contacto API helpers importados de Digitales/contacto.py
# ============================================================

obtener_mensaje_whatsapp = contacto_api.obtener_mensaje_whatsapp
replace_start = contacto_api.replace_start
enviar_texto_whatsapp = contacto_api.enviar_texto_whatsapp
enviar_template_whatsapp = contacto_api.enviar_template_whatsapp
subir_media_whatsapp = contacto_api.subir_media_whatsapp
enviar_media_whatsapp = contacto_api.enviar_media_whatsapp
editar_texto_whatsapp = contacto_api.editar_texto_whatsapp
download_media_whatsapp = contacto_api.download_media_whatsapp
obtener_numero_asesor_desde_webhook_value = contacto_api.obtener_numero_asesor_desde_webhook_value
obtener_templates_whatsapp = contacto_api.obtener_templates_whatsapp

MetaAPIError = getattr(contacto_api, "MetaAPIError", RuntimeError)
MetaMediaError = getattr(contacto_api, "MetaMediaError", RuntimeError)


# ============================================================
# Prospectos
# ============================================================

class ProspectosViewSet(viewsets.ModelViewSet):
    serializer_class = ProspectoSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = (
            ExpedienteDigital.objects
            .select_related("cliente")
            .all()
            .order_by("-actualizado", "-creado")
        )

        search = (self.request.query_params.get("search") or "").strip()
        agencia = (self.request.query_params.get("agencia") or "").strip()
        estado = (self.request.query_params.get("estado") or "").strip()
        asesor_digital = (self.request.query_params.get("asesor_digital") or "").strip()
        asesor_ventas = (self.request.query_params.get("asesor_ventas") or "").strip()

        if search:
            queryset = queryset.filter(
                Q(cliente__nombre__icontains=search)
                | Q(cliente__telefono__icontains=search)
                | Q(cliente__correo__icontains=search)
                | Q(agencia__icontains=search)
                | Q(business__icontains=search)
                | Q(canal_contacto__icontains=search)
                | Q(pauta__icontains=search)
                | Q(estado__icontains=search)
                | Q(auto_interes__icontains=search)
                | Q(asesor_digital__icontains=search)
                | Q(asesor_ventas__icontains=search)
                | Q(comentarios__icontains=search)
            )

        if agencia:
            queryset = queryset.filter(agencia__iexact=agencia)

        if estado:
            queryset = queryset.filter(estado__iexact=estado)

        if asesor_digital:
            queryset = queryset.filter(asesor_digital__icontains=asesor_digital)

        if asesor_ventas:
            queryset = queryset.filter(asesor_ventas__icontains=asesor_ventas)

        return queryset


# ============================================================
# Vistas públicas informativas
# ============================================================

def bienvenido(request):
    return HttpResponse("Funcionando módulo Digitales Volvo")


def privacidad_meta_view(request):
    html = """
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Aviso de Privacidad - CRM Volvo</title>
    </head>
    <body>
        <h1>Aviso de Privacidad</h1>
        <p>
            Automotriz R&R utiliza este sistema CRM Volvo para gestionar
            prospectos y clientes registrados por medios digitales.
        </p>
        <p>
            Los datos personales que pueden tratarse incluyen nombre, teléfono,
            correo electrónico, interés vehicular, agencia de atención,
            asesor asignado, mensajes de WhatsApp y comentarios necesarios
            para dar seguimiento comercial.
        </p>
        <p>
            La información se utiliza únicamente para brindar atención,
            seguimiento, cotizaciones, programación de citas y mejora del servicio.
        </p>
    </body>
    </html>
    """

    return HttpResponse(html, content_type="text/html; charset=utf-8")


def eliminacion_datos_meta_view(request):
    html = """
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Eliminación de Datos - CRM Volvo</title>
    </head>
    <body>
        <h1>Instrucciones para eliminación de datos</h1>
        <p>
            Para solicitar la eliminación de tus datos personales almacenados
            en el CRM, contacta al área responsable de Automotriz R&R.
        </p>
        <p>
            Incluye tu nombre completo y número telefónico asociado al registro
            para poder localizar tu información.
        </p>
    </body>
    </html>
    """

    return HttpResponse(html, content_type="text/html; charset=utf-8")


# ============================================================
# Helpers generales
# ============================================================

def _default_numero_asesor() -> str:
    if not WHATSAPP_LINES:
        return ""

    return next(iter(WHATSAPP_LINES.keys()))


def _numero_linea_valido(numero: str) -> str:
    numero = normaliza_tel_mx(numero or "")

    if numero and numero in WHATSAPP_LINES:
        return numero

    return ""


def _get_numero_asesor_request(request) -> str:
    numero = _numero_linea_valido(request.query_params.get("numero_asesor", ""))

    if numero:
        return numero

    try:
        numero = _numero_linea_valido(request.data.get("numero_asesor", ""))
        if numero:
            return numero
    except Exception:
        pass

    usuario = ""

    try:
        usuario = str(
            request.query_params.get("usuario")
            or request.data.get("usuario")
            or ""
        ).strip().lower()
    except Exception:
        usuario = ""

    if usuario:
        for numero_linea, cfg in WHATSAPP_LINES.items():
            key = str(cfg.get("key") or "").strip().lower()
            asesor = str(cfg.get("asesor_digital") or "").strip().lower()

            if usuario == key or usuario in asesor:
                return numero_linea

    default = _default_numero_asesor()

    if default:
        return default

    raise ValueError("No hay líneas de WhatsApp configuradas en WHATSAPP_LINES.")


def _cfg_linea(numero_asesor: str) -> dict:
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    return WHATSAPP_LINES.get(numero_asesor, {}) or {}


def _now():
    return timezone.now()


def _format_time(dt):
    if not dt:
        return ""

    try:
        local_dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        return local_dt.strftime("%I:%M %p").lower()
    except Exception:
        return ""


def _format_chat_time(dt):
    if not dt:
        return ""

    try:
        local_dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        return local_dt.strftime("%d/%m %H:%M")
    except Exception:
        return ""


def _absolute_url(request, url: str) -> str:
    url = str(url or "").strip()

    if not url:
        return ""

    if url.startswith("http://") or url.startswith("https://"):
        return url

    if request is not None:
        try:
            return request.build_absolute_uri(url)
        except Exception:
            return url

    return url


def _safe_json(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        return {}


def _wa_message_id(wa_res: dict) -> str:
    try:
        return (wa_res.get("messages") or [{}])[0].get("id", "") or ""
    except Exception:
        return ""


def _http_status_desde_meta_error(error) -> int:
    retryable = bool(getattr(error, "retryable", False))
    meta_status = int(getattr(error, "status_code", 0) or 0)

    if meta_status == 429:
        return status.HTTP_429_TOO_MANY_REQUESTS

    if retryable:
        return status.HTTP_503_SERVICE_UNAVAILABLE

    if meta_status == 400:
        return status.HTTP_400_BAD_REQUEST

    return status.HTTP_502_BAD_GATEWAY


def _meta_error_payload(error, *, numero_asesor: str = "", extra: dict | None = None):
    if hasattr(error, "to_dict") and callable(error.to_dict):
        meta = error.to_dict()
        msg = getattr(error, "meta_message", str(error))
        retryable = bool(getattr(error, "retryable", False))
    else:
        meta = {
            "message": str(error),
            "type": error.__class__.__name__,
        }
        msg = str(error)
        retryable = False

    payload = {
        "ok": False,
        "error": msg,
        "retryable": retryable,
        "meta": meta,
        "numero_asesor": numero_asesor,
    }

    if extra:
        payload.update(extra)

    return payload


def _response_meta_error(error, *, numero_asesor: str = "", extra: dict | None = None):
    return Response(
        _meta_error_payload(error, numero_asesor=numero_asesor, extra=extra),
        status=_http_status_desde_meta_error(error),
    )


def _media_no_disponible(error) -> bool:
    fn = getattr(error, "es_media_no_disponible", None)

    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            pass

    text = str(error).lower()

    return (
        "object with id" in text
        or "does not exist" in text
        or "missing permissions" in text
        or "error_subcode" in text and "33" in text
    )


def _guardar_mensaje_fallido(
    *,
    to: str,
    numero_asesor: str,
    cliente=None,
    body: str,
    error,
    extra_raw: dict | None = None,
):
    raw = {
        "provider": "meta",
        "numero_asesor": numero_asesor,
        "error": str(error),
    }

    if hasattr(error, "to_dict") and callable(error.to_dict):
        raw["meta"] = error.to_dict()

    if extra_raw:
        raw.update(extra_raw)

    try:
        MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction="out",
            body=body,
            wa_message_id="",
            status="failed",
            raw=raw,
        )
    except Exception as save_error:
        logger.exception(
            "No se pudo guardar mensaje fallido | to=%s numero_asesor=%s error=%s",
            to,
            numero_asesor,
            str(save_error),
        )


def _get_or_create_cliente_y_expediente(
    *,
    tel: str,
    profile_name: str = "",
    numero_asesor: str = "",
):
    tel = normaliza_tel_mx(tel)
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not tel:
        return None, None

    nombre_default = (profile_name or "").strip()

    cliente, _ = ClienteComercial.objects.get_or_create(
        telefono=tel,
        defaults={
            "nombre": nombre_default,
            "correo": "",
        },
    )

    if nombre_default and not (cliente.nombre or "").strip():
        cliente.nombre = nombre_default
        cliente.save(update_fields=["nombre", "actualizado_en"])

    cfg = _cfg_linea(numero_asesor)

    agencia = (cfg.get("agencia") or "Volvo").strip()
    business = (cfg.get("business") or "Nuevos").strip()
    asesor_digital = (cfg.get("asesor_digital") or "").strip()

    expediente, _ = ExpedienteDigital.objects.get_or_create(
        cliente=cliente,
        defaults={
            "agencia": agencia,
            "business": business,
            "canal_contacto": "WhatsApp",
            "estado": "Contactado",
            "asesor_digital": asesor_digital,
        },
    )

    cambios = []

    if agencia and expediente.agencia != agencia:
        expediente.agencia = agencia
        cambios.append("agencia")

    if business and expediente.business != business:
        expediente.business = business
        cambios.append("business")

    if asesor_digital and expediente.asesor_digital != asesor_digital:
        expediente.asesor_digital = asesor_digital
        cambios.append("asesor_digital")

    if not expediente.canal_contacto:
        expediente.canal_contacto = "WhatsApp"
        cambios.append("canal_contacto")

    if not expediente.estado:
        expediente.estado = "Contactado"
        cambios.append("estado")

    if cambios:
        cambios.append("actualizado")
        expediente.save(update_fields=list(dict.fromkeys(cambios)))

    return cliente, expediente


def _touch_expediente_contacto(expediente):
    if not expediente:
        return

    try:
        expediente.touch_ultimo_contacto(save_now=True)
    except Exception:
        logger.exception("No se pudo actualizar último contacto del expediente.")


def _actualizar_raw_status(mensaje: MensajeWhatsApp, status_payload: dict):
    raw = mensaje.raw or {}

    if not isinstance(raw, dict):
        raw = {}

    statuses = raw.get("statuses")

    if not isinstance(statuses, list):
        statuses = []

    statuses.append(status_payload)

    raw["statuses"] = statuses
    raw["last_status"] = status_payload

    mensaje.raw = raw
    mensaje.status = str(status_payload.get("status") or mensaje.status or "")

    mensaje.save(update_fields=["status", "raw"])


# ============================================================
# Serialización local de mensajes
# ============================================================

def _media_proxy_url(request, media_id: str, numero_asesor: str = "") -> str:
    media_id = str(media_id or "").strip()

    if not media_id:
        return ""

    try:
        path = reverse("digitales-media-proxy", args=[media_id])
    except Exception:
        path = f"/digitales/media/{media_id}/"

    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if numero_asesor:
        sep = "&" if "?" in path else "?"
        path = f"{path}{sep}numero_asesor={numero_asesor}"

    return _absolute_url(request, path)


def _attachment_from_raw(raw: dict, *, request=None, numero_asesor: str = "") -> list[dict]:
    if not isinstance(raw, dict):
        return []

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
                "url": _absolute_url(request, local_url),
                "mime": raw.get("content_type") or "",
                "name": raw.get("filename") or "",
                "size": raw.get("size") or 0,
            }
        ]

    upload = raw.get("upload")

    if isinstance(upload, dict):
        media_id = upload.get("id") or ""
        kind = str(raw.get("meta_type") or "file").lower()

        if media_id:
            return [
                {
                    "id": media_id,
                    "kind": "file" if kind == "document" else kind,
                    "url": _media_proxy_url(request, media_id, numero_asesor),
                    "mime": raw.get("content_type") or "",
                    "name": raw.get("filename") or "",
                    "size": raw.get("size") or 0,
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
                    "url": _media_proxy_url(request, media_id, numero_asesor),
                    "mime": payload.get("mime_type") or "",
                    "name": payload.get("filename") or "",
                    "size": 0,
                }
            ]

    return []


def _es_template(mensaje: MensajeWhatsApp) -> bool:
    return str(mensaje.body or "").strip().startswith("[TEMPLATE:")


def _es_media(mensaje: MensajeWhatsApp) -> bool:
    raw = mensaje.raw or {}

    if isinstance(raw, dict):
        if raw.get("meta_type") in ("image", "video", "audio", "document", "sticker"):
            return True

        if raw.get("type") in ("image", "video", "audio", "document", "sticker"):
            return True

    body = str(mensaje.body or "")

    return body.startswith("[FILE:") or "\n[FILE:" in body


def _editable(mensaje: MensajeWhatsApp) -> bool:
    if mensaje.direction != "out":
        return False

    if not mensaje.wa_message_id:
        return False

    if _es_template(mensaje) or _es_media(mensaje):
        return False

    if not mensaje.created_at:
        return False

    return timezone.now() <= mensaje.created_at + timedelta(minutes=EDIT_WINDOW_MINUTES)


def _serializar_mensaje(mensaje: MensajeWhatsApp, request=None) -> dict:
    raw = mensaje.raw or {}

    attachments = _attachment_from_raw(
        raw,
        request=request,
        numero_asesor=mensaje.numero_asesor,
    )

    edit_expires_at = None

    if mensaje.created_at:
        edit_expires_at = (
            mensaje.created_at + timedelta(minutes=EDIT_WINDOW_MINUTES)
        ).isoformat()

    return {
        "id": mensaje.id,
        "telefono": mensaje.telefono,
        "numero_asesor": mensaje.numero_asesor,
        "direction": mensaje.direction,
        "mine": mensaje.direction == "out",
        "text": mensaje.body or "",
        "body": mensaje.body or "",
        "wa_message_id": mensaje.wa_message_id or "",
        "status": mensaje.status or "",
        "raw": raw,
        "created_at": mensaje.created_at.isoformat() if mensaje.created_at else None,
        "time": _format_time(mensaje.created_at),
        "editable": _editable(mensaje),
        "edit_expires_at": edit_expires_at,
        "is_template": _es_template(mensaje),
        "is_media": bool(attachments) or _es_media(mensaje),
        "attachments": attachments,
        "is_ai": bool(isinstance(raw, dict) and raw.get("openai_model")),
    }


def _mensaje_preview(mensaje: MensajeWhatsApp) -> str:
    raw = mensaje.raw or {}

    attachments = _attachment_from_raw(
        raw,
        request=None,
        numero_asesor=mensaje.numero_asesor,
    )

    if attachments:
        kind = attachments[0].get("kind") or "file"

        if kind == "image":
            return "Imagen"
        if kind == "video":
            return "Video"
        if kind == "audio":
            return "Audio"

        return "Archivo"

    body = str(mensaje.body or "").strip()

    if body.startswith("[TEMPLATE:"):
        return "Plantilla enviada"

    return body


# ============================================================
# Chats
# ============================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def chats_list(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    qs = (
        MensajeWhatsApp.objects
        .filter(numero_asesor=numero_asesor)
        .select_related("cliente")
        .order_by("-created_at", "-id")
    )

    q = (request.query_params.get("q") or "").strip()

    if q:
        q_tel = normaliza_tel_mx(q)

        qs = qs.filter(
            Q(telefono__icontains=q)
            | Q(body__icontains=q)
            | Q(cliente__nombre__icontains=q)
            | Q(cliente__correo__icontains=q)
            | Q(telefono__icontains=q_tel)
        )

    vistos = set()
    salida = []

    for mensaje in qs[:1000]:
        tel = mensaje.telefono

        if tel in vistos:
            continue

        vistos.add(tel)

        cliente = mensaje.cliente or ClienteComercial.objects.filter(telefono=tel).first()
        expediente = ExpedienteDigital.objects.filter(cliente=cliente).first() if cliente else None

        nombre = ""

        if cliente:
            nombre = (cliente.nombre or "").strip()

        if not nombre:
            nombre = "Prospecto"

        last_read_at = None

        if expediente:
            lectura = (
                LecturaWhatsApp.objects
                .filter(expediente=expediente, numero_asesor=numero_asesor)
                .first()
            )

            if lectura and lectura.last_read_at:
                last_read_at = lectura.last_read_at
            elif expediente.last_read_at:
                last_read_at = expediente.last_read_at

        unread_qs = MensajeWhatsApp.objects.filter(
            telefono=tel,
            numero_asesor=numero_asesor,
            direction="in",
        )

        if last_read_at:
            unread_qs = unread_qs.filter(created_at__gt=last_read_at)

        unread = unread_qs.count()

        salida.append(
            {
                "id": tel,
                "telefono": tel,
                "numero_asesor": numero_asesor,
                "nombre": nombre,
                "agencia": expediente.agencia if expediente else "",
                "linea": expediente.business if expediente else "",
                "estado": expediente.estado if expediente else "",
                "unread": unread,
                "last_text": _mensaje_preview(mensaje),
                "last_time": _format_chat_time(mensaje.created_at),
            }
        )

        if len(salida) >= 300:
            break

    return Response(salida, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_por_telefono(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    telefono = normaliza_tel_mx(request.query_params.get("tel", ""))

    if not telefono:
        return Response(
            {
                "ok": False,
                "error": "Falta tel o el teléfono es inválido.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    limit = int(request.query_params.get("limit") or 80)
    limit = max(1, min(limit, 200))

    days = int(request.query_params.get("days") or 0)

    cliente = ClienteComercial.objects.filter(telefono=telefono).first()
    expediente = ExpedienteDigital.objects.filter(cliente=cliente).first() if cliente else None

    mensajes_qs = MensajeWhatsApp.objects.filter(
        telefono=telefono,
        numero_asesor=numero_asesor,
    )

    if days > 0:
        mensajes_qs = mensajes_qs.filter(
            created_at__gte=timezone.now() - timedelta(days=days)
        )

    mensajes = list(
        mensajes_qs
        .select_related("cliente")
        .order_by("-created_at", "-id")[:limit]
    )

    mensajes.reverse()

    return Response(
        {
            "ok": True,
            "numero_asesor": numero_asesor,
            "prospecto": ProspectoSerializer(expediente).data if expediente else None,
            "mensajes": [
                _serializar_mensaje(mensaje, request=request)
                for mensaje in mensajes
            ],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_updates(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    telefono = normaliza_tel_mx(request.query_params.get("tel", ""))

    if not telefono:
        return Response(
            {
                "ok": False,
                "error": "Falta tel.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    after = (request.query_params.get("after") or "").strip()
    after_id = (request.query_params.get("after_id") or "").strip()
    limit = int(request.query_params.get("limit") or 80)
    limit = max(1, min(limit, 200))

    qs = MensajeWhatsApp.objects.filter(
        telefono=telefono,
        numero_asesor=numero_asesor,
    )

    if after:
        parsed = parse_datetime(after)

        if parsed:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())

            qs = qs.filter(created_at__gt=parsed)

    if after_id and after_id.isdigit():
        qs = qs.filter(id__gt=int(after_id))

    mensajes = list(
        qs
        .select_related("cliente")
        .order_by("created_at", "id")[:limit]
    )

    return Response(
        {
            "ok": True,
            "numero_asesor": numero_asesor,
            "mensajes": [
                _serializar_mensaje(mensaje, request=request)
                for mensaje in mensajes
            ],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def mark_read_view(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    telefono = normaliza_tel_mx(
        request.data.get("tel")
        or request.data.get("telefono")
        or request.query_params.get("tel")
        or ""
    )

    if not telefono:
        return Response(
            {
                "ok": False,
                "error": "Falta tel.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente = ClienteComercial.objects.filter(telefono=telefono).first()

    if not cliente:
        return Response({"ok": True}, status=status.HTTP_200_OK)

    expediente = ExpedienteDigital.objects.filter(cliente=cliente).first()

    if not expediente:
        return Response({"ok": True}, status=status.HTTP_200_OK)

    when = timezone.now()

    expediente.last_read_at = when
    expediente.save(update_fields=["last_read_at", "actualizado"])

    lectura, _ = LecturaWhatsApp.objects.get_or_create(
        expediente=expediente,
        numero_asesor=numero_asesor,
    )

    lectura.touch(when=when)

    return Response(
        {
            "ok": True,
            "last_read_at": when.isoformat(),
        },
        status=status.HTTP_200_OK,
    )


# ============================================================
# Envío de mensajes
# ============================================================

@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_mensaje_view(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    to = normaliza_tel_mx(request.data.get("to", ""))
    text = (request.data.get("text") or "").strip()

    if not to or not text:
        return Response(
            {
                "ok": False,
                "error": "Falta to o text.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente = None

    try:
        cliente, expediente = _get_or_create_cliente_y_expediente(
            tel=to,
            numero_asesor=numero_asesor,
        )

        _touch_expediente_contacto(expediente)

        wa_res = enviar_texto_whatsapp(
            to=to,
            text=text,
            numero_asesor=numero_asesor,
        )

        wa_message_id = _wa_message_id(wa_res)

        mensaje = MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction="out",
            body=text,
            wa_message_id=wa_message_id,
            status="accepted",
            raw={
                "provider": "meta",
                "send": wa_res,
                "numero_asesor": numero_asesor,
            },
        )

        return Response(
            {
                "ok": True,
                "data": wa_res,
                "wa_message_id": wa_message_id,
                "numero_asesor": numero_asesor,
                "mensaje": _serializar_mensaje(mensaje, request=request),
            },
            status=status.HTTP_200_OK,
        )

    except MetaAPIError as e:
        logger.warning(
            "FALLO META ENVIAR MENSAJE VOLVO | to=%s numero_asesor=%s error=%s",
            to,
            numero_asesor,
            str(e),
        )

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=text,
            error=e,
            extra_raw={"request_type": "text"},
        )

        return _response_meta_error(
            e,
            numero_asesor=numero_asesor,
            extra={
                "tipo": "text",
                "to": to,
            },
        )

    except Exception as e:
        logger.exception(
            "ERROR INTERNO ENVIAR MENSAJE VOLVO | to=%s numero_asesor=%s",
            to,
            numero_asesor,
        )

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=text,
            error=e,
            extra_raw={
                "request_type": "text",
                "internal_error": True,
            },
        )

        return Response(
            {
                "ok": False,
                "error": str(e),
                "retryable": False,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


def _file_media_type(file_obj) -> str:
    content_type = str(getattr(file_obj, "content_type", "") or "").lower()
    name = str(getattr(file_obj, "name", "") or "")

    if not content_type:
        content_type = mimetypes.guess_type(name)[0] or ""

    if content_type.startswith("image/"):
        return "image"

    if content_type.startswith("video/"):
        return "video"

    if content_type.startswith("audio/"):
        return "audio"

    return "document"


def _guardar_upload_whatsapp_local(
    file_obj,
    *,
    numero_asesor: str,
    telefono: str,
    content_type: str = "",
) -> str:
    original_name = getattr(file_obj, "name", "archivo") or "archivo"
    _, ext = os.path.splitext(original_name)

    if not ext:
        ext = mimetypes.guess_extension(content_type or "") or ".bin"

    filename = f"{uuid.uuid4().hex}{ext.lower()}"
    path = f"whatsapp_uploads/volvo/{numero_asesor}/{telefono}/{filename}"

    try:
        file_obj.seek(0)
    except Exception:
        pass

    saved_path = default_storage.save(path, file_obj)

    try:
        file_obj.seek(0)
    except Exception:
        pass

    url = default_storage.url(saved_path)

    return url


@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser])
def enviar_media_view(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    to = normaliza_tel_mx(request.data.get("to", ""))
    text = (request.data.get("text") or "").strip()

    files = []
    files.extend(request.FILES.getlist("files"))
    files.extend(request.FILES.getlist("file"))
    files.extend(request.FILES.getlist("attachments"))

    if not to:
        return Response(
            {
                "ok": False,
                "error": "Falta to.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not files:
        return Response(
            {
                "ok": False,
                "error": "Falta archivo.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente = None
    items = []

    try:
        cliente, expediente = _get_or_create_cliente_y_expediente(
            tel=to,
            numero_asesor=numero_asesor,
        )

        _touch_expediente_contacto(expediente)

        for f in files:
            name = getattr(f, "name", "archivo") or "archivo"
            ct = getattr(f, "content_type", "") or mimetypes.guess_type(name)[0] or "application/octet-stream"
            size = getattr(f, "size", 0) or 0
            wtype = _file_media_type(f)

            local_media_url = _guardar_upload_whatsapp_local(
                f,
                numero_asesor=numero_asesor,
                telefono=to,
                content_type=ct,
            )

            try:
                f.seek(0)
            except Exception:
                pass

            up = subir_media_whatsapp(
                f,
                numero_asesor=numero_asesor,
                filename=name,
                content_type=ct,
            )

            media_id = up.get("id") or ""

            wa_res = enviar_media_whatsapp(
                to=to,
                media_id=media_id,
                media_type=wtype,
                numero_asesor=numero_asesor,
                caption=text if wtype in ("image", "video", "document") else "",
                filename=name if wtype == "document" else "",
            )

            wa_message_id = _wa_message_id(wa_res)

            body = text or f"[FILE:{name}]"

            mensaje = MensajeWhatsApp.objects.create(
                telefono=to,
                numero_asesor=numero_asesor,
                cliente=cliente,
                direction="out",
                body=body,
                wa_message_id=wa_message_id,
                status="accepted",
                raw={
                    "provider": "meta",
                    "upload": up,
                    "send": wa_res,
                    "meta_type": wtype,
                    "filename": name,
                    "content_type": ct,
                    "size": size,
                    "numero_asesor": numero_asesor,
                    "local_media_url": local_media_url,
                    "media_link": local_media_url if wtype in ("image", "video", "audio") else "",
                    "document_link": local_media_url if wtype == "document" else "",
                },
            )

            items.append(
                {
                    "ok": True,
                    "filename": name,
                    "media_id": media_id,
                    "wa_message_id": wa_message_id,
                    "mensaje": _serializar_mensaje(mensaje, request=request),
                }
            )

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "items": items,
            },
            status=status.HTTP_200_OK,
        )

    except MetaAPIError as e:
        logger.warning(
            "FALLO META ENVIAR MEDIA VOLVO | to=%s numero_asesor=%s error=%s",
            to,
            numero_asesor,
            str(e),
        )

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=text or "[MEDIA] failed",
            error=e,
            extra_raw={"request_type": "media"},
        )

        return _response_meta_error(
            e,
            numero_asesor=numero_asesor,
            extra={
                "tipo": "media",
                "to": to,
            },
        )

    except Exception as e:
        logger.exception(
            "ERROR INTERNO ENVIAR MEDIA VOLVO | to=%s numero_asesor=%s",
            to,
            numero_asesor,
        )

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=text or "[MEDIA] failed",
            error=e,
            extra_raw={
                "request_type": "media",
                "internal_error": True,
            },
        )

        return Response(
            {
                "ok": False,
                "error": str(e),
                "retryable": False,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_plantilla_view(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    to = normaliza_tel_mx(request.data.get("to", ""))
    template_name = (request.data.get("template_name") or "").strip()
    idioma = (request.data.get("idioma") or "es_MX").strip()
    params = request.data.get("params")
    components = request.data.get("components")

    if not to:
        return Response(
            {
                "ok": False,
                "error": "Falta to.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not template_name:
        return Response(
            {
                "ok": False,
                "error": "Falta template_name.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if components is not None and not isinstance(components, list):
        return Response(
            {
                "ok": False,
                "error": "components debe ser lista.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if params is None:
        params = []

    if params is not None and not isinstance(params, list):
        return Response(
            {
                "ok": False,
                "error": "params debe ser lista.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente = None

    try:
        cliente, expediente = _get_or_create_cliente_y_expediente(
            tel=to,
            numero_asesor=numero_asesor,
        )

        _touch_expediente_contacto(expediente)

        wa_res = enviar_template_whatsapp(
            to=to,
            template_name=template_name,
            numero_asesor=numero_asesor,
            params=[str(x) for x in (params or [])],
            idioma=idioma,
            components=components,
        )

        wa_message_id = _wa_message_id(wa_res)

        body_log = f"[TEMPLATE:{template_name}]"

        if components:
            flat = []

            for component in components:
                for parametro in component.get("parameters") or []:
                    if parametro.get("type") == "text":
                        flat.append(str(parametro.get("text") or ""))

            if flat:
                body_log += " " + " | ".join(flat)

        elif params:
            body_log += " " + " | ".join([str(x) for x in params])

        mensaje = MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction="out",
            body=body_log.strip(),
            wa_message_id=wa_message_id,
            status="accepted",
            raw={
                "provider": "meta",
                "send": wa_res,
                "numero_asesor": numero_asesor,
                "template_name": template_name,
                "idioma": idioma,
                "params": params or [],
                "components": components or [],
            },
        )

        return Response(
            {
                "ok": True,
                "data": wa_res,
                "wa_message_id": wa_message_id,
                "numero_asesor": numero_asesor,
                "mensaje": _serializar_mensaje(mensaje, request=request),
            },
            status=status.HTTP_200_OK,
        )

    except MetaAPIError as e:
        logger.warning(
            "FALLO META ENVIAR PLANTILLA VOLVO | to=%s numero_asesor=%s template=%s error=%s",
            to,
            numero_asesor,
            template_name,
            str(e),
        )

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=f"[TEMPLATE:{template_name}] failed",
            error=e,
            extra_raw={
                "request_type": "template",
                "template_name": template_name,
                "idioma": idioma,
                "params": params or [],
                "components": components or [],
            },
        )

        return _response_meta_error(
            e,
            numero_asesor=numero_asesor,
            extra={
                "tipo": "template",
                "to": to,
                "template_name": template_name,
                "idioma": idioma,
            },
        )

    except Exception as e:
        logger.exception(
            "ERROR INTERNO ENVIAR PLANTILLA VOLVO | to=%s numero_asesor=%s template=%s",
            to,
            numero_asesor,
            template_name,
        )

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=f"[TEMPLATE:{template_name}] failed",
            error=e,
            extra_raw={
                "request_type": "template",
                "template_name": template_name,
                "idioma": idioma,
                "params": params or [],
                "components": components or [],
                "internal_error": True,
            },
        )

        return Response(
            {
                "ok": False,
                "error": str(e),
                "retryable": False,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["PATCH"])
@permission_classes([AllowAny])
def editar_mensaje_view(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    to = normaliza_tel_mx(request.data.get("to", ""))
    message_id = (request.data.get("message_id") or "").strip()
    text = (request.data.get("text") or "").strip()

    if not to or not message_id or not text:
        return Response(
            {
                "ok": False,
                "error": "Falta to, message_id o text.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    mensaje = (
        MensajeWhatsApp.objects
        .filter(
            telefono=to,
            numero_asesor=numero_asesor,
            wa_message_id=message_id,
            direction="out",
        )
        .first()
    )

    if not mensaje:
        return Response(
            {
                "ok": False,
                "error": "No se encontró el mensaje saliente.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if not _editable(mensaje):
        return Response(
            {
                "ok": False,
                "error": "Este mensaje ya no se puede editar.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        wa_res = editar_texto_whatsapp(
            to=to,
            original_message_id=message_id,
            new_text=text,
            numero_asesor=numero_asesor,
        )

        raw = mensaje.raw or {}

        if not isinstance(raw, dict):
            raw = {}

        raw["edit"] = wa_res
        raw["edited_at"] = timezone.now().isoformat()
        raw["old_body"] = mensaje.body

        mensaje.body = text
        mensaje.status = "accepted"
        mensaje.raw = raw
        mensaje.save(update_fields=["body", "status", "raw"])

        return Response(
            {
                "ok": True,
                "data": wa_res,
                "mensaje": _serializar_mensaje(mensaje, request=request),
            },
            status=status.HTTP_200_OK,
        )

    except MetaAPIError as e:
        return _response_meta_error(
            e,
            numero_asesor=numero_asesor,
            extra={
                "tipo": "edit",
                "to": to,
                "message_id": message_id,
            },
        )

    except Exception as e:
        logger.exception(
            "ERROR EDITAR MENSAJE VOLVO | to=%s numero_asesor=%s message_id=%s",
            to,
            numero_asesor,
            message_id,
        )

        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def plantillas_whatsapp_view(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
                "items": [],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        items = obtener_templates_whatsapp(numero_asesor=numero_asesor)

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "items": items,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.exception(
            "ERROR OBTENER PLANTILLAS VOLVO | numero_asesor=%s",
            numero_asesor,
        )

        return Response(
            {
                "ok": False,
                "error": str(e),
                "items": [],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


# ============================================================
# Media proxy
# ============================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def media_proxy_view(request, media_id):
    numero_asesor = normaliza_tel_mx(request.query_params.get("numero_asesor", ""))

    if not numero_asesor:
        try:
            numero_asesor = _get_numero_asesor_request(request)
        except Exception:
            numero_asesor = _default_numero_asesor()

    try:
        blob, content_type = download_media_whatsapp(
            media_id,
            numero_asesor=numero_asesor,
        )

        resp = HttpResponse(blob, content_type=content_type)
        resp["Cache-Control"] = "private, max-age=86400"
        return resp

    except MetaMediaError as e:
        logger.warning(
            "MEDIA META NO DISPONIBLE VOLVO | media_id=%s numero_asesor=%s error=%s",
            media_id,
            numero_asesor,
            str(e),
        )

        status_code = status.HTTP_410_GONE if _media_no_disponible(e) else status.HTTP_502_BAD_GATEWAY

        meta_payload = e.to_dict() if hasattr(e, "to_dict") and callable(e.to_dict) else {
            "message": str(e),
            "type": e.__class__.__name__,
        }

        return HttpResponse(
            json.dumps(
                {
                    "ok": False,
                    "error": "El archivo ya no está disponible en Meta o no pertenece a esta línea.",
                    "meta": meta_payload,
                },
                ensure_ascii=False,
            ),
            status=status_code,
            content_type="application/json; charset=utf-8",
        )

    except Exception as e:
        logger.exception(
            "ERROR MEDIA PROXY VOLVO | media_id=%s numero_asesor=%s",
            media_id,
            numero_asesor,
        )

        status_code = status.HTTP_410_GONE if _media_no_disponible(e) else status.HTTP_400_BAD_REQUEST

        return HttpResponse(
            json.dumps(
                {
                    "ok": False,
                    "error": str(e),
                },
                ensure_ascii=False,
            ),
            status=status_code,
            content_type="application/json; charset=utf-8",
        )


# ============================================================
# Campañas Meta
# ============================================================

@api_view(["GET"])
@permission_classes([AllowAny])
def campanas_meta_recientes(request):
    try:
        limit = int(request.query_params.get("limit") or 50)
        limit = max(1, min(limit, 200))

        qs = CampanaMeta.objects.all().order_by("-inicio_campana")[:limit]

        items = [
            {
                "id_campana": item.id_campana,
                "id_concesionaria": item.id_concesionaria,
                "sucursal": item.sucursal,
                "nombre_campana": item.nombre_campana,
                "inicio_campana": item.inicio_campana.isoformat() if item.inicio_campana else None,
                "fin_campana": item.fin_campana.isoformat() if item.fin_campana else None,
            }
            for item in qs
        ]

        return Response(
            {
                "ok": True,
                "items": items,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.warning("No se pudieron obtener campañas Meta Volvo: %s", str(e))

        return Response(
            {
                "ok": True,
                "items": [],
                "warning": str(e),
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# Webhook WhatsApp Cloud API
# ============================================================

def _cache_media_meta_en_segundo_plano(*, media_id: str, numero_asesor: str):
    close_old_connections()

    try:
        download_media_whatsapp(
            media_id,
            numero_asesor=numero_asesor,
        )

        logger.info(
            "MEDIA CACHEADA OK VOLVO | media_id=%s numero_asesor=%s",
            media_id,
            numero_asesor,
        )

    except Exception as e:
        logger.warning(
            "NO SE PUDO CACHEAR MEDIA VOLVO | media_id=%s numero_asesor=%s error=%s",
            media_id,
            numero_asesor,
            str(e),
        )

    finally:
        close_old_connections()


def _procesar_statuses_webhook(statuses: list[dict], *, numero_asesor: str):
    for status_payload in statuses or []:
        wa_id = str(status_payload.get("id") or "").strip()
        nuevo_status = str(status_payload.get("status") or "").strip()

        if not wa_id:
            continue

        qs = MensajeWhatsApp.objects.filter(wa_message_id=wa_id)

        if numero_asesor:
            qs = qs.filter(numero_asesor=numero_asesor)

        mensaje = qs.order_by("-created_at").first()

        if not mensaje:
            continue

        if nuevo_status:
            _actualizar_raw_status(mensaje, status_payload)


def _procesar_mensajes_webhook(
    messages: list[dict],
    *,
    contacts: list[dict],
    numero_asesor: str,
):
    contactos_por_wa_id = {}

    for c in contacts or []:
        wa_id = normaliza_tel_mx(c.get("wa_id") or "")
        profile = c.get("profile") or {}
        name = (profile.get("name") or "").strip()

        if wa_id:
            contactos_por_wa_id[wa_id] = name

    for msg in messages or []:
        message_id = str(msg.get("id") or "").strip()
        raw_from = msg.get("from") or ""
        from_tel = normaliza_tel_mx(replace_start(raw_from))
        
        if not from_tel:
            continue

        profile_name = contactos_por_wa_id.get(from_tel, "")

        cliente, expediente = _get_or_create_cliente_y_expediente(
            tel=from_tel,
            profile_name=profile_name,
            numero_asesor=numero_asesor,
        )

        _touch_expediente_contacto(expediente)

        body = obtener_mensaje_whatsapp(msg)
        raw = dict(msg)
        raw["provider"] = "meta"
        raw["numero_asesor"] = numero_asesor

        if message_id:
            existente = MensajeWhatsApp.objects.filter(
                wa_message_id=message_id,
                numero_asesor=numero_asesor,
            ).first()

            if existente:
                continue

        MensajeWhatsApp.objects.create(
            telefono=from_tel,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction="in",
            body=body,
            wa_message_id=message_id,
            status="received",
            raw=raw,
        )

        media_type = str(msg.get("type") or "").lower()

        if media_type in ("image", "document", "video", "audio", "sticker"):
            media_payload = msg.get(media_type) or {}
            media_id = str(media_payload.get("id") or "").strip()

            if media_id:
                hilo_media = threading.Thread(
                    target=_cache_media_meta_en_segundo_plano,
                    kwargs={
                        "media_id": media_id,
                        "numero_asesor": numero_asesor,
                    },
                    daemon=True,
                )
                hilo_media.start()


@csrf_exempt
def webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode", "")
        verify_token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")

        if mode == "subscribe" and verify_token == VERIFY_TOKEN and challenge:
            return HttpResponse(challenge, content_type="text/plain")

        if challenge and not VERIFY_TOKEN:
            return HttpResponse(challenge, content_type="text/plain")

        return HttpResponse("Token inválido", status=403)

    if request.method != "POST":
        return HttpResponse("Método no permitido", status=405)

    try:
        body = request.body.decode("utf-8") if request.body else "{}"
        payload = json.loads(body or "{}")
    except Exception:
        logger.exception("Webhook Volvo recibió JSON inválido.")
        return HttpResponse("bad json", status=400)

    try:
        entries = payload.get("entry") or []

        for entry in entries:
            changes = entry.get("changes") or []

            for change in changes:
                value = change.get("value") or {}

                numero_asesor = obtener_numero_asesor_desde_webhook_value(value)

                if not numero_asesor:
                    numero_asesor = _default_numero_asesor()

                messages = value.get("messages") or []
                statuses = value.get("statuses") or []
                contacts = value.get("contacts") or []

                if statuses:
                    _procesar_statuses_webhook(
                        statuses,
                        numero_asesor=numero_asesor,
                    )

                if messages:
                    _procesar_mensajes_webhook(
                        messages,
                        contacts=contacts,
                        numero_asesor=numero_asesor,
                    )

        return HttpResponse("ok", content_type="text/plain")

    except Exception:
        logger.exception("ERROR PROCESANDO WEBHOOK VOLVO")
        return HttpResponse("ok", content_type="text/plain")