# Digitales/views.py
import json
from datetime import timedelta

from django.db.models import Q, Max
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from citas.models import ClienteComercial, normaliza_tel_mx

from .models import (
    ExpedienteDigital,
    MensajeWhatsApp,
    LecturaWhatsApp,
    MapeoFuenteMeta,
)
from .serializers import ProspectoSerializer
from .contacto import (
    obtener_config_linea,
    obtener_numero_asesor_desde_webhook_value,
    obtener_mensaje_whatsapp,
    obtener_templates_whatsapp,
    enviar_texto_whatsapp,
    enviar_template_whatsapp,
    subir_media_whatsapp,
    enviar_media_whatsapp,
    editar_texto_whatsapp,
    download_media_whatsapp,
)

try:
    from .sett import WHATSAPP_LINES, WHATSAPP_TEMPLATE_UI
except Exception:
    WHATSAPP_LINES = {}
    WHATSAPP_TEMPLATE_UI = {}


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


def _primer_numero_asesor():
    return next(iter(WHATSAPP_LINES.keys()), "")


def _request_value(request, key, default=""):
    if hasattr(request, "query_params"):
        value = request.query_params.get(key, None)
        if value is not None:
            return value

    data = getattr(request, "data", {}) or {}

    if isinstance(data, dict):
        return data.get(key, default)

    return default


def _bool_value(value, default=False):
    if value is None:
        return default

    return str(value).strip().lower() in ("1", "true", "sí", "si", "yes", "y")


def _int_value(value, default=80, min_value=1, max_value=200):
    try:
        number = int(value)
    except Exception:
        number = default

    return max(min_value, min(number, max_value))


def _parse_dt(value):
    if not value:
        return None

    dt = parse_datetime(str(value))

    if not dt:
        return None

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())

    return dt


def _get_cfg_request(request):
    numero_asesor = (
        _request_value(request, "numero_asesor", "")
        or _primer_numero_asesor()
    )

    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    return cfg, cfg["numero_asesor"]


def _meta_message_id(meta_response):
    messages = meta_response.get("messages") or []

    if messages and isinstance(messages[0], dict):
        return str(messages[0].get("id") or "")

    return ""


def _media_type_from_file(file_obj):
    content_type = str(getattr(file_obj, "content_type", "") or "").lower()

    if content_type.startswith("image/"):
        return "image"

    if content_type.startswith("video/"):
        return "video"

    if content_type.startswith("audio/"):
        return "audio"

    return "document"


def _ensure_cliente_expediente(telefono, cfg=None, nombre=""):
    telefono = normaliza_tel_mx(telefono)

    if not telefono:
        raise ValueError("Teléfono inválido.")

    cliente, creado_cliente = ClienteComercial.objects.get_or_create(
        telefono=telefono,
        defaults={
            "nombre": (nombre or "Prospecto").strip(),
            "correo": "",
        },
    )

    if nombre and not cliente.nombre:
        cliente.nombre = nombre.strip()
        cliente.save(update_fields=["nombre", "actualizado_en"])

    defaults = {
        "agencia": (cfg or {}).get("agencia", ""),
        "business": (cfg or {}).get("business", ""),
        "canal_contacto": "WhatsApp",
        "estado": "Sin Respuesta",
        "asesor_digital": (cfg or {}).get("asesor_digital", ""),
    }

    expediente, creado_expediente = ExpedienteDigital.objects.get_or_create(
        cliente=cliente,
        defaults=defaults,
    )

    cambios = []

    for field, value in defaults.items():
        if value and not getattr(expediente, field, ""):
            setattr(expediente, field, value)
            cambios.append(field)

    if cambios:
        cambios.append("actualizado")
        expediente.save(update_fields=cambios)

    return cliente, expediente


def _touch_read(expediente, numero_asesor, when=None):
    if not expediente:
        return

    when = when or timezone.now()

    expediente.last_read_at = when
    expediente.save(update_fields=["last_read_at", "actualizado"])

    lectura, _ = LecturaWhatsApp.objects.get_or_create(
        expediente=expediente,
        numero_asesor=normaliza_tel_mx(numero_asesor),
    )

    lectura.last_read_at = when
    lectura.save(update_fields=["last_read_at", "updated_at"])


def _set_unread(expediente, numero_asesor, telefono):
    if not expediente:
        return

    ultimo_entrante = (
        MensajeWhatsApp.objects
        .filter(
            telefono=normaliza_tel_mx(telefono),
            numero_asesor=normaliza_tel_mx(numero_asesor),
            direction=MensajeWhatsApp.Direccion.IN,
        )
        .order_by("-created_at", "-id")
        .first()
    )

    if ultimo_entrante:
        when = ultimo_entrante.created_at - timedelta(microseconds=1)
    else:
        when = None

    expediente.last_read_at = when
    expediente.save(update_fields=["last_read_at", "actualizado"])

    lectura, _ = LecturaWhatsApp.objects.get_or_create(
        expediente=expediente,
        numero_asesor=normaliza_tel_mx(numero_asesor),
    )

    lectura.last_read_at = when
    lectura.save(update_fields=["last_read_at", "updated_at"])


def _last_read_for(expediente, numero_asesor):
    if not expediente:
        return None

    lectura = (
        LecturaWhatsApp.objects
        .filter(
            expediente=expediente,
            numero_asesor=normaliza_tel_mx(numero_asesor),
        )
        .first()
    )

    if lectura:
        return lectura.last_read_at

    return expediente.last_read_at


def _attachment_url(request, media_id, numero_asesor):
    path = f"/digitales/media/{media_id}/?numero_asesor={numero_asesor}"

    if request is None:
        return path

    return request.build_absolute_uri(path)


def _attachments_from_raw(message_obj, request=None):
    raw = message_obj.raw or {}

    meta_message = raw.get("message") or {}
    media_type = (
        meta_message.get("type")
        or raw.get("media_type")
        or raw.get("type")
        or ""
    )

    media_type = str(media_type).lower()

    if media_type not in ("image", "document", "video", "audio", "sticker"):
        return []

    media_payload = meta_message.get(media_type) or raw

    media_id = (
        media_payload.get("id")
        or raw.get("media_id")
        or raw.get("id")
        or ""
    )

    if not media_id:
        return []

    filename = (
        media_payload.get("filename")
        or raw.get("filename")
        or raw.get("name")
        or ""
    )

    mime_type = (
        media_payload.get("mime_type")
        or raw.get("mime_type")
        or raw.get("content_type")
        or ""
    )

    size = (
        media_payload.get("file_size")
        or raw.get("size")
        or 0
    )

    kind = "file" if media_type == "document" else media_type

    return [
        {
            "id": media_id,
            "kind": kind,
            "media_type": media_type,
            "url": _attachment_url(request, media_id, message_obj.numero_asesor),
            "previewUrl": _attachment_url(request, media_id, message_obj.numero_asesor),
            "name": filename,
            "filename": filename,
            "mime": mime_type,
            "mime_type": mime_type,
            "size": size,
        }
    ]


def _serialize_message(message_obj, request=None):
    local_dt = timezone.localtime(message_obj.created_at)

    return {
        "id": message_obj.id,
        "telefono": message_obj.telefono,
        "numero_asesor": message_obj.numero_asesor,
        "direction": message_obj.direction,
        "mine": message_obj.direction == MensajeWhatsApp.Direccion.OUT,
        "body": message_obj.body or "",
        "text": message_obj.body or "",
        "wa_message_id": message_obj.wa_message_id or "",
        "status": message_obj.status or (
            "received"
            if message_obj.direction == MensajeWhatsApp.Direccion.IN
            else "sent"
        ),
        "created_at": message_obj.created_at.isoformat(),
        "time": local_dt.strftime("%H:%M"),
        "attachments": _attachments_from_raw(message_obj, request=request),
    }


def _find_message_ref(telefono, numero_asesor, ref):
    if not ref:
        return None

    qs = MensajeWhatsApp.objects.filter(
        telefono=normaliza_tel_mx(telefono),
        numero_asesor=normaliza_tel_mx(numero_asesor),
    )

    ref_str = str(ref).strip()

    if ref_str.isdigit():
        found = qs.filter(id=int(ref_str)).first()
        if found:
            return found

    return qs.filter(wa_message_id=ref_str).first()


def _get_contact_payload(request, updates_only=False):
    cfg, numero_asesor = _get_cfg_request(request)

    telefono = normaliza_tel_mx(_request_value(request, "tel", ""))

    if not telefono:
        return Response(
            {
                "ok": False,
                "error": "Falta tel o el teléfono es inválido.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    limit = _int_value(_request_value(request, "limit", 80), default=80)
    before_id = str(_request_value(request, "before_id", "") or "").strip()
    after_id = str(_request_value(request, "after_id", "") or "").strip()
    after = str(_request_value(request, "after", "") or "").strip()
    mark_read = _bool_value(_request_value(request, "mark_read", "0"))

    cliente, expediente = _ensure_cliente_expediente(telefono, cfg=cfg)

    base_qs = (
        MensajeWhatsApp.objects
        .filter(
            telefono=telefono,
            numero_asesor=numero_asesor,
        )
        .select_related("cliente")
    )

    has_more = False

    if before_id:
        ref = _find_message_ref(telefono, numero_asesor, before_id)

        if ref:
            qs = base_qs.filter(
                Q(created_at__lt=ref.created_at)
                | Q(created_at=ref.created_at, id__lt=ref.id)
            ).order_by("-created_at", "-id")
        else:
            qs = base_qs.none()

        page = list(qs[: limit + 1])
        has_more = len(page) > limit
        mensajes = list(reversed(page[:limit]))

    elif after_id or after:
        qs = base_qs

        ref = _find_message_ref(telefono, numero_asesor, after_id)

        if ref:
            qs = qs.filter(
                Q(created_at__gt=ref.created_at)
                | Q(created_at=ref.created_at, id__gt=ref.id)
            )
        else:
            after_dt = _parse_dt(after)

            if after_dt:
                qs = qs.filter(created_at__gt=after_dt)

        page = list(qs.order_by("created_at", "id")[: limit + 1])
        has_more = len(page) > limit
        mensajes = page[:limit]

    else:
        page = list(base_qs.order_by("-created_at", "-id")[: limit + 1])
        has_more = len(page) > limit
        mensajes = list(reversed(page[:limit]))

    if mark_read:
        _touch_read(expediente, numero_asesor)

    serialized = [_serialize_message(item, request=request) for item in mensajes]

    return Response(
        {
            "ok": True,
            "prospecto": ProspectoSerializer(expediente).data if expediente else None,
            "mensajes": serialized,
            "paginacion": {
                "has_more": has_more,
                "oldest_id": serialized[0]["id"] if serialized else None,
                "newest_id": serialized[-1]["id"] if serialized else None,
            },
        },
        status=status.HTTP_200_OK,
    )


def bienvenido(request):
    return HttpResponse("Funcionando módulo Digitales Volvo - WhatsApp activo")


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
            prospectos y clientes registrados manualmente por el equipo comercial.
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
    </body>
    </html>
    """

    return HttpResponse(html, content_type="text/html; charset=utf-8")


@api_view(["GET"])
@permission_classes([AllowAny])
def chats_list(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    limit = _int_value(request.query_params.get("limit", 150), default=150, max_value=300)
    search = str(request.query_params.get("search") or "").strip()

    base_qs = MensajeWhatsApp.objects.filter(numero_asesor=numero_asesor)

    if search:
        telefono_search = normaliza_tel_mx(search)

        base_qs = base_qs.filter(
            Q(telefono__icontains=telefono_search or search)
            | Q(cliente__nombre__icontains=search)
            | Q(body__icontains=search)
        )

    rows = (
        base_qs
        .values("telefono")
        .annotate(last_created=Max("created_at"))
        .order_by("-last_created")[:limit]
    )

    salida = []

    for row in rows:
        telefono = row["telefono"]

        ultimo = (
            MensajeWhatsApp.objects
            .filter(
                telefono=telefono,
                numero_asesor=numero_asesor,
                created_at=row["last_created"],
            )
            .select_related("cliente")
            .order_by("-id")
            .first()
        )

        if not ultimo:
            continue

        cliente = ultimo.cliente or ClienteComercial.objects.filter(telefono=telefono).first()
        expediente = ExpedienteDigital.objects.filter(cliente=cliente).first() if cliente else None

        last_read_at = _last_read_for(expediente, numero_asesor)

        unread_qs = MensajeWhatsApp.objects.filter(
            telefono=telefono,
            numero_asesor=numero_asesor,
            direction=MensajeWhatsApp.Direccion.IN,
        )

        if last_read_at:
            unread_qs = unread_qs.filter(created_at__gt=last_read_at)

        unread = unread_qs.count()

        nombre = ""
        if cliente:
            nombre = cliente.nombre or ""

        salida.append(
            {
                "id": telefono,
                "telefono": telefono,
                "nombre": nombre or "Prospecto",
                "agencia": expediente.agencia if expediente else cfg.get("agencia", ""),
                "linea": expediente.business if expediente else cfg.get("business", ""),
                "estado": expediente.estado if expediente else "",
                "unread": unread,
                "last_text": ultimo.body or "",
                "last_time": ultimo.created_at.isoformat(),
            }
        )

    return Response(salida, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_por_telefono(request):
    try:
        return _get_contact_payload(request, updates_only=False)
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_updates(request):
    try:
        return _get_contact_payload(request, updates_only=True)
    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def mark_read_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
        telefono = normaliza_tel_mx(
            _request_value(request, "tel", "")
            or _request_value(request, "telefono", "")
        )

        if not telefono:
            return Response(
                {
                    "ok": False,
                    "error": "Falta tel.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente, expediente = _ensure_cliente_expediente(telefono, cfg=cfg)
        _touch_read(expediente, numero_asesor)

        return Response({"ok": True}, status=status.HTTP_200_OK)

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def mark_unread_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
        telefono = normaliza_tel_mx(
            _request_value(request, "tel", "")
            or _request_value(request, "telefono", "")
        )

        if not telefono:
            return Response(
                {
                    "ok": False,
                    "error": "Falta tel.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente, expediente = _ensure_cliente_expediente(telefono, cfg=cfg)
        _set_unread(expediente, numero_asesor, telefono)

        return Response({"ok": True}, status=status.HTTP_200_OK)

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_mensaje_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)

        to = normaliza_tel_mx(_request_value(request, "to", ""))
        text = str(_request_value(request, "text", "") or "").strip()

        if not to:
            return Response(
                {
                    "ok": False,
                    "error": "Falta número destino.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not text:
            return Response(
                {
                    "ok": False,
                    "error": "Falta texto.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente, expediente = _ensure_cliente_expediente(to, cfg=cfg)

        meta_response = enviar_texto_whatsapp(
            to=to,
            text=text,
            numero_asesor=numero_asesor,
        )

        msg = MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction=MensajeWhatsApp.Direccion.OUT,
            body=text,
            wa_message_id=_meta_message_id(meta_response),
            status="sent",
            raw={
                "type": "text",
                "meta": meta_response,
            },
        )

        expediente.touch_ultimo_contacto(save_now=True)

        return Response(
            {
                "ok": True,
                "meta": meta_response,
                "mensaje": _serialize_message(msg, request=request),
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_media_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)

        to = normaliza_tel_mx(_request_value(request, "to", ""))
        text = str(_request_value(request, "text", "") or "").strip()
        files = request.FILES.getlist("files")

        if not to:
            return Response(
                {
                    "ok": False,
                    "error": "Falta número destino.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente, expediente = _ensure_cliente_expediente(to, cfg=cfg)

        mensajes_creados = []

        if not files and text:
            meta_response = enviar_texto_whatsapp(
                to=to,
                text=text,
                numero_asesor=numero_asesor,
            )

            msg = MensajeWhatsApp.objects.create(
                telefono=to,
                numero_asesor=numero_asesor,
                cliente=cliente,
                direction=MensajeWhatsApp.Direccion.OUT,
                body=text,
                wa_message_id=_meta_message_id(meta_response),
                status="sent",
                raw={
                    "type": "text",
                    "meta": meta_response,
                },
            )

            mensajes_creados.append(msg)

        for index, file_obj in enumerate(files):
            media_type = _media_type_from_file(file_obj)

            upload_response = subir_media_whatsapp(
                file_obj=file_obj,
                numero_asesor=numero_asesor,
                filename=file_obj.name,
                content_type=getattr(file_obj, "content_type", ""),
            )

            media_id = upload_response.get("id")

            if not media_id:
                raise RuntimeError(f"Meta no regresó media_id: {upload_response}")

            caption = text if index == 0 else ""

            meta_response = enviar_media_whatsapp(
                to=to,
                media_id=media_id,
                media_type=media_type,
                numero_asesor=numero_asesor,
                caption=caption,
                filename=file_obj.name,
            )

            body = caption or f"[{media_type.upper()}]"

            msg = MensajeWhatsApp.objects.create(
                telefono=to,
                numero_asesor=numero_asesor,
                cliente=cliente,
                direction=MensajeWhatsApp.Direccion.OUT,
                body=body,
                wa_message_id=_meta_message_id(meta_response),
                status="sent",
                raw={
                    "type": media_type,
                    "media_type": media_type,
                    "media_id": media_id,
                    "filename": file_obj.name,
                    "mime_type": getattr(file_obj, "content_type", ""),
                    "size": getattr(file_obj, "size", 0),
                    "upload": upload_response,
                    "meta": meta_response,
                },
            )

            mensajes_creados.append(msg)

        expediente.touch_ultimo_contacto(save_now=True)

        return Response(
            {
                "ok": True,
                "mensajes": [
                    _serialize_message(item, request=request)
                    for item in mensajes_creados
                ],
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


def _inyectar_header_estatico(template_name, components):
    components = list(components or [])

    ui = WHATSAPP_TEMPLATE_UI.get(template_name, {}) if isinstance(WHATSAPP_TEMPLATE_UI, dict) else {}
    header = ui.get("header") or {}

    if not header:
        return components

    ya_tiene_header = any(
        str(component.get("type", "")).lower() == "header"
        for component in components
    )

    if ya_tiene_header:
        return components

    header_type = str(header.get("type") or "").lower()
    link = str(header.get("link") or "").strip()

    if header_type not in ("image", "document", "video") or not link:
        return components

    return [
        {
            "type": "header",
            "parameters": [
                {
                    "type": header_type,
                    header_type: {
                        "link": link,
                    },
                }
            ],
        },
        *components,
    ]


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_plantilla_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)

        to = normaliza_tel_mx(_request_value(request, "to", ""))
        template_name = str(_request_value(request, "template_name", "") or "").strip()
        idioma = str(_request_value(request, "idioma", "es_MX") or "es_MX").strip()
        params = _request_value(request, "params", None)
        components = _request_value(request, "components", None)

        if not to:
            return Response(
                {
                    "ok": False,
                    "error": "Falta número destino.",
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

        if components:
            components = _inyectar_header_estatico(template_name, components)

        cliente, expediente = _ensure_cliente_expediente(to, cfg=cfg)

        meta_response = enviar_template_whatsapp(
            to=to,
            template_name=template_name,
            numero_asesor=numero_asesor,
            params=params,
            idioma=idioma,
            components=components,
        )

        body = f"Plantilla: {template_name}"

        msg = MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction=MensajeWhatsApp.Direccion.OUT,
            body=body,
            wa_message_id=_meta_message_id(meta_response),
            status="sent",
            raw={
                "type": "template",
                "template_name": template_name,
                "idioma": idioma,
                "params": params or [],
                "components": components or [],
                "meta": meta_response,
            },
        )

        expediente.touch_ultimo_contacto(save_now=True)

        return Response(
            {
                "ok": True,
                "meta": meta_response,
                "mensaje": _serialize_message(msg, request=request),
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["PATCH"])
@permission_classes([AllowAny])
def editar_mensaje_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)

        to = normaliza_tel_mx(_request_value(request, "to", ""))
        message_id = str(_request_value(request, "message_id", "") or "").strip()
        text = str(_request_value(request, "text", "") or "").strip()

        if not to or not message_id or not text:
            return Response(
                {
                    "ok": False,
                    "error": "Faltan datos para editar/enviar contexto.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente, expediente = _ensure_cliente_expediente(to, cfg=cfg)

        meta_response = editar_texto_whatsapp(
            to=to,
            original_message_id=message_id,
            new_text=text,
            numero_asesor=numero_asesor,
        )

        msg = MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction=MensajeWhatsApp.Direccion.OUT,
            body=text,
            wa_message_id=_meta_message_id(meta_response),
            status="sent",
            raw={
                "type": "text",
                "edited_from": message_id,
                "meta": meta_response,
            },
        )

        expediente.touch_ultimo_contacto(save_now=True)

        return Response(
            {
                "ok": True,
                "meta": meta_response,
                "mensaje": _serialize_message(msg, request=request),
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def plantillas_whatsapp_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)

        items = obtener_templates_whatsapp(numero_asesor=numero_asesor)

        return Response(
            {
                "ok": True,
                "items": items,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "items": [],
                "error": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def campanas_meta_recientes(request):
    try:
        rows = (
            MapeoFuenteMeta.objects
            .exclude(nombre_campana="")
            .values("nombre_campana")
            .distinct()
            .order_by("nombre_campana")[:300]
        )

        items = [
            {
                "value": row["nombre_campana"],
                "label": row["nombre_campana"],
                "nombre": row["nombre_campana"],
            }
            for row in rows
        ]

        return Response(
            {
                "ok": True,
                "items": items,
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        return Response(
            {
                "ok": True,
                "items": [],
            },
            status=status.HTTP_200_OK,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def media_proxy_view(request, media_id):
    try:
        cfg, numero_asesor = _get_cfg_request(request)

        content, content_type = download_media_whatsapp(
            media_id=media_id,
            numero_asesor=numero_asesor,
        )

        response = HttpResponse(content, content_type=content_type)
        response["Cache-Control"] = "private, max-age=3600"

        return response

    except Exception as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )


@csrf_exempt
def webhook(request):
    if request.method == "GET":
        challenge = request.GET.get("hub.challenge", "")

        if challenge:
            return HttpResponse(challenge, content_type="text/plain")

        return HttpResponse("Webhook Volvo activo.")

    if request.method != "POST":
        return HttpResponse("Método no permitido.", status=405)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return HttpResponse("JSON inválido.", status=400)

    entries = payload.get("entry") or []

    for entry in entries:
        changes = entry.get("changes") or []

        for change in changes:
            value = change.get("value") or {}

            numero_asesor = obtener_numero_asesor_desde_webhook_value(value)

            if not numero_asesor:
                continue

            try:
                cfg = obtener_config_linea(numero_asesor=numero_asesor)
            except Exception:
                continue

            messages = value.get("messages") or []

            for message in messages:
                telefono = normaliza_tel_mx(message.get("from", ""))

                if not telefono:
                    continue

                wa_message_id = str(message.get("id") or "").strip()
                body = obtener_mensaje_whatsapp(message)

                try:
                    cliente, expediente = _ensure_cliente_expediente(
                        telefono,
                        cfg=cfg,
                    )
                except Exception:
                    continue

                if wa_message_id:
                    msg, created = MensajeWhatsApp.objects.update_or_create(
                        wa_message_id=wa_message_id,
                        defaults={
                            "telefono": telefono,
                            "numero_asesor": numero_asesor,
                            "cliente": cliente,
                            "direction": MensajeWhatsApp.Direccion.IN,
                            "body": body,
                            "status": "received",
                            "raw": {
                                "message": message,
                                "webhook_value": value,
                            },
                        },
                    )
                else:
                    msg = MensajeWhatsApp.objects.create(
                        telefono=telefono,
                        numero_asesor=numero_asesor,
                        cliente=cliente,
                        direction=MensajeWhatsApp.Direccion.IN,
                        body=body,
                        status="received",
                        raw={
                            "message": message,
                            "webhook_value": value,
                        },
                    )

                expediente.touch_ultimo_contacto(save_now=True)

            statuses = value.get("statuses") or []

            for status_item in statuses:
                wa_message_id = str(status_item.get("id") or "").strip()
                status_value = str(status_item.get("status") or "").strip()

                if not wa_message_id or not status_value:
                    continue

                qs = MensajeWhatsApp.objects.filter(wa_message_id=wa_message_id)

                for msg in qs:
                    raw = msg.raw or {}
                    raw["last_status"] = status_item

                    msg.status = status_value
                    msg.raw = raw
                    msg.save(update_fields=["status", "raw"])

    return HttpResponse("ok")