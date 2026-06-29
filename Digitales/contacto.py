# Digitales/contacto.py
import hashlib
import logging
import mimetypes
import random
import re
import time

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from citas.models import normaliza_tel_mx

from .sett import GRAPH_VERSION, WHATSAPP_LINES, WHATSAPP_PHONE_ID_TO_NUMBER, whatsapp_token

try:
    from .sett import WHATSAPP_TEMPLATE_UI
except ImportError:
    WHATSAPP_TEMPLATE_UI = {}

DEFAULT_IDIOMA = "es_MX"
MEDIA_CACHE_DIR = "whatsapp_media_cache_volvo"

EXTENSIONES_MEDIA = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "application/pdf": ".pdf",
}

logger = logging.getLogger(__name__)


class MetaAPIError(RuntimeError):
    def __init__(
        self,
        *,
        status_code=0,
        error_body=None,
        retryable=False,
        attempts=1,
        message="Error al comunicarse con Meta.",
    ):
        self.status_code = int(status_code or 0)
        self.error_body = error_body or {}
        self.retryable = bool(retryable)
        self.attempts = int(attempts or 1)

        error = self._extraer_error()
        self.meta_message = str(error.get("message") or message)
        self.meta_type = str(error.get("type") or "")
        self.meta_code = error.get("code")
        self.meta_subcode = error.get("error_subcode") or error.get("subcode")
        self.fbtrace_id = str(error.get("fbtrace_id") or "")
        self.is_transient = bool(error.get("is_transient"))

        super().__init__(self.meta_message)

    def _extraer_error(self):
        if isinstance(self.error_body, dict):
            error = self.error_body.get("error")
            if isinstance(error, dict):
                return error
            return self.error_body
        return {}

    def to_dict(self):
        return {
            "provider": "meta",
            "status_code": self.status_code,
            "message": self.meta_message,
            "type": self.meta_type,
            "code": self.meta_code,
            "subcode": self.meta_subcode,
            "is_transient": self.is_transient,
            "retryable": self.retryable,
            "attempts": self.attempts,
            "fbtrace_id": self.fbtrace_id,
            "raw": self.error_body,
        }


class MetaMediaError(RuntimeError):
    def __init__(self, *, media_id: str, status_code: int, error_body=None, numero_asesor: str = ""):
        self.media_id = str(media_id or "")
        self.status_code = int(status_code or 0)
        self.error_body = error_body or {}
        self.numero_asesor = numero_asesor

        error = self._extraer_error()
        self.meta_message = str(error.get("message") or "Error consultando media de Meta.")
        self.meta_type = str(error.get("type") or "")
        self.meta_code = error.get("code")
        self.meta_subcode = error.get("error_subcode") or error.get("subcode")
        self.fbtrace_id = str(error.get("fbtrace_id") or "")

        super().__init__(self.meta_message)

    def _extraer_error(self):
        if isinstance(self.error_body, dict):
            error = self.error_body.get("error")
            if isinstance(error, dict):
                return error
            return self.error_body
        return {}

    def es_media_no_disponible(self) -> bool:
        return self.meta_code == 100 and self.meta_subcode == 33

    def to_dict(self):
        return {
            "provider": "meta",
            "media_id": self.media_id,
            "status_code": self.status_code,
            "message": self.meta_message,
            "type": self.meta_type,
            "code": self.meta_code,
            "subcode": self.meta_subcode,
            "fbtrace_id": self.fbtrace_id,
            "numero_asesor": self.numero_asesor,
            "raw": self.error_body,
        }


def _extraer_error_meta(error_body):
    if isinstance(error_body, dict):
        error = error_body.get("error")
        if isinstance(error, dict):
            return error
        return error_body
    return {}


def _es_error_meta_reintentable(status_code: int, error_body: dict) -> bool:
    error = _extraer_error_meta(error_body)
    meta_code = error.get("code")
    is_transient = bool(error.get("is_transient"))

    if is_transient:
        return True

    if status_code in (408, 409, 425, 429, 500, 502, 503, 504):
        return True

    return meta_code in (1, 2, 4, 17, 32, 613)


def _segundos_para_reintento(attempt: int, response=None) -> float:
    retry_after = ""
    if response is not None:
        retry_after = response.headers.get("Retry-After", "") or ""

    try:
        retry_after_num = float(retry_after)
        if 0 < retry_after_num <= 60:
            return retry_after_num
    except (TypeError, ValueError):
        pass

    return min(2 ** attempt, 12) + random.uniform(0.2, 1.2)


def _safe_media_id(media_id: str) -> str:
    value = str(media_id or "").strip()
    value = "".join(c for c in value if c.isalnum() or c in ("_", "-", "."))
    return value or hashlib.sha256(str(media_id or "").encode("utf-8")).hexdigest()


def _extension_por_content_type(content_type: str) -> str:
    content_type = str(content_type or "").split(";")[0].strip().lower()
    if content_type in EXTENSIONES_MEDIA:
        return EXTENSIONES_MEDIA[content_type]
    return mimetypes.guess_extension(content_type) or ".bin"


def _content_type_por_path(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _media_cache_path(media_id: str, content_type: str) -> str:
    return f"{MEDIA_CACHE_DIR}/{_safe_media_id(media_id)}{_extension_por_content_type(content_type)}"


def _buscar_media_en_cache(media_id: str):
    safe_id = _safe_media_id(media_id)
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".ogg", ".mp3", ".pdf", ".bin"):
        path = f"{MEDIA_CACHE_DIR}/{safe_id}{ext}"
        if not default_storage.exists(path):
            continue
        with default_storage.open(path, "rb") as archivo:
            return archivo.read(), _content_type_por_path(path)
    return None


def _guardar_media_en_cache(media_id: str, blob: bytes, content_type: str) -> str:
    path = _media_cache_path(media_id, content_type)
    if not default_storage.exists(path):
        default_storage.save(path, ContentFile(blob))
    return path


def _get_access_token(cfg: dict) -> str:
    token_linea = str((cfg or {}).get("access_token") or "").strip()
    return token_linea or whatsapp_token


def _json_headers(cfg: dict) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_access_token(cfg)}",
    }


def _auth_headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {_get_access_token(cfg)}"}


def _meta_error(response):
    try:
        return response.json()
    except Exception:
        return {"text": response.text}


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


def obtener_config_linea(*, numero_asesor: str = "", phone_number_id: str = "", display_phone_number: str = "") -> dict:
    if numero_asesor:
        numero_normalizado = _normaliza_numero_asesor(numero_asesor)
        cfg = WHATSAPP_LINES.get(numero_normalizado)
        if cfg:
            return {**cfg, "numero_asesor": numero_normalizado}

    if phone_number_id:
        phone_number_id = str(phone_number_id or "").strip()
        numero = WHATSAPP_PHONE_ID_TO_NUMBER.get(phone_number_id)
        if numero:
            cfg = WHATSAPP_LINES[numero]
            return {**cfg, "numero_asesor": numero}

    if display_phone_number:
        numero_normalizado = _normaliza_numero_asesor(display_phone_number)
        cfg = WHATSAPP_LINES.get(numero_normalizado)
        if cfg:
            return {**cfg, "numero_asesor": numero_normalizado}

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
        logger.warning(
            "No se pudo mapear línea WhatsApp | phone_number_id=%s display_phone_number=%s",
            phone_number_id,
            display_phone_number,
        )
        return ""


def _post_messages_api(cfg: dict, payload: dict, max_retries: int = 3) -> dict:
    messages_url = cfg["messages_url"]
    headers = _json_headers(cfg)

    log_context = {
        "line_key": cfg.get("key", ""),
        "phone_number_id": cfg.get("phone_number_id", ""),
        "numero_asesor": cfg.get("numero_asesor", ""),
        "payload_type": payload.get("type", ""),
        "template": (payload.get("template") or {}).get("name", ""),
    }

    last_error = None
    attempts_total = max_retries + 1

    for attempt in range(attempts_total):
        intento_actual = attempt + 1

        try:
            response = requests.post(messages_url, headers=headers, json=payload, timeout=(5, 30))

            if response.status_code < 400:
                data = response.json()
                logger.info("META WHATSAPP OK | intento=%s/%s | contexto=%s", intento_actual, attempts_total, log_context)
                return data

            error_body = _meta_error(response)
            retryable = _es_error_meta_reintentable(response.status_code, error_body)
            last_error = MetaAPIError(
                status_code=response.status_code,
                error_body=error_body,
                retryable=retryable,
                attempts=intento_actual,
                message="Meta rechazó el envío.",
            )

            if not retryable or attempt >= max_retries:
                logger.warning("META WHATSAPP ERROR FINAL | contexto=%s | error=%s", log_context, last_error.to_dict())
                raise last_error

            time.sleep(_segundos_para_reintento(attempt, response=response))

        except MetaAPIError:
            raise

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = MetaAPIError(
                status_code=0,
                error_body={"error": {"message": str(exc), "type": exc.__class__.__name__, "is_transient": True}},
                retryable=True,
                attempts=intento_actual,
                message="Error temporal de conexión con Meta.",
            )

            if attempt >= max_retries:
                raise last_error

            time.sleep(_segundos_para_reintento(attempt))

        except requests.RequestException as exc:
            raise MetaAPIError(
                status_code=0,
                error_body={"error": {"message": str(exc), "type": exc.__class__.__name__, "is_transient": False}},
                retryable=False,
                attempts=intento_actual,
                message="Error de request hacia Meta.",
            )

    if isinstance(last_error, MetaAPIError):
        raise last_error

    raise MetaAPIError(retryable=True, attempts=attempts_total)


def enviar_indicador_escribiendo_whatsapp(*, message_id: str, numero_asesor: str) -> dict:
    message_id = str(message_id or "").strip()
    if not message_id:
        return {"success": False, "skipped": True, "reason": "sin_message_id"}

    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    return _post_messages_api(cfg, payload)


def enviar_texto_whatsapp(to: str, text: str, numero_asesor: str, reply_to_message_id: str = "", preview_url: bool = False) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": bool(preview_url)},
    }

    reply_to_message_id = str(reply_to_message_id or "").strip()
    if reply_to_message_id:
        payload["context"] = {"message_id": reply_to_message_id}

    return _post_messages_api(cfg, payload)


def _normalizar_parametro_template(param: dict) -> dict | None:
    if not isinstance(param, dict):
        return None

    ptype = str(param.get("type") or "text").lower().strip()

    if ptype == "text":
        texto = str(param.get("text") or "").strip()

        if not texto:
            raise ValueError("Hay un parámetro de texto vacío en la plantilla.")

        return {
            "type": "text",
            "text": texto,
        }

    if ptype in ("image", "video", "document"):
        media_payload = param.get(ptype) or {}

        if isinstance(media_payload, str):
            media_payload = {"link": media_payload}

        media = {}

        media_id = str(media_payload.get("id") or "").strip()
        media_link = str(media_payload.get("link") or "").strip()

        if media_id:
            media["id"] = media_id
        elif media_link:
            media["link"] = media_link
        else:
            raise ValueError(
                f"El parámetro {ptype} necesita id o link."
            )

        if ptype == "document":
            filename = str(media_payload.get("filename") or "").strip()

            if filename:
                media["filename"] = filename

        return {
            "type": ptype,
            ptype: media,
        }

    if ptype == "payload":
        payload = str(param.get("payload") or "").strip()

        if not payload:
            raise ValueError("Hay un botón sin payload.")

        return {
            "type": "payload",
            "payload": payload,
        }

    return param


def _ya_viene_header_template(components: list[dict]) -> bool:
    for component in components or []:
        ctype = str(component.get("type") or "").lower().strip()

        if ctype == "header":
            return True

    return False


def _header_media_desde_settings(template_name: str, components: list[dict]) -> dict | None:
    if _ya_viene_header_template(components):
        return None

    ui = WHATSAPP_TEMPLATE_UI.get(template_name, {}) if isinstance(WHATSAPP_TEMPLATE_UI, dict) else {}
    header = ui.get("header") or {}

    header_type = str(header.get("type") or "").lower().strip()

    if header_type not in ("image", "video", "document"):
        return None

    media = {}

    media_id = str(header.get("id") or "").strip()
    media_link = str(header.get("link") or "").strip()

    if media_id:
        media["id"] = media_id
    elif media_link:
        media["link"] = media_link
    else:
        raise ValueError(
            f"La plantilla {template_name} tiene header {header_type}, "
            "pero falta configurar id o link en WHATSAPP_TEMPLATE_UI."
        )

    if header_type == "document":
        filename = str(header.get("filename") or "documento.pdf").strip()
        media["filename"] = filename

    return {
        "type": "header",
        "parameters": [
            {
                "type": header_type,
                header_type: media,
            }
        ],
    }


def _normalizar_components_template(template_name: str, components: list[dict] | None) -> list[dict]:
    norm_components = []

    for component in components or []:
        if not isinstance(component, dict):
            continue

        ctype = str(component.get("type") or "").lower().strip()

        if ctype == "buttons":
            ctype = "button"

        if ctype not in ("header", "body", "footer", "button"):
            continue

        item = {
            "type": ctype,
        }

        parameters = []

        for param in component.get("parameters") or []:
            normalizado = _normalizar_parametro_template(param)

            if normalizado:
                parameters.append(normalizado)

        if parameters:
            item["parameters"] = parameters

        if ctype == "button":
            if "sub_type" in component:
                item["sub_type"] = component["sub_type"]

            if "index" in component:
                item["index"] = str(component["index"])

        # Meta no necesita footer si no lleva parámetros.
        if ctype in ("header", "body", "button") and not item.get("parameters"):
            continue

        norm_components.append(item)

    header_media = _header_media_desde_settings(
        template_name=template_name,
        components=norm_components,
    )

    if header_media:
        norm_components.insert(0, header_media)

    return norm_components


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

    norm_components = _normalizar_components_template(
        template_name=template_name,
        components=components,
    )

    if norm_components:
        template_payload["components"] = norm_components

    elif params:
        template_payload["components"] = [
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": str(value).strip(),
                    }
                    for value in params
                    if str(value).strip()
                ],
            }
        ]

    # Importante:
    # Si no hay params pero la plantilla tiene header multimedia estático en
    # WHATSAPP_TEMPLATE_UI, lo inyectamos aunque components venga vacío.
    if "components" not in template_payload:
        header_media = _header_media_desde_settings(
            template_name=template_name,
            components=[],
        )

        if header_media:
            template_payload["components"] = [header_media]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template_payload,
    }

    return _post_messages_api(cfg, payload)

def subir_media_whatsapp(file_obj, numero_asesor: str, filename: str | None = None, content_type: str | None = None) -> dict:
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
        )
    }
    data = {"messaging_product": "whatsapp"}

    response = requests.post(media_url, headers=headers, files=files, data=data, timeout=45)

    if response.status_code >= 400:
        raise MetaAPIError(
            status_code=response.status_code,
            error_body=_meta_error(response),
            retryable=_es_error_meta_reintentable(response.status_code, _meta_error(response)),
            message="Meta rechazó la subida de media.",
        )

    return response.json()


def enviar_media_whatsapp(
    to: str,
    media_id: str,
    media_type: str,
    numero_asesor: str,
    caption: str = "",
    filename: str = "",
    reply_to_message_id: str = "",
) -> dict:
    if media_type not in ("image", "document", "video", "audio", "sticker"):
        raise ValueError("media_type inválido")

    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": media_type,
        media_type: {"id": media_id},
    }

    reply_to_message_id = str(reply_to_message_id or "").strip()
    if reply_to_message_id:
        payload["context"] = {"message_id": reply_to_message_id}

    if caption and media_type in ("image", "video", "document"):
        payload[media_type]["caption"] = caption

    if filename and media_type == "document":
        payload[media_type]["filename"] = filename

    return _post_messages_api(cfg, payload)


def editar_texto_whatsapp(to: str, original_message_id: str, new_text: str, numero_asesor: str) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "context": {"message_id": original_message_id},
        "text": {"body": new_text},
    }
    return _post_messages_api(cfg, payload)


def get_media_info_whatsapp(media_id: str, numero_asesor: str = "") -> dict:
    media_id = str(media_id or "").strip()
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not media_id:
        raise ValueError("Falta media_id")

    cfg = obtener_config_linea(numero_asesor=numero_asesor) if numero_asesor else next(iter(WHATSAPP_LINES.values()))
    graph_root = _graph_root_from_messages_url(cfg["messages_url"])

    if not graph_root:
        raise RuntimeError("No se pudo derivar graph_root.")

    url = f"{graph_root}/{media_id}"
    response = requests.get(url, headers=_auth_headers(cfg), timeout=20)

    if response.status_code >= 400:
        raise MetaMediaError(
            media_id=media_id,
            status_code=response.status_code,
            error_body=_meta_error(response),
            numero_asesor=numero_asesor,
        )

    return response.json()


def download_media_whatsapp(media_id: str, numero_asesor: str = "") -> tuple[bytes, str]:
    media_id = str(media_id or "").strip()
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not media_id:
        raise ValueError("Falta media_id")

    cached = _buscar_media_en_cache(media_id)
    if cached:
        return cached

    cfg = obtener_config_linea(numero_asesor=numero_asesor) if numero_asesor else next(iter(WHATSAPP_LINES.values()))
    info = get_media_info_whatsapp(media_id, numero_asesor=numero_asesor)
    media_url = info.get("url") or ""

    if not media_url:
        raise RuntimeError(f"Meta no regresó url para media_id={media_id}: {info}")

    response = requests.get(media_url, headers=_auth_headers(cfg), timeout=45)

    if response.status_code >= 400:
        raise MetaMediaError(
            media_id=media_id,
            status_code=response.status_code,
            error_body=_meta_error(response),
            numero_asesor=numero_asesor,
        )

    content_type = response.headers.get("content-type") or info.get("mime_type") or "application/octet-stream"
    blob = response.content
    _guardar_media_en_cache(media_id=media_id, blob=blob, content_type=content_type)

    return blob, content_type


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
        if interactive.get("type") == "nfm_reply":
            nfm_reply = interactive.get("nfm_reply", {})
            return nfm_reply.get("body") or nfm_reply.get("name") or "[FLOW]"

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


def enviar_imagen_whatsapp_por_link(to: str, link: str, numero_asesor: str, caption: str = "") -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "image",
        "image": {"link": link},
    }
    if caption:
        payload["image"]["caption"] = caption
    return _post_messages_api(cfg, payload)


def enviar_documento_whatsapp_por_link(
    to: str,
    link: str,
    numero_asesor: str,
    caption: str = "",
    filename: str = "ficha-tecnica.pdf",
) -> dict:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "document",
        "document": {"link": link, "filename": filename},
    }
    if caption:
        payload["document"]["caption"] = caption
    return _post_messages_api(cfg, payload)


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
    return re.sub(r"\{\{(\d+)\}\}", r"(\1)", texto_final)


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
        for variable_index in _extraer_variables(texto):
            fields.append(
                {
                    "key": f"{tipo}_{variable_index}",
                    "label": f"{tipo.capitalize()} parámetro {variable_index}",
                    "type": "text",
                    "component": tipo,
                    "index": variable_index,
                }
            )

    ui = WHATSAPP_TEMPLATE_UI.get(nombre, {}) if isinstance(WHATSAPP_TEMPLATE_UI, dict) else {}
    labels = ui.get("labels") or {}

    for field in fields:
        if field["key"] in labels:
            field["label"] = labels[field["key"]]

    return {
        "id": template_id,
        "key": nombre,
        "name": nombre,
        "title": ui.get("title") or nombre.replace("_", " ").title(),
        "idioma": idioma,
        "language": idioma,
        "status": status,
        "category": category,
        "help": ui.get("help") or _texto_visible_desde_componentes(components),
        "fields": fields,
        "components": components,
        "header": ui.get("header") or None,
    }


def obtener_templates_whatsapp(numero_asesor: str) -> list[dict]:
    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    waba_id = str(cfg.get("waba_id") or "").strip()

    if not waba_id:
        raise ValueError(
            "Esta línea no tiene waba_id configurado en WHATSAPP_LINES."
        )

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/message_templates"

    headers = _auth_headers(cfg)

    params = {
        "fields": "name,status,category,language,components,id",
        "limit": 100,
    }

    permitidas = set(cfg.get("template_names") or [])

    salida = []
    next_url = url
    next_params = params

    while next_url:
        response = requests.get(
            next_url,
            headers=headers,
            params=next_params,
            timeout=25,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Meta templates error {response.status_code}: {_meta_error(response)}"
            )

        data = response.json()
        items = data.get("data") or []

        for item in items:
            normalizada = _normalizar_template_meta(item)

            # Solo mostramos plantillas aprobadas.
            if str(normalizada.get("status") or "").upper() != "APPROVED":
                continue

            key = normalizada.get("key") or normalizada.get("name") or ""

            # Ya no ocultamos las que no estén en template_names.
            # Solo agregamos una bandera para saber si estaba registrada manualmente.
            normalizada["permitida"] = key in permitidas if permitidas else True
            normalizada["registrada_en_settings"] = key in permitidas

            salida.append(normalizada)

        paging = data.get("paging") or {}
        next_url = paging.get("next") or ""

        # Cuando Meta manda paging.next, ya viene con querystring incluido.
        next_params = None

    return sorted(
        salida,
        key=lambda item: (
            str(item.get("title") or "").lower(),
            str(item.get("language") or item.get("idioma") or "").lower(),
        ),
    )