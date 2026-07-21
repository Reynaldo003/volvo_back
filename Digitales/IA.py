#volvo
# Digitales/IA.py
from __future__ import annotations
import logging
from functools import lru_cache
import json
import re
import unicodedata
from typing import Any, Optional
import time
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from google import genai
from google.genai import types

from .sett import WHATSAPP_LINES
from citas.models import ClienteComercial, normaliza_tel_mx
from .models import ExpedienteDigital, MensajeWhatsApp, ConfiguracionIAWhatsApp, ConversacionIA
from .contacto import (
    enviar_texto_whatsapp,
    enviar_documento_whatsapp_por_link,
    enviar_imagen_whatsapp_por_link,
    enviar_video_whatsapp_por_link,
    replace_start,
    download_media_whatsapp,
    enviar_indicador_escribiendo_whatsapp,
)
from .ia_catalogo import obtener_catalogo_activo_para_ia

logger = logging.getLogger(__name__)

# Sucursales y geolocalización por LADA 
SUCURSALES_VOLVO: list[dict] = [
    {
        "nombre": "Volvo Cars Puebla",
        "ciudad": "San Andrés Cholula, Puebla",
        "direccion": "Av. Atlixcáyotl 4012, Santa María Tonantzintla, 72840",
        "telefono": "221-109-2815",
        "horario": "Lun-Sáb 9:00-20:00",
        "ladas_cercanas": ["221", "222"],
        "google_maps": "https://maps.app.goo.gl/8y7J64tuSwWKBddC6",
    },
]

IA_CONFIG_GLOBAL_KEY = "GLOBAL"

def _obtener_config_ia(numero_asesor: str) -> dict:
    """
    Obtiene la configuración propia de IA para el número de WhatsApp.

    Antes:
    - Si no encontraba configuración del número, usaba GLOBAL.

    Ahora:
    - Solo usa configuración propia del número.
    - Si el número no tiene configuración o está inactiva, devuelve {}.
    """
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not numero_asesor:
        return {}

    cfg = ConfiguracionIAWhatsApp.objects.filter(
        numero_asesor=numero_asesor,
    ).first()

    if not cfg:
        return {}

    if not cfg.activo:
        return {}

    return {
        "identidad": cfg.identidad or "",
        "precios": cfg.precios or "",
        "perfilamiento": cfg.perfilamiento or "",
        "limites": cfg.limites or "",
        "personalidad": cfg.personalidad or "",
        "condiciones_fijas": cfg.condiciones_fijas or "",
        "promociones_eventos": cfg.promociones_eventos or "",
    }

def _clave_catalogo(item: dict) -> str:
    base = f"{item.get('modelo', '')} {item.get('ano', '')}".strip().upper()

    if item.get("version"):
        base = f"{base} {item.get('version')}".strip().upper()

    return base


def _obtener_catalogo_dict() -> dict:
    items = obtener_catalogo_activo_para_ia()

    catalogo = {}

    for item in items:
        clave = _clave_catalogo(item)
        if clave:
            catalogo[clave] = item

    return catalogo


def _normalizar_version_catalogo(version: str | None) -> str | None:
    if not version:
        return None

    version_normalizada = str(version).strip().upper()
    catalogo = _obtener_catalogo_dict()

    return version_normalizada if version_normalizada in catalogo else None


def _catalogo_para_prompt() -> list[dict]:
    return obtener_catalogo_activo_para_ia()


def _texto_precios_version(version: str) -> str:
    catalogo = _obtener_catalogo_dict()
    item = catalogo.get(str(version or "").strip().upper())

    if not item:
        return "Por el momento no tengo precio activo para ese modelo."

    precio_lista = item.get("precio_lista")
    precio_contado = item.get("precio_contado")
    precio_financiado = item.get("precio_financiado")

    lineas = []

    if precio_lista:
        lineas.append(f"Precio de lista: ${precio_lista:,.0f} MXN")

    if precio_contado:
        lineas.append(f"Precio contado: ${precio_contado:,.0f} MXN")

    if precio_financiado:
        lineas.append(f"Precio financiado: ${precio_financiado:,.0f} MXN")

    return "\n".join(lineas) if lineas else "Por el momento no tengo precio activo para ese modelo."


def _resumen_ficha_texto(version: str) -> str:
    catalogo = _obtener_catalogo_dict()
    item = catalogo.get(str(version or "").strip().upper())

    if not item:
        return "Con gusto te comparto información, pero necesito confirmar el modelo exacto."

    resumen = item.get("resumen") or ""
    ficha = item.get("ficha_tecnica") or {}

    lineas = []

    if resumen:
        lineas.append(resumen)

    if isinstance(ficha, dict):
        for clave, valor in ficha.items():
            if valor:
                lineas.append(f"• {clave}: {valor}")

    return "\n".join(lineas).strip() or "Tengo información disponible de este modelo."


def _imagenes_de_version(version: str) -> list[str]:
    catalogo = _obtener_catalogo_dict()
    item = catalogo.get(str(version or "").strip().upper())

    if not item:
        return []

    imagenes = item.get("imagenes") or []

    return imagenes if isinstance(imagenes, list) else []

def _videos_de_version(version: str) -> list[str]:
    catalogo = _obtener_catalogo_dict()
    item = catalogo.get(str(version or "").strip().upper())

    if not item:
        return []

    videos = item.get("videos") or []

    return videos if isinstance(videos, list) else []

def _lada_de_telefono(telefono: str) -> str:
    """Extrae la LADA (3 dígitos) de un número mexicano normalizado (10 dígitos sin +52)."""
    tel = re.sub(r"\D", "", telefono or "")
    if tel.startswith("52") and len(tel) == 12:
        tel = tel[2:]
    if len(tel) == 10:
        return tel[:3]
    return ""


def _sucursal_mas_cercana(telefono: str) -> dict:
    """Devuelve la sucursal más cercana según la LADA del teléfono del cliente."""
    lada = _lada_de_telefono(telefono)
    if lada:
        for sucursal in SUCURSALES_VOLVO:
            if lada in sucursal.get("ladas_cercanas", []):
                return sucursal
    return SUCURSALES_VOLVO[0] if SUCURSALES_VOLVO else {}


def _texto_ubicacion(telefono: str) -> str:
    s = _sucursal_mas_cercana(telefono)
    if not s:
        return "Por favor contáctanos directamente para indicarte nuestra ubicación."
    lineas = [
        f"📍 *Ubicación de tu agencia Volvo:*",
        f"",
        f"🏢 *Agencia:* {s['nombre']}",
        f"🏙️ *Ciudad:* {s['ciudad']}",
        f"🗺️ *Dirección:* {s['direccion']}",
        f"📞 *Teléfono:* {s['telefono']}",
        f"🕐 *Horario:* {s['horario']}",
    ]
    if s.get("google_maps"):
        lineas += [
            f"",
            f"🔗 *Cómo llegar:*",
            f"{s['google_maps']}",
        ]
    lineas += [
        f"",
        f"¡Te esperamos! 🚗",
    ]
    return "\n".join(lineas)


def _enganche_referencial(version: str) -> Optional[str]:
    item = _obtener_catalogo_dict().get(str(version or "").strip().upper())

    if not item:
        return None

    precio_num = item.get("precio_lista")

    if not precio_num:
        return None

    enganche = round(int(precio_num) * 0.20 / 1000) * 1000

    return f"${enganche:,} MXN aprox. (20% referencial)"

COMPARACION_DESEMPENO: dict[str, dict] = {}
# La información de desempeño se toma de ficha_tecnica en CatalogoVehiculos.
# Evitamos mantener cifras duplicadas y desactualizadas dentro del código.

# Perfilado / filtrado de leads
ENGANCHE_MINIMO_CALIFICADO = 69_000   # MXN

ETAPA_PERFILADO = {
    "sin_iniciar":    0,
    "pedir_nombre":   1,
    "pedir_enganche": 2,
    "pedir_buro":     3,
    "completado":     4,
}

SALUDO_BASE = (
    "¡Hola! Soy Ava, asistente digital de Volvo Cars Puebla 🚙\n\n"
    "Puedo ayudarte con información de modelos, versiones, precios registrados, "
    "fichas técnicas, fotografías, videos y seguimiento comercial.\n\n"
    "¿Qué Volvo te interesa o qué información necesitas?"
)

RESPUESTA_MEDIA = (
    "Recibí tu archivo. Dame un momento para revisarlo y continuar con tu atención."
)

RESPUESTA_FALLBACK = (
    "Con gusto te ayudo. Tenemos información de los modelos Volvo registrados "
    "en nuestro catálogo del CRM. Cuéntame qué modelo te interesa o qué necesitas revisar."
)

RESPUESTA_CONFIRMAR_ASESOR = (
    "Gracias. En un momento un asesor se comunicara contigo para darte atencion personalizada y seguimiento."
)

# Mensaje para autos no disponibles como nuevos
RESPUESTA_AUTO_NO_DISPONIBLE = (
    "Ese modelo no aparece activo en nuestro catálogo de vehículos nuevos. "
    "Puedo solicitar que un asesor revise disponibilidad o alternativas para ti."
)

STOPWORDS_NOMBRE = {
    "SI", "SIP", "OK", "OKEY", "VA", "CLARO", "EN", "PDF", "MANDAMELA", "MANDAME",
    "COMPARTELA", "COMPARTEME", "COMPARTEMELA", "FICHA", "TECNICA", "PRECIO",
    "QUIERO", "NECESITO", "PASAME", "PASAMELA", "LISTO", "PERFECTO", "SALE",
    "SERVICIO", "PUBLICO", "TRANSPORTE", "LINEA", "IMAGEN", "IMAGENES", "FOTO", "FOTOS",
    "FINANCIAMIENTO", "CREDITO", "MENSUALIDADES", "COTIZACION", "5", "8", "9",
}

PALABRAS_COTIZACION = {
    "COTIZACION", "COTIZAR", "COTIZA", "PROPUESTA", "PROPUESTA FORMAL",
    "CORRIDA", "CORRIDA FINANCIERA", "MENSUALIDADES", "MENSUALIDAD",
    "ENGANCHE", "PLAN DE PAGOS", "FINANCIAMIENTO", "CREDITO", "LEASING",
    "ARRENDAMIENTO", "NUMEROS", "PAGOS",
}

PALABRAS_COMPRA = {
    "COMPRAR", "ADQUIRIR", "APARTAR", "QUIERO LA UNIDAD", "QUIERO COMPRAR",
    "ME INTERESA COMPRAR", "QUIERO AVANZAR", "QUIERO QUE ME CONTACTEN",
    "QUIERO HABLAR CON VENTAS", "ATENCION PERSONALIZADA",
}

ACCIONES_OFRECIDAS_VALIDAS = {
    "saludo_inicial", "pedir_nombre", "pedir_necesidad", "compartir_precio",
    "compartir_pdf", "confirmar_canalizacion", "preguntar_tipo_cliente",
    "preguntar_forma_pago", "continuar_contexto", "pedir_enganche",
    "pedir_buro", "lead_calificado", "ninguna",
}

PALABRAS_CATALOGO_ANTERIOR: set[str] = set()

_ALIASES_VERSION: dict[str, list[str]] = {
    "EX30": ["EX30", "VOLVO EX30"],
    "EX40": ["EX40", "VOLVO EX40"],
    "EC40": ["EC40", "VOLVO EC40", "C40", "VOLVO C40"],
    "EX90": ["EX90", "VOLVO EX90"],
    "XC40": ["XC40", "VOLVO XC40"],
    "XC60": ["XC60", "VOLVO XC60"],
    "XC90": ["XC90", "VOLVO XC90"],
    "XC60 BLACK EDITION": ["XC60 BLACK EDITION", "BLACK EDITION XC60"],
    "XC90 BLACK EDITION": ["XC90 BLACK EDITION", "BLACK EDITION XC90"],
}


# Utilidades de texto
def _strip_accents(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )


def _normalizar_texto(texto: str) -> str:
    texto = _strip_accents(texto or "").upper().strip()
    texto = re.sub(r"[^A-Z0-9$@._ -]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _media_base_url() -> str:
    base = getattr(settings, "PUBLIC_API_BASE_URL", "").rstrip("/")
    media_url = getattr(settings, "MEDIA_URL", "/media/")
    return f"{base}{media_url}"


def _build_media_url(relativo: str) -> str:
    return f"{_media_base_url()}{relativo}".replace(" ", "%20")

def _resolver_url_media(valor: str) -> str:
    valor = str(valor or "").strip()

    if not valor:
        return ""

    if valor.startswith("http://") or valor.startswith("https://"):
        return valor

    return _build_media_url(valor)

def _build_pdf_url(pdf_relativo: str) -> str:
    return _build_media_url(pdf_relativo)


def _limitar_texto(texto: str, max_len: int = 900) -> str:
    texto = re.sub(r"\n{3,}", "\n\n", (texto or "").strip())
    if len(texto) <= max_len:
        return texto
    return texto[: max_len - 3].rstrip() + "..."


def _es_email(texto: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (texto or "").strip()))


def _limpiar_nombre_candidato(texto: str) -> str:
    texto = re.sub(r"[^a-zA-ZáéíóúÁÉÍÓÚüÜñÑ ]+", " ", texto or "").strip()
    return re.sub(r"\s+", " ", texto)


def _parece_nombre_solo(texto: str) -> bool:
    texto = (texto or "").strip()
    if not texto or _es_email(texto):
        return False
    texto_limpio = _limpiar_nombre_candidato(texto)
    if not texto_limpio:
        return False
    palabras = [p.upper() for p in texto_limpio.split() if p.strip()]
    if not palabras or len(palabras) > 3:
        return False
    if any(p in STOPWORDS_NOMBRE for p in palabras):
        return False
    if any(len(p) < 2 for p in palabras):
        return False
    return True


def _extraer_nombre_basico(profile_name: str, texto: str) -> str:
    pn = (profile_name or "").strip()
    if pn and not _es_email(pn) and _parece_nombre_solo(pn):
        return _limpiar_nombre_candidato(pn)
    texto = (texto or "").strip()
    for patron in [
        r"\bmi nombre es\s+([a-zA-ZáéíóúÁÉÍÓÚüÜñÑ ]{2,80})",
        r"\bme llamo\s+([a-zA-ZáéíóúÁÉÍÓÚüÜñÑ ]{2,80})",
        r"\bsoy\s+([a-zA-ZáéíóúÁÉÍÓÚüÜñÑ ]{2,80})",
    ]:
        m = re.search(patron, texto, flags=re.IGNORECASE)
        if m:
            nombre = _limpiar_nombre_candidato(re.sub(r"\s+", " ", m.group(1)).strip(" .,-"))
            if nombre and not _es_email(nombre):
                return nombre
    if _parece_nombre_solo(texto):
        return _limpiar_nombre_candidato(texto)
    return ""


def _json_seguro(texto: str) -> dict[str, Any]:
    """Parsea JSON robusto: maneja prefijos, markdown, trailing commas y JSON truncado."""
    texto = (texto or "").strip()
    if not texto:
        return {}
    try:
        return json.loads(texto)
    except Exception:
        pass
    texto_limpio = re.sub(r"```(?:json)?\s*", "", texto).strip()
    texto_limpio = re.sub(r"```\s*$", "", texto_limpio).strip()
    try:
        return json.loads(texto_limpio)
    except Exception:
        pass
    m = re.search(r"\{.*\}", texto_limpio, flags=re.DOTALL)
    if m:
        fragmento = m.group(0)
        try:
            return json.loads(fragmento)
        except Exception:
            pass
        fragmento_rep = re.sub(r",\s*([}\]])", r"\1", fragmento)
        try:
            return json.loads(fragmento_rep)
        except Exception:
            pass
        try:
            cierre = "]" * max(fragmento_rep.count("[") - fragmento_rep.count("]"), 0)
            cierre += "}" * max(fragmento_rep.count("{") - fragmento_rep.count("}"), 0)
            return json.loads(fragmento_rep + cierre)
        except Exception:
            pass
    return {}


def _texto_refiere_catalogo_anterior(texto: str) -> bool:
    t = _normalizar_texto(texto)
    return any(f in t for f in PALABRAS_CATALOGO_ANTERIOR)


def _raw_refiere_catalogo_anterior(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    candidatos = [
        raw.get("version_contexto"), raw.get("filename"),
        raw.get("document_link"), raw.get("media_link"), raw.get("body"),
    ]
    d = raw.get("decision") or {}
    if isinstance(d, dict):
        candidatos += [d.get("selected_version"), d.get("reply_text")]
    return any(_texto_refiere_catalogo_anterior(str(c or "")) for c in candidatos)


def _mensaje_de_historial_vigente(*, body: str, raw: Any = None) -> bool:
    if _texto_refiere_catalogo_anterior(body or ""):
        return False
    if _raw_refiere_catalogo_anterior(raw):
        return False
    return True


def _limpiar_auto_interes_invalido(expediente: ExpedienteDigital) -> Optional[str]:
    ai = (expediente.auto_interes or "").strip()
    if not ai:
        return None
    if ai in _obtener_catalogo_dict():
        return ai
    expediente.auto_interes = ""
    expediente.save(update_fields=["auto_interes", "actualizado"])
    return None


def _buscar_version_en_texto(texto: str) -> Optional[str]:
    texto_normalizado = _normalizar_texto(texto)
    catalogo = _obtener_catalogo_dict()
    candidatos: list[tuple[int, str, str]] = []

    for clave, item in catalogo.items():
        modelo = str(item.get("modelo") or "").strip()
        ano = str(item.get("ano") or "").strip()
        version = str(item.get("version") or "").strip()
        aliases = {
            clave,
            modelo,
            f"{modelo} {ano}".strip(),
            f"{modelo} {version}".strip(),
            f"{modelo} {ano} {version}".strip(),
        }

        for alias_base, aliases_extra in _ALIASES_VERSION.items():
            if _normalizar_texto(alias_base) in _normalizar_texto(clave):
                aliases.update(aliases_extra)

        for alias in aliases:
            alias_normalizado = _normalizar_texto(alias)
            if alias_normalizado and alias_normalizado in texto_normalizado:
                candidatos.append((len(alias_normalizado), clave, alias_normalizado))

    if not candidatos:
        return None

    candidatos.sort(reverse=True)
    return candidatos[0][1]

def _respuesta_precio_version(version: str) -> str:
    return _limitar_texto(
        f"Precios de {version.title()}:\n\n{_texto_precios_version(version)}\n\n"
        "Si gustas, tambien te comparto la ficha tecnica en PDF."
    )

def _detectar_intencion_minima(texto_usuario: str) -> dict[str, bool]:
    t = _normalizar_texto(texto_usuario)
    return {
        "pregunta_precio": any(k in t for k in [
            "PRECIO", "PRECIOS", "COSTO", "COSTOS", "CUANTO CUESTA", "CUANTO VALE",
            "CUANTO SALE", "CUANTO ESTA", "EN CUANTO", "A CUANTO",
            "VALE", "CUESTA", "SALE", "$", "MXN", "PESOS", "DESDE", "MONTO",
            "VERSION", "VERSIONES", "VERSIÓN", "TRIMS", "TRIM", "CUAL TIENE", "QUE VERSIONES",
        ]),
        "pregunta_pdf": any(k in t for k in [
            "PDF", "FICHA", "FICHA TECNICA", "ESPECIFICACIONES", "SPECS",
            "CATALOGO", "DETALLES", "BROCHURE", "INFO", "INFORMACION",
            "DATOS", "CARACTERISTICAS", "QUE TRAE", "QUE TIENE", "COMO ES",
            "CUENTAME", "DIME MAS",
        ]),
        "pregunta_imagenes": any(k in t for k in [
            "IMAGEN", "IMAGENES", "FOTO", "FOTOS", "FOTOGRAFIA",
            "PIC", "PICS", "MUESTRAME FOTOS","MUESTRAME IMAGENES",
            "MANDAME FOTOS", "MANDAME IMAGENES", "PASAME FOTOS",
            "PASAME IMAGENES", "COMO SE VE",
        ]),
        "pregunta_videos": any(k in t for k in [
            "VIDEO", "VIDEOS", "GRABACION", "GRABACIÓN", "RECORRIDO",
            "TOUR", "REEL", "COMO SE VE EN VIDEO", "MANDAME VIDEO",
            "MÁNDAME VIDEO", "PASAME VIDEO", "PÁSAME VIDEO",
            "QUIERO VERLO EN VIDEO", "VERLO EN VIDEO",
        ]),
        "cotizacion_personalizada": any(k in t for k in PALABRAS_COTIZACION),
        "intencion_compra": any(k in t for k in PALABRAS_COMPRA),
        "pregunta_desempeno": any(k in t for k in [
            "RAPIDO", "MAS RAPIDO", "VELOZ", "POTENTE", "MAS POTENTE", "MAS HP",
            "CABALLOS", "HP", "TORQUE", "CUAL ES MEJOR", "COMPARAR",
            "DIFERENCIA", "VS", "VERSUS", "ENTRE EL", "ENTRE LA",
        ]),
        "pregunta_catalogo": any(k in t for k in [
            "QUE MODELOS", "CUALES TIENES", "CUALES SON", "QUE TIENEN", "CATALOGO",
            "QUE AUTOS", "QUE CARROS", "QUE VEHICULOS", "OPCIONES TIENES",
            "TIENEN", "MANEJAN", "VENDEN",
        ]),
        "pregunta_arrendamiento": any(k in t for k in [
            "ARRENDAMIENTO", "ARRENDAR", "LEASING", "RENTA", "RENTA LARGA",
        ]),
        #señal de ubicación ────────────────────────────────────
        "pregunta_ubicacion": any(k in t for k in [
            "UBICACION", "DONDE ESTAN", "DONDE QUEDAN", "DONDE SE ENCUENTRAN",
            "DIRECCION", "COMO LLEGAR", "MAPA", "MAPS", "AGENCIA", "SUCURSAL",
            "DONDE PUEDO IR", "EN PERSONA", "VISITAR", "DONDE ES",
        ]),
    }

# Perfilado de leads
_NUMEROS_LETRAS_MONTO: dict[str, int] = {
    "DIEZ": 10, "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14, "QUINCE": 15,
    "VEINTE": 20, "TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50,
    "SESENTA": 60, "SETENTA": 70, "OCHENTA": 80, "NOVENTA": 90,
    "CIEN": 100, "CIENTO": 100, "CIENTO CINCUENTA": 150, "DOSCIENTOS": 200,
    "TRESCIENTOS": 300, "CUATROCIENTOS": 400, "QUINIENTOS": 500,
}

def _extraer_monto_pesos(texto: str) -> Optional[int]:
    """Extrae monto en pesos. Soporta digitos, sufijos K/MIL y numeros en letras."""
    if not texto:
        return None
    t = _normalizar_texto(texto)
    t = re.sub(r"[$,]", "", t)
    m = re.search(r"(\d[\d\s\.]*)(\s*(?:MIL|K)\b)?", t)
    if m:
        try:
            num = int(float(re.sub(r"[\s\.]", "", m.group(1))))
            if (m.group(2) or "").strip() in ("MIL", "K"):
                num *= 1000
            elif num < 1000 and any(k in t for k in ["MIL", "K", "PESOS", "MXN"]):
                num *= 1000
            if num > 0:
                return num
        except Exception:
            pass
    for palabra, valor in sorted(_NUMEROS_LETRAS_MONTO.items(), key=lambda x: -len(x[0])):
        if palabra in t and "MIL" in t:
            return valor * 1000
    return None


def _evaluar_buro(texto: str) -> str:
    t = _normalizar_texto(texto)
    if any(k in t for k in ["BUENO", "BUEN BURO", "BUEN HISTORIAL", "EXCELENTE", "MUY BIEN", "LIMPIO"]):
        return "bueno"
    if any(k in t for k in ["REGULAR", "MAS O MENOS", "MEDIO", "NO TAN BUENO"]):
        return "regular"
    if any(k in t for k in ["INICIANDO", "INICIO", "SIN HISTORIAL", "NO TENGO", "NUEVO", "NULO", "NUNCA"]):
        return "iniciando"
    return "desconocido"


def _lead_es_calificado(enganche: Optional[int], buro: str) -> bool:
    buro_normalizado = _normalizar_texto(buro or "")

    if enganche is None or enganche < ENGANCHE_MINIMO_CALIFICADO:
        return False

    if not buro_normalizado or buro_normalizado == "DESCONOCIDO":
        return False

    return not any(k in buro_normalizado for k in ["INICIANDO", "SIN HISTORIAL", "NO TENGO", "NULO"])


def _int_detectado(valor) -> Optional[int]:
    """Convierte valores detectados por IA a entero sin romper el flujo."""
    if valor in (None, ""):
        return None

    try:
        if isinstance(valor, str):
            valor = re.sub(r"[^0-9]", "", valor)

        if valor in (None, ""):
            return None

        entero = int(valor)
        return entero if entero > 0 else None
    except (TypeError, ValueError):
        return None


def _texto_detectado(valor, max_len: int = 120) -> str:
    """Limpia texto detectado para guardarlo en campos formales del expediente."""
    return str(valor or "").strip()[:max_len]


def _get_or_create_conversacion_ia(expediente: ExpedienteDigital, numero_asesor: str) -> ConversacionIA:
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    conversacion, _ = ConversacionIA.objects.get_or_create(
        expediente=expediente,
        numero_asesor=numero_asesor,
    )

    return conversacion


def _leer_dato_conversacion(
    expediente: ExpedienteDigital,
    numero_asesor: str,
    clave: str,
    default=None,
):
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not numero_asesor:
        return default

    conversacion = ConversacionIA.objects.filter(
        expediente=expediente,
        numero_asesor=numero_asesor,
    ).first()

    if not conversacion:
        return default

    datos_extra = conversacion.datos_extra if isinstance(conversacion.datos_extra, dict) else {}
    return datos_extra.get(clave, default)


def _actualizar_datos_conversacion(
    *,
    expediente: ExpedienteDigital,
    numero_asesor: str,
    datos: dict[str, Any],
    estado_conversacion: str = "",
    pregunta_pendiente: str = "",
) -> None:
    numero_asesor = normaliza_tel_mx(numero_asesor or "")

    if not numero_asesor:
        return

    conversacion = _get_or_create_conversacion_ia(expediente, numero_asesor)
    datos_extra = conversacion.datos_extra if isinstance(conversacion.datos_extra, dict) else {}

    for clave, valor in (datos or {}).items():
        if valor in (None, ""):
            continue
        datos_extra[clave] = valor

    conversacion.datos_extra = datos_extra

    campos_update = ["datos_extra"]

    if estado_conversacion:
        conversacion.estado_conversacion = estado_conversacion
        campos_update.append("estado_conversacion")

    conversacion.pregunta_pendiente = pregunta_pendiente or ""
    campos_update.append("pregunta_pendiente")

    conversacion.save(update_fields=list(dict.fromkeys(campos_update)))


def _obtener_etapa_perfilado(expediente: ExpedienteDigital, numero_asesor: str = "") -> int:
    """
    La pauta del expediente se reserva para la campaña/anuncio de Meta.
    La etapa conversacional de la IA se guarda en ConversacionIA.datos_extra.
    """
    etapa_guardada = _leer_dato_conversacion(
        expediente,
        numero_asesor,
        "etapa_perfilado",
        default="",
    )

    if isinstance(etapa_guardada, int):
        return max(0, min(4, etapa_guardada))

    etapa_guardada = str(etapa_guardada or "").strip()

    if etapa_guardada in ETAPA_PERFILADO:
        return ETAPA_PERFILADO[etapa_guardada]

    # Fallback usando campos reales del expediente, sin tocar pauta.
    if expediente.enganche_monto and expediente.buro_estado:
        return ETAPA_PERFILADO["completado"]

    if expediente.enganche_monto and not expediente.buro_estado:
        return ETAPA_PERFILADO["pedir_buro"]

    if (expediente.cliente.nombre or "").strip():
        return ETAPA_PERFILADO["pedir_enganche"]

    return ETAPA_PERFILADO["sin_iniciar"]


def _determinar_accion_ofrecida(
    *, reply_text: str, send_pdf: bool, requiere_asesor: bool,
    selected_version: Optional[str], texto_usuario: str,
) -> str:
    if requiere_asesor:
        return "confirmar_canalizacion"
    if send_pdf and selected_version:
        return "compartir_pdf"
    rn = _normalizar_texto(reply_text)
    if "TU NOMBRE" in rn or "COMO TE LLAMAS" in rn:
        return "pedir_nombre"
    if any(k in rn for k in ["PARA QUE USO", "QUE USO LE DARAS"]):
        return "pedir_necesidad"
    return "continuar_contexto" if selected_version else "ninguna"


@lru_cache(maxsize=1)
def _get_gemini_client():
    api_key = getattr(settings, "GEMINI_API_KEY", "") or ""

    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY")

    return genai.Client(api_key=api_key)

GEMINI_DECISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reply_text": {"type": "STRING"},
        "selected_version": {
            "anyOf": [
                {"type": "STRING"},
                {"type": "NULL"},
            ],
        },
        "send_pdf": {"type": "BOOLEAN"},
        "send_images": {"type": "BOOLEAN"},
        "send_videos": {"type": "BOOLEAN"},
        "requiere_asesor": {"type": "BOOLEAN"},
        "accion_ofrecida": {"type": "STRING"},
        "nueva_etapa_perfilado": {"type": "INTEGER"},
        "detected_profile": {
            "type": "OBJECT",
            "properties": {
                "nombre_detectado": {"type": "STRING"},
                "enganche_monto": {
                    "anyOf": [
                        {"type": "INTEGER"},
                        {"type": "NULL"},
                    ],
                },
                "presupuesto_mensual": {
                    "anyOf": [
                        {"type": "INTEGER"},
                        {"type": "NULL"},
                    ],
                },
                "buro_estado": {"type": "STRING"},
                "tipo_cliente": {"type": "STRING"},
                "forma_pago": {"type": "STRING"},
                "uso_vehiculo": {"type": "STRING"},
                "plazo_compra": {"type": "STRING"},
                "interes_principal": {"type": "STRING"},
            },
        },
        "reasoning_tags": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
    },
    "required": [
        "reply_text",
        "selected_version",
        "send_pdf",
        "send_images",
        "send_videos",
        "requiere_asesor",
        "accion_ofrecida",
        "nueva_etapa_perfilado",
        "detected_profile",
        "reasoning_tags",
    ],
}

def _construir_instrucciones_desde_bd(config_ia: dict) -> str:
    partes = [
        config_ia.get("identidad", ""),
        config_ia.get("precios", ""),
        config_ia.get("promociones_eventos", ""),
        config_ia.get("perfilamiento", ""),
        config_ia.get("limites", ""),
        config_ia.get("personalidad", ""),
        config_ia.get("condiciones_fijas", ""),
    ]

    return "\n\n".join(
        str(parte or "").strip()
        for parte in partes
        if str(parte or "").strip()
    )

# Motor de decisión principal (IA)
def _decision_conversacional_ia(
    *,
    numero_asesor: str,
    telefono: str,
    nombre_cliente: str,
    texto_usuario: str,
    auto_interes_actual: Optional[str],
    ultimo_mensaje_saliente: str,
    historial_reciente: list[dict[str, str]],
    accion_ofrecida_previa: Optional[str],
    etapa_perfilado: int,
    enganche_registrado: Optional[int],
    buro_registrado: str,
    es_primer_mensaje: bool,
) -> dict[str, Any]:
    auto_interes_actual = _normalizar_version_catalogo(auto_interes_actual)
    
    client = _get_gemini_client()
    
    config_ia = _obtener_config_ia(numero_asesor)
    
    catalogo_dict = _obtener_catalogo_dict()
    versiones_validas = sorted(catalogo_dict.keys())
    versiones_str = "\n".join(f"- {v}" for v in versiones_validas)

    # ANTI-CICLO: cuenta preguntas repetidas de la IA en el historial reciente.
    def _contar_intentos_sin_avance(historial: list[dict], pregunta_clave: str) -> int:
        clave = _normalizar_texto(pregunta_clave)
        count = 0

        for msg in reversed(historial or []):
            if msg.get("role") != "assistant":
                continue

            contenido = _normalizar_texto(msg.get("content") or "")

            if clave and clave in contenido:
                count += 1

        return count

    intentos_enganche = _contar_intentos_sin_avance(historial_reciente, "enganche")
    intentos_buro     = _contar_intentos_sin_avance(historial_reciente, "buró")

    enganches_info = {v: _enganche_referencial(v) for v in versiones_validas}
    from datetime import date as _date
    _hoy = _date.today()
    _meses_es = {1:"enero",2:"febrero",3:"marzo",4:"abril",5:"mayo",6:"junio",
                 7:"julio",8:"agosto",9:"septiembre",10:"octubre",11:"noviembre",12:"diciembre"}
    _ultimo_dia = [31,28,31,30,31,30,31,31,30,31,30,31][_hoy.month - 1]
    _vigencia = f"al {_ultimo_dia} de {_meses_es[_hoy.month]} de {_hoy.year}"

    contexto = {
        "telefono": telefono,
        "nombre_cliente": nombre_cliente,
        "mensaje_usuario": texto_usuario,
        "ultimo_mensaje_saliente": ultimo_mensaje_saliente,
        "auto_interes_actual": auto_interes_actual,
        "historial_reciente": historial_reciente,
        "accion_ofrecida_previa": accion_ofrecida_previa,
        "es_primer_mensaje": es_primer_mensaje,
        "contexto_configuracion_ia": config_ia,
        "perfilado": {
            "etapa_actual": etapa_perfilado,
            "etapa_nombres": ETAPA_PERFILADO,
            "enganche_registrado": enganche_registrado,
            "buro_registrado": buro_registrado,
            "enganche_minimo_calificado": ENGANCHE_MINIMO_CALIFICADO,
        },
        "anti_loop": {
            "intentos_pregunta_enganche_sin_respuesta": intentos_enganche,
            "intentos_pregunta_buro_sin_respuesta": intentos_buro,
            "regla": "Si intentos >= 2 para una pregunta, NO repetirla en este turno.",
        },
        "senales_minimas": _detectar_intencion_minima(texto_usuario),
        "catalogo": _catalogo_para_prompt(),
        "enganches_referenciales_20pct": enganches_info,
        "desempeno_modelos": COMPARACION_DESEMPENO,
        "ubicacion_sucursal": _sucursal_mas_cercana(telefono),
        "regla_contexto": {
            "ignorar_catalogo_anterior": True,
            "catalogo_anterior": sorted(PALABRAS_CATALOGO_ANTERIOR),
            "catalogo_actual": versiones_validas,
        },
        "reglas_multimedia": {
            "si_mensaje_contiene_contexto_multimedia_analizado": (
                "Usa el análisis multimedia como contexto real del cliente. "
                "No respondas que estás limitado a texto. "
                "Si el cliente pregunta 'qué opinas', da una opinión comercial breve basada en el análisis. "
                "No marques send_images, send_videos ni send_pdf salvo que el cliente lo pida explícitamente."
            ),
            "no_enviar_catalogo_por_defecto": (
                "Si el cliente envió una imagen/video/audio/sticker, no envíes más fotos/videos/fichas "
                "solo por haber recibido multimedia. Primero responde a la intención."
            ),
        },
    }


    instrucciones = _construir_instrucciones_desde_bd(config_ia)

    instrucciones_extra = """
Reglas adicionales obligatorias para este CRM:
- Si el mensaje contiene [CONTEXTO MULTIMEDIA ANALIZADO], úsalo como contexto real.
- Nunca digas que solo puedes procesar texto cuando ya existe contexto multimedia analizado.
- Si el cliente manda una imagen y pregunta "qué opinas", responde con una opinión útil del vehículo o contenido.
- No envíes imágenes, videos ni fichas técnicas solo porque el cliente mandó una imagen/video/audio.
- Solo marca send_images=true, send_videos=true o send_pdf=true si el cliente lo pidió explícitamente.
- Si no estás seguro del modelo exacto, usa lenguaje de probabilidad y pide confirmación.
""".strip()

    instrucciones = "\n\n".join(
        parte for parte in [instrucciones, instrucciones_extra]
        if str(parte or "").strip()
    )

    if not instrucciones:
        return {}
    
    try:
        modelo = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")

        respuesta = client.models.generate_content(
            model=modelo,
            contents=json.dumps(contexto, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=instrucciones,
                response_mime_type="application/json",
                response_schema=GEMINI_DECISION_SCHEMA,
                temperature=0.3,
            ),
        )

        salida = _json_seguro(getattr(respuesta, "text", "") or "")

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error Gemini: {e}", exc_info=True)
        return {}

    salida.setdefault("reply_text", "")
    salida.setdefault("selected_version", None)
    salida.setdefault("send_pdf", False)
    salida.setdefault("send_images", False)
    salida.setdefault("send_videos", False)
    salida.setdefault("requiere_asesor", False)
    salida.setdefault("accion_ofrecida", "ninguna")
    salida.setdefault("nueva_etapa_perfilado", etapa_perfilado)
    salida.setdefault("detected_profile", {})
    salida.setdefault("reasoning_tags", [])

    version = _normalizar_version_catalogo(salida.get("selected_version"))
    salida["selected_version"] = version

    accion = (salida.get("accion_ofrecida") or "ninguna").strip()
    salida["accion_ofrecida"] = accion if accion in ACCIONES_OFRECIDAS_VALIDAS else "ninguna"

    salida["send_pdf"] = bool(salida.get("send_pdf")) and bool(version)
    salida["send_images"] = bool(salida.get("send_images")) and bool(version)
    salida["send_videos"] = bool(salida.get("send_videos")) and bool(version)
    salida["requiere_asesor"] = bool(salida.get("requiere_asesor"))
    if salida["accion_ofrecida"] in ("lead_calificado", "confirmar_canalizacion"):
        salida["requiere_asesor"] = True
    salida["reply_text"] = _limitar_texto(salida.get("reply_text") or "")

    try:
        nueva_etapa = max(etapa_perfilado, min(4, int(salida.get("nueva_etapa_perfilado", etapa_perfilado))))
    except (TypeError, ValueError):
        nueva_etapa = etapa_perfilado
    salida["nueva_etapa_perfilado"] = nueva_etapa

    dp = salida.get("detected_profile") or {}
    if dp.get("enganche_monto") is not None:
        try:
            dp["enganche_monto"] = int(dp["enganche_monto"])
        except (TypeError, ValueError):
            dp["enganche_monto"] = None
    salida["detected_profile"] = dp

    if salida["requiere_asesor"]:
        salida["send_pdf"] = False
        salida["send_images"] = False
        salida["send_videos"] = False
        if salida["accion_ofrecida"] not in ("lead_calificado", "confirmar_canalizacion"):
            salida["accion_ofrecida"] = "confirmar_canalizacion"

    return salida


# Historial y persistencia
def _obtener_ultimo_mensaje_saliente(cliente: ClienteComercial, numero_asesor: str) -> str:
    mensajes = (
        MensajeWhatsApp.objects
        .filter(cliente=cliente, numero_asesor=numero_asesor, direction="out")
        .order_by("-id").only("body", "raw")
    )[:25]
    for m in mensajes:
        body = (m.body or "").strip()
        if _mensaje_de_historial_vigente(body=body, raw=m.raw):
            return body
    return ""


def _obtener_ultima_accion_ofrecida(cliente: ClienteComercial, numero_asesor: str) -> Optional[str]:
    mensajes = (
        MensajeWhatsApp.objects
        .filter(cliente=cliente, numero_asesor=numero_asesor, direction="out")
        .order_by("-id").only("body", "raw")
    )[:25]
    for m in mensajes:
        raw = m.raw or {}
        body = (m.body or "").strip()
        if not _mensaje_de_historial_vigente(body=body, raw=raw):
            continue
        accion = (
            raw.get("conversation_meta", {}).get("accion_ofrecida")
            or raw.get("accion_ofrecida") or ""
        ).strip()
        if accion in ACCIONES_OFRECIDAS_VALIDAS:
            return accion
    return None


def _contar_mensajes_entrantes(cliente: ClienteComercial, numero_asesor: str) -> int:
    return MensajeWhatsApp.objects.filter(
        cliente=cliente, numero_asesor=numero_asesor, direction="in"
    ).count()


def _serializar_historial(cliente: ClienteComercial, numero_asesor: str, limite: int = 12) -> list[dict[str, str]]:
    mensajes = (
        MensajeWhatsApp.objects
        .filter(cliente=cliente, numero_asesor=numero_asesor)
        .order_by("-id").only("direction", "body", "raw")
    )[: max(limite * 4, 24)]
    historial = []
    for m in reversed(list(mensajes)):
        body = (m.body or "").strip()
        if not body:
            continue
        if not _mensaje_de_historial_vigente(body=body, raw=m.raw):
            continue
        historial.append({"role": "assistant" if m.direction == "out" else "user", "content": body})
    return historial[-limite:]


def _guardar_salida(
    *, telefono: str, numero_asesor: str, cliente: ClienteComercial,
    texto: str, wa_message_id: str = "", raw: Optional[dict] = None,
    status_msg: str = "accepted",
) -> MensajeWhatsApp:
    return MensajeWhatsApp.objects.create(
        telefono=telefono, numero_asesor=numero_asesor, cliente=cliente,
        direction="out", body=texto, wa_message_id=wa_message_id or "",
        status=status_msg, raw=raw or {},
    )


# Cliente / expediente

@transaction.atomic
def _get_or_create_cliente_y_expediente(
    *, telefono: str, numero_asesor: str,
    profile_name: str = "", texto_entrante: str = "",
) -> tuple[ClienteComercial, ExpedienteDigital]:
    telefono = normaliza_tel_mx(telefono)
    numero_asesor = normaliza_tel_mx(numero_asesor)
    if not telefono:
        raise ValueError("Telefono invalido")

    nombre_detectado = _extraer_nombre_basico(profile_name, texto_entrante)
    cliente, _ = ClienteComercial.objects.get_or_create(
        telefono=telefono, defaults={"nombre": nombre_detectado},
    )
    if nombre_detectado and not (cliente.nombre or "").strip():
        cliente.nombre = nombre_detectado
        cliente.save(update_fields=["nombre", "actualizado_en"])

    cfg_linea = WHATSAPP_LINES.get(numero_asesor, {})
    agencia_linea = (cfg_linea.get("agencia") or "").strip()
    business_linea = (cfg_linea.get("business") or "Nuevos").strip()
    asesor_digital_linea = (cfg_linea.get("asesor_digital") or "").strip()

    expediente, _ = ExpedienteDigital.objects.get_or_create(
        cliente=cliente,
        defaults={"agencia": agencia_linea, "business": business_linea,
                  "asesor_digital": asesor_digital_linea,
                  "canal_contacto": "WhatsApp", "estado": "Contactado"},
    )

    cambios = []
    for campo, valor in [
        ("agencia", agencia_linea), ("business", business_linea),
        ("asesor_digital", asesor_digital_linea),
    ]:
        if valor and getattr(expediente, campo) != valor:
            setattr(expediente, campo, valor); cambios.append(campo)
    if expediente.canal_contacto != "WhatsApp":
        expediente.canal_contacto = "WhatsApp"; cambios.append("canal_contacto")
    if not (expediente.estado or "").strip():
        expediente.estado = "Contactado"; cambios.append("estado")

    version_detectada = _buscar_version_en_texto(texto_entrante)
    if version_detectada and expediente.auto_interes != version_detectada:
        expediente.auto_interes = version_detectada; cambios.append("auto_interes")
    if expediente.auto_interes and expediente.auto_interes not in _obtener_catalogo_dict():
        expediente.auto_interes = ""
        cambios.append("auto_interes")

    now = timezone.now()
    if not expediente.primer_contacto_at:
        expediente.primer_contacto_at = now
        cambios.append("primer_contacto_at")

    if cambios:
        cambios.append("actualizado")
        expediente.save(update_fields=list(dict.fromkeys(cambios)))

    return cliente, expediente


def _estado_conversacion_desde_etapa(etapa: int) -> tuple[str, str]:
    if etapa <= ETAPA_PERFILADO["sin_iniciar"]:
        return "sin_iniciar", ""

    if etapa == ETAPA_PERFILADO["pedir_nombre"]:
        return "perfilando", "nombre"

    if etapa == ETAPA_PERFILADO["pedir_enganche"]:
        return "perfilando", "enganche"

    if etapa == ETAPA_PERFILADO["pedir_buro"]:
        return "perfilando", "buro"

    return "informando", ""


def _guardar_datos_detectados_en_cliente_y_expediente(
    *, cliente: ClienteComercial, expediente: ExpedienteDigital,
    profile_name: str, detected_profile: dict[str, Any],
    version_detectada: Optional[str], nueva_etapa_perfilado: int,
    numero_asesor: str = "",
) -> None:
    cambios_cliente: list[str] = []
    cambios_expediente: list[str] = []
    detected_profile = detected_profile or {}

    nombre_detectado = (
        detected_profile.get("nombre_detectado")
        or _extraer_nombre_basico(profile_name, "")
        or ""
    ).strip()

    if nombre_detectado and not (cliente.nombre or "").strip():
        cliente.nombre = nombre_detectado
        cambios_cliente.extend(["nombre", "actualizado_en"])

    version_detectada = _normalizar_version_catalogo(version_detectada)

    if version_detectada and expediente.auto_interes != version_detectada:
        expediente.auto_interes = version_detectada
        cambios_expediente.append("auto_interes")

    enganche = _int_detectado(detected_profile.get("enganche_monto"))
    if enganche is not None and expediente.enganche_monto != enganche:
        expediente.enganche_monto = enganche
        cambios_expediente.append("enganche_monto")

    presupuesto_mensual = _int_detectado(detected_profile.get("presupuesto_mensual"))
    if presupuesto_mensual is not None and expediente.presupuesto_mensual != presupuesto_mensual:
        expediente.presupuesto_mensual = presupuesto_mensual
        cambios_expediente.append("presupuesto_mensual")

    buro = _texto_detectado(detected_profile.get("buro_estado"), 30).lower()
    if buro and expediente.buro_estado != buro:
        expediente.buro_estado = buro
        cambios_expediente.append("buro_estado")

    forma_pago = _texto_detectado(detected_profile.get("forma_pago"), 30).lower()
    if forma_pago and expediente.forma_pago != forma_pago:
        expediente.forma_pago = forma_pago
        cambios_expediente.append("forma_pago")

    tipo_cliente = _texto_detectado(detected_profile.get("tipo_cliente"), 30).lower()
    if tipo_cliente and expediente.tipo_cliente != tipo_cliente:
        expediente.tipo_cliente = tipo_cliente
        cambios_expediente.append("tipo_cliente")

    uso_vehiculo = _texto_detectado(
        detected_profile.get("uso_vehiculo")
        or detected_profile.get("uso_detectado"),
        255,
    )
    if uso_vehiculo and expediente.uso_vehiculo != uso_vehiculo:
        expediente.uso_vehiculo = uso_vehiculo
        cambios_expediente.append("uso_vehiculo")

    plazo_compra = _texto_detectado(detected_profile.get("plazo_compra"), 120)
    if plazo_compra and expediente.plazo_compra != plazo_compra:
        expediente.plazo_compra = plazo_compra
        cambios_expediente.append("plazo_compra")

    enganche_para_calificar = expediente.enganche_monto or enganche
    buro_para_calificar = expediente.buro_estado or buro or "desconocido"

    if _lead_es_calificado(enganche_para_calificar, buro_para_calificar):
        if expediente.estado not in ("Lead Calificado", "Pendiente de Cotización"):
            expediente.estado = "Lead Calificado"
            cambios_expediente.append("estado")

    estado_conversacion, pregunta_pendiente = _estado_conversacion_desde_etapa(nueva_etapa_perfilado)
    etapa_str = {v: k for k, v in ETAPA_PERFILADO.items()}.get(
        nueva_etapa_perfilado,
        "sin_iniciar",
    )

    datos_conversacion = {
        "etapa_perfilado": etapa_str,
        "etapa_perfilado_num": nueva_etapa_perfilado,
        "auto_interes": version_detectada,
        "enganche_monto": expediente.enganche_monto or enganche,
        "presupuesto_mensual": expediente.presupuesto_mensual or presupuesto_mensual,
        "buro_estado": expediente.buro_estado or buro,
        "forma_pago": expediente.forma_pago or forma_pago,
        "tipo_cliente": expediente.tipo_cliente or tipo_cliente,
        "uso_vehiculo": expediente.uso_vehiculo or uso_vehiculo,
        "plazo_compra": expediente.plazo_compra or plazo_compra,
    }

    _actualizar_datos_conversacion(
        expediente=expediente,
        numero_asesor=numero_asesor,
        datos=datos_conversacion,
        estado_conversacion=estado_conversacion,
        pregunta_pendiente=pregunta_pendiente,
    )

    if cambios_cliente:
        cliente.save(update_fields=list(dict.fromkeys(cambios_cliente)))

    if cambios_expediente:
        cambios_expediente.append("actualizado")
        expediente.save(update_fields=list(dict.fromkeys(cambios_expediente)))

def _ya_se_respondio_a_entrada(numero_asesor: str, wa_message_id_entrante: str) -> bool:
    numero_asesor = normaliza_tel_mx(numero_asesor)
    wa_message_id_entrante = (wa_message_id_entrante or "").strip()
    if not numero_asesor or len(wa_message_id_entrante) < 5:
        return False
    return MensajeWhatsApp.objects.filter(
        numero_asesor=numero_asesor, direction="out",
        raw__reply_to=wa_message_id_entrante,
    ).exists()


# Fallback si Gemini falla
def _fallback_respuesta(
    *, texto_usuario: str, profile_name: str, version_contexto: Optional[str],
    es_primer_mensaje: bool, etapa_perfilado: int, nombre_cliente: str,
    telefono: str = "",
) -> dict[str, Any]:
    version_contexto = _normalizar_version_catalogo(version_contexto)
    senales = _detectar_intencion_minima(texto_usuario)
    version_directa = _normalizar_version_catalogo(_buscar_version_en_texto(texto_usuario))
    version_final = version_directa or version_contexto
    nombre = nombre_cliente or _extraer_nombre_basico(profile_name, texto_usuario)

    if es_primer_mensaje or not (texto_usuario or "").strip():
        return {
            "reply_text": SALUDO_BASE, "selected_version": None,
            "send_pdf": False, "send_images": False, "requiere_asesor": False,
            "detected_profile": {"nombre_detectado": nombre},
            "reasoning_tags": ["fallback_saludo_inicial"],
            "accion_ofrecida": "pedir_nombre",
            "nueva_etapa_perfilado": ETAPA_PERFILADO["pedir_nombre"],
        }

    #ubicación en fallback
    if senales.get("pregunta_ubicacion"):
        return {
            "reply_text": _texto_ubicacion(telefono),
            "selected_version": version_final,
            "send_pdf": False, "send_images": False, "requiere_asesor": False,
            "detected_profile": {}, "reasoning_tags": ["fallback_ubicacion"],
            "accion_ofrecida": "ninguna", "nueva_etapa_perfilado": etapa_perfilado,
        }

    if etapa_perfilado == ETAPA_PERFILADO["pedir_enganche"]:
        pfx = f"Hola {nombre}! " if nombre else ""
        return {
            "reply_text": (
                f"{pfx}Para orientarte mejor, ¿cuánto tienes para el enganche o qué mensualidad buscas? "
                "También contamos con planes de arrendamiento. ¿Me lo puedes decir?"
            ),
            "selected_version": version_final, "send_pdf": False, "send_images": False,
            "requiere_asesor": False, "detected_profile": {},
            "reasoning_tags": ["fallback_insistir_enganche"],
            "accion_ofrecida": "pedir_enganche",
            "nueva_etapa_perfilado": ETAPA_PERFILADO["pedir_enganche"],
        }

    if etapa_perfilado == ETAPA_PERFILADO["pedir_buro"]:
        pfx = f"Hola {nombre}! " if nombre else ""
        return {
            "reply_text": f"{pfx}Solo me falta saber cómo estás en buró de crédito (bueno, regular o iniciando) para enviarte una propuesta real.",
            "selected_version": version_final, "send_pdf": False, "send_images": False,
            "requiere_asesor": False, "detected_profile": {},
            "reasoning_tags": ["fallback_insistir_buro"],
            "accion_ofrecida": "pedir_buro",
            "nueva_etapa_perfilado": ETAPA_PERFILADO["pedir_buro"],
        }
    
    if version_final and senales.get("pregunta_videos"):
        return {
            "reply_text": f"Claro, te comparto un video de {version_final.title()}.",
            "selected_version": version_final,
            "send_pdf": False,
            "send_images": False,
            "send_videos": True,
            "requiere_asesor": False,
            "detected_profile": {},
            "reasoning_tags": ["fallback_videos"],
            "accion_ofrecida": "continuar_contexto",
            "nueva_etapa_perfilado": etapa_perfilado,
        }

    if version_final and any([
        senales["pregunta_pdf"],
        any(k in _normalizar_texto(texto_usuario) for k in [
            "FICHA", "ESPECIFICACIONES", "COMO ES", "QUE TRAE", "QUE TIENE",
            "DIME MAS", "CUENTAME", "INFO", "INFORMACION", "DATOS", 
        ]),
    ]):
        return {
            "reply_text": _resumen_ficha_texto(version_final), "selected_version": version_final,
            "send_pdf": True, "send_images": False, "requiere_asesor": False,
            "detected_profile": {}, "reasoning_tags": ["fallback_pdf"],
            "accion_ofrecida": "compartir_pdf", "nueva_etapa_perfilado": etapa_perfilado,
        }

    if version_final and senales["pregunta_imagenes"]:
        return {
            "reply_text": f"Claro, te comparto imágenes de {version_final.title()}.",
            "selected_version": version_final, "send_pdf": False, "send_images": True,
            "requiere_asesor": False, "detected_profile": {},
            "reasoning_tags": ["fallback_imagenes"],
            "accion_ofrecida": "continuar_contexto", "nueva_etapa_perfilado": etapa_perfilado,
        }

    if version_final and senales["pregunta_precio"]:
        return {
            "reply_text": _respuesta_precio_version(version_final), "selected_version": version_final,
            "send_pdf": False, "send_images": False, "requiere_asesor": False,
            "detected_profile": {}, "reasoning_tags": ["fallback_precio"],
            "accion_ofrecida": "compartir_precio", "nueva_etapa_perfilado": etapa_perfilado,
        }

    if senales["cotizacion_personalizada"] or senales["intencion_compra"]:
        return {
            "reply_text": RESPUESTA_CONFIRMAR_ASESOR, "selected_version": version_final,
            "send_pdf": False, "send_images": False, "requiere_asesor": True,
            "detected_profile": {}, "reasoning_tags": ["fallback_asesor"],
            "accion_ofrecida": "confirmar_canalizacion", "nueva_etapa_perfilado": etapa_perfilado,
        }

    if version_directa:
        return {
            "reply_text": (
                f"Claro, te comparto información de {version_directa.title()}. "
                "Puedo ayudarte con precio, imágenes y ficha técnica en PDF."
            ),
            "selected_version": version_directa, "send_pdf": False, "send_images": False,
            "requiere_asesor": False, "detected_profile": {},
            "reasoning_tags": ["fallback_version_directa"],
            "accion_ofrecida": "continuar_contexto", "nueva_etapa_perfilado": etapa_perfilado,
        }

    return {
        "reply_text": RESPUESTA_FALLBACK, "selected_version": None,
        "send_pdf": False, "send_images": False, "requiere_asesor": False,
        "detected_profile": {}, "reasoning_tags": ["fallback_generico"],
        "accion_ofrecida": "pedir_necesidad", "nueva_etapa_perfilado": etapa_perfilado,
    }


def construir_respuesta_informativa(
    *,
    numero_asesor: str,
    telefono: str,
    profile_name: str,
    texto_usuario: str,
    auto_interes_actual: Optional[str] = None,
    ultimo_mensaje_saliente: str = "",
    historial_reciente: Optional[list[dict[str, str]]] = None,
    accion_ofrecida_previa: Optional[str] = None,
    etapa_perfilado: int = 0,
    enganche_registrado: Optional[int] = None,
    buro_registrado: str = "",
    es_primer_mensaje: bool = False,
    nombre_cliente: str = "",
) -> tuple[
    str,
    Optional[str],
    bool,
    bool,
    bool,
    bool,
    dict[str, Any],
    dict[str, Any],
    str,
    int,
]:
    texto_usuario = (texto_usuario or "").strip()
    historial_reciente = historial_reciente or []
    es_contexto_multimedia = _tiene_contexto_multimedia_analizado(texto_usuario)

    if texto_usuario.upper() in {
        "[IMAGE]",
        "[VIDEO]",
        "[AUDIO]",
        "[DOCUMENT]",
        "[STICKER]",
        "[LOCATION]",
        "[CONTACTS]",
        "[ORDER]",
        "[SYSTEM]",
        "[UNSUPPORTED_MESSAGE]",
    }:
        tipo_placeholder = texto_usuario.strip("[]").lower()
        return (
            (
                "Recibí tu mensaje. Para ayudarte mejor, ¿me confirmas qué necesitas revisar "
                "o qué modelo te interesa?"
            ),
            auto_interes_actual,
            False,  # send_pdf
            False,  # send_images
            False,  # send_videos
            False,  # requiere_asesor
            {},
            {"reasoning_tags": [f"placeholder_{tipo_placeholder}"]},
            "pedir_necesidad",
            etapa_perfilado,
        )

    auto_interes_actual = _normalizar_version_catalogo(auto_interes_actual)

    decision: dict[str, Any] = {}

    try:
        decision = _decision_conversacional_ia(
            numero_asesor=numero_asesor,
            telefono=telefono,
            nombre_cliente=nombre_cliente or profile_name,
            texto_usuario=texto_usuario,
            auto_interes_actual=auto_interes_actual,
            ultimo_mensaje_saliente=ultimo_mensaje_saliente,
            historial_reciente=historial_reciente,
            accion_ofrecida_previa=accion_ofrecida_previa,
            etapa_perfilado=etapa_perfilado,
            enganche_registrado=enganche_registrado,
            buro_registrado=buro_registrado,
            es_primer_mensaje=es_primer_mensaje,
        )
    except Exception:
        decision = {}

    if not decision:
        decision = _fallback_respuesta(
            texto_usuario=texto_usuario,
            profile_name=profile_name,
            version_contexto=auto_interes_actual,
            es_primer_mensaje=es_primer_mensaje,
            etapa_perfilado=etapa_perfilado,
            nombre_cliente=nombre_cliente,
            telefono=telefono,
        )

    selected_version = _normalizar_version_catalogo(
        decision.get("selected_version")
        or _buscar_version_en_texto(texto_usuario)
        or auto_interes_actual
    )

    senales_media = _detectar_intencion_minima(texto_usuario)

    t_norm = _normalizar_texto(texto_usuario)

    pide_pdf_explicito = any(k in t_norm for k in [
        "PDF",
        "FICHA",
        "FICHA TECNICA",
        "FICHA TÉCNICA",
        "BROCHURE",
        "CATALOGO",
        "CATÁLOGO",
        "ESPECIFICACIONES",
    ])

    pide_imagenes_explicito = bool(senales_media.get("pregunta_imagenes"))
    pide_videos_explicito = bool(senales_media.get("pregunta_videos"))

    es_peticion_media = bool(
        selected_version
        and (
            pide_pdf_explicito
            or pide_imagenes_explicito
            or pide_videos_explicito
        )
    )

    requiere_asesor = bool(decision.get("requiere_asesor"))

    # IMPORTANTE:
    # Si el cliente pidió fotos, video o ficha, NO debemos bloquear el envío
    # aunque Gemini haya escrito una frase de canalización.
    if es_peticion_media:
        requiere_asesor = False
        decision["requiere_asesor"] = False

    # Si el cliente envió multimedia, Gemini puede interpretar que debe mandar más media.
    # Lo bloqueamos salvo que el usuario lo pida explícitamente.
    decision_puede_enviar_media = not es_contexto_multimedia

    send_pdf = (
        (
            (bool(decision.get("send_pdf")) and decision_puede_enviar_media)
            or pide_pdf_explicito
        )
        and bool(selected_version)
        and not requiere_asesor
    )

    send_images = (
        (
            (bool(decision.get("send_images")) and decision_puede_enviar_media)
            or pide_imagenes_explicito
        )
        and bool(selected_version)
        and not requiere_asesor
    )

    send_videos = (
        (
            (bool(decision.get("send_videos")) and decision_puede_enviar_media)
            or pide_videos_explicito
        )
        and bool(selected_version)
        and not requiere_asesor
    )

    detected_profile = decision.get("detected_profile") or {}

    reply_text = _limitar_texto(
        (decision.get("reply_text") or RESPUESTA_FALLBACK).strip()
    )

    if es_contexto_multimedia and not es_peticion_media and _respuesta_quiere_enviar_media(reply_text):
        send_pdf = False
        send_images = False
        send_videos = False
        reply_text = _respuesta_desde_contexto_multimedia(
            texto_usuario=texto_usuario,
            selected_version=selected_version,
            telefono=telefono,
        )

    if es_contexto_multimedia and not es_peticion_media:
        send_pdf = False
        send_images = False
        send_videos = False

    if es_peticion_media:
        # Prioridad correcta:
        # si pide video, NO mandar fotos aunque el texto diga "ver".
        if pide_videos_explicito:
            send_videos = True
            send_images = False
            send_pdf = False
            reply_text = f"¡Claro! Te comparto un video de {selected_version.title()}."

        elif pide_imagenes_explicito:
            send_images = True
            send_videos = False
            send_pdf = False
            reply_text = f"¡Claro! Te comparto unas imágenes de {selected_version.title()}."

        elif pide_pdf_explicito:
            send_pdf = True
            send_images = False
            send_videos = False
            reply_text = f"¡Claro! Te comparto la ficha técnica de {selected_version.title()}."

    accion_ofrecida = (decision.get("accion_ofrecida") or "ninguna").strip()

    if accion_ofrecida not in ACCIONES_OFRECIDAS_VALIDAS:
        accion_ofrecida = _determinar_accion_ofrecida(
            reply_text=reply_text,
            send_pdf=send_pdf,
            requiere_asesor=requiere_asesor,
            selected_version=selected_version,
            texto_usuario=texto_usuario,
        )

    try:
        nueva_etapa = max(
            etapa_perfilado,
            min(4, int(decision.get("nueva_etapa_perfilado", etapa_perfilado))),
        )
    except (TypeError, ValueError):
        nueva_etapa = etapa_perfilado

    raw_decision = dict(decision)

    raw_decision.update({
        "selected_version": selected_version,
        "send_pdf": send_pdf,
        "send_images": send_images,
        "send_videos": send_videos,
        "requiere_asesor": requiere_asesor,
        "accion_ofrecida": accion_ofrecida,
        "reply_text": reply_text,
        "nueva_etapa_perfilado": nueva_etapa,
    })

    return (
        reply_text,
        selected_version,
        send_pdf,
        send_images,
        send_videos,
        requiere_asesor,
        detected_profile,
        raw_decision,
        accion_ofrecida,
        nueva_etapa,
    )

TIPOS_MEDIA_PROCESABLE_IA = {"image", "sticker", "video", "audio"}


def _describir_media_entrante_con_ia(
    *,
    raw_message: Optional[dict],
    numero_asesor: str,
) -> str:
    """
    Descarga el archivo desde Meta y le pide a Gemini que lo convierta
    en contexto útil para atención automotriz.
    """
    media = _extraer_media_entrante(raw_message)

    if not media:
        return ""

    try:
        blob, content_type = download_media_whatsapp(
            media.get("media_id") or media.get("id"),
            numero_asesor=numero_asesor,
        )

        mime_type = media.get("mime_type") or content_type or "application/octet-stream"
        media_type = media.get("type") or "media"

        prompt = f"""
Eres una IA de atención comercial para Volvo Cars Puebla.

El cliente envió un archivo de tipo: {media_type}.
Analiza el contenido y responde SOLO con un resumen útil para continuar la conversación.

Enfócate en:
- Si se ve o menciona algún vehículo.
- Si parece comprobante, identificación, cotización, captura de pantalla o documento.
- Si el audio/video contiene una solicitud de precio, modelo, cita, financiamiento o ubicación.
- Si el sticker comunica emoción/intención: interés, duda, aprobación, molestia, risa, etc.
- No inventes datos que no se vean o escuchen.

Devuelve máximo 8 líneas.
""".strip()

        client = _get_gemini_client()

        response = client.models.generate_content(
            model=getattr(
                settings,
                "GEMINI_MEDIA_MODEL",
                getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
            ),
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=blob,
                    mime_type=mime_type,
                ),
            ],
        )

        return _limitar_texto((getattr(response, "text", "") or "").strip(), 900)

    except Exception as exc:
        return (
            "El cliente envió un archivo multimedia, pero no pude analizarlo "
            f"automáticamente. Tipo detectado: {media.get('type')}. Error interno: {str(exc)[:180]}"
        )

TIPOS_MEDIA_IA = {
    "image",
    "video",
    "audio",
    "sticker",
    "document",
}

MIME_FALLBACK_MEDIA = {
    "image": "image/jpeg",
    "video": "video/mp4",
    "audio": "audio/ogg",
    "sticker": "image/webp",
    "document": "application/pdf",
}


def _extraer_media_entrante(raw_message: Optional[dict]) -> dict[str, Any]:
    """
    Extrae metadata del media entrante de WhatsApp Cloud API.

    Soporta:
    - image
    - video
    - audio
    - sticker
    - document

    WhatsApp envía el archivo como media_id.
    Después nosotros lo descargamos con download_media_whatsapp().
    """
    if not isinstance(raw_message, dict):
        return {}

    tipo = str(raw_message.get("type") or "").lower().strip()

    if tipo not in TIPOS_MEDIA_IA:
        return {}

    payload = raw_message.get(tipo) or {}

    if not isinstance(payload, dict):
        return {}

    media_id = str(payload.get("id") or "").strip()

    if not media_id:
        return {}

    caption = ""

    if tipo in ("image", "video", "document"):
        caption = str(payload.get("caption") or "").strip()

    return {
        "type": tipo,
        "media_id": media_id,
        "mime_type": str(payload.get("mime_type") or "").strip(),
        "sha256": str(payload.get("sha256") or "").strip(),
        "filename": str(payload.get("filename") or "").strip(),
        "caption": caption,
    }


def _mime_para_gemini(tipo: str, content_type: str = "") -> str:
    """
    Normaliza MIME type para que Gemini pueda interpretar el archivo.

    Cuando Meta no manda content-type claro, usamos un fallback por tipo.
    """
    tipo = str(tipo or "").lower().strip()
    content_type = str(content_type or "").split(";")[0].lower().strip()

    if content_type and content_type != "application/octet-stream":
        return content_type

    return MIME_FALLBACK_MEDIA.get(tipo, "application/octet-stream")


def _instruccion_analisis_multimedia(
    *,
    tipo: str,
    caption: str = "",
    texto_usuario: str = "",
) -> str:
    """
    Prompt para convertir un archivo de WhatsApp en contexto textual útil.

    Punto importante:
    Esta función NO debe vender ni cerrar la conversación. Solo traduce el
    contenido multimedia a texto para que el motor comercial responda mejor.
    """
    tipo = str(tipo or "media").lower().strip()
    caption = str(caption or "").strip()
    texto_usuario = str(texto_usuario or "").strip()

    reglas_por_tipo = {
        "image": (
            "Analiza la imagen. Indica si parece una foto real, render, captura, "
            "documento o publicidad. Si aparece un auto, describe marca visible, "
            "modelo probable, color, ángulo, condición aparente y elementos relevantes. "
            "Si el modelo no es seguro, dilo como probabilidad."
        ),
        "sticker": (
            "Analiza el sticker como reacción emocional del cliente. Describe la "
            "emoción probable: aprobación, duda, risa, molestia, sorpresa, rechazo "
            "o interés. No inventes intención de compra si no hay señales."
        ),
        "video": (
            "Analiza el video. Resume qué ocurre, si aparece o se menciona un vehículo, "
            "detalles visibles, sonido relevante, dudas del cliente y señales comerciales."
        ),
        "audio": (
            "Transcribe primero la idea principal del audio y luego resume intención, "
            "modelo mencionado, presupuesto, forma de pago, enganche, buró, cita, "
            "ubicación o cualquier dato útil del prospecto."
        ),
        "document": (
            "Analiza el documento. Resume datos visibles y clasifica si parece "
            "identificación, comprobante, ficha técnica, cotización, captura, recibo "
            "u otro archivo comercial. No extraigas datos sensibles innecesarios."
        ),
    }

    instruccion_tipo = reglas_por_tipo.get(
        tipo,
        "Analiza el archivo y resume su contenido útil para atención comercial.",
    )

    return f"""
Eres un asistente de CRM automotriz especializado en WhatsApp.

Tu tarea es analizar el archivo que envió el cliente y convertirlo en contexto útil
para que otra IA responda de forma natural y comercial.

{instruccion_tipo}

Reglas estrictas:
- Responde en español.
- No inventes datos que no aparezcan, se vean o se escuchen.
- Si no puedes identificar modelo, versión o documento, dilo claramente.
- No digas que estás limitado a texto.
- No ofrezcas enviar fotos, videos ni fichas; eso lo decide otra parte del flujo.
- No cierres venta ni prometas disponibilidad, precio final o promoción.
- Sé breve pero útil.
- Máximo 1200 caracteres.

Devuelve el análisis con este formato:
Contenido detectado:
Vehículo o documento:
Intención probable del cliente:
Datos útiles para responder:
Nivel de certeza:

Contexto textual adicional del mensaje:
{texto_usuario or "Sin texto adicional."}

Caption del archivo:
{caption or "Sin caption."}
""".strip()



def _analizar_media_con_gemini(
    *,
    media: dict[str, Any],
    blob: bytes,
    content_type: str,
    texto_usuario: str,
    numero_asesor: str,
) -> str:
    """
    Envía el archivo descargado desde Meta a Gemini para convertirlo en texto.

    Para archivos pequeños usamos inline bytes.
    Si el archivo es muy grande, no lo mandamos para evitar romper el request.
    """
    if not blob:
        return ""

    max_bytes = int(
        getattr(
            settings,
            "GEMINI_MAX_INLINE_MEDIA_BYTES",
            18 * 1024 * 1024,
        )
    )

    tipo = str(media.get("type") or "media").lower().strip()

    if len(blob) > max_bytes:
        return (
            f"El cliente envió un archivo de tipo {tipo}, "
            f"pero pesa {round(len(blob) / 1024 / 1024, 2)} MB y supera el límite "
            "configurado para análisis automático."
        )

    mime_type = _mime_para_gemini(tipo, content_type)

    if mime_type == "application/octet-stream":
        return f"El cliente envió un archivo de tipo {tipo}, pero no se pudo determinar el formato."

    prompt = _instruccion_analisis_multimedia(
        tipo=tipo,
        caption=media.get("caption", ""),
        texto_usuario=texto_usuario,
    )

    client = _get_gemini_client()

    modelo_multimodal = getattr(
        settings,
        "GEMINI_MULTIMODAL_MODEL",
        getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
    )

    respuesta = client.models.generate_content(
        model=modelo_multimodal,
        contents=[
            types.Part.from_bytes(
                data=blob,
                mime_type=mime_type,
            ),
            prompt,
        ],
        config=types.GenerateContentConfig(
            temperature=0.2,
        ),
    )

    texto = str(getattr(respuesta, "text", "") or "").strip()

    return _limitar_texto(texto, max_len=1200)


def _enriquecer_texto_usuario_con_media(
    *,
    texto_usuario: str,
    raw_message: Optional[dict],
    numero_asesor: str,
) -> str:
    """
    Si el cliente mandó media, descarga el archivo de Meta, lo analiza con Gemini
    y agrega el resultado al texto que ya usa tu flujo conversacional.

    Esto permite que tu función construir_respuesta_informativa() siga funcionando
    sin reescribir toda la lógica comercial.
    """
    texto_usuario = str(texto_usuario or "").strip()

    media = _extraer_media_entrante(raw_message)

    if not media:
        return texto_usuario

    tipo = media.get("type") or "media"
    caption = str(media.get("caption") or "").strip()
    media_id = str(media.get("media_id") or "").strip()

    descripcion = ""

    try:
        blob, content_type_descargado = download_media_whatsapp(
            media_id,
            numero_asesor=numero_asesor,
        )

        content_type = media.get("mime_type") or content_type_descargado

        descripcion = _analizar_media_con_gemini(
            media=media,
            blob=blob,
            content_type=content_type,
            texto_usuario=texto_usuario,
            numero_asesor=numero_asesor,
        )

    except Exception as exc:
        logger.exception(
            "No se pudo analizar media con Gemini | tipo=%s media_id=%s numero_asesor=%s error=%s",
            tipo,
            media_id,
            numero_asesor,
            str(exc),
        )

        descripcion = (
            f"El cliente envió un archivo de tipo {tipo}, "
            "pero no se pudo analizar automáticamente."
        )

    partes = []

    if texto_usuario and texto_usuario not in {
        "[IMAGE]",
        "[VIDEO]",
        "[AUDIO]",
        "[STICKER]",
        "[DOCUMENT]",
    }:
        partes.append(texto_usuario)

    if caption:
        partes.append(f"Caption del cliente: {caption}")

    if descripcion:
        partes.append(
            "[CONTEXTO MULTIMEDIA ANALIZADO]\n"
            f"Tipo: {tipo}\n"
            f"Media ID: {media_id}\n"
            f"Resumen: {descripcion}"
        )

    return "\n\n".join(partes).strip() or f"El cliente envió un archivo de tipo {tipo}."

def _tiene_contexto_multimedia_analizado(texto: str) -> bool:
    return "[CONTEXTO MULTIMEDIA ANALIZADO]" in str(texto or "")


def _extraer_tipo_multimedia_analizado(texto: str) -> str:
    match = re.search(r"Tipo:\s*([a-zA-Z0-9_-]+)", str(texto or ""), flags=re.IGNORECASE)
    return match.group(1).lower().strip() if match else ""


def _extraer_resumen_multimedia_analizado(texto: str) -> str:
    """
    Extrae solo el resumen del bloque multimedia para poder construir
    una respuesta de respaldo sin mostrar Media ID ni marcadores internos.
    """
    value = str(texto or "")

    if "[CONTEXTO MULTIMEDIA ANALIZADO]" not in value:
        return ""

    match = re.search(r"Resumen:\s*(.+)", value, flags=re.IGNORECASE | re.DOTALL)

    if not match:
        return ""

    resumen = match.group(1).strip()

    # Si en el futuro se agregan más secciones después del resumen, cortamos
    # antes de otros encabezados internos comunes.
    resumen = re.split(
        r"\n(?:Media ID|Raw|Payload|Contexto interno):",
        resumen,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()

    return _limitar_texto(resumen, max_len=700)


def _respuesta_quiere_enviar_media(texto: str) -> bool:
    t = _normalizar_texto(texto)
    patrones = [
        "TE COMPARTO UNAS IMAGENES",
        "TE COMPARTO IMAGENES",
        "TE COMPARTO FOTOS",
        "TE COMPARTO UN VIDEO",
        "TE COMPARTO VIDEO",
        "TE COMPARTO LA FICHA",
        "TE ENVIO IMAGENES",
        "TE ENVIO FOTOS",
        "TE ENVIO VIDEO",
        "TE ENVIO LA FICHA",
    ]

    return any(patron in t for patron in patrones)


def _respuesta_desde_contexto_multimedia(
    *,
    texto_usuario: str,
    selected_version: Optional[str],
    telefono: str = "",
) -> str:
    """
    Respuesta de seguridad para cuando el cliente mandó una imagen/video/audio
    y preguntó algo como "qué opinas", pero el modelo intentó mandar más media.
    """
    resumen = _extraer_resumen_multimedia_analizado(texto_usuario)
    tipo = _extraer_tipo_multimedia_analizado(texto_usuario)

    if selected_version:
        base = (
            f"Se ve interesante. Por lo que enviaste, parece relacionado con {selected_version.title()}. "
        )
    elif tipo == "sticker":
        base = "Recibí tu sticker. Lo tomo como una reacción a la conversación. "
    elif tipo == "audio":
        base = "Escuché tu audio y tomé los puntos importantes. "
    elif tipo == "document":
        base = "Revisé el documento que enviaste. "
    elif tipo == "video":
        base = "Revisé el video que enviaste. "
    else:
        base = "Revisé la imagen que enviaste. "

    if resumen:
        return _limitar_texto(
            f"{base}\n\n{resumen}\n\n"
            "Si te interesa avanzar, puedo ayudarte con precio, ficha técnica, "
            "opciones de financiamiento o agendar una visita.",
            max_len=900,
        )

    return _limitar_texto(
        f"{base}"
        "Si quieres, puedo ayudarte a identificar el modelo, revisar opciones de precio "
        "o canalizarte con un asesor para una propuesta formal.",
        max_len=700,
    )


def _dividir_mensaje_whatsapp(
    texto: str,
    max_len: int = 500,
    max_partes: int = 2,
) -> list[str]:
    """
    Divide sin cortar palabras ni ideas cuando sea posible.
    Prioridad de corte:
    1. párrafo
    2. oración
    3. espacio
    """
    texto = re.sub(r"\n{3,}", "\n\n", (texto or "").strip())

    if not texto:
        return []

    if len(texto) <= max_len:
        return [texto]

    partes = []
    restante = texto

    while restante and len(partes) < max_partes:
        if len(restante) <= max_len:
            partes.append(restante.strip())
            break

        ventana = restante[:max_len]

        cortes = [
            ventana.rfind("\n\n"),
            ventana.rfind(". "),
            ventana.rfind("? "),
            ventana.rfind("! "),
            ventana.rfind("; "),
            ventana.rfind(", "),
            ventana.rfind(" "),
        ]

        corte = max(cortes)

        if corte < int(max_len * 0.55):
            corte = ventana.rfind(" ")

        if corte <= 0:
            corte = max_len

        parte = restante[:corte].strip()
        restante = restante[corte:].strip()

        if parte:
            partes.append(parte)

    if restante and partes:
        aviso = "Te comparto el resto en el siguiente seguimiento para no saturarte."
        espacio = max_len - len(partes[-1]) - 2

        if espacio >= len(aviso):
            partes[-1] = f"{partes[-1]}\n\n{aviso}"
        else:
            partes[-1] = partes[-1][: max_len - 3].rstrip() + "..."

    return partes


def _segundos_escritura_ia(texto: str) -> int:
    """
    Delay humano. Puedes fijarlo en settings.py:
    IA_WHATSAPP_TYPING_SECONDS = 4
    """
    fijo = getattr(settings, "IA_WHATSAPP_TYPING_SECONDS", None)

    if fijo is not None:
        try:
            return max(0, min(int(fijo), 24))
        except (TypeError, ValueError):
            pass

    largo = len(texto or "")

    if largo <= 180:
        return 2

    if largo <= 500:
        return 4

    return 6

# Respuesta automática completa

def responder_mensaje_automatico(
    *, wa_from: str, numero_asesor: str, profile_name: str = "",
    texto_usuario: str = "", wa_message_id_entrante: str = "",
    raw_message: Optional[dict] = None,
) -> dict:
    telefono = normaliza_tel_mx(replace_start(wa_from))
    numero_asesor = normaliza_tel_mx(numero_asesor)
    wa_message_id_entrante = (wa_message_id_entrante or "").strip()

    texto_usuario_original = texto_usuario

    texto_usuario = _enriquecer_texto_usuario_con_media(
        texto_usuario=texto_usuario,
        raw_message=raw_message,
        numero_asesor=numero_asesor,
    )
    
    if not telefono:
        raise ValueError("Numero invalido para responder automaticamente")
    if not numero_asesor:
        raise ValueError("Numero de asesor invalido")

    if _ya_se_respondio_a_entrada(numero_asesor, wa_message_id_entrante):
        return {
            "ok": True, "skipped": True, "reason": "ya_se_respondio_a_esta_entrada",
            "telefono": telefono, "numero_asesor": numero_asesor,
            "wa_message_id_entrante": wa_message_id_entrante,
        }

    texto_usuario = _enriquecer_texto_usuario_con_media(
        texto_usuario=texto_usuario,
        raw_message=raw_message,
        numero_asesor=numero_asesor,
    )

    cliente, expediente = _get_or_create_cliente_y_expediente(
        telefono=telefono, numero_asesor=numero_asesor,
        profile_name=profile_name, texto_entrante=texto_usuario,
    )

    auto_interes_actual = _limpiar_auto_interes_invalido(expediente)
    nombre_contexto = (cliente.nombre or "").strip() or _extraer_nombre_basico(profile_name, "") or ""
    ultimo_mensaje_saliente = _obtener_ultimo_mensaje_saliente(cliente, numero_asesor)
    historial_reciente = _serializar_historial(cliente, numero_asesor)
    accion_ofrecida_previa = _obtener_ultima_accion_ofrecida(cliente, numero_asesor)

    total_entrantes = _contar_mensajes_entrantes(cliente, numero_asesor)
    es_primer_mensaje = total_entrantes <= 1

    etapa_perfilado = _obtener_etapa_perfilado(expediente, numero_asesor)
    enganche_registrado: Optional[int] = expediente.enganche_monto
    buro_str = expediente.buro_estado or _leer_dato_conversacion(
        expediente,
        numero_asesor,
        "buro_estado",
        default="desconocido",
    )

    (
        respuesta_texto, version_contexto, enviar_pdf, enviar_imagenes, enviar_videos,
        requiere_asesor, detected_profile, raw_decision, accion_ofrecida,
        nueva_etapa_perfilado,
    ) = construir_respuesta_informativa(
        numero_asesor=numero_asesor,
        telefono=telefono,
        profile_name=profile_name,
        texto_usuario=texto_usuario,
        auto_interes_actual=auto_interes_actual,
        ultimo_mensaje_saliente=ultimo_mensaje_saliente,
        historial_reciente=historial_reciente,
        accion_ofrecida_previa=accion_ofrecida_previa,
        etapa_perfilado=etapa_perfilado,
        enganche_registrado=enganche_registrado,
        buro_registrado=buro_str,
        es_primer_mensaje=es_primer_mensaje,
        nombre_cliente=nombre_contexto,
    )

    _guardar_datos_detectados_en_cliente_y_expediente(
        cliente=cliente, expediente=expediente, profile_name=profile_name,
        detected_profile=detected_profile, version_detectada=version_contexto,
        nueva_etapa_perfilado=nueva_etapa_perfilado,
        numero_asesor=numero_asesor,
    )

    partes_respuesta = _dividir_mensaje_whatsapp(
        respuesta_texto,
        max_len=500,
        max_partes=2,
    )

    if not partes_respuesta:
        partes_respuesta = [RESPUESTA_FALLBACK]

    try:
        enviar_indicador_escribiendo_whatsapp(
            message_id=wa_message_id_entrante,
            numero_asesor=numero_asesor,
        )
        time.sleep(_segundos_escritura_ia(respuesta_texto))
    except Exception:
        # No rompemos el flujo si Meta no acepta el typing indicator.
        pass

    wa_res = None
    wa_message_id_salida = ""

    for index, parte in enumerate(partes_respuesta):
        reply_context_id = wa_message_id_entrante if index == 0 else ""

        wa_res_parte = enviar_texto_whatsapp(
            to=telefono,
            text=parte,
            numero_asesor=numero_asesor,
            reply_to_message_id=reply_context_id,
        )

        wa_message_id_parte = ""
        try:
            wa_message_id_parte = (wa_res_parte.get("messages") or [{}])[0].get("id", "") or ""
        except Exception:
            pass

        if index == 0:
            wa_res = wa_res_parte
            wa_message_id_salida = wa_message_id_parte

        _guardar_salida(
            telefono=telefono,
            numero_asesor=numero_asesor,
            cliente=cliente,
            texto=parte,
            wa_message_id=wa_message_id_parte,
            raw={
                "reply_to": wa_message_id_entrante,
                "ia_provider": "gemini",
                "ia_model": getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
                "numero_asesor": numero_asesor,
                "version_contexto": version_contexto,
                "requiere_asesor": requiere_asesor,
                "detected_profile": detected_profile,
                "decision": raw_decision,
                "accion_ofrecida": accion_ofrecida,
                "nueva_etapa_perfilado": nueva_etapa_perfilado,
                "parte": index + 1,
                "partes_total": len(partes_respuesta),
                "texto_usuario_original": texto_usuario_original,
                "texto_usuario_enriquecido": texto_usuario,
                "conversation_meta": {
                    "accion_ofrecida": accion_ofrecida,
                    "accion_ofrecida_previa": accion_ofrecida_previa,
                    "etapa_perfilado": nueva_etapa_perfilado,
                },
                "wa_response": wa_res_parte,
                "raw_message": raw_message or {},
            },
            status_msg="accepted",
        )

        if index < len(partes_respuesta) - 1:
            time.sleep(1.2)

    # Envio de imagenes
    image_results: list = []
    image_errors: list = []
    if enviar_imagenes and version_contexto:
        for imagen_relativa in _imagenes_de_version(version_contexto):
            image_url = _resolver_url_media(imagen_relativa)
            filename = imagen_relativa.rsplit("/", 1)[-1]
            image_error = ""
            try:
                image_res = enviar_imagen_whatsapp_por_link(
                    to=telefono, link=image_url, numero_asesor=numero_asesor,
                    caption=f"Imagen de {version_contexto.title()}",
                )
            except Exception as exc:
                image_error = str(exc)
                image_res = {"ok": False, "error": image_error}

            image_message_id = ""
            try:
                image_message_id = (image_res.get("messages") or [{}])[0].get("id", "") or ""
            except Exception:
                pass

            _guardar_salida(
                telefono=telefono, numero_asesor=numero_asesor, cliente=cliente,
                texto=f"[FILE:{filename}]", wa_message_id=image_message_id,
                raw={"reply_to": wa_message_id_entrante, "version_contexto": version_contexto,
                     "meta_type": "image", "filename": filename, "media_link": image_url,
                     "accion_ofrecida": "continuar_contexto",
                     "conversation_meta": {"accion_ofrecida": "continuar_contexto"},
                     "wa_response": image_res, "image_error": image_error},
                status_msg="accepted" if image_message_id else "failed",
            )
            image_results.append(image_res)
            if image_error:
                image_errors.append(image_error)
    
    # Envio de videos
    video_results: list = []
    video_errors: list = []
    if enviar_videos and version_contexto:
        for video_relativo in _videos_de_version(version_contexto):
            video_url = _resolver_url_media(video_relativo)

            if not video_url:
                continue

            filename = video_relativo.rsplit("/", 1)[-1]
            video_error = ""

            try:
                video_res = enviar_video_whatsapp_por_link(
                    to=telefono, link=video_url, numero_asesor=numero_asesor,
                    caption=f"Video de {version_contexto.title()}",
                )
            except Exception as exc:
                video_error = str(exc)
                video_res = {"ok": False, "error": video_error}

            video_message_id = ""
            try:
                video_message_id = (video_res.get("messages") or [{}])[0].get("id", "") or ""
            except Exception:
                pass

            _guardar_salida(
                telefono=telefono, numero_asesor=numero_asesor, cliente=cliente,
                texto=f"[FILE:{filename}]", wa_message_id=video_message_id,
                raw={"reply_to": wa_message_id_entrante, "version_contexto": version_contexto,
                     "meta_type": "video", "filename": filename, "media_link": video_url,
                     "accion_ofrecida": "continuar_contexto",
                     "conversation_meta": {"accion_ofrecida": "continuar_contexto"},
                     "wa_response": video_res, "video_error": video_error},
                status_msg="accepted" if video_message_id else "failed",
            )
            video_results.append(video_res)
            if video_error:
                video_errors.append(video_error)

    # Envio de PDF
    pdf_res = None
    pdf_error = ""

    if enviar_pdf and version_contexto:
        catalogo = _obtener_catalogo_dict()
        data = catalogo.get(version_contexto) or {}
        pdf_url = _resolver_url_media(data.get("url_ficha_tecnica") or "")

        if pdf_url:
            try:
                pdf_res = enviar_documento_whatsapp_por_link(
                    to=telefono,
                    link=pdf_url,
                    numero_asesor=numero_asesor,
                    caption=f"Ficha tecnica de {version_contexto}",
                    filename=f"{version_contexto.lower().replace(' ', '-')}.pdf",
                )
            except Exception as exc:
                pdf_error = str(exc)
                pdf_res = {"ok": False, "error": pdf_error}

            pdf_message_id = ""
            try:
                pdf_message_id = (pdf_res.get("messages") or [{}])[0].get("id", "") or ""
            except Exception:
                pass

            _guardar_salida(
                telefono=telefono,
                numero_asesor=numero_asesor,
                cliente=cliente,
                texto=f"[FILE:{version_contexto}.pdf]",
                wa_message_id=pdf_message_id,
                raw={
                    "reply_to": wa_message_id_entrante,
                    "version_contexto": version_contexto,
                    "meta_type": "document",
                    "filename": f"{version_contexto.lower().replace(' ', '-')}.pdf",
                    "document_link": pdf_url,
                    "accion_ofrecida": "compartir_pdf",
                    "conversation_meta": {"accion_ofrecida": "compartir_pdf"},
                    "wa_response": pdf_res,
                    "pdf_error": pdf_error,
                },
                status_msg="accepted" if pdf_message_id else "failed",
            )
        else:
            enviar_pdf = False
            pdf_error = "El vehículo no tiene url_ficha_tecnica configurada."

    # Actualizar expediente
    # La IA no debe actualizar ultimo_contacto_at. Ese campo se reserva para
    # respuestas enviadas manualmente por un asesor humano desde el CRM.
    cambios = []

    if version_contexto and expediente.auto_interes != version_contexto:
        expediente.auto_interes = version_contexto
        cambios.append("auto_interes")

    if requiere_asesor:
        texto_normalizado = _normalizar_texto(texto_usuario)
        requiere_cotizacion = (
            accion_ofrecida in ("lead_calificado", "confirmar_canalizacion")
            or any(palabra in texto_normalizado for palabra in PALABRAS_COTIZACION)
        )

        # Marcar que requiere atención humana, pero SIN pausar la IA automáticamente.
        expediente.requiere_asesor = True
        expediente.motivo_requiere_asesor = (
            "Solicitud de cotización" if requiere_cotizacion else "Atención de asesor requerida"
        )
        cambios.extend(["requiere_asesor", "motivo_requiere_asesor"])

        if requiere_cotizacion:
            expediente.cotizacion_pendiente = True
            expediente.cotizacion_solicitada_at = timezone.now()
            expediente.estado = "Pendiente de Cotización"
            cambios.extend([
                "cotizacion_pendiente",
                "cotizacion_solicitada_at",
                "estado",
            ])
        elif expediente.estado not in ("Lead Calificado", "Requiere Asesor", "Pendiente de Cotización"):
            expediente.estado = "Requiere Asesor"
            cambios.append("estado")
        conversacion = _get_or_create_conversacion_ia(expediente, numero_asesor)

        datos_extra = conversacion.datos_extra if isinstance(conversacion.datos_extra, dict) else {}
        datos_extra.update({
            "requiere_asesor": True,
            "requiere_cotizacion": requiere_cotizacion,
            "accion_ofrecida": accion_ofrecida,
            "auto_interes": version_contexto,
            "marcado_at": timezone.now().isoformat(),
        })

        conversacion.datos_extra = datos_extra
        conversacion.estado_conversacion = (
            "pendiente_cotizacion" if requiere_cotizacion else "informando"
        )
        conversacion.ultima_intencion = accion_ofrecida or ""
        conversacion.ultimo_modelo_mencionado = version_contexto or ""

        conversacion.save(update_fields=[
            "datos_extra",
            "estado_conversacion",
            "ultima_intencion",
            "ultimo_modelo_mencionado",
        ])

    cfg_linea = WHATSAPP_LINES.get(numero_asesor, {})
    for campo, valor in [
        ("agencia", (cfg_linea.get("agencia") or "").strip()),
        ("business", (cfg_linea.get("business") or "Nuevos").strip()),
    ]:
        if valor and getattr(expediente, campo) != valor:
            setattr(expediente, campo, valor); cambios.append(campo)

    if expediente.canal_contacto != "WhatsApp":
        expediente.canal_contacto = "WhatsApp"; cambios.append("canal_contacto")

    cambios.append("actualizado")
    expediente.save(update_fields=list(dict.fromkeys(cambios)))

    return {
        "ok": True, "telefono": telefono, "numero_asesor": numero_asesor,
        "cliente_id": cliente.id_cliente, "expediente_id": expediente.pk,
        "respuesta": respuesta_texto, "version_detectada": version_contexto,
        "pdf_enviado": enviar_pdf, "imagenes_enviadas": enviar_imagenes, 
        "videos_enviados": enviar_videos, "requiere_asesor": requiere_asesor,
        "accion_ofrecida": accion_ofrecida,"accion_ofrecida_previa": accion_ofrecida_previa,
        "etapa_perfilado_anterior": etapa_perfilado,
        "etapa_perfilado_nueva": nueva_etapa_perfilado,
        "detected_profile": detected_profile, "decision": raw_decision,
        "wa_response": wa_res, "pdf_response": pdf_res, "pdf_error": pdf_error,
        "image_responses": image_results, "image_errors": image_errors,
        "video_responses": video_results, "video_errors": video_errors,
    }