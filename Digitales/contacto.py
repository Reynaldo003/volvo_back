#volvo
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


logger = logging.getLogger(__name__)

MEDIA_CACHE_DIR = "whatsapp_media_cache"

EXTENSIONES_MEDIA = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "application/pdf": ".pdf",
}


class MetaAPIError(RuntimeError):
    """
    Error controlado para fallos de Meta Graph API.
    Mantiene el status real, el code, el fbtrace_id y si el error es reintentable.
    """

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
    """
    Error controlado para media de Meta.

    code=100 y subcode=33 normalmente significa:
    - media_id expirado,
    - media_id inexistente,
    - media_id consultado con token/WABA equivocado,
    - o falta de permisos sobre ese objeto.
    """

    def __init__(
        self,
        *,
        media_id: str,
        status_code: int,
        error_body: dict | None = None,
        numero_asesor: str = "",
    ):
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

    # Códigos comunes de Meta para errores temporales o rate limit.
    if meta_code in (1, 2, 4, 17, 32, 613):
        return True

    return False


def _segundos_para_reintento(attempt: int, response=None) -> float:
    """
    Backoff exponencial con jitter.
    attempt inicia en 0.
    """

    retry_after = ""

    if response is not None:
        retry_after = response.headers.get("Retry-After", "") or ""

    try:
        retry_after_num = float(retry_after)
        if 0 < retry_after_num <= 60:
            return retry_after_num
    except (TypeError, ValueError):
        pass

    base = min(2 ** attempt, 12)
    jitter = random.uniform(0.2, 1.2)

    return base + jitter


def _safe_media_id(media_id: str) -> str:
    value = str(media_id or "").strip()
    value = "".join(c for c in value if c.isalnum() or c in ("_", "-", "."))

    if value:
        return value

    return hashlib.sha256(str(media_id or "").encode("utf-8")).hexdigest()


def _extension_por_content_type(content_type: str) -> str:
    content_type = str(content_type or "").split(";")[0].strip().lower()

    if content_type in EXTENSIONES_MEDIA:
        return EXTENSIONES_MEDIA[content_type]

    guessed = mimetypes.guess_extension(content_type)
    return guessed or ".bin"


def _content_type_por_path(path: str) -> str:
    content_type = mimetypes.guess_type(path)[0]
    return content_type or "application/octet-stream"


def _media_cache_path(media_id: str, content_type: str) -> str:
    safe_id = _safe_media_id(media_id)
    ext = _extension_por_content_type(content_type)
    return f"{MEDIA_CACHE_DIR}/{safe_id}{ext}"


def _buscar_media_en_cache(media_id: str):
    safe_id = _safe_media_id(media_id)

    posibles_extensiones = [
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".mp4",
        ".ogg",
        ".mp3",
        ".pdf",
        ".bin",
    ]

    for ext in posibles_extensiones:
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
            response = requests.post(
                messages_url,
                headers=headers,
                json=payload,
                timeout=(5, 30),
            )

            if response.status_code < 400:
                data = response.json()

                logger.info(
                    "META WHATSAPP OK | intento=%s/%s | contexto=%s | message_id=%s",
                    intento_actual,
                    attempts_total,
                    log_context,
                    ((data.get("messages") or [{}])[0].get("id", "") if isinstance(data, dict) else ""),
                )

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
                logger.warning(
                    "META WHATSAPP ERROR FINAL | intento=%s/%s | retryable=%s | contexto=%s | error=%s",
                    intento_actual,
                    attempts_total,
                    retryable,
                    log_context,
                    last_error.to_dict(),
                )
                raise last_error

            espera = _segundos_para_reintento(attempt, response=response)

            logger.warning(
                "META WHATSAPP RETRY | intento=%s/%s | espera=%.2fs | contexto=%s | error=%s",
                intento_actual,
                attempts_total,
                espera,
                log_context,
                last_error.to_dict(),
            )

            time.sleep(espera)

        except MetaAPIError:
            raise

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = MetaAPIError(
                status_code=0,
                error_body={
                    "error": {
                        "message": str(exc),
                        "type": exc.__class__.__name__,
                        "is_transient": True,
                    }
                },
                retryable=True,
                attempts=intento_actual,
                message="Error temporal de conexión con Meta.",
            )

            if attempt >= max_retries:
                logger.warning(
                    "META WHATSAPP CONEXION ERROR FINAL | intento=%s/%s | contexto=%s | error=%s",
                    intento_actual,
                    attempts_total,
                    log_context,
                    last_error.to_dict(),
                )
                raise last_error

            espera = _segundos_para_reintento(attempt)

            logger.warning(
                "META WHATSAPP CONEXION RETRY | intento=%s/%s | espera=%.2fs | contexto=%s | error=%s",
                intento_actual,
                attempts_total,
                espera,
                log_context,
                str(exc),
            )

            time.sleep(espera)

        except requests.RequestException as exc:
            last_error = MetaAPIError(
                status_code=0,
                error_body={
                    "error": {
                        "message": str(exc),
                        "type": exc.__class__.__name__,
                        "is_transient": False,
                    }
                },
                retryable=False,
                attempts=intento_actual,
                message="Error de request hacia Meta.",
            )

            logger.exception(
                "META WHATSAPP REQUEST ERROR NO REINTENTABLE | contexto=%s | error=%s",
                log_context,
                str(exc),
            )

            raise last_error

    if isinstance(last_error, MetaAPIError):
        raise last_error

    raise MetaAPIError(
        status_code=0,
        error_body={
            "error": {
                "message": "No se pudo enviar a Meta.",
                "type": "UnknownError",
                "is_transient": True,
            }
        },
        retryable=True,
        attempts=attempts_total,
    )

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

def iniciar_llamada_whatsapp(
    to: str,
    numero_asesor: str,
) -> dict:

    cfg = obtener_config_linea(numero_asesor=numero_asesor)

    base = _graph_base_from_messages_url(
        cfg["messages_url"]
    )

    url = f"{base}/calls"

    headers = _json_headers(cfg)

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
    }

    r = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=20,
    )

    if r.status_code >= 400:
        raise RuntimeError(
            f"Meta call error {r.status_code}: {_meta_error(r)}"
        )

    return r.json()

def enviar_template_whatsapp(
    to: str,
    template_name: str,
    numero_asesor: str,
    params: list[str] | None = None,
    idioma: str = DEFAULT_IDIOMA,
    components: list[dict] | None = None,
) -> dict:
    """
    Envía una plantilla de WhatsApp Cloud API.

    Soporta:
    - Plantillas solo con BODY dinámico usando params=[...].
    - Plantillas con components completos enviados desde el frontend.
    - Plantillas con HEADER multimedia configurado en WHATSAPP_TEMPLATE_UI.

    Nota importante:
    Si en Meta la plantilla tiene HEADER tipo IMAGE/VIDEO/DOCUMENT,
    Meta exige enviar ese HEADER dentro de template.components al momento
    del envío. Si no se manda, Meta responde errores como:
    "header: Format mismatch, expected IMAGE, received UNKNOWN".
    """
    if not to:
        raise ValueError("Falta número destino")

    if not template_name:
        raise ValueError("Falta template_name")

    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    idioma = (idioma or DEFAULT_IDIOMA).strip()
    params = params or []

    ui_config = {}

    if isinstance(WHATSAPP_TEMPLATE_UI, dict):
        ui_config = WHATSAPP_TEMPLATE_UI.get(template_name, {}) or {}

    def _texto(value) -> str:
        return str(value or "").strip()

    def _normalizar_parametro(parametro: dict) -> dict | None:
        if not isinstance(parametro, dict):
            return None

        ptype = _texto(parametro.get("type")).lower()

        if not ptype:
            return None

        if ptype == "text":
            return {
                "type": "text",
                "text": str(parametro.get("text") or ""),
            }

        if ptype in ("image", "video", "document"):
            media_payload = parametro.get(ptype) or {}

            if not isinstance(media_payload, dict):
                return None

            media_id = _texto(media_payload.get("id"))
            link = _texto(media_payload.get("link") or media_payload.get("url"))

            if not media_id and not link:
                return None

            media_final = {"id": media_id} if media_id else {"link": link}

            filename = _texto(
                media_payload.get("filename")
                or media_payload.get("name")
            )

            if ptype == "document" and filename:
                media_final["filename"] = filename

            return {
                "type": ptype,
                ptype: media_final,
            }

        if ptype == "currency":
            currency = parametro.get("currency") or {}

            if isinstance(currency, dict):
                return {
                    "type": "currency",
                    "currency": currency,
                }

            return None

        if ptype == "date_time":
            date_time = parametro.get("date_time") or {}

            if isinstance(date_time, dict):
                return {
                    "type": "date_time",
                    "date_time": date_time,
                }

            return None

        if ptype == "payload":
            return {
                "type": "payload",
                "payload": str(parametro.get("payload") or ""),
            }

        # Fallback conservador para no romper parámetros nuevos de Meta.
        salida = dict(parametro)
        salida["type"] = ptype
        return salida

    def _normalizar_componentes(raw_components) -> list[dict]:
        salida = []

        if not isinstance(raw_components, list):
            return salida

        for component in raw_components:
            if not isinstance(component, dict):
                continue

            ctype = _texto(component.get("type")).lower()

            if ctype == "buttons":
                ctype = "button"

            if ctype not in ("header", "body", "footer", "button"):
                continue

            item = {
                "type": ctype,
            }

            parametros = component.get("parameters")

            if isinstance(parametros, list):
                parametros_normalizados = []

                for parametro in parametros:
                    normalizado = _normalizar_parametro(parametro)

                    if normalizado:
                        parametros_normalizados.append(normalizado)

                if parametros_normalizados:
                    item["parameters"] = parametros_normalizados

            sub_type = _texto(component.get("sub_type"))
            index = component.get("index")

            if sub_type:
                item["sub_type"] = sub_type

            if index is not None and str(index).strip() != "":
                item["index"] = str(index)

            salida.append(item)

        return salida

    def _body_component_desde_params(valores: list) -> dict | None:
        valores_limpios = [str(value) for value in (valores or [])]

        if not valores_limpios:
            return None

        return {
            "type": "body",
            "parameters": [
                {
                    "type": "text",
                    "text": value,
                }
                for value in valores_limpios
            ],
        }

    def _header_media_desde_config() -> dict | None:
        if not isinstance(ui_config, dict):
            return None

        header_cfg = ui_config.get("header") or ui_config.get("media_header") or {}

        if not isinstance(header_cfg, dict):
            header_cfg = {}

        # Compatibilidad con llaves simples.
        if not header_cfg:
            if ui_config.get("header_image_link") or ui_config.get("header_image_id"):
                header_cfg = {
                    "type": "image",
                    "link": ui_config.get("header_image_link"),
                    "id": ui_config.get("header_image_id"),
                }
            elif ui_config.get("header_video_link") or ui_config.get("header_video_id"):
                header_cfg = {
                    "type": "video",
                    "link": ui_config.get("header_video_link"),
                    "id": ui_config.get("header_video_id"),
                }
            elif ui_config.get("header_document_link") or ui_config.get("header_document_id"):
                header_cfg = {
                    "type": "document",
                    "link": ui_config.get("header_document_link"),
                    "id": ui_config.get("header_document_id"),
                    "filename": ui_config.get("header_document_filename"),
                }

        if not header_cfg:
            return None

        media_type = _texto(
            header_cfg.get("type")
            or header_cfg.get("media_type")
            or header_cfg.get("format")
        ).lower()

        if media_type in ("imagen", "photo", "picture"):
            media_type = "image"

        if media_type not in ("image", "video", "document"):
            return None

        media_id = _texto(header_cfg.get("id") or header_cfg.get("media_id"))
        link = _texto(header_cfg.get("link") or header_cfg.get("url"))

        if not media_id and not link:
            raise ValueError(
                f"La plantilla '{template_name}' requiere HEADER {media_type.upper()}, "
                "pero no tiene configurado 'id' ni 'link' en WHATSAPP_TEMPLATE_UI."
            )

        media_final = {"id": media_id} if media_id else {"link": link}

        filename = _texto(header_cfg.get("filename") or header_cfg.get("name"))

        if media_type == "document" and filename:
            media_final["filename"] = filename

        return {
            "type": "header",
            "parameters": [
                {
                    "type": media_type,
                    media_type: media_final,
                }
            ],
        }

    componentes_finales = _normalizar_componentes(components)

    if not componentes_finales:
        body_component = _body_component_desde_params(params)

        if body_component:
            componentes_finales.append(body_component)

    header_media = _header_media_desde_config()

    if header_media:
        componentes_finales = [
            header_media,
            *[
                component
                for component in componentes_finales
                if component.get("type") != "header"
            ],
        ]

    template_payload = {
        "name": template_name,
        "language": {
            "code": idioma,
        },
    }

    if componentes_finales:
        template_payload["components"] = componentes_finales

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
    media_id = str(media_id or "").strip()
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not media_id:
        raise ValueError("Falta media_id")

    if numero_asesor:
        cfg = obtener_config_linea(numero_asesor=numero_asesor)
    else:
        cfg = next(iter(WHATSAPP_LINES.values()))

    graph_root = _graph_root_from_messages_url(cfg["messages_url"])

    if not graph_root:
        raise RuntimeError("No se pudo derivar graph_root.")

    url = f"{graph_root}/{media_id}"
    headers = _auth_headers(cfg)

    response = requests.get(
        url,
        headers=headers,
        timeout=20,
    )

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

    if numero_asesor:
        cfg = obtener_config_linea(numero_asesor=numero_asesor)
    else:
        cfg = next(iter(WHATSAPP_LINES.values()))

    info = get_media_info_whatsapp(media_id, numero_asesor=numero_asesor)
    media_url = info.get("url") or ""

    if not media_url:
        raise RuntimeError(f"Meta no regresó url para media_id={media_id}: {info}")

    headers = _auth_headers(cfg)

    response = requests.get(
        media_url,
        headers=headers,
        timeout=45,
    )

    if response.status_code >= 400:
        raise MetaMediaError(
            media_id=media_id,
            status_code=response.status_code,
            error_body=_meta_error(response),
            numero_asesor=numero_asesor,
        )

    content_type = (
        response.headers.get("content-type")
        or info.get("mime_type")
        or "application/octet-stream"
    )

    blob = response.content

    _guardar_media_en_cache(
        media_id=media_id,
        blob=blob,
        content_type=content_type,
    )

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
        "document": {
            "link": link,
            "filename": filename,
        },
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