# Digitales/views.py
import json
import logging
import mimetypes
from datetime import date, timedelta

from django.conf import settings
from django.db.models import OuterRef, Subquery, Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from usuarios.models import Usuario
from citas.models import ClienteComercial, normaliza_tel_mx

from .sett import WHATSAPP_LINES
from .models import ExpedienteDigital, MensajeWhatsApp, CampanaMeta, LecturaWhatsApp
from .serializers import ProspectoSerializer, WhatsAppMessageSerializer
from .contacto import (
    obtener_mensaje_whatsapp,
    replace_start,
    enviar_texto_whatsapp,
    enviar_template_whatsapp,
    subir_media_whatsapp,
    enviar_media_whatsapp,
    editar_texto_whatsapp,
    download_media_whatsapp,
    obtener_numero_asesor_desde_webhook_value,
    obtener_templates_whatsapp,
)


try:
    from notificaciones.services import notificar_mensaje_whatsapp
except Exception:
    def notificar_mensaje_whatsapp(**kwargs):
        return None


try:
    from .atribucion_meta import aplicar_pauta_desde_referencia_meta
except Exception:
    aplicar_pauta_desde_referencia_meta = None


TOKEN = "CBAR&RVOLKS"

logger = logging.getLogger(__name__)


class ProspectosViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = ProspectoSerializer

    def get_queryset(self):
        return (
            ExpedienteDigital.objects
            .select_related("cliente")
            .all()
            .order_by("-ultimo_contacto_at", "-actualizado", "-creado")
        )


def bienvenido(request):
    return HttpResponse("Funcionando Digitales WhatsApp Volvo, desde Django")


def privacidad_meta_view(request):
    html = """
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Aviso de Privacidad - CRM Volvo WhatsApp</title>
    </head>
    <body>
        <h1>Aviso de Privacidad</h1>

        <p>
            Automotriz R&R utiliza este sistema CRM Volvo para gestionar la atención
            de prospectos y clientes que se comunican por canales digitales,
            incluyendo WhatsApp Business.
        </p>

        <p>
            Los datos personales que pueden tratarse incluyen nombre, teléfono,
            correo electrónico, mensajes enviados por el cliente, interés vehicular,
            agencia de atención y datos necesarios para dar seguimiento comercial.
        </p>

        <p>
            La información se utiliza únicamente para brindar atención, seguimiento,
            cotizaciones, programación de citas, atención postventa y mejora del servicio.
        </p>

        <p>
            El titular puede solicitar acceso, rectificación, cancelación u oposición
            al tratamiento de sus datos personales enviando un correo al área responsable.
        </p>

        <p>
            Esta política puede actualizarse conforme a necesidades operativas,
            legales o comerciales.
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
        <title>Eliminación de Datos - CRM Volvo WhatsApp</title>
    </head>
    <body>
        <h1>Instrucciones para eliminación de datos</h1>

        <p>
            Para solicitar la eliminación de tus datos personales almacenados en el CRM,
            envía un correo al área responsable con el asunto:
            "Solicitud de eliminación de datos".
        </p>

        <p>
            Incluye tu nombre completo y número telefónico asociado a la conversación
            de WhatsApp para poder localizar tu información.
        </p>

        <p>
            Una vez recibida la solicitud, se revisará y procesará conforme a los
            procedimientos internos y obligaciones legales aplicables.
        </p>
    </body>
    </html>
    """
    return HttpResponse(html, content_type="text/html; charset=utf-8")


def _get_or_create_cliente_y_expediente(*, tel, profile_name="", numero_asesor=""):
    tel = normaliza_tel_mx(tel)
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not tel:
        return None, None

    cliente, _ = ClienteComercial.objects.get_or_create(
        telefono=tel,
        defaults={
            "nombre": (profile_name or "").strip(),
        },
    )

    if profile_name and not (cliente.nombre or "").strip():
        cliente.nombre = profile_name.strip()
        cliente.save(update_fields=["nombre", "actualizado_en"])

    cfg_linea = WHATSAPP_LINES.get(numero_asesor, {})

    agencia_linea = (cfg_linea.get("agencia") or "").strip()
    business_linea = (cfg_linea.get("business") or "").strip()
    asesor_digital_linea = (cfg_linea.get("asesor_digital") or "").strip()

    exp, _ = ExpedienteDigital.objects.get_or_create(cliente=cliente)

    cambios = []

    if agencia_linea and exp.agencia != agencia_linea:
        exp.agencia = agencia_linea
        cambios.append("agencia")

    if business_linea and exp.business != business_linea:
        exp.business = business_linea
        cambios.append("business")

    if asesor_digital_linea and exp.asesor_digital != asesor_digital_linea:
        exp.asesor_digital = asesor_digital_linea
        cambios.append("asesor_digital")

    if exp.canal_contacto != "WhatsApp":
        exp.canal_contacto = "WhatsApp"
        cambios.append("canal_contacto")

    if not (exp.estado or "").strip():
        exp.estado = "Contactado"
        cambios.append("estado")

    if cambios:
        cambios.append("actualizado")
        exp.save(update_fields=list(dict.fromkeys(cambios)))

    return cliente, exp


def _numero_linea_valido(numero):
    numero = normaliza_tel_mx(numero or "")
    return numero if numero in WHATSAPP_LINES else ""


def _obtener_usuario_crm_request(request):
    username = (request.query_params.get("usuario", "") or "").strip()

    if username:
        return username

    try:
        username = (request.data.get("usuario", "") or "").strip()

        if username:
            return username
    except Exception:
        pass

    return ""


def _buscar_numero_por_usuario(username):
    username = (username or "").strip()

    if not username:
        return ""

    usuario = Usuario.objects.filter(usuario__iexact=username).first()

    if not usuario:
        return ""

    return _numero_linea_valido(getattr(usuario, "telefono", "") or "")


def _get_numero_asesor_request(request):
    numero = _numero_linea_valido(request.query_params.get("numero_asesor", "") or "")

    if numero:
        return numero

    try:
        numero = _numero_linea_valido(request.data.get("numero_asesor", "") or "")

        if numero:
            return numero
    except Exception:
        pass

    username = _obtener_usuario_crm_request(request)
    numero = _buscar_numero_por_usuario(username)

    if numero:
        return numero

    raise PermissionDenied(
        "No se pudo determinar la línea de WhatsApp. "
        "Envía numero_asesor o usuario."
    )


def _get_or_create_lectura(exp, numero_asesor):
    lectura, _ = LecturaWhatsApp.objects.get_or_create(
        expediente=exp,
        numero_asesor=numero_asesor,
    )

    return lectura


def _mark_read_exp(exp, numero_asesor, when=None):
    lectura = _get_or_create_lectura(exp, numero_asesor)
    lectura.last_read_at = when or timezone.now()
    lectura.save(update_fields=["last_read_at", "updated_at"])


def _unread_count(exp, numero_asesor):
    qs = MensajeWhatsApp.objects.filter(
        telefono=exp.cliente.telefono,
        numero_asesor=numero_asesor,
        direction="in",
    )

    lectura = LecturaWhatsApp.objects.filter(
        expediente=exp,
        numero_asesor=numero_asesor,
    ).first()

    if lectura and lectura.last_read_at:
        qs = qs.filter(created_at__gt=lectura.last_read_at)

    return qs.count()


def _obtener_referral_meta(msg):
    if not isinstance(msg, dict):
        return {}

    referral = msg.get("referral") or {}

    if not referral:
        context = msg.get("context") or {}

        if isinstance(context, dict):
            referral = context.get("referral") or {}

    if not isinstance(referral, dict):
        return {}

    return referral


def _normalizar_id_campana_meta(value):
    texto = str(value or "").strip()

    if not texto:
        return None

    if not texto.isdigit():
        return None

    try:
        return int(texto)
    except (TypeError, ValueError, OverflowError):
        return None


def _buscar_campana_meta_por_source_id(source_id):
    id_campana = _normalizar_id_campana_meta(source_id)

    if id_campana is None:
        return None

    try:
        return (
            CampanaMeta.objects.using("sqlserver")
            .filter(id_campana=id_campana)
            .only("id_campana", "sucursal", "nombre_campana")
            .first()
        )
    except Exception as e:
        logger.exception(
            "ERROR CONSULTANDO CAMPANA META | source_id=%s id_campana=%s error=%s",
            source_id,
            id_campana,
            str(e),
        )
        return None


def _armar_label_campana_meta(campana):
    if not campana:
        return ""

    sucursal = str(campana.sucursal or "").strip()
    nombre = str(campana.nombre_campana or "").strip()

    if sucursal and nombre:
        return f"{sucursal} - {nombre}"

    return nombre or sucursal


def aplicar_pauta_desde_referral_meta(*, expediente, msg):
    if not expediente:
        return {
            "ok": False,
            "motivo": "sin_expediente",
        }

    referral = _obtener_referral_meta(msg)

    if not referral:
        return {
            "ok": False,
            "motivo": "sin_referral",
        }

    source_id = str(referral.get("source_id") or "").strip()

    if not source_id:
        return {
            "ok": False,
            "motivo": "sin_source_id",
            "referral": referral,
        }

    if (expediente.pauta or "").strip():
        return {
            "ok": True,
            "motivo": "pauta_ya_existia",
            "source_id": source_id,
            "pauta": expediente.pauta,
            "referral": referral,
        }

    campana = _buscar_campana_meta_por_source_id(source_id)

    if not campana:
        return {
            "ok": False,
            "motivo": "campana_no_encontrada_en_sqlserver",
            "source_id": source_id,
            "referral": referral,
        }

    pauta = _armar_label_campana_meta(campana)

    if not pauta:
        return {
            "ok": False,
            "motivo": "campana_sin_nombre",
            "source_id": source_id,
            "id_campana": campana.id_campana,
            "referral": referral,
        }

    expediente.pauta = pauta
    expediente.save(update_fields=["pauta", "actualizado"])

    return {
        "ok": True,
        "motivo": "pauta_asignada",
        "source_id": source_id,
        "id_campana": campana.id_campana,
        "pauta": pauta,
        "referral": referral,
    }


def _aplicar_atribucion_meta_segura(*, expediente, mensaje_whatsapp, numero_asesor, telefono, wa_id):
    if aplicar_pauta_desde_referencia_meta is not None:
        try:
            return aplicar_pauta_desde_referencia_meta(
                expediente=expediente,
                mensaje_whatsapp=mensaje_whatsapp,
            )
        except Exception as e:
            logger.exception(
                "ERROR ATRIBUCION META EXTERNA | numero_asesor=%s telefono=%s wa_id=%s error=%s",
                numero_asesor,
                telefono,
                wa_id,
                str(e),
            )

    try:
        return aplicar_pauta_desde_referral_meta(
            expediente=expediente,
            msg=mensaje_whatsapp,
        )
    except Exception as e:
        logger.exception(
            "ERROR ATRIBUCION META LOCAL | numero_asesor=%s telefono=%s wa_id=%s error=%s",
            numero_asesor,
            telefono,
            wa_id,
            str(e),
        )

        return {
            "ok": False,
            "motivo": "error_atribucion_meta",
            "error": str(e),
        }


@csrf_exempt
def webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode", "")
        token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")

        logger.info(
            "WEBHOOK VERIFY | mode=%s token_ok=%s challenge=%s",
            mode,
            token == TOKEN,
            challenge,
        )

        if mode == "subscribe" and token == TOKEN and challenge:
            return HttpResponse(challenge, content_type="text/plain")

        return HttpResponse("token incorrecto", status=403)

    if request.method != "POST":
        return HttpResponse("method not allowed", status=405)

    try:
        raw_body = request.body.decode("utf-8")
        body = json.loads(raw_body)

        logger.info("WEBHOOK RAW BODY: %s", json.dumps(body, ensure_ascii=False))
    except Exception as e:
        logger.exception("ERROR PARSEANDO WEBHOOK: %s", str(e))
        return HttpResponse("ok")

    try:
        entries = body.get("entry") or []

        logger.info("WEBHOOK ENTRIES COUNT: %s", len(entries))

        for entry in entries:
            changes = entry.get("changes") or []

            logger.info(
                "WEBHOOK ENTRY | entry_id=%s changes_count=%s",
                entry.get("id"),
                len(changes),
            )

            for ch in changes:
                value = ch.get("value") or {}
                metadata = value.get("metadata") or {}

                numero_asesor = obtener_numero_asesor_desde_webhook_value(value)

                logger.info(
                    "WEBHOOK META LINEA | entry_id=%s phone_number_id=%s display_phone_number=%s numero_asesor_resuelto=%s",
                    entry.get("id"),
                    metadata.get("phone_number_id"),
                    metadata.get("display_phone_number"),
                    numero_asesor,
                )

                if not numero_asesor:
                    logger.warning(
                        "WEBHOOK SIN MAPEO DE LINEA | phone_number_id=%s display_phone_number=%s contacts_count=%s messages_count=%s statuses_count=%s",
                        metadata.get("phone_number_id"),
                        metadata.get("display_phone_number"),
                        len(value.get("contacts") or []),
                        len(value.get("messages") or []),
                        len(value.get("statuses") or []),
                    )

                contacts = value.get("contacts") or []
                profile_name = ""

                if contacts:
                    profile_name = (contacts[0].get("profile") or {}).get("name", "") or ""

                messages = value.get("messages") or []

                logger.info("WEBHOOK MESSAGES COUNT: %s", len(messages))

                for msg in messages:
                    wa_from = msg.get("from", "")
                    tel = normaliza_tel_mx(replace_start(wa_from))
                    wa_id = (msg.get("id", "") or "").strip()
                    text = obtener_mensaje_whatsapp(msg)

                    logger.info(
                        "WEBHOOK MENSAJE RECIBIDO | from=%s tel=%s wa_id=%s type=%s text=%s",
                        wa_from,
                        tel,
                        wa_id,
                        msg.get("type"),
                        text,
                    )

                    if not tel or not wa_id:
                        logger.warning(
                            "WEBHOOK MENSAJE OMITIDO SIN TEL O WA_ID | from=%s tel=%s wa_id=%s msg=%s",
                            wa_from,
                            tel,
                            wa_id,
                            json.dumps(msg, ensure_ascii=False),
                        )
                        continue

                    if not numero_asesor:
                        logger.warning(
                            "MENSAJE ENTRANTE OMITIDO POR LINEA NO RESUELTA | from=%s tel=%s wa_id=%s type=%s phone_number_id=%s display_phone_number=%s",
                            wa_from,
                            tel,
                            wa_id,
                            msg.get("type"),
                            metadata.get("phone_number_id"),
                            metadata.get("display_phone_number"),
                        )
                        continue

                    cliente, exp = _get_or_create_cliente_y_expediente(
                        tel=tel,
                        profile_name=profile_name,
                        numero_asesor=numero_asesor,
                    )

                    if not cliente or not exp:
                        logger.warning(
                            "WEBHOOK OMITIDO SIN CLIENTE O EXPEDIENTE | tel=%s numero_asesor=%s cliente=%s exp=%s",
                            tel,
                            numero_asesor,
                            bool(cliente),
                            bool(exp),
                        )
                        continue

                    exp.touch_ultimo_contacto(save_now=True)

                    resultado_atribucion_meta = _aplicar_atribucion_meta_segura(
                        expediente=exp,
                        mensaje_whatsapp=msg,
                        numero_asesor=numero_asesor,
                        telefono=tel,
                        wa_id=wa_id,
                    )

                    raw_msg = dict(msg)
                    raw_msg["numero_asesor"] = numero_asesor
                    raw_msg["phone_number_id"] = metadata.get("phone_number_id", "")
                    raw_msg["display_phone_number"] = metadata.get("display_phone_number", "")
                    raw_msg["atribucion_meta"] = resultado_atribucion_meta

                    mensaje_entrante, created = MensajeWhatsApp.objects.get_or_create(
                        wa_message_id=wa_id,
                        numero_asesor=numero_asesor,
                        defaults={
                            "telefono": tel,
                            "cliente": cliente,
                            "direction": "in",
                            "body": text,
                            "status": "received",
                            "raw": raw_msg,
                        },
                    )

                    logger.info(
                        "WEBHOOK MENSAJE GUARDADO | created=%s id=%s tel=%s numero_asesor=%s wa_id=%s body=%s",
                        created,
                        mensaje_entrante.id,
                        tel,
                        numero_asesor,
                        wa_id,
                        text,
                    )

                    if not created:
                        cambios = []

                        if not mensaje_entrante.cliente_id and cliente:
                            mensaje_entrante.cliente = cliente
                            cambios.append("cliente")

                        if not (mensaje_entrante.telefono or "").strip():
                            mensaje_entrante.telefono = tel
                            cambios.append("telefono")

                        raw_actual = dict(mensaje_entrante.raw or {})
                        raw_actual["ultimo_webhook_payload"] = raw_msg
                        mensaje_entrante.raw = raw_actual
                        cambios.append("raw")

                        if cambios:
                            mensaje_entrante.save(update_fields=list(dict.fromkeys(cambios)))

                    if created:
                        try:
                            notificar_mensaje_whatsapp(
                                numero_asesor=numero_asesor,
                                telefono=tel,
                                nombre=getattr(cliente, "nombre", "") or profile_name or "Prospecto",
                                mensaje=text,
                                wa_message_id=wa_id,
                                expediente_id=exp.id if exp else None,
                                created_at=mensaje_entrante.created_at,
                            )
                        except Exception as e:
                            logger.exception(
                                "Error enviando notificación websocket | tel=%s wa_id=%s error=%s",
                                tel,
                                wa_id,
                                str(e),
                            )

                statuses = value.get("statuses") or []

                logger.info("WEBHOOK STATUSES COUNT: %s", len(statuses))

                for s in statuses:
                    wa_id = s.get("id")
                    st = s.get("status")
                    errors = s.get("errors") or []
                    ts = s.get("timestamp")

                    if not (wa_id and st):
                        logger.warning(
                            "WEBHOOK STATUS OMITIDO SIN ID O STATUS | payload=%s",
                            json.dumps(s, ensure_ascii=False),
                        )
                        continue

                    q = MensajeWhatsApp.objects.filter(wa_message_id=wa_id)

                    if numero_asesor:
                        q = q.filter(numero_asesor=numero_asesor)

                    msg_obj = q.first()

                    if not msg_obj:
                        logger.warning(
                            "WEBHOOK STATUS SIN MENSAJE LOCAL | wa_id=%s status=%s numero_asesor=%s",
                            wa_id,
                            st,
                            numero_asesor,
                        )
                        continue

                    new_raw = dict(msg_obj.raw or {})
                    new_raw["status_payload"] = s

                    if errors:
                        new_raw["errors"] = errors

                    if ts:
                        new_raw["status_timestamp"] = ts

                    msg_obj.status = st
                    msg_obj.raw = new_raw
                    msg_obj.save(update_fields=["status", "raw"])

                    logger.info(
                        "WEBHOOK STATUS ACTUALIZADO | id=%s wa_id=%s status=%s numero_asesor=%s",
                        msg_obj.id,
                        wa_id,
                        st,
                        numero_asesor,
                    )

        return HttpResponse("ok")

    except Exception as e:
        logger.exception("ERROR GENERAL WEBHOOK: %s", str(e))
        return HttpResponse("ok")


@api_view(["GET"])
@permission_classes([AllowAny])
def media_proxy_view(request, media_id):
    try:
        numero_asesor = normaliza_tel_mx(request.query_params.get("numero_asesor", ""))

        blob, content_type = download_media_whatsapp(
            media_id,
            numero_asesor=numero_asesor,
        )

        resp = HttpResponse(blob, content_type=content_type)
        resp["Cache-Control"] = "private, max-age=300"

        return resp
    except Exception as e:
        return HttpResponse(
            f"error: {str(e)}",
            status=400,
            content_type="text/plain",
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def chats_list(request):
    numero_asesor = _get_numero_asesor_request(request)
    limit = 200

    last_msg_qs = (
        MensajeWhatsApp.objects
        .filter(
            telefono=OuterRef("cliente__telefono"),
            numero_asesor=numero_asesor,
        )
        .order_by("-created_at", "-id")
    )

    telefonos_con_mensajes = (
        MensajeWhatsApp.objects
        .filter(numero_asesor=numero_asesor)
        .values("telefono")
    )

    expedientes = (
        ExpedienteDigital.objects
        .select_related("cliente")
        .filter(cliente__telefono__in=telefonos_con_mensajes)
        .annotate(
            last_text=Subquery(last_msg_qs.values("body")[:1]),
            last_time=Subquery(last_msg_qs.values("created_at")[:1]),
        )
        .distinct()
        .order_by("-last_time", "-actualizado", "-creado")[:limit]
    )

    data = []

    for exp in expedientes:
        if exp.last_time:
            dt = exp.last_time

            if settings.USE_TZ and timezone.is_aware(dt):
                dt = timezone.localtime(dt)

            last_time_str = dt.strftime("%I:%M %p").lower()
        else:
            last_time_str = ""

        data.append(
            {
                "id": exp.id,
                "telefono": exp.cliente.telefono,
                "nombre": exp.cliente.nombre or "Prospecto",
                "agencia": exp.agencia or "",
                "linea": exp.business or "",
                "estado": exp.estado or "",
                "unread": _unread_count(exp, numero_asesor),
                "last_text": exp.last_text or "",
                "last_time": last_time_str,
                "numero_asesor": numero_asesor,
            }
        )

    return Response(data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_por_telefono(request):
    numero_asesor = _get_numero_asesor_request(request)
    tel = normaliza_tel_mx(request.query_params.get("tel", ""))

    if not tel:
        return Response(
            {
                "ok": False,
                "error": "Falta tel",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente = ClienteComercial.objects.filter(telefono=tel).first()

    exp = None

    if cliente:
        exp = ExpedienteDigital.objects.filter(cliente=cliente).first()

    mensajes = (
        MensajeWhatsApp.objects
        .filter(telefono=tel, numero_asesor=numero_asesor)
        .order_by("created_at", "id")
    )

    if exp:
        _mark_read_exp(exp, numero_asesor)

    return Response(
        {
            "ok": True,
            "numero_asesor_activo": numero_asesor,
            "prospecto": ProspectoSerializer(exp).data if exp else None,
            "mensajes": WhatsAppMessageSerializer(
                mensajes,
                many=True,
                context={"request": request},
            ).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def mark_read_view(request):
    numero_asesor = _get_numero_asesor_request(request)
    tel = normaliza_tel_mx(request.data.get("tel", ""))

    if not tel:
        return Response(
            {
                "ok": False,
                "error": "Falta tel",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente = ClienteComercial.objects.filter(telefono=tel).first()

    if not cliente:
        return Response(
            {
                "ok": False,
                "error": "No existe prospecto",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    exp = ExpedienteDigital.objects.filter(cliente=cliente).first()

    if not exp:
        return Response(
            {
                "ok": False,
                "error": "No existe expediente",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    _mark_read_exp(exp, numero_asesor)

    return Response({"ok": True}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def contacto_updates(request):
    numero_asesor = _get_numero_asesor_request(request)
    tel = normaliza_tel_mx(request.query_params.get("tel", ""))
    after = request.query_params.get("after", "")

    if not tel:
        return Response(
            {
                "ok": False,
                "error": "Falta tel",
            },
            status=400,
        )

    qs = (
        MensajeWhatsApp.objects
        .filter(telefono=tel, numero_asesor=numero_asesor)
        .order_by("created_at", "id")
    )

    if after:
        try:
            after_dt = timezone.datetime.fromisoformat(after.replace("Z", "+00:00"))

            if not settings.USE_TZ:
                if timezone.is_aware(after_dt):
                    after_dt = timezone.make_naive(
                        after_dt,
                        timezone.get_current_timezone(),
                    )
            else:
                if timezone.is_naive(after_dt):
                    after_dt = timezone.make_aware(after_dt, timezone=timezone.utc)

            qs = qs.filter(created_at__gt=after_dt)
        except Exception:
            pass

    return Response(
        {
            "ok": True,
            "numero_asesor_activo": numero_asesor,
            "mensajes": WhatsAppMessageSerializer(
                qs,
                many=True,
                context={"request": request},
            ).data,
            "server_now": timezone.now().isoformat(),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_mensaje_view(request):
    numero_asesor = _get_numero_asesor_request(request)
    to = normaliza_tel_mx(request.data.get("to", ""))
    text = (request.data.get("text") or "").strip()

    if not to or not text:
        return Response(
            {
                "ok": False,
                "error": "Falta to o text",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        cliente, exp = _get_or_create_cliente_y_expediente(
            tel=to,
            numero_asesor=numero_asesor,
        )

        if exp:
            exp.touch_ultimo_contacto(save_now=True)

        wa_res = enviar_texto_whatsapp(
            to=to,
            text=text,
            numero_asesor=numero_asesor,
        )

        wa_message_id = ""

        try:
            wa_message_id = (wa_res.get("messages") or [{}])[0].get("id", "") or ""
        except Exception:
            pass

        MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction="out",
            body=text,
            wa_message_id=wa_message_id,
            status="accepted",
            raw=wa_res,
        )

        return Response(
            {
                "ok": True,
                "data": wa_res,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser, FormParser])
def enviar_media_view(request):
    numero_asesor = _get_numero_asesor_request(request)
    to = normaliza_tel_mx(request.data.get("to", ""))
    caption = (request.data.get("text") or "").strip()
    files = request.FILES.getlist("files") or []

    if not to:
        return Response(
            {
                "ok": False,
                "error": "Falta to",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not files:
        return Response(
            {
                "ok": False,
                "error": "Faltan files",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    cliente, exp = _get_or_create_cliente_y_expediente(
        tel=to,
        numero_asesor=numero_asesor,
    )

    if exp:
        exp.touch_ultimo_contacto(save_now=True)

    sent = []
    failed = []

    for f in files:
        try:
            name = getattr(f, "name", "archivo")
            ct = getattr(f, "content_type", "") or (mimetypes.guess_type(name)[0] or "")

            if (ct or "").startswith("image/"):
                wtype = "image"
            elif (ct or "").startswith("video/"):
                wtype = "video"
            elif (ct or "").startswith("audio/"):
                wtype = "audio"
            else:
                wtype = "document"

            up = subir_media_whatsapp(
                f,
                numero_asesor=numero_asesor,
                filename=name,
                content_type=ct,
            )

            media_id = up.get("id") or ""

            if not media_id:
                raise RuntimeError(f"No regresó media_id: {up}")

            wa_res = enviar_media_whatsapp(
                to=to,
                media_id=media_id,
                media_type=wtype,
                numero_asesor=numero_asesor,
                caption=caption if caption else "",
                filename=name if wtype == "document" else "",
            )

            wa_message_id = ""

            try:
                wa_message_id = (wa_res.get("messages") or [{}])[0].get("id", "") or ""
            except Exception:
                pass

            body = caption if caption else ""
            body = f"{body}\n[FILE:{name}]".strip() if body else f"[FILE:{name}]"

            MensajeWhatsApp.objects.create(
                telefono=to,
                numero_asesor=numero_asesor,
                cliente=cliente,
                direction="out",
                body=body,
                wa_message_id=wa_message_id,
                status="accepted",
                raw={
                    "upload": up,
                    "send": wa_res,
                    "meta_type": wtype,
                    "filename": name,
                    "content_type": ct,
                    "numero_asesor": numero_asesor,
                },
            )

            sent.append(
                {
                    "filename": name,
                    "type": wtype,
                    "data": wa_res,
                }
            )

        except Exception as e:
            failed.append(
                {
                    "filename": getattr(f, "name", "archivo"),
                    "error": str(e),
                }
            )

    return Response(
        {
            "ok": True,
            "sent": sent,
            "failed": failed,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def enviar_plantilla_view(request):
    numero_asesor = _get_numero_asesor_request(request)
    to = normaliza_tel_mx(request.data.get("to", ""))
    template_name = (request.data.get("template_name") or "").strip()
    params = request.data.get("params")
    components = request.data.get("components")
    idioma = (request.data.get("idioma") or "es_MX").strip()

    cliente = None

    if not to:
        return Response(
            {
                "ok": False,
                "error": "Falta to",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not template_name:
        return Response(
            {
                "ok": False,
                "error": "Falta template_name",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if components is not None and not isinstance(components, list):
        return Response(
            {
                "ok": False,
                "error": "components debe ser lista",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if components is None:
        if params is None:
            params = []

        if not isinstance(params, list):
            return Response(
                {
                    "ok": False,
                    "error": "params debe ser lista",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        cliente, exp = _get_or_create_cliente_y_expediente(
            tel=to,
            numero_asesor=numero_asesor,
        )

        if exp:
            exp.touch_ultimo_contacto(save_now=True)

        wa_res = enviar_template_whatsapp(
            to=to,
            template_name=template_name,
            numero_asesor=numero_asesor,
            params=[str(x) for x in (params or [])],
            idioma=idioma,
            components=components,
        )

        wa_message_id = ""

        try:
            wa_message_id = (wa_res.get("messages") or [{}])[0].get("id", "") or ""
        except Exception:
            pass

        body_log = f"[TEMPLATE:{template_name}]"

        if components:
            flat = []

            for c in components:
                for p in (c.get("parameters") or []):
                    if p.get("type") == "text":
                        flat.append(str(p.get("text") or ""))

            if flat:
                body_log += " " + " | ".join(flat)
        else:
            body_log += " " + " | ".join([str(x) for x in (params or [])])

        MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction="out",
            body=body_log.strip(),
            wa_message_id=wa_message_id,
            status="accepted",
            raw=wa_res,
        )

        return Response(
            {
                "ok": True,
                "data": wa_res,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        MensajeWhatsApp.objects.create(
            telefono=to,
            numero_asesor=numero_asesor,
            cliente=cliente,
            direction="out",
            body=f"[TEMPLATE:{template_name}] failed",
            wa_message_id="",
            status="failed",
            raw={
                "error": str(e),
                "numero_asesor": numero_asesor,
            },
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
def campanas_meta_recientes(request):
    try:
        days = int(request.query_params.get("days", "30"))
    except ValueError:
        days = 30

    cutoff = date.today() - timedelta(days=days)

    try:
        qs = (
            CampanaMeta.objects.using("sqlserver")
            .filter(Q(inicio_campana__gte=cutoff) | Q(fin_campana__gte=cutoff))
            .order_by("-inicio_campana", "-fin_campana")
        )

        seen = set()
        out = []

        for c in qs[:500]:
            label = f"{(c.sucursal or '').strip()} - {(c.nombre_campana or '').strip()}".strip(" -")

            if not label or label in seen:
                continue

            seen.add(label)

            out.append(
                {
                    "value": label,
                    "label": label,
                }
            )

        return Response(
            {
                "ok": True,
                "items": out,
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.exception("ERROR CONSULTANDO CAMPANAS META: %s", str(e))

        return Response(
            {
                "ok": False,
                "error": str(e),
                "items": [],
            },
            status=status.HTTP_200_OK,
        )


@api_view(["PATCH"])
@permission_classes([AllowAny])
def editar_mensaje_view(request):
    numero_asesor = _get_numero_asesor_request(request)
    to = normaliza_tel_mx(request.data.get("to", ""))
    message_id = (request.data.get("message_id") or "").strip()
    text = (request.data.get("text") or "").strip()

    if not to or not message_id or not text:
        return Response(
            {
                "ok": False,
                "error": "Falta to, message_id o text",
            },
            status=400,
        )

    msg = MensajeWhatsApp.objects.filter(
        telefono=to,
        numero_asesor=numero_asesor,
        wa_message_id=message_id,
    ).first()

    if not msg:
        return Response(
            {
                "ok": False,
                "error": "Mensaje no encontrado",
            },
            status=404,
        )

    if msg.direction != "out":
        return Response(
            {
                "ok": False,
                "error": "Solo puedes editar mensajes enviados",
            },
            status=400,
        )

    if (msg.body or "").startswith("[TEMPLATE:"):
        return Response(
            {
                "ok": False,
                "error": "No se editan plantillas ya enviadas",
            },
            status=400,
        )

    if msg.created_at and timezone.now() - msg.created_at > timedelta(minutes=15):
        return Response(
            {
                "ok": False,
                "error": "Ya no es editable. La ventana de edición expiró.",
            },
            status=400,
        )

    try:
        wa_res = editar_texto_whatsapp(
            to=to,
            original_message_id=message_id,
            new_text=text,
            numero_asesor=numero_asesor,
        )

        msg.body = text

        raw = dict(msg.raw or {})
        raw["edit_response"] = wa_res

        msg.raw = raw
        msg.save(update_fields=["body", "raw"])

        return Response(
            {
                "ok": True,
                "data": wa_res,
            },
            status=200,
        )

    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
            },
            status=400,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def plantillas_whatsapp_view(request):
    try:
        numero_asesor = _get_numero_asesor_request(request)
        templates = obtener_templates_whatsapp(numero_asesor)

        cfg = WHATSAPP_LINES.get(numero_asesor, {})

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "linea": {
                    "key": cfg.get("key", ""),
                    "asesor_digital": cfg.get("asesor_digital", ""),
                    "agencia": cfg.get("agencia", ""),
                    "business": cfg.get("business", ""),
                    "phone_number_id": cfg.get("phone_number_id", ""),
                },
                "items": templates,
            },
            status=200,
        )

    except Exception as e:
        return Response(
            {
                "ok": False,
                "error": str(e),
                "items": [],
            },
            status=400,
        )