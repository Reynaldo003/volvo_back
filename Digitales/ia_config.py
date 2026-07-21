#volvo
# Digitales/ia_config.py
from __future__ import annotations

from typing import Any
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from usuarios.authentication import SignedUserAuthentication
from citas.models import ClienteComercial, normaliza_tel_mx

from .models import (
    ConfiguracionIAWhatsApp,
    ConversacionIA,
    ExpedienteDigital,
)
from .sett import WHATSAPP_LINES

IA_CONFIG_GLOBAL_KEY = "GLOBAL"

CONDICIONES_FIJAS_DEFAULT = """- No proporcionar precios finales ni cotizaciones cerradas.
- No comprometer disponibilidad de unidades sin verificación previa.
- No inventar precios, mensualidades, promociones ni descuentos.
- Siempre derivar al asesor humano para cierre comercial o cotización formal.
- Mantener el tono institucional de Grupo Automotriz R&R.

Cuando el cliente pida video, recorrido, tour, reel o quiera ver cómo se ve el auto en movimiento:
- Debes seleccionar el modelo/version correcto en selected_version.
- Debes responder con un texto breve indicando que compartirás el video.
- Debes marcar send_videos=true.
- No marques send_videos=true si no estás seguro del modelo solicitado.
- Si el cliente pide ficha técnica, marca send_pdf=true.
- Si el cliente pide fotos o imágenes, marca send_images=true.
- Si el cliente pide video, marca send_videos=true.

Cuando el mensaje del cliente contenga [CONTEXTO MULTIMEDIA ANALIZADO]:

- Usa ese análisis como si el cliente hubiera explicado el contenido por texto.
- Si el análisis viene de audio, toma la transcripción como mensaje principal del cliente.
- Si el análisis viene de imagen o video y aparece un auto, identifica modelo, color, condición aparente o duda comercial.
- Si el análisis viene de sticker, interpreta solo la emoción probable, sin inventar intención de compra.
- Si el contenido no es claro, responde pidiendo confirmación de forma amable.
- No digas “no puedo ver archivos” si ya existe contexto multimedia analizado.
- No inventes datos técnicos, precios, disponibilidad ni promociones a partir de una imagen, sticker, audio o video.
"""

def _normalizar_numero_config_ia(value: str, permitir_global: bool = False) -> str:
    raw = str(value or "").strip()

    if permitir_global and raw.upper() in ("GLOBAL", "TODOS", "ALL", "*"):
        return IA_CONFIG_GLOBAL_KEY

    return normaliza_tel_mx(raw)


def _normalizar_numero_linea_ia(value: str) -> str:
    numero = _normalizar_numero_config_ia(value, permitir_global=False)

    if not numero:
        return ""

    if numero not in WHATSAPP_LINES:
        return ""

    return numero


def obtener_config_ia_para_numero(numero_asesor: str):
    numero_asesor = _normalizar_numero_linea_ia(numero_asesor)

    if not numero_asesor:
        return None, ""

    config = ConfiguracionIAWhatsApp.objects.filter(
        numero_asesor=numero_asesor,
    ).first()

    if not config:
        return None, ""

    return config, "especifica"

def _parse_hora_ia(value):
    try:
        return timezone.datetime.strptime(str(value or "").strip(), "%H:%M").time()
    except Exception:
        return None


def _aware_datetime_ia(fecha, hora):
    dt = timezone.datetime.combine(fecha, hora)

    if settings.USE_TZ and timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())

    return dt


def _ia_esta_en_horario(horarios: dict) -> bool:
    if not isinstance(horarios, dict) or not horarios:
        return True

    dias = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
    ahora = timezone.now()

    if settings.USE_TZ and timezone.is_aware(ahora):
        ahora = timezone.localtime(ahora)

    hoy_idx = ahora.weekday()

    for inicio_idx, dia_key in enumerate(dias):
        config_dia = horarios.get(dia_key) or {}

        if not config_dia.get("activo", False):
            continue

        hora_inicio = _parse_hora_ia(config_dia.get("inicio"))
        hora_fin = _parse_hora_ia(config_dia.get("fin"))

        if not hora_inicio or not hora_fin:
            continue

        hasta_dia = config_dia.get("hastaDia")
        hasta_idx = dias.index(hasta_dia) if hasta_dia in dias else None
        base_delta = inicio_idx - hoy_idx

        for semana_offset in (0, -7):
            fecha_inicio = ahora.date() + timedelta(days=base_delta + semana_offset)

            if hasta_idx is not None:
                dias_duracion = (hasta_idx - inicio_idx) % 7
                fecha_fin = fecha_inicio + timedelta(days=dias_duracion)
            else:
                fecha_fin = fecha_inicio
                if hora_fin <= hora_inicio:
                    fecha_fin = fecha_fin + timedelta(days=1)

            inicio_dt = _aware_datetime_ia(fecha_inicio, hora_inicio)
            fin_dt = _aware_datetime_ia(fecha_fin, hora_fin)

            if inicio_dt <= ahora <= fin_dt:
                return True

    return False


def obtener_estado_ia_conversacion(*, numero_asesor: str, tel: str = "", expediente=None) -> dict[str, Any]:
    numero_asesor = normaliza_tel_mx(numero_asesor or "")
    tel = normaliza_tel_mx(tel or "")

    config, config_origen = obtener_config_ia_para_numero(numero_asesor)
    if expediente is None and tel:
        expediente = _obtener_expediente_por_tel(tel)

    conversacion = None
    if expediente and numero_asesor:
        conversacion = ConversacionIA.objects.filter(
            expediente=expediente,
            numero_asesor=numero_asesor,
        ).first()

    en_horario = _ia_esta_en_horario(config.horarios if config else {}) if config else False
    bloqueos: list[str] = []

    if not numero_asesor:
        bloqueos.append("numero_asesor_invalido")

    if not config:
        bloqueos.append("configuracion_ia_no_existe")
    else:
        if not config.activo:
            bloqueos.append("configuracion_ia_inactiva")
        if not en_horario:
            bloqueos.append("fuera_de_horario")

    if not expediente:
        bloqueos.append("expediente_no_encontrado")
    else:
        if expediente.ia_pausada:
            bloqueos.append("expediente_ia_pausada")

    if conversacion:
        if not conversacion.ia_activa:
            bloqueos.append("conversacion_ia_inactiva")
        if conversacion.ia_pausada:
            bloqueos.append("conversacion_ia_pausada")

    return {
        "numero_asesor": numero_asesor,
        "telefono": tel or (expediente.cliente.telefono if expediente and expediente.cliente_id else ""),
        "puede_responder": len(bloqueos) == 0,
        "bloqueos": bloqueos,
        "hora_servidor": timezone.now().isoformat(),
        "timezone": str(getattr(settings, "TIME_ZONE", "")),
        "use_tz": bool(getattr(settings, "USE_TZ", False)),
        "configuracion": {
            "existe": bool(config),
            "activo": bool(config.activo) if config else False,
            "en_horario": en_horario,
            "horarios": config.horarios if config else {},
            "origen": config_origen,
            "numero_config": config.numero_asesor if config else "",
        },
        "expediente": {
            "existe": bool(expediente),
            "id": expediente.id if expediente else None,
            "estado": expediente.estado if expediente else "",
            "ia_pausada": bool(expediente.ia_pausada) if expediente else False,
            "ia_pausada_motivo": expediente.ia_pausada_motivo if expediente else "",
            "ia_pausada_at": expediente.ia_pausada_at.isoformat() if expediente and expediente.ia_pausada_at else None,
            "requiere_asesor": bool(expediente.requiere_asesor) if expediente else False,
            "motivo_requiere_asesor": expediente.motivo_requiere_asesor if expediente else "",
            "cotizacion_pendiente": bool(expediente.cotizacion_pendiente) if expediente else False,
            "cotizacion_solicitada_at": expediente.cotizacion_solicitada_at.isoformat() if expediente and expediente.cotizacion_solicitada_at else None,
        },
        "conversacion": {
            "existe": bool(conversacion),
            "ia_activa": bool(conversacion.ia_activa) if conversacion else True,
            "ia_pausada": bool(conversacion.ia_pausada) if conversacion else False,
            "motivo_pausa": conversacion.motivo_pausa if conversacion else "",
            "estado_conversacion": conversacion.estado_conversacion if conversacion else "sin_iniciar",
            "ultima_intencion": conversacion.ultima_intencion if conversacion else "",
            "ultimo_modelo_mencionado": conversacion.ultimo_modelo_mencionado if conversacion else "",
            "pregunta_pendiente": conversacion.pregunta_pendiente if conversacion else "",
        },
    }


@api_view(["GET"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def ia_lineas_whatsapp(request):
    """
    Lista las líneas reales de WhatsApp y muestra si cada una tiene
    configuración propia de IA.

    Ya no usa configuración GLOBAL como respaldo.
    """
    configs = {
        item.numero_asesor: item
        for item in ConfiguracionIAWhatsApp.objects
        .exclude(numero_asesor=IA_CONFIG_GLOBAL_KEY)
        .all()
    }

    items = []

    for numero, cfg in WHATSAPP_LINES.items():
        config = configs.get(numero)
        en_horario = _ia_esta_en_horario(config.horarios if config else {}) if config else False

        bloqueos = []

        if not config:
            bloqueos.append("configuracion_ia_no_existe")
        else:
            if not config.activo:
                bloqueos.append("configuracion_ia_inactiva")

            if not en_horario:
                bloqueos.append("fuera_de_horario")

        items.append({
            "numero": numero,
            "key": cfg.get("key", ""),
            "label": f"{cfg.get('asesor_digital', 'Sin asesor')} - {cfg.get('agencia', '')}",
            "asesor_digital": cfg.get("asesor_digital", ""),
            "agencia": cfg.get("agencia", ""),
            "business": cfg.get("business", ""),
            "phone_number_id": cfg.get("phone_number_id", ""),

            # Estado real de configuración por número.
            "ia_configurada": bool(config),
            "ia_activa": bool(config.activo) if config else False,
            "en_horario": en_horario,
            "puede_responder_linea": bool(config and config.activo and en_horario),
            "bloqueos_linea": bloqueos,

            "horarios": config.horarios if config else {},
            "config_origen": "especifica" if config else "",
            "numero_config": config.numero_asesor if config else "",
        })

    return Response({
        "ok": True,
        "items": items,
    })

def _usuario_request(request) -> str:
    user = getattr(request, "user", None)

    if user and getattr(user, "is_authenticated", False):
        return (
            getattr(user, "usuario", "")
            or getattr(user, "username", "")
            or getattr(user, "email", "")
            or ""
        ).strip()

    return (
        request.data.get("usuario", "")
        if hasattr(request, "data")
        else ""
    ).strip()


def _rol_usuario(request) -> str:
    user = getattr(request, "user", None)
    rol = getattr(user, "rol", None) if user else None

    return str(
        getattr(rol, "nombre", "")
        or getattr(rol, "name", "")
        or (rol if isinstance(rol, str) else "")
        or ""
    ).strip().lower()


def _usuario_es_admin(request) -> bool:
    return _rol_usuario(request) in ("administrador", "admin")


def _numero_usuario_autenticado(request) -> str:
    user = getattr(request, "user", None)

    if not user or not getattr(user, "is_authenticated", False):
        return ""

    return _normalizar_numero_linea_ia(getattr(user, "telefono", "") or "")


def _numero_solicitado(request) -> str:
    numero = ""

    try:
        numero = request.data.get("numero_asesor", "")
    except Exception:
        numero = ""

    if not numero:
        numero = request.query_params.get("numero_asesor", "")

    return _normalizar_numero_linea_ia(numero)


def _numero_desde_request(request) -> str:
    """
    Resuelve la línea usando el usuario autenticado de la app `usuarios`.

    - Un usuario normal usa el teléfono asignado en usuarios_volvo.
    - Un administrador puede seleccionar otra línea válida.
    - Mientras Volvo tenga una sola línea, se conserva compatibilidad para
      usuarios antiguos que todavía no tengan teléfono configurado.
    """
    numero_usuario = _numero_usuario_autenticado(request)
    numero_solicitado = _numero_solicitado(request)

    if _usuario_es_admin(request):
        return numero_solicitado or numero_usuario or (
            next(iter(WHATSAPP_LINES.keys()), "")
            if len(WHATSAPP_LINES) == 1
            else ""
        )

    if numero_usuario:
        return numero_usuario

    if len(WHATSAPP_LINES) == 1:
        return numero_solicitado or next(iter(WHATSAPP_LINES.keys()), "")

    return ""

def _bool_seguro(valor, default=False) -> bool:
    if isinstance(valor, bool):
        return valor

    if valor in (None, ""):
        return default

    texto = str(valor).strip().lower()

    if texto in ("1", "true", "si", "sí", "yes", "activo"):
        return True

    if texto in ("0", "false", "no", "inactivo"):
        return False

    return bool(valor)


def _serializar_config(item):
    numero = item.numero_asesor or ""
    linea = WHATSAPP_LINES.get(numero, {})

    return {
        "id": item.id,
        "numero_asesor": numero,

        "key": linea.get("key", ""),
        "asesor_digital": linea.get("asesor_digital", ""),
        "agencia": linea.get("agencia", ""),
        "business": linea.get("business", ""),
        "phone_number_id": linea.get("phone_number_id", ""),

        "activo": item.activo,
        "horarios": item.horarios or {},

        "identidad": item.identidad or "",
        "precios": item.precios or "",
        "perfilamiento": item.perfilamiento or "",
        "limites": item.limites or "",
        "personalidad": item.personalidad or "",
        "condiciones_fijas": item.condiciones_fijas or "",
        "promociones_eventos": item.promociones_eventos or "",
        "actualizado_por": item.actualizado_por or "",

        "config_origen": "especifica",
    }

def _get_or_create_config(numero_asesor: str) -> ConfiguracionIAWhatsApp:
    """
    Crea o recupera la configuración propia de una línea real de WhatsApp.

    Importante:
    - No permite GLOBAL.
    - No hereda configuración de otra línea.
    - Si la línea no tiene configuración, crea una configuración vacía e inactiva.
    """
    numero_asesor = _normalizar_numero_linea_ia(numero_asesor)

    if not numero_asesor:
        raise ValueError("Número de asesor inválido o no registrado en WHATSAPP_LINES.")

    item, _ = ConfiguracionIAWhatsApp.objects.get_or_create(
        numero_asesor=numero_asesor,
        defaults={
            "activo": False,
            "horarios": {},
            "identidad": "",
            "precios": "",
            "perfilamiento": "",
            "limites": "",
            "personalidad": "",
            "condiciones_fijas": CONDICIONES_FIJAS_DEFAULT,
            "promociones_eventos": "",
            "actualizado_por": "",
        },
    )

    return item

def _aplicar_payload_config(
    item: ConfiguracionIAWhatsApp,
    data: dict[str, Any],
    actualizado_por: str = "",
) -> ConfiguracionIAWhatsApp:
    campos_texto = [
        "identidad",
        "precios",
        "perfilamiento",
        "limites",
        "personalidad",
        "condiciones_fijas",
        "promociones_eventos",
    ]

    for campo in campos_texto:
        if campo in data:
            setattr(item, campo, str(data.get(campo) or ""))

    if "activo" in data:
        item.activo = _bool_seguro(data.get("activo"), default=item.activo)

    if "horarios" in data:
        horarios = data.get("horarios")
        item.horarios = horarios if isinstance(horarios, dict) else {}

    if actualizado_por:
        item.actualizado_por = actualizado_por

    return item


@api_view(["GET", "POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def ia_config_list(request):
    """
    GET:
    - Devuelve únicamente configuraciones por número real.
    - No devuelve GLOBAL como configuración operativa.

    POST:
    - Crea/actualiza configuración para un número específico.
    """
    if request.method == "GET":
        qs = (
            ConfiguracionIAWhatsApp.objects
            .exclude(numero_asesor=IA_CONFIG_GLOBAL_KEY)
            .filter(numero_asesor__in=WHATSAPP_LINES.keys())
            .order_by("numero_asesor")
        )

        return Response(
            {
                "ok": True,
                "items": [_serializar_config(item) for item in qs],
            },
            status=status.HTTP_200_OK,
        )

    numero_asesor = _normalizar_numero_linea_ia(
        request.data.get("numero_asesor", "")
    )

    if not numero_asesor:
        return Response(
            {
                "ok": False,
                "error": "Falta numero_asesor válido. Debe ser una línea registrada en WHATSAPP_LINES.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        item = _get_or_create_config(numero_asesor)
    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    item = _aplicar_payload_config(
        item,
        request.data or {},
        actualizado_por=_usuario_request(request),
    )
    item.save()

    return Response(
        {
            "ok": True,
            "item": _serializar_config(item),
        },
        status=status.HTTP_200_OK,
    )

@api_view(["GET", "PATCH", "PUT"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def ia_config_detail(request, numero_asesor: str):
    """
    Consulta o actualiza la configuración propia de una línea.

    Nota:
    - El número válido es el del path:
      /digitales/ia/config/<numero_asesor>/
    - No se toma GLOBAL ni se hereda configuración de otra línea.
    """
    numero_asesor = _normalizar_numero_linea_ia(numero_asesor)

    if not numero_asesor:
        return Response(
            {
                "ok": False,
                "error": "Número de asesor inválido o no registrado en WHATSAPP_LINES.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        item = _get_or_create_config(numero_asesor)
    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if request.method == "GET":
        return Response(
            {
                "ok": True,
                "item": _serializar_config(item),
            },
            status=status.HTTP_200_OK,
        )

    item = _aplicar_payload_config(
        item,
        request.data or {},
        actualizado_por=_usuario_request(request),
    )
    item.save()

    return Response(
        {
            "ok": True,
            "item": _serializar_config(item),
        },
        status=status.HTTP_200_OK,
    )

@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def ia_config_publicar(request, numero_asesor: str):
    """
    Activa/publica únicamente la configuración del número indicado.
    No activa GLOBAL ni afecta otras líneas.
    """
    numero_asesor = _normalizar_numero_linea_ia(numero_asesor)

    if not numero_asesor:
        return Response(
            {
                "ok": False,
                "error": "Número de asesor inválido o no registrado en WHATSAPP_LINES.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        item = _get_or_create_config(numero_asesor)
    except ValueError as exc:
        return Response(
            {
                "ok": False,
                "error": str(exc),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    item.activo = True
    item.actualizado_por = _usuario_request(request)
    item.save(update_fields=["activo", "actualizado_por"])

    return Response({
        "ok": True,
        "item": _serializar_config(item),
    })

def _obtener_expediente_por_tel(tel: str):
    tel = normaliza_tel_mx(tel)

    if not tel:
        return None

    cliente = ClienteComercial.objects.filter(telefono=tel).first()

    if not cliente:
        return None

    return ExpedienteDigital.objects.filter(cliente=cliente).first()


@api_view(["GET"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def ia_estado_conversacion(request):
    tel = normaliza_tel_mx(request.query_params.get("tel", ""))
    numero_asesor = _numero_desde_request(request)

    if not tel:
        return Response(
            {"ok": False, "error": "Falta tel."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not numero_asesor:
        return Response(
            {"ok": False, "error": "Falta numero_asesor."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            "ok": True,
            "estado_ia": obtener_estado_ia_conversacion(
                tel=tel,
                numero_asesor=numero_asesor,
            ),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def ia_pausar_conversacion(request):
    tel = normaliza_tel_mx(request.data.get("tel", ""))
    numero_asesor = _numero_desde_request(request)
    motivo = (request.data.get("motivo") or "manual").strip()[:120]

    if not tel:
        return Response(
            {
                "ok": False,
                "error": "Falta tel.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not numero_asesor:
        return Response(
            {
                "ok": False,
                "error": "Falta numero_asesor.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    expediente = _obtener_expediente_por_tel(tel)

    if not expediente:
        return Response(
            {
                "ok": False,
                "error": "No existe expediente para ese teléfono.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    expediente.ia_pausada = True
    expediente.ia_pausada_motivo = motivo
    expediente.ia_pausada_at = timezone.now()
    expediente.save(
        update_fields=[
            "ia_pausada",
            "ia_pausada_motivo",
            "ia_pausada_at",
            "actualizado",
        ]
    )

    conversacion, _ = ConversacionIA.objects.get_or_create(
        expediente=expediente,
        numero_asesor=numero_asesor,
    )
    conversacion.ia_activa = False
    conversacion.ia_pausada = True
    conversacion.motivo_pausa = motivo
    conversacion.estado_conversacion = "pausada"
    conversacion.save(
        update_fields=[
            "ia_activa",
            "ia_pausada",
            "motivo_pausa",
            "estado_conversacion",
        ]
    )

    return Response(
        {
            "ok": True,
            "mensaje": "IA pausada correctamente.",
            "estado_ia": obtener_estado_ia_conversacion(
                tel=tel,
                numero_asesor=numero_asesor,
            ),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def ia_reactivar_conversacion(request):
    tel = normaliza_tel_mx(request.data.get("tel", ""))
    numero_asesor = _numero_desde_request(request)

    if not tel:
        return Response(
            {
                "ok": False,
                "error": "Falta tel.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not numero_asesor:
        return Response(
            {
                "ok": False,
                "error": "Falta numero_asesor.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    expediente = _obtener_expediente_por_tel(tel)

    if not expediente:
        return Response(
            {
                "ok": False,
                "error": "No existe expediente para ese teléfono.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    expediente.ia_pausada = False
    expediente.ia_pausada_motivo = ""
    expediente.ia_pausada_at = None
    expediente.save(
        update_fields=[
            "ia_pausada",
            "ia_pausada_motivo",
            "ia_pausada_at",
            "actualizado",
        ]
    )

    conversacion, _ = ConversacionIA.objects.get_or_create(
        expediente=expediente,
        numero_asesor=numero_asesor,
    )
    conversacion.ia_activa = True
    conversacion.ia_pausada = False
    conversacion.motivo_pausa = ""
    conversacion.estado_conversacion = "informando"
    conversacion.save(
        update_fields=[
            "ia_activa",
            "ia_pausada",
            "motivo_pausa",
            "estado_conversacion",
        ]
    )

    return Response(
        {
            "ok": True,
            "mensaje": "IA reactivada correctamente.",
            "estado_ia": obtener_estado_ia_conversacion(
                tel=tel,
                numero_asesor=numero_asesor,
            ),
        },
        status=status.HTTP_200_OK,
    )