# Digitales/contacto.py
import mimetypes
import re
import time

import requests

from citas.models import normaliza_tel_mx

from .sett import (
    GRAPH_VERSION,
    WHATSAPP_LINES,
    WHATSAPP_PHONE_ID_TO_NUMBER,
    whatsapp_token,
)

try:
    from .sett import WHATSAPP_TEMPLATE_UI
except ImportError:
    WHATSAPP_TEMPLATE_UI = {}

DEFAULT_IDIOMA = "es_MX"

def _get_access_token(cfg: dict) -> str:
    token_linea = str((cfg or {}).get("access_token") or "").strip()

    if token_linea:
        return token_linea

    return whatsapp_token


def _json_headers(cfg: dict) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_access_token(cfg)}",
    }


def _auth_headers(cfg: dict) -> dict:
    return {
        "Authorization": f"Bearer {_get_access_token(cfg)}",
    }

def _meta_error(r):
    try:
        return r.json()
    except Exception:
        return {"text": r.text}


def _graph_base_from_messages_url(messages_url: str) -> str:
    url = (messages_url or "").strip().rstrip("/")

    if not url:
        return ""

    if url.endswith("/messages"):
        return url[: -len("/messages")]

    return url


def _graph_root_from_messages_url(messages_url: str) -> str:
    base = _graph_base_from_messages_url(messages_url)

    if not base:
        return ""

    return "/".join(base.split("/")[:-1])


def _normaliza_numero_asesor(numero: str) -> str:
    return normaliza_tel_mx(numero or "")


def obtener_config_linea(
    *,
    numero_asesor: str = "",
    phone_number_id: str = "",
    display_phone_number: str = "",
) -> dict:
    if numero_asesor:
        numero_normalizado = _normaliza_numero_asesor(numero_asesor)
        cfg = WHATSAPP_LINES.get(numero_normalizado)

        if cfg:
            return {
                **cfg,
                "numero_asesor": numero_normalizado,
            }

    if phone_number_id:
        phone_number_id = str(phone_number_id or "").strip()
        numero = WHATSAPP_PHONE_ID_TO_NUMBER.get(phone_number_id)

        if numero:
            cfg = WHATSAPP_LINES[numero]

            return {
                **cfg,
                "numero_asesor": numero,
            }

    if display_phone_number:
        numero_normalizado = _normaliza_numero_asesor(display_phone_number)
        cfg = WHATSAPP_LINES.get(numero_normalizado)

        if cfg:
            return {
                **cfg,
                "numero_asesor": numero_normalizado,
            }

    raise ValueError("No se encontró una línea de WhatsApp configurada para ese número.")


def obtener_numero_asesor_desde_webhook_value(value: dict) -> str:
    metadata = value.get("metadata") or {}

    phone_number_id = str(metadata.get("phone_number_id") or "").strip()
    display_phone_number = str(metadata.get("display_phone_number") or "").strip()

    try:
        cfg = obtener_config_linea(
            phone_number_id=phone_number_id,
            display_phone_number=display_phone_number,
        )
        return cfg["numero_asesor"]
    except Exception:
        return ""


def _post_messages_api(cfg: dict, payload: dict, max_retries: int = 2) -> dict:
    messages_url = cfg["messages_url"]
    headers = _json_headers(cfg)

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                messages_url,
                headers=headers,
                json=payload,
                timeout=20,
            )

            if r.status_code < 400:
                return r.json()

            error_body = _meta_error(r)
            should_retry = r.status_code in (408, 409, 429) or r.status_code >= 500

            if not should_retry or attempt >= max_retries:
                raise RuntimeError(f"Meta error {r.status_code}: {error_body}")

            time.sleep(1.2 * (attempt + 1))

        except requests.RequestException as exc:
            last_error = exc

            if attempt >= max_retries:
                raise RuntimeError(f"Error de conexión con Meta: {str(exc)}")

            time.sleep(1.2 * (attempt + 1))

    raise RuntimeError(f"No se pudo enviar a Meta. Último error: {str(last_error)}")

def enviar_texto_whatsapp(to: str, text: str, numero_asesor: str) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {
            "body": text,
        },
    }

    return _post_messages_api(cfg, payload)

def enviar_template_whatsapp(
    to: str,
    template_name: str,
    numero_asesor: str,
    params: list[str] | None = None,
    idioma: str = DEFAULT_IDIOMA,
    components: list[dict] | None = None,
) -> dict:
    if not to:
        raise ValueError("Falta número destino")

    if not template_name:
        raise ValueError("Falta template_name")

    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    idioma = (idioma or DEFAULT_IDIOMA).strip()

    template_payload = {
        "name": template_name,
        "language": {
            "code": idioma,
        },
    }

    if components:
        norm_components = []

        for component in components:
            ctype = str(component.get("type", "")).lower().strip()

            if ctype == "buttons":
                ctype = "button"

            if ctype not in ("header", "body", "footer", "button"):
                continue

            item = {
                "type": ctype,
            }

            if "parameters" in component:
                item["parameters"] = component["parameters"]

            if "sub_type" in component:
                item["sub_type"] = component["sub_type"]

            if "index" in component:
                item["index"] = component["index"]

            norm_components.append(item)

        if norm_components:
            template_payload["components"] = norm_components

    elif params:
        template_payload["components"] = [
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": str(value),
                    }
                    for value in params
                ],
            }
        ]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template_payload,
    }

    return _post_messages_api(cfg, payload)


def subir_media_whatsapp(
    file_obj,
    numero_asesor: str,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    base = _graph_base_from_messages_url(cfg["messages_url"])
    if not base:
        raise RuntimeError("No se pudo derivar la URL base de la línea de WhatsApp.")

    media_url = f"{base}/media"

    headers = _auth_headers(cfg)

    ct = content_type or ""

    if not ct and filename:
        ct = mimetypes.guess_type(filename)[0] or ""

    files = {
        "file": (
            filename or getattr(file_obj, "name", "file"),
            file_obj,
            ct or "application/octet-stream",
        ),
    }

    data = {
        "messaging_product": "whatsapp",
    }

    r = requests.post(
        media_url,
        headers=headers,
        files=files,
        data=data,
        timeout=45,
    )

    if r.status_code >= 400:
        raise RuntimeError(f"Meta media upload error {r.status_code}: {_meta_error(r)}")

    return r.json()


def enviar_media_whatsapp(
    to: str,
    media_id: str,
    media_type: str,
    numero_asesor: str,
    caption: str = "",
    filename: str = "",
) -> dict:
    if media_type not in ("image", "document", "video", "audio"):
        raise ValueError("media_type inválido")

    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": media_type,
        media_type: {
            "id": media_id,
        },
    }

    if caption and media_type in ("image", "video", "document"):
        payload[media_type]["caption"] = caption

    if filename and media_type == "document":
        payload[media_type]["filename"] = filename

    return _post_messages_api(cfg, payload)


def editar_texto_whatsapp(
    to: str,
    original_message_id: str,
    new_text: str,
    numero_asesor: str,
) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "context": {
            "message_id": original_message_id,
        },
        "text": {
            "body": new_text,
        },
    }

    return _post_messages_api(cfg, payload)


def get_media_info_whatsapp(media_id: str, numero_asesor: str = "") -> dict:
    if numero_asesor:
        cfg = obtener_config_linea(numero_asesor=numero_asesor)
    else:
        cfg = next(iter(WHATSAPP_LINES.values()))

    graph_root = _graph_root_from_messages_url(cfg["messages_url"])

    if not graph_root:
        raise RuntimeError("No se pudo derivar graph_root.")

    url = f"{graph_root}/{media_id}"
    headers = _auth_headers(cfg)

    r = requests.get(
        url,
        headers=headers,
        timeout=20,
    )

    if r.status_code >= 400:
        raise RuntimeError(f"Meta media info error {r.status_code}: {r.text}")

    return r.json()


def download_media_whatsapp(media_id: str, numero_asesor: str = "") -> tuple[bytes, str]:
    if numero_asesor:
        cfg = obtener_config_linea(numero_asesor=numero_asesor)
    else:
        cfg = next(iter(WHATSAPP_LINES.values()))

    info = get_media_info_whatsapp(media_id, numero_asesor=numero_asesor)
    media_url = info.get("url") or ""

    if not media_url:
        raise RuntimeError(f"Meta no regresó url para media_id={media_id}: {info}")

    headers = _auth_headers(cfg)

    r = requests.get(
        media_url,
        headers=headers,
        timeout=45,
    )

    if r.status_code >= 400:
        raise RuntimeError(f"Meta media download error {r.status_code}: {r.text}")

    content_type = (
        r.headers.get("content-type")
        or info.get("mime_type")
        or "application/octet-stream"
    )

    return r.content, content_type


def obtener_mensaje_whatsapp(message: dict) -> str:
    if not isinstance(message, dict) or "type" not in message:
        return "mensaje no reconocido"

    message_type = message["type"]

    if message_type == "text":
        return message.get("text", {}).get("body", "")

    if message_type == "button":
        return message.get("button", {}).get("text", "")

    if message_type == "interactive":
        interactive = message.get("interactive", {})

        if interactive.get("type") == "list_reply":
            return interactive.get("list_reply", {}).get("title", "")

        if interactive.get("type") == "button_reply":
            return interactive.get("button_reply", {}).get("title", "")

    if message_type in ("image", "document", "video", "audio", "sticker"):
        caption = ""

        if message_type in ("image", "video", "document"):
            caption = (message.get(message_type) or {}).get("caption") or ""

        return caption.strip() or f"[{message_type.upper()}]"

    return "mensaje no procesado"


def replace_start(s: str) -> str:
    digits = "".join(char for char in str(s or "") if char.isdigit())

    if digits.startswith("521"):
        return "52" + digits[3:]

    return digits


def enviar_imagen_whatsapp_por_link(
    to: str,
    link: str,
    numero_asesor: str,
    caption: str = "",
) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    headers = _json_headers(cfg)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "image",
        "image": {
            "link": link,
        },
    }

    if caption:
        payload["image"]["caption"] = caption

    r = requests.post(
        cfg["messages_url"],
        headers=headers,
        json=payload,
        timeout=20,
    )

    if r.status_code >= 400:
        raise RuntimeError(f"Meta send image link error {r.status_code}: {_meta_error(r)}")

    return r.json()


def enviar_documento_whatsapp_por_link(
    to: str,
    link: str,
    numero_asesor: str,
    caption: str = "",
    filename: str = "ficha-tecnica.pdf",
) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    headers = _json_headers(cfg)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "document",
        "document": {
            "link": link,
            "filename": filename,
        },
    }

    if caption:
        payload["document"]["caption"] = caption

    r = requests.post(
        cfg["messages_url"],
        headers=headers,
        json=payload,
        timeout=20,
    )

    if r.status_code >= 400:
        raise RuntimeError(f"Meta send document link error {r.status_code}: {_meta_error(r)}")

    return r.json()


def _extraer_variables(texto: str) -> list[int]:
    encontrados = re.findall(r"\{\{(\d+)\}\}", str(texto or ""))
    return sorted({int(item) for item in encontrados})


def _texto_visible_desde_componentes(components: list[dict]) -> str:
    partes = []

    for component in components or []:
        tipo = str(component.get("type") or "").upper()
        texto = str(component.get("text") or "").strip()

        if tipo in ("HEADER", "BODY", "FOOTER") and texto:
            partes.append(texto)

    texto_final = "\n".join(partes)
    texto_final = re.sub(r"\{\{(\d+)\}\}", r"(\1)", texto_final)

    return texto_final


def _normalizar_template_meta(template: dict) -> dict:
    nombre = str(template.get("name") or "").strip()
    idioma = str(template.get("language") or DEFAULT_IDIOMA).strip()
    status = str(template.get("status") or "").strip()
    category = str(template.get("category") or "").strip()
    template_id = str(template.get("id") or "").strip()
    components = template.get("components") or []

    fields = []

    for component in components:
        tipo = str(component.get("type") or "").lower()
        texto = str(component.get("text") or "")

        if tipo not in ("header", "body"):
            continue

        variables = _extraer_variables(texto)

        for variable_index in variables:
            key = f"{tipo}_{variable_index}"

            fields.append({
                "key": key,
                "label": f"{tipo.capitalize()} parámetro {variable_index}",
                "type": "text",
                "component": tipo,
                "index": variable_index,
            })

    ui = WHATSAPP_TEMPLATE_UI.get(nombre, {}) if isinstance(WHATSAPP_TEMPLATE_UI, dict) else {}
    labels = ui.get("labels") or {}

    for field in fields:
        if field["key"] in labels:
            field["label"] = labels[field["key"]]

    help_text = ui.get("help") or _texto_visible_desde_componentes(components)

    return {
        "id": template_id,
        "key": nombre,
        "name": nombre,
        "title": ui.get("title") or nombre.replace("_", " ").title(),
        "idioma": idioma,
        "language": idioma,
        "status": status,
        "category": category,
        "help": help_text,
        "fields": fields,
        "components_meta": components,
    }


def obtener_templates_whatsapp(numero_asesor: str) -> list[dict]:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    waba_id = str(cfg.get("waba_id") or "").strip()

    if not waba_id:
        raise ValueError("Esta línea no tiene waba_id configurado en WHATSAPP_LINES.")

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/message_templates"

    headers = _auth_headers(cfg)

    params = {
        "fields": "name,status,category,language,components,id",
        "limit": 200,
    }

    r = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=25,
    )

    if r.status_code >= 400:
        raise RuntimeError(f"Meta templates error {r.status_code}: {_meta_error(r)}")

    data = r.json()
    items = data.get("data") or []

    permitidas = set(cfg.get("template_names") or [])

    salida = []

    for item in items:
        normalizada = _normalizar_template_meta(item)

        if normalizada["status"].upper() != "APPROVED":
            continue

        if permitidas and normalizada["key"] not in permitidas:
            continue

        salida.append(normalizada)

    return sorted(salida, key=lambda item: item["title"].lower())