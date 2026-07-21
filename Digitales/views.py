#volvo
# Digitales/views.py
import json
import logging
from datetime import timedelta
import mimetypes
import threading
import traceback

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Max, Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from citas.models import ClienteComercial, normaliza_tel_mx
from usuarios.authentication import SignedUserAuthentication

from .models import CampanaMeta, ExpedienteDigital, LecturaWhatsApp, MensajeWhatsApp
from .serializers import ProspectoSerializer, WhatsAppMessageSerializer
from .contacto import (
    MetaAPIError,
    MetaMediaError,
    download_media_whatsapp,
    editar_texto_whatsapp,
    enviar_media_whatsapp,
    enviar_template_whatsapp,
    enviar_texto_whatsapp,
    obtener_config_linea,
    obtener_mensaje_whatsapp,
    obtener_numero_asesor_desde_webhook_value,
    obtener_templates_whatsapp,
    replace_start,
    subir_media_whatsapp,
)
from .atribucion_meta import aplicar_pauta_desde_referencia_meta
from .IA import responder_mensaje_automatico
from .ia_config import obtener_estado_ia_conversacion

from .plantillas_meta import (
    REGLAS_UTILITY,
    analizar_estructura_plantilla,
    crear_plantilla_meta,
    editar_plantilla_meta,
    eliminar_plantilla_meta,
    listar_plantillas_meta,
)

try:
    from .sett import WHATSAPP_LINES, token as VERIFY_TOKEN
except Exception:
    WHATSAPP_LINES = {}
    VERIFY_TOKEN = "PBAR&RVOLVO"

logger = logging.getLogger(__name__)


class ProspectosViewSet(viewsets.ModelViewSet):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = ProspectoSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = (
            ExpedienteDigital.objects
            .select_related("cliente")
            .all()
            .order_by("-ultimo_contacto_at", "-primer_contacto_at", "-actualizado", "-creado")
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
                | Q(motivo_descalificacion__icontains=search)
                | Q(auto_interes__icontains=search)
                | Q(buro_estado__icontains=search)
                | Q(forma_pago__icontains=search)
                | Q(tipo_cliente__icontains=search)
                | Q(plazo_compra__icontains=search)
                | Q(uso_vehiculo__icontains=search)
                | Q(comprobacion_ingresos__icontains=search)
                | Q(id_cotizacion__icontains=search)
                | Q(folio_solicitud_credito__icontains=search)
                | Q(solicitud_credito_estado__icontains=search)
                | Q(vin_facturado__icontains=search)
                | Q(vin_estatus_entrega__icontains=search)
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


# ── Helpers de fechas compatibles con USE_TZ=False ───────────────────────────

def _safe_local_dt(dt):
    if not dt:
        return None

    if settings.USE_TZ and timezone.is_aware(dt):
        return timezone.localtime(dt)

    return dt


def _parse_dt_param(value: str):
    value = (value or "").strip()
    if not value:
        return None

    dt = parse_datetime(value)
    if not dt:
        return None

    if settings.USE_TZ:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    if timezone.is_aware(dt):
        return timezone.make_naive(dt, timezone.get_current_timezone())

    return dt


def _format_time(dt):
    dt = _safe_local_dt(dt)
    if not dt:
        return ""
    return dt.strftime("%H:%M")


def _iso_or_none(dt):
    if not dt:
        return None
    return dt.isoformat()


# ── Helpers de request/configuración ─────────────────────────────────────────

def _request_value(request, key: str, default=""):
    if hasattr(request, "query_params"):
        value = request.query_params.get(key, None)
        if value is not None:
            return value

    data = getattr(request, "data", {}) or {}
    if isinstance(data, dict):
        return data.get(key, default)

    return default


def _primer_numero_asesor():
    return next(iter(WHATSAPP_LINES.keys()), "")


def _usuario_es_admin_request(request) -> bool:
    user = getattr(request, "user", None)
    rol = getattr(user, "rol", None) if user else None
    nombre_rol = str(
        getattr(rol, "nombre", "")
        or (rol if isinstance(rol, str) else "")
        or ""
    ).strip().lower()
    return nombre_rol in ("administrador", "admin")


def _numero_usuario_request(request) -> str:
    user = getattr(request, "user", None)
    numero = normaliza_tel_mx(getattr(user, "telefono", "") or "") if user else ""
    return numero if numero in WHATSAPP_LINES else ""


def _get_cfg_request(request):
    numero_param = normaliza_tel_mx(_request_value(request, "numero_asesor", "") or "")
    numero_param = numero_param if numero_param in WHATSAPP_LINES else ""
    numero_usuario = _numero_usuario_request(request)

    if _usuario_es_admin_request(request):
        numero_asesor = numero_param or numero_usuario or _primer_numero_asesor()
    else:
        numero_asesor = numero_usuario

        # Compatibilidad temporal mientras Volvo conserva una sola línea.
        if not numero_asesor and len(WHATSAPP_LINES) == 1:
            numero_asesor = numero_param or _primer_numero_asesor()

    if not numero_asesor:
        raise ValueError(
            "El usuario no tiene una línea de WhatsApp válida asignada en usuarios_volvo."
        )

    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    return cfg, cfg["numero_asesor"]


def _int_param(request, name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(_request_value(request, name, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(value, max_value))


def _meta_message_id(meta_response):
    try:
        return str((meta_response.get("messages") or [{}])[0].get("id") or "")
    except Exception:
        return ""


def _media_type_from_file(file_obj):
    content_type = str(getattr(file_obj, "content_type", "") or "").lower()

    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"

    guessed = mimetypes.guess_type(getattr(file_obj, "name", "") or "")[0] or ""
    if guessed.startswith("image/"):
        return "image"
    if guessed.startswith("video/"):
        return "video"
    if guessed.startswith("audio/"):
        return "audio"

    return "document"


# ── Helpers de negocio WhatsApp ──────────────────────────────────────────────

def _get_or_create_cliente_y_expediente(*, tel: str, profile_name: str = "", numero_asesor: str = ""):
    tel = normaliza_tel_mx(tel)
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not tel:
        return None, None

    cliente, _ = ClienteComercial.objects.get_or_create(
        telefono=tel,
        defaults={"nombre": (profile_name or "Prospecto").strip()},
    )

    if profile_name and not (cliente.nombre or "").strip():
        cliente.nombre = profile_name.strip()
        cliente.save(update_fields=["nombre", "actualizado_en"])

    cfg_linea = WHATSAPP_LINES.get(numero_asesor, {})
    defaults = {
        "agencia": (cfg_linea.get("agencia") or "").strip(),
        "business": (cfg_linea.get("business") or "").strip(),
        "canal_contacto": "WhatsApp",
        "estado": "Contactado",
        "asesor_digital": (cfg_linea.get("asesor_digital") or "").strip(),
    }

    exp, creado = ExpedienteDigital.objects.get_or_create(
        cliente=cliente,
        defaults=defaults,
    )

    # Estos valores solamente sirven para inicializar un expediente nuevo.
    # Si el usuario ya modificó el canal, agencia, business, estado o asesor
    # desde el CRM, abrir el chat no debe volver a sobrescribir esos cambios.
    cambios = []

    if not creado:
        for field, value in defaults.items():
            valor_actual = str(getattr(exp, field, "") or "").strip()
            valor_default = str(value or "").strip()

            if valor_default and not valor_actual:
                setattr(exp, field, valor_default)
                cambios.append(field)

    if cambios:
        cambios.append("actualizado")
        exp.save(update_fields=list(dict.fromkeys(cambios)))

    return cliente, exp


def _get_or_create_lectura(exp: ExpedienteDigital, numero_asesor: str) -> LecturaWhatsApp:
    lectura, _ = LecturaWhatsApp.objects.get_or_create(
        expediente=exp,
        numero_asesor=normaliza_tel_mx(numero_asesor),
    )
    return lectura


def _mark_read_exp(exp: ExpedienteDigital, numero_asesor: str, when=None):
    when = when or timezone.now()
    exp.last_read_at = when
    exp.save(update_fields=["last_read_at", "actualizado"])

    lectura = _get_or_create_lectura(exp, numero_asesor)
    lectura.last_read_at = when
    lectura.save(update_fields=["last_read_at", "updated_at"])


def _mark_unread_exp(exp: ExpedienteDigital, numero_asesor: str):
    ultimo_entrante = (
        MensajeWhatsApp.objects
        .filter(
            telefono=exp.cliente.telefono,
            numero_asesor=normaliza_tel_mx(numero_asesor),
            direction=MensajeWhatsApp.Direccion.IN,
        )
        .order_by("-created_at", "-id")
        .first()
    )

    when = None
    if ultimo_entrante and ultimo_entrante.created_at:
        # Con USE_TZ=False esto también queda naive, no llama localtime.
        when = ultimo_entrante.created_at - timedelta(microseconds=1)

    exp.last_read_at = when
    exp.save(update_fields=["last_read_at", "actualizado"])

    lectura = _get_or_create_lectura(exp, numero_asesor)
    lectura.last_read_at = when
    lectura.save(update_fields=["last_read_at", "updated_at"])


def _unread_count(exp: ExpedienteDigital, numero_asesor: str) -> int:
    qs = MensajeWhatsApp.objects.filter(
        telefono=exp.cliente.telefono,
        numero_asesor=normaliza_tel_mx(numero_asesor),
        direction=MensajeWhatsApp.Direccion.IN,
    )

    lectura = (
        LecturaWhatsApp.objects
        .filter(expediente=exp, numero_asesor=normaliza_tel_mx(numero_asesor))
        .first()
    )

    last_read_at = lectura.last_read_at if lectura else exp.last_read_at

    if last_read_at:
        qs = qs.filter(created_at__gt=last_read_at)

    return qs.count()


def _cache_media_meta_en_segundo_plano(*, media_id: str, numero_asesor: str):
    close_old_connections()
    try:
        download_media_whatsapp(media_id, numero_asesor=numero_asesor)
        logger.info("MEDIA CACHEADA OK | media_id=%s numero_asesor=%s", media_id, numero_asesor)
    except Exception as exc:
        logger.warning("NO SE PUDO CACHEAR MEDIA | media_id=%s numero_asesor=%s error=%s", media_id, numero_asesor, exc)
    finally:
        close_old_connections()


def _guardar_mensaje_fallido(*, to: str, numero_asesor: str, cliente=None, body: str, error, extra_raw=None):
    raw = {
        "provider": "meta",
        "numero_asesor": numero_asesor,
        "error": str(error),
        "internal_error": not isinstance(error, MetaAPIError),
    }

    if isinstance(error, MetaAPIError):
        raw["meta"] = error.to_dict()

    if extra_raw:
        raw.update(extra_raw)

    try:
        MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction=MensajeWhatsApp.Direccion.OUT,
            body=body,
            wa_message_id="",
            status="failed",
            raw=raw,
        )
    except Exception as save_error:
        logger.exception("No se pudo guardar mensaje fallido | to=%s numero_asesor=%s error=%s", to, numero_asesor, save_error)


def _response_meta_error(error: MetaAPIError, *, numero_asesor: str = "", extra=None):
    payload = {
        "ok": False,
        "error": error.meta_message,
        "retryable": error.retryable,
        "meta": error.to_dict(),
        "numero_asesor": numero_asesor,
    }
    if extra:
        payload.update(extra)

    if error.status_code == 429:
        http_status = status.HTTP_429_TOO_MANY_REQUESTS
    elif error.retryable:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif error.status_code == 400:
        http_status = status.HTTP_400_BAD_REQUEST
    else:
        http_status = status.HTTP_502_BAD_GATEWAY

    return Response(payload, status=http_status)

def _aplicar_atribucion_meta_segura(
    *,
    expediente,
    mensaje_whatsapp,
    numero_asesor,
    telefono,
    wa_id,
):
    try:
        return aplicar_pauta_desde_referencia_meta(
            expediente=expediente,
            mensaje_whatsapp=mensaje_whatsapp,
            numero_asesor=numero_asesor,
        )
    except Exception as error:
        logger.exception(
            "ERROR ATRIBUCION META VOLVO | numero_asesor=%s telefono=%s wa_id=%s error=%s",
            numero_asesor,
            telefono,
            wa_id,
            str(error),
        )

        return {
            "ok": False,
            "motivo": "error_atribucion_meta",
            "error": str(error),
        }



def _debe_responder_con_ia(numero_asesor: str, expediente=None) -> bool:
    numero_asesor = normaliza_tel_mx(numero_asesor or "")
    cfg_linea = WHATSAPP_LINES.get(numero_asesor, {})

    if not cfg_linea.get("responder_ia", False):
        return False

    estado_ia = obtener_estado_ia_conversacion(
        numero_asesor=numero_asesor,
        expediente=expediente,
    )

    if not estado_ia.get("puede_responder"):
        logger.info(
            "IA VOLVO OMITIDA | linea=%s expediente=%s bloqueos=%s",
            numero_asesor,
            getattr(expediente, "id", None),
            estado_ia.get("bloqueos", []),
        )
        return False

    return True


def _ya_existe_respuesta_ia_para_entrada(
    numero_asesor: str,
    wa_message_id_entrante: str,
) -> bool:
    numero_asesor = normaliza_tel_mx(numero_asesor or "")
    wa_message_id_entrante = str(wa_message_id_entrante or "").strip()

    if not numero_asesor or not wa_message_id_entrante:
        return False

    return MensajeWhatsApp.objects.filter(
        numero_asesor=numero_asesor,
        direction=MensajeWhatsApp.Direccion.OUT,
        raw__reply_to=wa_message_id_entrante,
    ).exists()


def _procesar_respuesta_ia_en_segundo_plano(
    *,
    wa_from: str,
    numero_asesor: str,
    profile_name: str,
    texto_usuario: str,
    wa_message_id_entrante: str,
    raw_message: dict,
):
    close_old_connections()

    try:
        if _ya_existe_respuesta_ia_para_entrada(
            numero_asesor,
            wa_message_id_entrante,
        ):
            return

        responder_mensaje_automatico(
            wa_from=wa_from,
            profile_name=profile_name,
            texto_usuario=texto_usuario,
            wa_message_id_entrante=wa_message_id_entrante,
            raw_message=raw_message,
            numero_asesor=numero_asesor,
        )
    except Exception as exc:
        logger.exception(
            "ERROR IA VOLVO | linea=%s cliente=%s wa_id=%s error=%s",
            numero_asesor,
            wa_from,
            wa_message_id_entrante,
            exc,
        )
    finally:
        close_old_connections()

# ── Vistas simples ───────────────────────────────────────────────────────────

def bienvenido(request):
    return HttpResponse("Funcionando módulo Digitales Volvo - WhatsApp activo")


def privacidad_meta_view(request):
    html = """
    <!doctype html>
    <html lang="es">
    <head><meta charset="utf-8"><title>Aviso de Privacidad - CRM Volvo</title></head>
    <body>
        <h1>Aviso de Privacidad</h1>
        <p>Automotriz R&R utiliza este CRM Volvo para gestionar prospectos y clientes contactados por canales digitales, incluido WhatsApp Business.</p>
    </body>
    </html>
    """
    return HttpResponse(html, content_type="text/html; charset=utf-8")


def eliminacion_datos_meta_view(request):
    html = """
    <!doctype html>
    <html lang="es">
    <head><meta charset="utf-8"><title>Eliminación de Datos - CRM Volvo</title></head>
    <body>
        <h1>Instrucciones para eliminación de datos</h1>
        <p>Para solicitar la eliminación de tus datos personales almacenados en el CRM, contacta al área responsable de Automotriz R&R.</p>
    </body>
    </html>
    """
    return HttpResponse(html, content_type="text/html; charset=utf-8")


# ── Webhook Cloud API ────────────────────────────────────────────────────────

@csrf_exempt
def webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode", "")
        verify_token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")

        logger.info(
            "WEBHOOK VERIFY VOLVO | mode=%s token_ok=%s challenge=%s",
            mode,
            verify_token == VERIFY_TOKEN,
            challenge,
        )

        if mode == "subscribe" and verify_token == VERIFY_TOKEN and challenge:
            return HttpResponse(challenge, content_type="text/plain")

        return HttpResponse("token incorrecto", status=403)

    if request.method != "POST":
        return HttpResponse("method not allowed", status=405)

    try:
        raw_body = request.body.decode("utf-8")
        body = json.loads(raw_body)
        logger.info("WEBHOOK RAW BODY VOLVO: %s", json.dumps(body, ensure_ascii=False))
    except Exception as exc:
        logger.exception("ERROR PARSEANDO WEBHOOK VOLVO: %s", exc)
        return HttpResponse("ok")

    try:
        entries = body.get("entry") or []

        for entry in entries:
            changes = entry.get("changes") or []

            for change in changes:
                value = change.get("value") or {}
                metadata = value.get("metadata") or {}
                numero_asesor = obtener_numero_asesor_desde_webhook_value(value)

                if not numero_asesor:
                    logger.warning(
                        "WEBHOOK VOLVO SIN MAPEO DE LINEA | phone_number_id=%s display_phone_number=%s",
                        metadata.get("phone_number_id"),
                        metadata.get("display_phone_number"),
                    )

                contacts = value.get("contacts") or []
                profile_name = ""
                if contacts:
                    profile_name = (contacts[0].get("profile") or {}).get("name", "") or ""

                messages = value.get("messages") or []

                for msg in messages:
                    wa_from = str(msg.get("from") or "").strip()
                    tel = normaliza_tel_mx(replace_start(wa_from))
                    wa_id = str(msg.get("id") or "").strip()
                    text = obtener_mensaje_whatsapp(msg)

                    logger.info(
                        "WEBHOOK MENSAJE VOLVO | from=%s tel=%s wa_id=%s type=%s text=%s",
                        wa_from,
                        tel,
                        wa_id,
                        msg.get("type"),
                        text,
                    )

                    if not tel or not wa_id:
                        logger.warning("WEBHOOK VOLVO OMITIDO SIN TEL O WA_ID | from=%s wa_id=%s", wa_from, wa_id)
                        continue

                    if not numero_asesor:
                        logger.warning("WEBHOOK VOLVO OMITIDO POR LINEA NO RESUELTA | from=%s tel=%s wa_id=%s", wa_from, tel, wa_id)
                        continue

                    cliente, expediente = _get_or_create_cliente_y_expediente(
                        tel=tel,
                        profile_name=profile_name,
                        numero_asesor=numero_asesor,
                    )

                    if not cliente or not expediente:
                        logger.warning("WEBHOOK VOLVO OMITIDO SIN CLIENTE O EXPEDIENTE | tel=%s", tel)
                        continue
                    
                    expediente.touch_mensaje_cliente(save_now=True)

                    resultado_atribucion_meta = _aplicar_atribucion_meta_segura(
                        expediente=expediente,
                        mensaje_whatsapp=msg,
                        numero_asesor=numero_asesor,
                        telefono=tel,
                        wa_id=wa_id,
                    )

                    raw_msg = dict(msg)
                    raw_msg["numero_asesor"] = numero_asesor
                    raw_msg["phone_number_id"] = metadata.get("phone_number_id", "")
                    raw_msg["display_phone_number"] = metadata.get("display_phone_number", "")
                    raw_msg["profile_name"] = profile_name
                    raw_msg["atribucion_meta"] = resultado_atribucion_meta

                    mensaje_entrante, created = MensajeWhatsApp.objects.get_or_create(
                        wa_message_id=wa_id,
                        numero_asesor=numero_asesor,
                        defaults={
                            "telefono": tel,
                            "cliente": cliente,
                            "direction": MensajeWhatsApp.Direccion.IN,
                            "body": text,
                            "status": "received",
                            "raw": raw_msg,
                        },
                    )

                    if created:
                        logger.info("WEBHOOK VOLVO MENSAJE GUARDADO | id=%s tel=%s wa_id=%s", mensaje_entrante.id, tel, wa_id)
                    else:
                        cambios = []

                        if not mensaje_entrante.cliente_id:
                            mensaje_entrante.cliente = cliente
                            cambios.append("cliente")

                        if not (mensaje_entrante.telefono or "").strip():
                            mensaje_entrante.telefono = tel
                            cambios.append("telefono")

                        if not (mensaje_entrante.body or "").strip() and text:
                            mensaje_entrante.body = text
                            cambios.append("body")

                        raw_actual = dict(mensaje_entrante.raw or {})
                        raw_actual["ultimo_webhook_payload"] = raw_msg
                        mensaje_entrante.raw = raw_actual
                        cambios.append("raw")

                        if cambios:
                            mensaje_entrante.save(update_fields=list(dict.fromkeys(cambios)))

                        logger.info("WEBHOOK VOLVO MENSAJE DUPLICADO ACTUALIZADO | id=%s tel=%s wa_id=%s", mensaje_entrante.id, tel, wa_id)

                    if created:
                        media_type = str(msg.get("type") or "").lower()
                        if media_type in ("image", "document", "video", "audio", "sticker"):
                            media_payload = msg.get(media_type) or {}
                            media_id = str(media_payload.get("id") or "").strip()

                            if media_id:
                                hilo_media = threading.Thread(
                                    target=_cache_media_meta_en_segundo_plano,
                                    kwargs={"media_id": media_id, "numero_asesor": numero_asesor},
                                    daemon=True,
                                )
                                hilo_media.start()

                    if created and _debe_responder_con_ia(numero_asesor, expediente):
                        hilo_ia = threading.Thread(
                            target=_procesar_respuesta_ia_en_segundo_plano,
                            kwargs={
                                "wa_from": wa_from,
                                "numero_asesor": numero_asesor,
                                "profile_name": profile_name,
                                "texto_usuario": text,
                                "wa_message_id_entrante": wa_id,
                                "raw_message": raw_msg,
                            },
                            daemon=True,
                        )
                        hilo_ia.start()

                statuses = value.get("statuses") or []

                for status_payload in statuses:
                    wa_id = str(status_payload.get("id") or "").strip()
                    st = str(status_payload.get("status") or "").strip()
                    errors = status_payload.get("errors") or []
                    ts = status_payload.get("timestamp")

                    if not wa_id or not st:
                        logger.warning("WEBHOOK STATUS VOLVO OMITIDO SIN ID O STATUS | payload=%s", json.dumps(status_payload, ensure_ascii=False))
                        continue

                    qs = MensajeWhatsApp.objects.filter(wa_message_id=wa_id)
                    if numero_asesor:
                        qs = qs.filter(numero_asesor=numero_asesor)

                    msg_obj = qs.order_by("-id").first()

                    if not msg_obj:
                        logger.warning("WEBHOOK STATUS VOLVO SIN MENSAJE LOCAL | wa_id=%s status=%s", wa_id, st)
                        continue

                    new_raw = dict(msg_obj.raw or {})
                    new_raw["status_payload"] = status_payload

                    if errors:
                        new_raw["errors"] = errors
                    if ts:
                        new_raw["status_timestamp"] = ts

                    msg_obj.status = st
                    msg_obj.raw = new_raw
                    msg_obj.save(update_fields=["status", "raw"])

                    logger.info("WEBHOOK STATUS VOLVO ACTUALIZADO | wa_id=%s status=%s", wa_id, st)

        return HttpResponse("ok")

    except Exception as exc:
        logger.exception("ERROR GENERAL WEBHOOK VOLVO: %s", exc)
        traceback.print_exc()
        return HttpResponse("ok")


# ── API de chats/contacto ────────────────────────────────────────────────────

@api_view(["GET"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def chats_list(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
    except Exception as exc:
        return Response({"ok": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    limit = _int_param(request, "limit", default=200, min_value=1, max_value=300)
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
            .filter(telefono=telefono, numero_asesor=numero_asesor, created_at=row["last_created"])
            .select_related("cliente")
            .order_by("-id")
            .first()
        )

        if not ultimo:
            continue

        cliente = ultimo.cliente or ClienteComercial.objects.filter(telefono=telefono).first()
        expediente = ExpedienteDigital.objects.filter(cliente=cliente).first() if cliente else None

        salida.append(
            {
                "id": expediente.id if expediente else telefono,
                "telefono": telefono,
                "nombre": (cliente.nombre if cliente else "") or "Prospecto",
                "agencia": expediente.agencia if expediente else cfg.get("agencia", ""),
                "linea": expediente.business if expediente else cfg.get("business", ""),
                "estado": expediente.estado if expediente else "",
                "unread": _unread_count(expediente, numero_asesor) if expediente else 0,
                "last_text": ultimo.body or "",
                "last_time": _format_time(ultimo.created_at),
                "last_created_at": _iso_or_none(ultimo.created_at),
                "numero_asesor": numero_asesor,
                "ia_estado": obtener_estado_ia_conversacion(numero_asesor=numero_asesor, expediente=expediente) if expediente else None,
            }
        )

    return Response(salida, status=status.HTTP_200_OK)


def _safe_raw_dict(raw):
    if isinstance(raw, dict):
        return raw

    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    return {}


def _to_int_or_none(value):
    value = str(value or "").strip()

    if not value or not value.isdigit():
        return None

    try:
        return int(value)
    except Exception:
        return None


def _campana_meta_to_dict(campana, pauta_fallback=""):
    if not campana:
        return {
            "id_campana": "",
            "sucursal": "",
            "nombre_campana": "",
            "pauta": pauta_fallback or "",
            "encontrada": False,
        }

    sucursal = str(campana.sucursal or "").strip()
    nombre_campana = str(campana.nombre_campana or "").strip()
    pauta = f"{sucursal} - {nombre_campana}".strip(" -")

    return {
        "id_campana": str(campana.id_campana or ""),
        "sucursal": sucursal,
        "nombre_campana": nombre_campana,
        "pauta": pauta or pauta_fallback or "",
        "encontrada": True,
    }


def _buscar_campana_meta_volvo_por_id(id_campana):
    id_campana_int = _to_int_or_none(id_campana)

    if id_campana_int is None:
        return None

    try:
        return (
            CampanaMeta.objects.using("sqlserver_meta")
            .filter(id_campana=id_campana_int)
            .only("id_campana", "sucursal", "nombre_campana")
            .first()
        )
    except Exception as exc:
        logger.exception(
            "ERROR BUSCANDO campana_meta_volvo en contacto | id_campana=%s | error=%s",
            id_campana,
            exc,
        )
        return None


def _buscar_campana_meta_volvo_por_pauta(pauta):
    pauta = str(pauta or "").strip()

    if not pauta:
        return None

    nombre_posible = pauta

    if " - " in pauta:
        nombre_posible = pauta.split(" - ", 1)[1].strip()

    try:
        qs = CampanaMeta.objects.using("sqlserver_meta").only(
            "id_campana",
            "sucursal",
            "nombre_campana",
        )

        campana = qs.filter(nombre_campana__iexact=nombre_posible).first()

        if campana:
            return campana

        return qs.filter(nombre_campana__icontains=nombre_posible).first()

    except Exception as exc:
        logger.exception(
            "ERROR BUSCANDO campana_meta_volvo por pauta | pauta=%s | error=%s",
            pauta,
            exc,
        )
        return None


def _extraer_id_campana_de_atribucion(raw):
    raw = _safe_raw_dict(raw)

    atribucion = raw.get("atribucion_meta") or {}

    if not isinstance(atribucion, dict):
        return ""

    return str(
        atribucion.get("id_campana")
        or atribucion.get("campaign_id")
        or ""
    ).strip()


def _obtener_campana_meta_para_contacto(*, expediente, tel, numero_asesor):
    pauta_actual = str(getattr(expediente, "pauta", "") or "").strip()

    salida_default = {
        "id_campana": "",
        "sucursal": "",
        "nombre_campana": "",
        "pauta": pauta_actual,
        "encontrada": False,
        "origen": "expediente_pauta" if pauta_actual else "",
    }

    if not expediente:
        return salida_default

    # 1. Buscar id_campana en los mensajes entrantes que tengan raw["atribucion_meta"].
    mensajes_atribucion = (
        MensajeWhatsApp.objects
        .filter(
            telefono=tel,
            numero_asesor=numero_asesor,
            direction=MensajeWhatsApp.Direccion.IN,
        )
        .exclude(raw={})
        .order_by("-created_at", "-id")[:30]
    )

    for mensaje in mensajes_atribucion:
        id_campana = _extraer_id_campana_de_atribucion(mensaje.raw)

        if not id_campana:
            continue

        campana = _buscar_campana_meta_volvo_por_id(id_campana)

        if campana:
            data = _campana_meta_to_dict(campana, pauta_fallback=pauta_actual)
            data["origen"] = "mensaje_raw_atribucion_meta"
            return data

    # 2. Fallback: si ya tienes expediente.pauta, buscarla contra campanas_meta_volvo.
    campana_por_pauta = _buscar_campana_meta_volvo_por_pauta(pauta_actual)

    if campana_por_pauta:
        data = _campana_meta_to_dict(campana_por_pauta, pauta_fallback=pauta_actual)
        data["origen"] = "expediente_pauta_match"
        return data

    return salida_default


def _obtener_origen_preview_para_contacto(*, expediente, tel, numero_asesor):
    """
    Recupera la referencia del anuncio desde los primeros mensajes entrantes.

    Esto evita depender de que el mensaje original esté incluido en la página
    actual del historial. No realiza llamadas a Meta: usa únicamente el raw que
    ya quedó almacenado por el webhook.
    """
    if not expediente:
        return None

    serializer = WhatsAppMessageSerializer()

    mensajes_iniciales = (
        MensajeWhatsApp.objects
        .filter(
            telefono=tel,
            numero_asesor=numero_asesor,
            direction=MensajeWhatsApp.Direccion.IN,
        )
        .only("id", "wa_message_id", "direction", "raw", "created_at")
        .order_by("created_at", "id")[:40]
    )

    for mensaje in mensajes_iniciales:
        preview = serializer.get_origin_preview(mensaje)

        if not preview:
            continue

        return {
            **preview,
            "message_id": mensaje.wa_message_id or str(mensaje.id),
            "created_at": mensaje.created_at.isoformat() if mensaje.created_at else None,
        }

    return None

@api_view(["GET"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def contacto_por_telefono(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
        tel = normaliza_tel_mx(request.query_params.get("tel", ""))

        if not tel:
            return Response(
                {"ok": False, "error": "Falta tel o teléfono inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        limit = _int_param(request, "limit", default=50, min_value=1, max_value=100)
        before_id = str(request.query_params.get("before_id") or "").strip()

        mark_read_raw = str(request.query_params.get("mark_read", "1")).strip().lower()
        mark_read = mark_read_raw not in ("0", "false", "no", "off")

        cliente, expediente = _get_or_create_cliente_y_expediente(
            tel=tel,
            numero_asesor=numero_asesor,
        )

        # Query base sin select_related.
        # Esta se usa para buscar referencias ligeras.
        base_qs = MensajeWhatsApp.objects.filter(
            telefono=tel,
            numero_asesor=numero_asesor,
        )

        # Query completa para serializar mensajes.
        # Aquí sí conviene traer cliente para evitar consultas extra.
        qs = base_qs.select_related("cliente")

        if before_id:
            ref = None

            if before_id.isdigit():
                ref = (
                    base_qs
                    .filter(id=int(before_id))
                    .only("id", "created_at")
                    .first()
                )

            if not ref:
                ref = (
                    base_qs
                    .filter(wa_message_id=before_id)
                    .only("id", "created_at")
                    .first()
                )

            if ref:
                qs = qs.filter(
                    Q(created_at__lt=ref.created_at)
                    | Q(created_at=ref.created_at, id__lt=ref.id)
                )
            else:
                qs = qs.none()

        mensajes_desc = list(qs.order_by("-created_at", "-id")[: limit + 1])

        has_more = len(mensajes_desc) > limit
        mensajes_desc = mensajes_desc[:limit]

        mensajes = list(reversed(mensajes_desc))

        if expediente and not before_id and mark_read:
            _mark_read_exp(expediente, numero_asesor)

        serialized = WhatsAppMessageSerializer(
            mensajes,
            many=True,
            context={"request": request},
        ).data

        prospecto_data = ProspectoSerializer(expediente).data if expediente else None

        if prospecto_data is not None:
            campana_meta = _obtener_campana_meta_para_contacto(
                expediente=expediente,
                tel=tel,
                numero_asesor=numero_asesor,
            )

            prospecto_data["campana_meta"] = campana_meta
            prospecto_data["campana_meta_nombre"] = campana_meta.get("nombre_campana") or ""
            prospecto_data["campana_meta_sucursal"] = campana_meta.get("sucursal") or ""
            prospecto_data["campana_meta_id"] = campana_meta.get("id_campana") or ""

            origen_preview = _obtener_origen_preview_para_contacto(
                expediente=expediente,
                tel=tel,
                numero_asesor=numero_asesor,
            )
            prospecto_data["origen_preview"] = origen_preview

            if campana_meta.get("pauta") and not prospecto_data.get("pauta"):
                prospecto_data["pauta"] = campana_meta.get("pauta")

        return Response(
            {
                "ok": True,
                "numero_asesor_activo": numero_asesor,
                "ia_estado": obtener_estado_ia_conversacion(tel=tel, numero_asesor=numero_asesor, expediente=expediente),
                "prospecto": prospecto_data,
                "mensajes": serialized,
                "messages": serialized,
                "paginacion": {
                    "limit": limit,
                    "has_more": has_more,
                    "oldest_id": serialized[0]["id"] if serialized else None,
                    "newest_id": serialized[-1]["id"] if serialized else None,
                    "oldest_created_at": serialized[0]["created_at"] if serialized else None,
                    "newest_created_at": serialized[-1]["created_at"] if serialized else None,
                    "before_id": serialized[0]["id"] if serialized else None,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        logger.exception("ERROR CONTACTO VOLVO | error=%s", exc)
        return Response(
            {"ok": False, "error": str(exc), "endpoint": "contacto"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["GET"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def contacto_updates(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
        tel = normaliza_tel_mx(request.query_params.get("tel", ""))

        if not tel:
            return Response(
                {"ok": False, "error": "Falta tel o teléfono inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        limit = _int_param(request, "limit", default=50, min_value=1, max_value=100)
        after = str(request.query_params.get("after") or "").strip()
        after_id = str(request.query_params.get("after_id") or "").strip()

        # Query base sin select_related.
        # Se usa para buscar referencias con only().
        base_qs = MensajeWhatsApp.objects.filter(
            telefono=tel,
            numero_asesor=numero_asesor,
        )

        # Query completa para serializar.
        qs = base_qs.select_related("cliente")

        if after_id:
            ref = None

            if after_id.isdigit():
                ref = (
                    base_qs
                    .filter(id=int(after_id))
                    .only("id", "created_at")
                    .first()
                )

            if not ref:
                ref = (
                    base_qs
                    .filter(wa_message_id=after_id)
                    .only("id", "created_at")
                    .first()
                )

            if ref:
                qs = qs.filter(
                    Q(created_at__gt=ref.created_at)
                    | Q(created_at=ref.created_at, id__gt=ref.id)
                )
            else:
                qs = qs.none()
        else:
            after_dt = _parse_dt_param(after)

            if after_dt:
                qs = qs.filter(created_at__gt=after_dt)
            else:
                qs = qs.none()

        mensajes = list(qs.order_by("created_at", "id")[:limit])

        serialized = WhatsAppMessageSerializer(
            mensajes,
            many=True,
            context={"request": request},
        ).data

        return Response(
            {
                "ok": True,
                "numero_asesor_activo": numero_asesor,
                "mensajes": serialized,
                "messages": serialized,
                "server_now": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        logger.exception("ERROR CONTACTO UPDATES VOLVO | error=%s", exc)
        return Response(
            {"ok": False, "error": str(exc), "endpoint": "contacto_updates"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def mark_read_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
        tel = normaliza_tel_mx(_request_value(request, "tel", "") or _request_value(request, "telefono", ""))

        if not tel:
            return Response({"ok": False, "error": "Falta tel."}, status=status.HTTP_400_BAD_REQUEST)

        cliente, expediente = _get_or_create_cliente_y_expediente(tel=tel, numero_asesor=numero_asesor)
        _mark_read_exp(expediente, numero_asesor)

        return Response({"ok": True}, status=status.HTTP_200_OK)

    except Exception as exc:
        logger.exception("ERROR MARK READ VOLVO | error=%s", exc)
        return Response({"ok": False, "error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def mark_unread_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
        tel = normaliza_tel_mx(_request_value(request, "tel", "") or _request_value(request, "telefono", ""))

        if not tel:
            return Response({"ok": False, "error": "Falta tel."}, status=status.HTTP_400_BAD_REQUEST)

        cliente, expediente = _get_or_create_cliente_y_expediente(tel=tel, numero_asesor=numero_asesor)
        _mark_unread_exp(expediente, numero_asesor)

        return Response({"ok": True}, status=status.HTTP_200_OK)

    except Exception as exc:
        logger.exception("ERROR MARK UNREAD VOLVO | error=%s", exc)
        return Response({"ok": False, "error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Envíos WhatsApp ──────────────────────────────────────────────────────────

@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@parser_classes([JSONParser])
@permission_classes([IsAuthenticated])
def enviar_mensaje_view(request):
    numero_asesor = ""
    to = ""
    text = ""
    cliente = None

    try:
        cfg, numero_asesor = _get_cfg_request(request)
        to = normaliza_tel_mx(_request_value(request, "to", ""))
        text = str(_request_value(request, "text", "") or "").strip()
        reply_to_message_id = str(_request_value(request, "reply_to_message_id", "") or "").strip()

        if not to:
            return Response({"ok": False, "error": "Falta número destino."}, status=status.HTTP_400_BAD_REQUEST)
        if not text:
            return Response({"ok": False, "error": "Falta texto."}, status=status.HTTP_400_BAD_REQUEST)

        cliente, expediente = _get_or_create_cliente_y_expediente(tel=to, numero_asesor=numero_asesor)
        expediente.touch_ultimo_contacto(save_now=True)

        meta_response = enviar_texto_whatsapp(
            to=to,
            text=text,
            numero_asesor=numero_asesor,
            reply_to_message_id=reply_to_message_id,
        )

        msg = MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction=MensajeWhatsApp.Direccion.OUT,
            body=text,
            wa_message_id=_meta_message_id(meta_response),
            status="accepted",
            raw={
                "provider": "meta",
                "type": "text",
                "send": meta_response,
                "numero_asesor": numero_asesor,
                "origen": "asesor_humano",
                "reply_to": reply_to_message_id,
            },
        )

        return Response(
            {
                "ok": True,
                "data": meta_response,
                "meta": meta_response,
                "wa_message_id": msg.wa_message_id,
                "numero_asesor": numero_asesor,
                "mensaje": WhatsAppMessageSerializer(msg, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )

    except MetaAPIError as exc:
        _guardar_mensaje_fallido(to=to, numero_asesor=numero_asesor, cliente=cliente, body=text, error=exc, extra_raw={"request_type": "text"})
        return _response_meta_error(exc, numero_asesor=numero_asesor, extra={"tipo": "text", "to": to})

    except Exception as exc:
        logger.exception("ERROR ENVIAR MENSAJE VOLVO | to=%s numero_asesor=%s error=%s", to, numero_asesor, exc)
        _guardar_mensaje_fallido(to=to, numero_asesor=numero_asesor, cliente=cliente, body=text, error=exc, extra_raw={"request_type": "text"})
        return Response({"ok": False, "error": str(exc), "numero_asesor": numero_asesor}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def enviar_media_view(request):
    numero_asesor = ""
    to = ""
    text = ""
    cliente = None

    try:
        cfg, numero_asesor = _get_cfg_request(request)
        to = normaliza_tel_mx(_request_value(request, "to", ""))
        text = str(_request_value(request, "text", "") or "").strip()
        reply_to_message_id = str(_request_value(request, "reply_to_message_id", "") or "").strip()
        files = request.FILES.getlist("files")

        if not to:
            return Response({"ok": False, "error": "Falta número destino."}, status=status.HTTP_400_BAD_REQUEST)
        if not files and not text:
            return Response({"ok": False, "error": "Falta texto o archivo."}, status=status.HTTP_400_BAD_REQUEST)

        cliente, expediente = _get_or_create_cliente_y_expediente(tel=to, numero_asesor=numero_asesor)
        expediente.touch_ultimo_contacto(save_now=True)

        mensajes_creados = []

        if not files and text:
            meta_response = enviar_texto_whatsapp(
                to=to,
                text=text,
                numero_asesor=numero_asesor,
                reply_to_message_id=reply_to_message_id,
            )

            msg = MensajeWhatsApp.objects.create(
                telefono=to,
                numero_asesor=numero_asesor,
                cliente=cliente,
                direction=MensajeWhatsApp.Direccion.OUT,
                body=text,
                wa_message_id=_meta_message_id(meta_response),
                status="accepted",
                raw={
                    "provider": "meta",
                    "type": "text",
                    "send": meta_response,
                    "reply_to": reply_to_message_id,
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
                reply_to_message_id=reply_to_message_id,
            )

            body = caption or f"[{media_type.upper()}]"
            msg = MensajeWhatsApp.objects.create(
                telefono=to,
                numero_asesor=numero_asesor,
                cliente=cliente,
                direction=MensajeWhatsApp.Direccion.OUT,
                body=body,
                wa_message_id=_meta_message_id(meta_response),
                status="accepted",
                raw={
                    "provider": "meta",
                    "type": media_type,
                    "meta_type": media_type,
                    "media_type": media_type,
                    "media_id": media_id,
                    "filename": file_obj.name,
                    "mime_type": getattr(file_obj, "content_type", ""),
                    "content_type": getattr(file_obj, "content_type", ""),
                    "size": getattr(file_obj, "size", 0),
                    "meta_upload": upload_response,
                    "upload": upload_response,
                    "send": meta_response,
                    "reply_to": reply_to_message_id,
                },
            )
            mensajes_creados.append(msg)

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "mensajes": WhatsAppMessageSerializer(mensajes_creados, many=True, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )

    except MetaAPIError as exc:
        _guardar_mensaje_fallido(to=to, numero_asesor=numero_asesor, cliente=cliente, body=text, error=exc, extra_raw={"request_type": "media"})
        return _response_meta_error(exc, numero_asesor=numero_asesor, extra={"tipo": "media", "to": to})

    except Exception as exc:
        logger.exception("ERROR ENVIAR MEDIA VOLVO | to=%s numero_asesor=%s error=%s", to, numero_asesor, exc)
        _guardar_mensaje_fallido(to=to, numero_asesor=numero_asesor, cliente=cliente, body=text or "[MEDIA]", error=exc, extra_raw={"request_type": "media"})
        return Response({"ok": False, "error": str(exc), "numero_asesor": numero_asesor}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@parser_classes([JSONParser])
@permission_classes([IsAuthenticated])
def enviar_plantilla_view(request):
    numero_asesor = ""
    to = ""
    template_name = ""
    cliente = None
    preview_text = ""

    try:
        cfg, numero_asesor = _get_cfg_request(request)

        to = normaliza_tel_mx(_request_value(request, "to", ""))
        template_name = str(_request_value(request, "template_name", "") or "").strip()
        idioma = str(_request_value(request, "idioma", "es_MX") or "es_MX").strip()
        params = _request_value(request, "params", None)
        components = _request_value(request, "components", None)
        preview_text = str(_request_value(request, "preview_text", "") or "").strip()

        if not to:
            return Response(
                {"ok": False, "error": "Falta número destino."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not template_name:
            return Response(
                {"ok": False, "error": "Falta template_name."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if params is None:
            params = []

        if not isinstance(params, list):
            return Response(
                {"ok": False, "error": "params debe ser una lista."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if components is not None and not isinstance(components, list):
            return Response(
                {"ok": False, "error": "components debe ser una lista."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente, expediente = _get_or_create_cliente_y_expediente(
            tel=to,
            numero_asesor=numero_asesor,
        )

        expediente.touch_ultimo_contacto(save_now=True)

        meta_response = enviar_template_whatsapp(
            to=to,
            template_name=template_name,
            numero_asesor=numero_asesor,
            params=params,
            idioma=idioma,
            components=components,
        )

        # Esto es lo que se mostrará en el chat.
        # Si el front manda preview_text, guardamos el mensaje completo.
        # Si por alguna razón no llega, dejamos el marcador como respaldo.
        body = preview_text or f"[TEMPLATE:{template_name}]"

        if not preview_text and params:
            body = f"{body} " + " | ".join(str(item) for item in params)

        msg = MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction=MensajeWhatsApp.Direccion.OUT,
            body=body,
            wa_message_id=_meta_message_id(meta_response),
            status="accepted",
            raw={
                "provider": "meta",
                "type": "template",
                "template_name": template_name,
                "idioma": idioma,
                "params": params,
                "components": components or [],
                "preview_text": preview_text,
                "template_preview": preview_text,
                "send": meta_response,
            },
        )

        return Response(
            {
                "ok": True,
                "meta": meta_response,
                "wa_message_id": msg.wa_message_id,
                "numero_asesor": numero_asesor,
                "mensaje": WhatsAppMessageSerializer(
                    msg,
                    context={"request": request},
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    except MetaAPIError as exc:
        body_error = preview_text or f"[TEMPLATE:{template_name}]"

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=body_error,
            error=exc,
            extra_raw={
                "request_type": "template",
                "template_name": template_name,
                "preview_text": preview_text,
            },
        )

        return _response_meta_error(
            exc,
            numero_asesor=numero_asesor,
            extra={"tipo": "template", "to": to},
        )

    except Exception as exc:
        logger.exception(
            "ERROR ENVIAR PLANTILLA VOLVO | to=%s numero_asesor=%s error=%s",
            to,
            numero_asesor,
            exc,
        )

        body_error = preview_text or f"[TEMPLATE:{template_name}]"

        _guardar_mensaje_fallido(
            to=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            body=body_error,
            error=exc,
            extra_raw={
                "request_type": "template",
                "template_name": template_name,
                "preview_text": preview_text,
            },
        )

        return Response(
            {
                "ok": False,
                "error": str(exc),
                "numero_asesor": numero_asesor,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

@api_view(["PATCH", "POST"])
@authentication_classes([SignedUserAuthentication])
@parser_classes([JSONParser])
@permission_classes([IsAuthenticated])
def editar_mensaje_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)
        to = normaliza_tel_mx(_request_value(request, "to", ""))
        message_id = str(_request_value(request, "message_id", "") or "").strip()
        text = str(_request_value(request, "text", "") or "").strip()

        if not to or not message_id or not text:
            return Response({"ok": False, "error": "Falta to, message_id o text."}, status=status.HTTP_400_BAD_REQUEST)

        meta_response = editar_texto_whatsapp(
            to=to,
            original_message_id=message_id,
            new_text=text,
            numero_asesor=numero_asesor,
        )

        msg = (
            MensajeWhatsApp.objects
            .filter(telefono=to, numero_asesor=numero_asesor, wa_message_id=message_id, direction=MensajeWhatsApp.Direccion.OUT)
            .order_by("-id")
            .first()
        )

        if msg:
            raw = dict(msg.raw or {})
            raw["edit"] = {"text": text, "meta": meta_response}
            msg.body = text
            msg.raw = raw
            msg.save(update_fields=["body", "raw"])

        return Response({"ok": True, "meta": meta_response}, status=status.HTTP_200_OK)

    except MetaAPIError as exc:
        return _response_meta_error(exc, numero_asesor=locals().get("numero_asesor", ""), extra={"tipo": "edit"})
    except Exception as exc:
        logger.exception("ERROR EDITAR MENSAJE VOLVO | error=%s", exc)
        return Response({"ok": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ── Media, plantillas y campañas ─────────────────────────────────────────────

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def media_proxy_view(request, media_id: str):
    numero_asesor = normaliza_tel_mx(request.query_params.get("numero_asesor", ""))

    try:
        blob, content_type = download_media_whatsapp(media_id, numero_asesor=numero_asesor)
        response = HttpResponse(blob, content_type=content_type)
        response["Cache-Control"] = "private, max-age=86400"
        return response

    except MetaMediaError as exc:
        logger.warning("MEDIA META VOLVO NO DISPONIBLE | media_id=%s numero_asesor=%s error=%s", media_id, numero_asesor, exc.to_dict())
        status_code = 410 if exc.es_media_no_disponible() else 502
        return Response(
            {
                "ok": False,
                "error": "El archivo ya no está disponible en Meta o no pertenece a esta línea.",
                "meta": exc.to_dict(),
            },
            status=status_code,
        )

    except Exception as exc:
        logger.exception("ERROR MEDIA PROXY VOLVO | media_id=%s numero_asesor=%s error=%s", media_id, numero_asesor, exc)
        return Response({"ok": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def plantillas_whatsapp_view(request):
    try:
        cfg, numero_asesor = _get_cfg_request(request)

        items = obtener_templates_whatsapp(numero_asesor=numero_asesor)

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "waba_id": cfg.get("waba_id", ""),
                "phone_number_id": cfg.get("phone_number_id", ""),
                "total": len(items),
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
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def campanas_meta_recientes(request):
    try:
        try:
            days = int(request.query_params.get("days", "180"))
        except (TypeError, ValueError):
            days = 180

        days = max(1, min(days, 730))
        desde = timezone.now().date() - timedelta(days=days)

        qs_recientes = (
            CampanaMeta.objects.using("sqlserver_meta")
            .filter(
                Q(inicio_campana__gte=desde)
                | Q(fin_campana__gte=desde)
                | Q(fin_campana__isnull=True)
            )
            .order_by("-inicio_campana", "-fin_campana", "sucursal", "nombre_campana")
        )

        qs = qs_recientes

        if not qs_recientes.exists():
            qs = (
                CampanaMeta.objects.using("sqlserver_meta")
                .all()
                .order_by("-inicio_campana", "-fin_campana", "sucursal", "nombre_campana")
            )

        vistos = set()
        items = []

        for campana in qs[:700]:
            sucursal = str(campana.sucursal or "").strip()
            nombre_campana = str(campana.nombre_campana or "").strip()

            label = f"{sucursal} - {nombre_campana}".strip(" -")

            if not label:
                continue

            key = label.lower()

            if key in vistos:
                continue

            vistos.add(key)

            items.append({
                "value": label,
                "label": label,
                "id_campana": str(campana.id_campana),
                "sucursal": sucursal,
                "nombre_campana": nombre_campana,
                "inicio_campana": campana.inicio_campana.isoformat() if campana.inicio_campana else None,
                "fin_campana": campana.fin_campana.isoformat() if campana.fin_campana else None,
            })

        return Response(
            {
                "ok": True,
                "items": items,
                "results": items,
                "source": "campanas_meta_volvo",
            },
            status=status.HTTP_200_OK,
        )

    except Exception as exc:
        logger.exception("ERROR CARGANDO campanas_meta_volvo: %s", exc)

        return Response(
            {
                "ok": False,
                "items": [],
                "results": [],
                "source": "campanas_meta_volvo",
                "error": str(exc),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )