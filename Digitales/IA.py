from __future__ import annotations

from functools import lru_cache
import json
import re
import unicodedata
from typing import Any, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from openai import OpenAI

from .sett import WHATSAPP_LINES
from citas.models import ClienteComercial, normaliza_tel_mx
from .models import ExpedienteDigital, MensajeWhatsApp
from .contacto import (
    enviar_texto_whatsapp,
    enviar_documento_whatsapp_por_link,
    enviar_imagen_whatsapp_por_link,
    replace_start,
)


CATALOGO_VEHICULOS = {
    "TRANSPORTER COMBI 5 ASIENTOS": {
        "precio_desde": "$783,529 MXN",
        "precios": {
            "lista": "$783,529 MXN",
        },
        "pdf_relativo": "fichas/transporter/ficha-tecnica-transporter-pasajeros.pdf",
        "brochure_relativo": "fichas/transporter/brochure-transporter-pasajeros.pdf",
        "imagenes_relativas": [
            "fichas/transporter/transporter-combi-5-asientos.jpeg",
        ],
        "resumen": (
            "Transporter Combi 5 Asientos es la version mas practica para quien necesita una unidad de trabajo agil, "
            "con espacio para pasajeros y posibilidad de llevar equipo o herramientas sin sacrificar comodidad. "
            "La configuracion de 5 asientos, junto con su transmision manual de 6 velocidades y motor 2.0 TDI Diesel, "
            "la vuelve una alternativa muy funcional para traslados operativos, cuadrillas de servicio y uso mixto."
        ),
        "ficha_tecnica": {
            "version_modelo": "Transporter Combi 2025",
            "configuracion_asientos": "5 asientos (2 individuales delante y banca de 3 plazas en segunda fila)",
            "motor": "4 cilindros 2.0 TDI Diesel",
            "potencia": "120 Hp",
            "torque": "360 Nm",
            "transmision": "Manual de 6 velocidades",
            "traccion": "Delantera",
            "combustible": "Diesel",
            "largo": "5,350 mm",
            "alto": "1,886 mm",
            "ancho_con_espejos": "2,208 mm",
            "ancho_sin_espejos": "1,910 mm",
            "distancia_entre_ejes": "3,270 mm",
            "tanque_combustible": "55 L",
            "capacidad_arrastre": "3,500 kg con freno / 750 kg sin freno",
            "garantia": "Hasta 5 años o 200,000 km",
            "equipamiento_destacado": [
                "Pantalla tactil a color de 13 pulgadas",
                "Volante multifuncion",
                "Cuadro de instrumentos digital 13.2 pulgadas TFT",
                "App-Connect inalambrico",
                "Dos puertas laterales y porton trasero",
                "2 USB en cabina y 2 USB en habitaculo",
                "Iluminacion interior LED",
            ],
            "seguridad_base": [
                "Front Assist",
                "Lane Assist",
                "ESP",
                "Ayuda de aparcamiento trasera",
                "Airbags para conductor y acompanante",
                "Reconocimiento de senales de trafico",
                "Light Assist",
                "Detector de cansancio",
            ],
            "enfoque_de_uso": "Cuadrillas, servicios tecnicos, uso mixto, equipo y herramientas con pasajeros",
        },
    },
    "TRANSPORTER COMBI 8 ASIENTOS": {
        "precio_desde": "$742,723 MXN",
        "precios": {
            "lista": "$833,203 MXN",
            "contado": "$792,603 MXN",
            "financiado": "$742,723 MXN",
        },
        "pdf_relativo": "fichas/transporter/ficha-tecnica-transporter-pasajeros.pdf",
        "brochure_relativo": "fichas/transporter/brochure-transporter-pasajeros.pdf",
        "imagenes_relativas": [
            "fichas/transporter/transporter-combi-8-asientos.jpeg",
        ],
        "resumen": (
            "Transporter Combi 8 Asientos es la version mas equilibrada para quien busca transportar personal o pasajeros "
            "con buena capacidad, comodidad y una configuracion muy versatil. Integra motor 2.0 TDI Diesel, "
            "transmision automatica de 8 velocidades, 150 Hp y 360 Nm, por lo que resulta muy conveniente para "
            "traslados de personal, hoteleria, turismo y viajes frecuentes."
        ),
        "ficha_tecnica": {
            "version_modelo": "Transporter Combi 2025",
            "configuracion_asientos": "8 asientos (2 individuales delante, 3 plazas en segunda fila y 3 plazas en tercera fila)",
            "motor": "4 cilindros 2.0 TDI Diesel",
            "potencia": "150 Hp",
            "torque": "360 Nm",
            "transmision": "Automatica de 8 velocidades",
            "traccion": "Delantera",
            "combustible": "Diesel",
            "largo": "5,350 mm",
            "alto": "1,886 mm",
            "ancho_con_espejos": "2,208 mm",
            "ancho_sin_espejos": "1,910 mm",
            "distancia_entre_ejes": "3,270 mm",
            "tanque_combustible": "55 L",
            "capacidad_arrastre": "3,500 kg con freno / 750 kg sin freno",
            "garantia": "Hasta 5 años o 200,000 km",
            "equipamiento_destacado": [
                "Pantalla tactil a color de 13 pulgadas",
                "Volante multifuncion",
                "Cuadro de instrumentos digital 13.2 pulgadas TFT",
                "App-Connect inalambrico",
                "6 altavoces",
                "Dos puertas laterales y porton trasero",
                "2 USB en cabina y 2 USB en habitaculo",
                "Iluminacion interior LED",
            ],
            "seguridad_base": [
                "Front Assist",
                "Lane Assist",
                "ESP",
                "Ayuda de aparcamiento trasera",
                "Airbags para conductor y acompanante",
                "Reconocimiento de senales de trafico",
                "Light Assist",
                "Detector de cansancio",
            ],
            "enfoque_de_uso": "Transporte de personal, hoteleria, turismo, traslados privados y viajes frecuentes",
        },
    },
    "TRANSPORTER COMBI 9 ASIENTOS": {
        "precio_desde": "$870,000 MXN",
        "precios": {
            "lista": "$870,000 MXN",
        },
        "pdf_relativo": "fichas/transporter/ficha-tecnica-transporter-pasajeros.pdf",
        "brochure_relativo": "fichas/transporter/brochure-transporter-pasajeros.pdf",
        "imagenes_relativas": [
            "fichas/transporter/transporter-combi-9-asientos.jpeg",
        ],
        "resumen": (
            "Transporter Combi 9 Asientos es la opcion para quien necesita mover mas pasajeros sin salir de una configuracion "
            "comoda y moderna. Conserva motor 2.0 TDI Diesel, transmision automatica de 8 velocidades, 150 Hp y 360 Nm, "
            "pero suma una distribucion interior pensada para aprovechar mejor la capacidad de personas."
        ),
        "ficha_tecnica": {
            "version_modelo": "Transporter Combi 2025",
            "configuracion_asientos": "9 asientos (2 individuales delante, 2 plazas en segunda y tercera fila, y 3 plazas en cuarta fila)",
            "motor": "4 cilindros 2.0 TDI Diesel",
            "potencia": "150 Hp",
            "torque": "360 Nm",
            "transmision": "Automatica de 8 velocidades",
            "traccion": "Delantera",
            "combustible": "Diesel",
            "largo": "5,350 mm",
            "alto": "1,886 mm",
            "ancho_con_espejos": "2,208 mm",
            "ancho_sin_espejos": "1,910 mm",
            "distancia_entre_ejes": "3,270 mm",
            "tanque_combustible": "55 L",
            "capacidad_arrastre": "3,500 kg con freno / 750 kg sin freno",
            "garantia": "Hasta 5 años o 200,000 km",
            "equipamiento_destacado": [
                "Pantalla tactil a color de 13 pulgadas",
                "Volante multifuncion",
                "Cuadro de instrumentos digital 13.2 pulgadas TFT",
                "App-Connect inalambrico",
                "6 altavoces",
                "Dos puertas laterales y porton trasero",
                "2 USB en cabina y 2 USB en habitaculo",
                "Iluminacion interior LED",
            ],
            "seguridad_base": [
                "Front Assist",
                "Lane Assist",
                "ESP",
                "Ayuda de aparcamiento trasera",
                "Airbags para conductor y acompanante",
                "Reconocimiento de senales de trafico",
                "Light Assist",
                "Detector de cansancio",
            ],
            "enfoque_de_uso": "Empresas, grupos de trabajo, hoteleria y traslados con mayor capacidad de pasajeros",
        },
    },
}

SALUDO_BASE = (
    "Hola, soy Vagen. Te puedo apoyar con informacion de Transporter Combi 5, 8 y 9 asientos. "
    "Tambien te puedo compartir precio, imagenes y ficha tecnica en PDF. Como te llamas?"
)

RESPUESTA_MEDIA = (
    "Por ahora te puedo apoyar por texto con informacion de Transporter Combi 5, 8 y 9 asientos, "
    "ademas de precio, imagenes y ficha tecnica en PDF."
)

RESPUESTA_FALLBACK = (
    "Con gusto te ayudo con Transporter Combi 5, 8 y 9 asientos. "
    "Cuentame si te interesa precio, ficha tecnica, imagenes o cual version quieres revisar."
)

RESPUESTA_CONFIRMAR_ASESOR = (
    "Gracias. En un momento un asesor se comunicara contigo para brindarte atencion mas personalizada y dar seguimiento."
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
    "QUIERO HABLAR CON VENTAS", "ASESOR", "ATENCION PERSONALIZADA",
}

ACCIONES_OFRECIDAS_VALIDAS = {
    "saludo_inicial",
    "pedir_nombre",
    "pedir_necesidad",
    "compartir_precio",
    "compartir_pdf",
    "confirmar_canalizacion",
    "preguntar_tipo_cliente",
    "preguntar_forma_pago",
    "continuar_contexto",
    "ninguna",
}

PALABRAS_CATALOGO_ANTERIOR = {
    "CRAFTER", "CRAFTER ELEMENTAL", "CRAFTER INSPIRE", "CRAFTER ELITE", "CRAFTER URBAN",
    "ELEMENTAL", "INSPIRE", "ELITE", "URBAN",
}

MENCIONES_CATALOGO_ACTUAL = {
    "TRANSPORTER", "TRANSPORTER COMBI", "5 ASIENTOS", "8 ASIENTOS", "9 ASIENTOS",
    "CINCO ASIENTOS", "OCHO ASIENTOS", "NUEVE ASIENTOS",
}


# =========================
# Utilidades base
# =========================

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


def _build_pdf_url(pdf_relativo: str) -> str:
    return _build_media_url(pdf_relativo)


def _limitar_texto(texto: str, max_len: int = 900) -> str:
    texto = re.sub(r"\n{3,}", "\n\n", (texto or "").strip())
    if len(texto) <= max_len:
        return texto
    return texto[: max_len - 3].rstrip() + "..."


def _es_email(texto: str) -> bool:
    texto = (texto or "").strip()
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", texto))


def _limpiar_nombre_candidato(texto: str) -> str:
    texto = re.sub(r"[^a-zA-Z ]+", " ", texto or "").strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _parece_nombre_solo(texto: str) -> bool:
    texto = (texto or "").strip()
    if not texto or _es_email(texto):
        return False

    texto_limpio = _limpiar_nombre_candidato(texto)
    if not texto_limpio:
        return False

    palabras = [p.upper() for p in texto_limpio.split() if p.strip()]
    if len(palabras) == 0 or len(palabras) > 3:
        return False

    if any(p in STOPWORDS_NOMBRE for p in palabras):
        return False

    if any(len(p) < 2 for p in palabras):
        return False

    return True


def _extraer_nombre_basico(profile_name: str, texto: str) -> str:
    profile_name = (profile_name or "").strip()
    if profile_name and not _es_email(profile_name) and _parece_nombre_solo(profile_name):
        return _limpiar_nombre_candidato(profile_name)

    texto = (texto or "").strip()
    patrones = [
        r"\bmi nombre es\s+([a-zA-Z ]{2,80})",
        r"\bme llamo\s+([a-zA-Z ]{2,80})",
        r"\bsoy\s+([a-zA-Z ]{2,80})",
    ]

    for patron in patrones:
        m = re.search(patron, texto, flags=re.IGNORECASE)
        if m:
            nombre = re.sub(r"\s+", " ", m.group(1)).strip(" .,-")
            nombre = _limpiar_nombre_candidato(nombre)
            if nombre and not _es_email(nombre):
                return nombre

    if _parece_nombre_solo(texto):
        return _limpiar_nombre_candidato(texto)

    return ""


def _json_seguro(texto: str) -> dict[str, Any]:
    texto = (texto or "").strip()
    if not texto:
        return {}

    try:
        return json.loads(texto)
    except Exception:
        pass

    match = re.search(r"\{.*\}", texto, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}

    return {}


def _normalizar_version_catalogo(version: Optional[str]) -> Optional[str]:
    version = (version or "").strip()
    if version in CATALOGO_VEHICULOS:
        return version
    return None


# =========================
# Contexto válido / limpieza de catálogo anterior
# =========================

def _texto_refiere_catalogo_anterior(texto: str) -> bool:
    t = _normalizar_texto(texto)
    if not t:
        return False
    if "CRAFTER" in t:
        return True
    return any(frase in t for frase in PALABRAS_CATALOGO_ANTERIOR)


def _raw_refiere_catalogo_anterior(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False

    candidatos = [
        raw.get("version_contexto"),
        raw.get("filename"),
        raw.get("document_link"),
        raw.get("media_link"),
        raw.get("body"),
    ]

    decision = raw.get("decision") or {}
    if isinstance(decision, dict):
        candidatos.extend([
            decision.get("selected_version"),
            decision.get("reply_text"),
        ])

    return any(_texto_refiere_catalogo_anterior(str(c or "")) for c in candidatos)


def _mensaje_de_historial_vigente(*, body: str, raw: Any = None) -> bool:
    body = (body or "").strip()
    if _texto_refiere_catalogo_anterior(body):
        return False
    if _raw_refiere_catalogo_anterior(raw):
        return False
    return True


def _limpiar_auto_interes_invalido(expediente: ExpedienteDigital) -> Optional[str]:
    auto_interes = (expediente.auto_interes or "").strip()
    if not auto_interes:
        return None
    if auto_interes in CATALOGO_VEHICULOS:
        return auto_interes

    expediente.auto_interes = ""
    expediente.save(update_fields=["auto_interes", "actualizado"])
    return None


# =========================
# Catálogo actual
# =========================

def _buscar_version_en_texto(texto: str) -> Optional[str]:
    t = _normalizar_texto(texto)

    aliases = {
        "TRANSPORTER COMBI 5 ASIENTOS": [
            "TRANSPORTER COMBI 5 ASIENTOS", "TRANSPORTER 5 ASIENTOS", "COMBI 5 ASIENTOS",
            "VERSION 5 ASIENTOS", "5 ASIENTOS", "CINCO ASIENTOS", "LA DE 5", "EL DE 5",
        ],
        "TRANSPORTER COMBI 8 ASIENTOS": [
            "TRANSPORTER COMBI 8 ASIENTOS", "TRANSPORTER 8 ASIENTOS", "COMBI 8 ASIENTOS",
            "VERSION 8 ASIENTOS", "8 ASIENTOS", "OCHO ASIENTOS", "LA DE 8", "EL DE 8",
        ],
        "TRANSPORTER COMBI 9 ASIENTOS": [
            "TRANSPORTER COMBI 9 ASIENTOS", "TRANSPORTER 9 ASIENTOS", "COMBI 9 ASIENTOS",
            "VERSION 9 ASIENTOS", "9 ASIENTOS", "NUEVE ASIENTOS", "LA DE 9", "EL DE 9",
        ],
    }

    for version, nombres in aliases.items():
        for nombre in nombres:
            if _normalizar_texto(nombre) in t:
                return version
    return None


def _precio_de_version(version: str) -> str:
    if version in CATALOGO_VEHICULOS:
        return CATALOGO_VEHICULOS[version].get("precio_desde", "")
    return ""


def _texto_precios_version(version: str) -> str:
    if version not in CATALOGO_VEHICULOS:
        return ""

    precios = CATALOGO_VEHICULOS[version].get("precios") or {}
    lineas = []

    if precios.get("lista"):
        lineas.append(f"- Precio de lista: {precios['lista']}")
    if precios.get("contado"):
        lineas.append(f"- Precio de contado: {precios['contado']}")
    if precios.get("financiado"):
        lineas.append(f"- Precio financiado: {precios['financiado']}")

    if not lineas and CATALOGO_VEHICULOS[version].get("precio_desde"):
        lineas.append(f"- Precio desde: {CATALOGO_VEHICULOS[version]['precio_desde']}")

    return "\n".join(lineas)


def _resumen_ficha_texto(version: str) -> str:
    if version not in CATALOGO_VEHICULOS:
        return ""

    ficha = CATALOGO_VEHICULOS[version]["ficha_tecnica"]
    lineas = [
        f"Claro. Te comparto un resumen de {version.title()}:",
        "",
        f"- Configuracion: {ficha.get('configuracion_asientos', 'No disponible')}",
        f"- Motor: {ficha.get('motor', 'No disponible')}",
        f"- Potencia: {ficha.get('potencia', 'No disponible')}",
        f"- Torque: {ficha.get('torque', 'No disponible')}",
        f"- Transmision: {ficha.get('transmision', 'No disponible')}",
        f"- Traccion: {ficha.get('traccion', 'No disponible')}",
        f"- Combustible: {ficha.get('combustible', 'No disponible')}",
        f"- Garantia: {ficha.get('garantia', 'No disponible')}",
    ]

    if ficha.get("enfoque_de_uso"):
        lineas.append(f"- Uso recomendado: {ficha['enfoque_de_uso']}")

    destacados = ficha.get("equipamiento_destacado") or []
    if destacados:
        lineas.extend([
            "",
            "Lo mas destacado:",
            *[f"- {item}" for item in destacados[:4]],
            "",
            "Tambien te comparto la ficha tecnica en PDF.",
        ])

    return "\n".join(lineas).strip()


def _respuesta_precio_version(version: str) -> str:
    detalle = _texto_precios_version(version)
    return _limitar_texto(
        f"Claro. Te comparto los precios de {version.title()}:\n\n{detalle}\n\nSi quieres, tambien te comparto su ficha tecnica en PDF."
    )


def _respuesta_imagenes_version(version: str, incluir_pdf: bool = False) -> str:
    if incluir_pdf:
        return f"Claro. Te comparto imagenes y la ficha tecnica de {version.title()}."
    return f"Claro. Te comparto imagenes de {version.title()}. Si tambien quieres, te envio su ficha tecnica en PDF."


def _imagenes_de_version(version: str) -> list[str]:
    if version not in CATALOGO_VEHICULOS:
        return []
    return list(CATALOGO_VEHICULOS[version].get("imagenes_relativas") or [])


def _catalogo_para_prompt() -> str:
    catalogo = {}
    for version, data in CATALOGO_VEHICULOS.items():
        catalogo[version] = {
            "precio_desde": data["precio_desde"],
            "precios": data.get("precios", {}),
            "resumen": data["resumen"],
            "ficha_tecnica": data["ficha_tecnica"],
        }
    return json.dumps(catalogo, ensure_ascii=False, indent=2)


# =========================
# Señales mínimas para soporte / envío media
# =========================

def _detectar_intencion_minima(texto_usuario: str) -> dict[str, bool]:
    t = _normalizar_texto(texto_usuario)
    return {
        "pregunta_precio": any(k in t for k in ["PRECIO", "COSTO", "CUANTO CUESTA", "CUANTO VALE", "$", "DESDE"]),
        "pregunta_pdf": any(k in t for k in ["PDF", "FICHA", "FICHA TECNICA", "ESPECIFICACIONES", "CATALOGO", "DETALLES", "BROCHURE"]),
        "pregunta_imagenes": any(k in t for k in ["IMAGEN", "IMAGENES", "FOTO", "FOTOS", "FOTOGRAFIA", "FOTOGRAFIAS"]),
        "cotizacion_personalizada": any(k in t for k in PALABRAS_COTIZACION),
        "intencion_compra": any(k in t for k in PALABRAS_COMPRA),
    }


def _determinar_accion_ofrecida(
    *,
    reply_text: str,
    send_pdf: bool,
    handoff_advisor: bool,
    selected_version: Optional[str],
    texto_usuario: str,
) -> str:
    if handoff_advisor:
        return "confirmar_canalizacion"
    if send_pdf and selected_version:
        return "compartir_pdf"

    reply_norm = _normalizar_texto(reply_text)
    if "COMO TE LLAMAS" in reply_norm:
        return "pedir_nombre"
    if any(k in reply_norm for k in ["PARA QUE USO", "QUE USO LE DARAS", "EN QUE LA PIENSAS UTILIZAR"]):
        return "pedir_necesidad"
    if selected_version:
        return "continuar_contexto"
    return "ninguna"


# =========================
# OpenAI
# =========================
@lru_cache(maxsize=1)
def _get_openai_client() -> OpenAI:
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        raise RuntimeError("Falta configurar OPENAI_API_KEY")

    return OpenAI(
        api_key=api_key,
        timeout=25.0,
        max_retries=2,
    )


def _decision_conversacional_ia(
    *,
    telefono: str,
    nombre_cliente: str,
    texto_usuario: str,
    auto_interes_actual: Optional[str],
    ultimo_mensaje_saliente: str,
    historial_reciente: list[dict[str, str]],
    accion_ofrecida_previa: Optional[str],
) -> dict[str, Any]:
    auto_interes_actual = _normalizar_version_catalogo(auto_interes_actual)
    client = _get_openai_client()

    contexto = {
        "telefono": telefono,
        "nombre_cliente": nombre_cliente,
        "mensaje_usuario": texto_usuario,
        "ultimo_mensaje_saliente": ultimo_mensaje_saliente,
        "auto_interes_actual": auto_interes_actual,
        "historial_reciente": historial_reciente,
        "accion_ofrecida_previa": accion_ofrecida_previa,
        "senales_minimas": _detectar_intencion_minima(texto_usuario),
        "catalogo": json.loads(_catalogo_para_prompt()),
        "regla_contexto": {
            "ignorar_catalogo_anterior": True,
            "catalogo_anterior": sorted(PALABRAS_CATALOGO_ANTERIOR),
            "catalogo_actual": sorted(CATALOGO_VEHICULOS.keys()),
        },
    }

    instrucciones = """
Eres Vagen, asistente virtual comercial por WhatsApp para Volkswagen Vehiculos Comerciales.

SOLO puedes hablar del catalogo actual:
- TRANSPORTER COMBI 5 ASIENTOS
- TRANSPORTER COMBI 8 ASIENTOS
- TRANSPORTER COMBI 9 ASIENTOS

REGLA CRITICA DE CONTEXTO
- Ignora por completo cualquier contexto del catalogo anterior de Crafter.
- Si en el historial aparece Crafter, Elemental, Inspire, Elite o Urban, debes tratarlo como contexto obsoleto.
- No mezcles informacion de Crafter con Transporter.
- Si auto_interes_actual es null o no pertenece al catalogo actual, no lo tomes como contexto valido.

OBJETIVO
- Responder de forma natural, breve, util y comercial.
- Mantener el contexto conversacional sin depender de que el cliente responda con frases exactas.
- Interpretar correctamente mensajes muy ambiguos usando el ultimo mensaje saliente, el historial reciente y el contexto de version actual.

COMO INTERPRETAR MENSAJES AMBIGUOS
- Si el cliente escribe solo "5", "8", "9", "5 asientos", "8 asientos", "9 asientos", debes entender que eligio esa version.
- Si el cliente pregunta "precio de cada 1", "precio de las 3", "dame precio de todas", debes responder con los precios de las tres versiones en una sola respuesta.
- Si el cliente ya venia hablando de una version y luego manda "ficha tecnica", "pdf", "imagenes", "fotos", "detalles", "precio", debes asumir que se refiere a la version actual salvo que cambie claramente.
- Si el cliente va saltando entre 8, 9 y 5 asientos, debes seguir el cambio mas reciente sin confundirte.
- Si el cliente manda un saludo en medio de una conversacion ya avanzada, no reinicies. Continua con el contexto valido actual.

REGLA DE RECOMENDACION
- Si el cliente habla de cuadrillas, herramientas, equipo, trabajo operativo o uso mixto, prioriza 5 asientos.
- Si habla de transporte de personal, turismo, hoteleria o viajes frecuentes, prioriza 8 asientos.
- Si habla de mayor capacidad, mas pasajeros o grupos grandes, prioriza 9 asientos.

REGLA DE FINANCIAMIENTO Y COTIZACION
- Puedes compartir los precios disponibles del catalogo.
- NO inventes planes, tasas, mensualidades, enganches o condiciones financieras.
- Si el cliente pide cotizacion, mensualidades, corrida financiera, plan de pagos, credito o financiamiento mas detallado, debes canalizar con un asesor.
- Puedes decir que un asesor puede apoyarlo con esa informacion.

REGLA DE MEDIA
- send_pdf debe ser true solo si el cliente pidio ficha, pdf, brochure o ficha tecnica y hay una version clara.
- send_images debe ser true solo si el cliente pidio imagenes o fotos y hay una version clara.
- Si el cliente pidio precios generales de las tres versiones, no envies pdf ni imagenes a menos que tambien lo haya pedido y exista una version especifica.

ESTILO
- Español claro, natural, comercial y breve.
- No uses markdown complejo.
- No pongas URLs.
- reply_text debe venir listo para WhatsApp.
- No seas robotico.

FORMATO DE SALIDA
Responde EXCLUSIVAMENTE en JSON valido con esta estructura exacta:
{
  "reply_text": "texto listo para enviar",
  "selected_version": "TRANSPORTER COMBI 5 ASIENTOS | TRANSPORTER COMBI 8 ASIENTOS | TRANSPORTER COMBI 9 ASIENTOS | null",
  "send_pdf": true,
  "send_images": false,
  "handoff_advisor": false,
  "accion_ofrecida": "saludo_inicial | pedir_nombre | pedir_necesidad | compartir_precio | compartir_pdf | confirmar_canalizacion | preguntar_tipo_cliente | preguntar_forma_pago | continuar_contexto | ninguna",
  "detected_profile": {
    "nombre_detectado": "string o vacio",
    "tipo_cliente": "persona_fisica | persona_moral | desconocido",
    "forma_pago": "credito | contado | desconocido",
    "uso_detectado": "string breve",
    "interes_principal": "precio | ficha | comparacion | recomendacion | especificaciones | asesoria | cotizacion | compra | general"
  },
  "reasoning_tags": ["etiquetas", "breves"]
}

RESTRICCIONES
- selected_version debe ser una version valida del catalogo actual o null.
- No regreses versiones de Crafter.
- send_pdf y send_images no pueden ser true si selected_version es null.
- handoff_advisor debe ser true cuando pidan cotizacion o financiamiento detallado.
- reply_text maximo 900 caracteres.
"""

    respuesta = client.responses.create(
        model="gpt-4.1",
        instructions=instrucciones,
        input=json.dumps(contexto, ensure_ascii=False),
    )

    salida = _json_seguro(getattr(respuesta, "output_text", "") or "")
    if not salida:
        return {}

    salida.setdefault("reply_text", "")
    salida.setdefault("selected_version", None)
    salida.setdefault("send_pdf", False)
    salida.setdefault("send_images", False)
    salida.setdefault("handoff_advisor", False)
    salida.setdefault("accion_ofrecida", "ninguna")
    salida.setdefault("detected_profile", {})
    salida.setdefault("reasoning_tags", [])

    version = _normalizar_version_catalogo(salida.get("selected_version"))
    salida["selected_version"] = version

    accion_ofrecida = (salida.get("accion_ofrecida") or "ninguna").strip()
    if accion_ofrecida not in ACCIONES_OFRECIDAS_VALIDAS:
        accion_ofrecida = "ninguna"

    salida["send_pdf"] = bool(salida.get("send_pdf")) and bool(version)
    salida["send_images"] = bool(salida.get("send_images")) and bool(version)
    salida["handoff_advisor"] = bool(salida.get("handoff_advisor"))
    salida["reply_text"] = _limitar_texto(salida.get("reply_text") or "")
    salida["accion_ofrecida"] = accion_ofrecida

    if salida["handoff_advisor"]:
        salida["send_pdf"] = False
        salida["send_images"] = False
        salida["accion_ofrecida"] = "confirmar_canalizacion"

    return salida


# =========================
# Historial y persistencia
# =========================

def _obtener_ultimo_mensaje_saliente(cliente: ClienteComercial, numero_asesor: str) -> str:
    mensajes = (
        MensajeWhatsApp.objects
        .filter(cliente=cliente, numero_asesor=numero_asesor, direction="out")
        .order_by("-id")
        .only("body", "raw")
    )[:25]

    for mensaje in mensajes:
        body = (mensaje.body or "").strip()
        if _mensaje_de_historial_vigente(body=body, raw=mensaje.raw):
            return body
    return ""


def _obtener_ultima_accion_ofrecida(cliente: ClienteComercial, numero_asesor: str) -> Optional[str]:
    mensajes = (
        MensajeWhatsApp.objects
        .filter(cliente=cliente, numero_asesor=numero_asesor, direction="out")
        .order_by("-id")
        .only("body", "raw")
    )[:25]

    for mensaje in mensajes:
        raw = mensaje.raw or {}
        body = (mensaje.body or "").strip()
        if not _mensaje_de_historial_vigente(body=body, raw=raw):
            continue

        accion = (
            raw.get("conversation_meta", {}).get("accion_ofrecida")
            or raw.get("accion_ofrecida")
            or ""
        ).strip()

        if accion in ACCIONES_OFRECIDAS_VALIDAS:
            return accion

    return None


def _serializar_historial(cliente: ClienteComercial, numero_asesor: str, limite: int = 12) -> list[dict[str, str]]:
    mensajes = (
        MensajeWhatsApp.objects
        .filter(cliente=cliente, numero_asesor=numero_asesor)
        .order_by("-id")
        .only("direction", "body", "raw")
    )[: max(limite * 4, 24)]

    historial = []
    for m in reversed(list(mensajes)):
        body = (m.body or "").strip()
        if not body:
            continue
        if not _mensaje_de_historial_vigente(body=body, raw=m.raw):
            continue
        historial.append({
            "role": "assistant" if m.direction == "out" else "user",
            "content": body,
        })

    return historial[-limite:]


def _guardar_salida(
    *,
    telefono: str,
    numero_asesor: str,
    cliente: ClienteComercial,
    texto: str,
    wa_message_id: str = "",
    raw: Optional[dict] = None,
    status_msg: str = "accepted",
) -> MensajeWhatsApp:
    return MensajeWhatsApp.objects.create(
        telefono=telefono,
        numero_asesor=numero_asesor,
        cliente=cliente,
        direction="out",
        body=texto,
        wa_message_id=wa_message_id or "",
        status=status_msg,
        raw=raw or {},
    )


# =========================
# Cliente / expediente
# =========================
@transaction.atomic
def _get_or_create_cliente_y_expediente(
    *,
    telefono: str,
    numero_asesor: str,
    profile_name: str = "",
    texto_entrante: str = "",
) -> tuple[ClienteComercial, ExpedienteDigital]:
    telefono = normaliza_tel_mx(telefono)
    numero_asesor = normaliza_tel_mx(numero_asesor)

    if not telefono:
        raise ValueError("Telefono invalido")

    nombre_detectado = _extraer_nombre_basico(profile_name, texto_entrante)

    cliente, _ = ClienteComercial.objects.get_or_create(
        telefono=telefono,
        defaults={"nombre": nombre_detectado},
    )

    if nombre_detectado and not (cliente.nombre or "").strip():
        cliente.nombre = nombre_detectado
        cliente.save(update_fields=["nombre", "actualizado_en"])

    cfg_linea = WHATSAPP_LINES.get(numero_asesor, {})
    agencia_linea = (cfg_linea.get("agencia") or "").strip()
    business_linea = (cfg_linea.get("business") or "Comerciales").strip()
    asesor_digital_linea = (cfg_linea.get("asesor_digital") or "").strip()

    expediente, _ = ExpedienteDigital.objects.get_or_create(
        cliente=cliente,
        defaults={
            "agencia": agencia_linea,
            "business": business_linea,
            "asesor_digital": asesor_digital_linea,
            "canal_contacto": "WhatsApp",
            "estado": "Contactado",
        },
    )

    cambios = []
    if agencia_linea and expediente.agencia != agencia_linea:
        expediente.agencia = agencia_linea
        cambios.append("agencia")
    if business_linea and expediente.business != business_linea:
        expediente.business = business_linea
        cambios.append("business")
    if asesor_digital_linea and expediente.asesor_digital != asesor_digital_linea:
        expediente.asesor_digital = asesor_digital_linea
        cambios.append("asesor_digital")
    if expediente.canal_contacto != "WhatsApp":
        expediente.canal_contacto = "WhatsApp"
        cambios.append("canal_contacto")
    if not (expediente.estado or "").strip():
        expediente.estado = "Contactado"
        cambios.append("estado")

    version_detectada = _buscar_version_en_texto(texto_entrante)
    if version_detectada and expediente.auto_interes != version_detectada:
        expediente.auto_interes = version_detectada
        cambios.append("auto_interes")

    if expediente.auto_interes and expediente.auto_interes not in CATALOGO_VEHICULOS:
        expediente.auto_interes = ""
        cambios.append("auto_interes")

    now = timezone.now()
    if not expediente.primer_contacto_at:
        expediente.primer_contacto_at = now
        cambios.append("primer_contacto_at")
    expediente.ultimo_contacto_at = now
    cambios.append("ultimo_contacto_at")

    if cambios:
        cambios.append("actualizado")
        expediente.save(update_fields=list(dict.fromkeys(cambios)))

    return cliente, expediente


def _guardar_datos_detectados_en_cliente_y_expediente(
    *,
    cliente: ClienteComercial,
    expediente: ExpedienteDigital,
    profile_name: str,
    detected_profile: dict[str, Any],
    version_detectada: Optional[str],
) -> None:
    cambios_cliente = []
    cambios_expediente = []

    nombre_detectado = (
        (detected_profile or {}).get("nombre_detectado")
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

    uso_detectado = ((detected_profile or {}).get("uso_detectado") or "").strip()
    if uso_detectado:
        pauta_actual = (expediente.pauta or "").strip()
        uso_normalizado = f"Uso detectado: {uso_detectado}"
        if uso_normalizado not in pauta_actual:
            expediente.pauta = f"{pauta_actual}\n{uso_normalizado}".strip() if pauta_actual else uso_normalizado
            cambios_expediente.append("pauta")

    if cambios_cliente:
        cliente.save(update_fields=list(dict.fromkeys(cambios_cliente)))

    if cambios_expediente:
        cambios_expediente.append("actualizado")
        expediente.save(update_fields=list(dict.fromkeys(cambios_expediente)))


def _ya_se_respondio_a_entrada(numero_asesor: str, wa_message_id_entrante: str) -> bool:
    numero_asesor = normaliza_tel_mx(numero_asesor)
    wa_message_id_entrante = (wa_message_id_entrante or "").strip()

    if not numero_asesor or not wa_message_id_entrante:
        return False

    return MensajeWhatsApp.objects.filter(
        numero_asesor=numero_asesor,
        direction="out",
        raw__reply_to=wa_message_id_entrante,
    ).exists()


# =========================
# Fallback si OpenAI falla
# =========================

def _fallback_respuesta(
    *,
    texto_usuario: str,
    profile_name: str,
    version_contexto: Optional[str],
) -> dict[str, Any]:
    version_contexto = _normalizar_version_catalogo(version_contexto)
    senales = _detectar_intencion_minima(texto_usuario)
    version_directa = _normalizar_version_catalogo(_buscar_version_en_texto(texto_usuario))
    version_final = version_directa or version_contexto
    nombre = _extraer_nombre_basico(profile_name, texto_usuario)

    if not (texto_usuario or "").strip():
        return {
            "reply_text": SALUDO_BASE,
            "selected_version": None,
            "send_pdf": False,
            "send_images": False,
            "handoff_advisor": False,
            "detected_profile": {"nombre_detectado": nombre},
            "reasoning_tags": ["fallback_vacio"],
            "accion_ofrecida": "pedir_nombre" if not nombre else "pedir_necesidad",
        }

    if version_final and senales["pregunta_pdf"]:
        return {
            "reply_text": _resumen_ficha_texto(version_final),
            "selected_version": version_final,
            "send_pdf": True,
            "send_images": False,
            "handoff_advisor": False,
            "detected_profile": {},
            "reasoning_tags": ["fallback_pdf"],
            "accion_ofrecida": "compartir_pdf",
        }

    if version_final and senales["pregunta_imagenes"]:
        return {
            "reply_text": _respuesta_imagenes_version(version_final),
            "selected_version": version_final,
            "send_pdf": False,
            "send_images": True,
            "handoff_advisor": False,
            "detected_profile": {},
            "reasoning_tags": ["fallback_imagenes"],
            "accion_ofrecida": "continuar_contexto",
        }

    if version_final and senales["pregunta_precio"]:
        return {
            "reply_text": _respuesta_precio_version(version_final),
            "selected_version": version_final,
            "send_pdf": False,
            "send_images": False,
            "handoff_advisor": False,
            "detected_profile": {},
            "reasoning_tags": ["fallback_precio"],
            "accion_ofrecida": "compartir_precio",
        }

    if senales["cotizacion_personalizada"] or senales["intencion_compra"]:
        return {
            "reply_text": RESPUESTA_CONFIRMAR_ASESOR,
            "selected_version": version_final,
            "send_pdf": False,
            "send_images": False,
            "handoff_advisor": True,
            "detected_profile": {},
            "reasoning_tags": ["fallback_asesor"],
            "accion_ofrecida": "confirmar_canalizacion",
        }

    if version_directa:
        return {
            "reply_text": (
                f"Claro. Te comparto informacion de {version_directa.title()}. "
                "Tambien te puedo apoyar con precio, imagenes y ficha tecnica en PDF."
            ),
            "selected_version": version_directa,
            "send_pdf": False,
            "send_images": False,
            "handoff_advisor": False,
            "detected_profile": {},
            "reasoning_tags": ["fallback_version_directa"],
            "accion_ofrecida": "continuar_contexto",
        }

    return {
        "reply_text": RESPUESTA_FALLBACK,
        "selected_version": None,
        "send_pdf": False,
        "send_images": False,
        "handoff_advisor": False,
        "detected_profile": {},
        "reasoning_tags": ["fallback_generico"],
        "accion_ofrecida": "pedir_necesidad",
    }


# =========================
# Construcción de respuesta
# =========================

def construir_respuesta_informativa(
    *,
    telefono: str,
    profile_name: str,
    texto_usuario: str,
    auto_interes_actual: Optional[str] = None,
    ultimo_mensaje_saliente: str = "",
    historial_reciente: Optional[list[dict[str, str]]] = None,
    accion_ofrecida_previa: Optional[str] = None,
) -> tuple[str, Optional[str], bool, bool, bool, dict[str, Any], dict[str, Any], str]:
    texto_usuario = (texto_usuario or "").strip()
    historial_reciente = historial_reciente or []

    if (texto_usuario or "").strip().upper() in {"[IMAGE]", "[VIDEO]", "[AUDIO]", "[DOCUMENT]", "[STICKER]"}:
        return RESPUESTA_MEDIA, auto_interes_actual, False, False, False, {}, {
            "reasoning_tags": ["media_placeholder"]
        }, "ninguna"

    auto_interes_actual = _normalizar_version_catalogo(auto_interes_actual)

    decision = {}
    try:
        decision = _decision_conversacional_ia(
            telefono=telefono,
            nombre_cliente=profile_name,
            texto_usuario=texto_usuario,
            auto_interes_actual=auto_interes_actual,
            ultimo_mensaje_saliente=ultimo_mensaje_saliente,
            historial_reciente=historial_reciente,
            accion_ofrecida_previa=accion_ofrecida_previa,
        )
    except Exception:
        decision = {}

    if not decision:
        decision = _fallback_respuesta(
            texto_usuario=texto_usuario,
            profile_name=profile_name,
            version_contexto=auto_interes_actual,
        )

    selected_version = _normalizar_version_catalogo(
        decision.get("selected_version") or _buscar_version_en_texto(texto_usuario) or auto_interes_actual
    )
    handoff_advisor = bool(decision.get("handoff_advisor"))
    send_pdf = bool(decision.get("send_pdf")) and bool(selected_version) and not handoff_advisor
    send_images = bool(decision.get("send_images")) and bool(selected_version) and not handoff_advisor
    detected_profile = decision.get("detected_profile") or {}
    reply_text = _limitar_texto((decision.get("reply_text") or RESPUESTA_FALLBACK).strip())

    accion_ofrecida = (decision.get("accion_ofrecida") or "ninguna").strip()
    if accion_ofrecida not in ACCIONES_OFRECIDAS_VALIDAS:
        accion_ofrecida = _determinar_accion_ofrecida(
            reply_text=reply_text,
            send_pdf=send_pdf,
            handoff_advisor=handoff_advisor,
            selected_version=selected_version,
            texto_usuario=texto_usuario,
        )

    raw_decision = dict(decision)
    raw_decision["selected_version"] = selected_version
    raw_decision["send_pdf"] = send_pdf
    raw_decision["send_images"] = send_images
    raw_decision["handoff_advisor"] = handoff_advisor
    raw_decision["accion_ofrecida"] = accion_ofrecida
    raw_decision["reply_text"] = reply_text

    return (
        reply_text,
        selected_version,
        send_pdf,
        send_images,
        handoff_advisor,
        detected_profile,
        raw_decision,
        accion_ofrecida,
    )


# =========================
# Respuesta automática completa
# =========================

def responder_mensaje_automatico(
    *,
    wa_from: str,
    numero_asesor: str,
    profile_name: str = "",
    texto_usuario: str = "",
    wa_message_id_entrante: str = "",
    raw_message: Optional[dict] = None,
) -> dict:
    telefono = normaliza_tel_mx(replace_start(wa_from))
    numero_asesor = normaliza_tel_mx(numero_asesor)
    wa_message_id_entrante = (wa_message_id_entrante or "").strip()

    if not telefono:
        raise ValueError("Numero invalido para responder automaticamente")
    if not numero_asesor:
        raise ValueError("Numero de asesor invalido para responder automaticamente")

    if _ya_se_respondio_a_entrada(numero_asesor, wa_message_id_entrante):
        return {
            "ok": True,
            "skipped": True,
            "reason": "ya_se_respondio_a_esta_entrada",
            "telefono": telefono,
            "numero_asesor": numero_asesor,
            "wa_message_id_entrante": wa_message_id_entrante,
        }

    cliente, expediente = _get_or_create_cliente_y_expediente(
        telefono=telefono,
        numero_asesor=numero_asesor,
        profile_name=profile_name,
        texto_entrante=texto_usuario,
    )

    auto_interes_actual = _limpiar_auto_interes_invalido(expediente)
    nombre_contexto = (cliente.nombre or "").strip() or _extraer_nombre_basico(profile_name, "") or ""
    ultimo_mensaje_saliente = _obtener_ultimo_mensaje_saliente(cliente, numero_asesor)
    historial_reciente = _serializar_historial(cliente, numero_asesor)
    accion_ofrecida_previa = _obtener_ultima_accion_ofrecida(cliente, numero_asesor)

    (
        respuesta_texto,
        version_contexto,
        enviar_pdf,
        enviar_imagenes,
        handoff_advisor,
        detected_profile,
        raw_decision,
        accion_ofrecida,
    ) = construir_respuesta_informativa(
        telefono=telefono,
        profile_name=nombre_contexto,
        texto_usuario=texto_usuario,
        auto_interes_actual=auto_interes_actual,
        ultimo_mensaje_saliente=ultimo_mensaje_saliente,
        historial_reciente=historial_reciente,
        accion_ofrecida_previa=accion_ofrecida_previa,
    )

    _guardar_datos_detectados_en_cliente_y_expediente(
        cliente=cliente,
        expediente=expediente,
        profile_name=profile_name,
        detected_profile=detected_profile,
        version_detectada=version_contexto,
    )

    wa_res = enviar_texto_whatsapp(
        to=telefono,
        text=respuesta_texto,
        numero_asesor=numero_asesor,
    )

    wa_message_id_salida = ""
    try:
        wa_message_id_salida = (wa_res.get("messages") or [{}])[0].get("id", "") or ""
    except Exception:
        wa_message_id_salida = ""

    _guardar_salida(
        telefono=telefono,
        numero_asesor=numero_asesor,
        cliente=cliente,
        texto=respuesta_texto,
        wa_message_id=wa_message_id_salida,
        raw={
            "openai_model": "gpt-4.1",
            "reply_to": wa_message_id_entrante,
            "numero_asesor": numero_asesor,
            "version_contexto": version_contexto,
            "handoff_advisor": handoff_advisor,
            "detected_profile": detected_profile,
            "decision": raw_decision,
            "accion_ofrecida": accion_ofrecida,
            "conversation_meta": {
                "accion_ofrecida": accion_ofrecida,
                "accion_ofrecida_previa": accion_ofrecida_previa,
            },
            "wa_response": wa_res,
            "raw_message": raw_message or {},
        },
        status_msg="accepted",
    )

    image_results = []
    image_errors = []
    if enviar_imagenes and version_contexto:
        for imagen_relativa in _imagenes_de_version(version_contexto):
            image_url = _build_media_url(imagen_relativa)
            filename = imagen_relativa.rsplit("/", 1)[-1]
            try:
                image_res = enviar_imagen_whatsapp_por_link(
                    to=telefono,
                    link=image_url,
                    numero_asesor=numero_asesor,
                    caption=f"Imagen de {version_contexto.title()}",
                )
                image_error = ""
            except Exception as exc:
                image_error = str(exc)
                image_res = {"ok": False, "error": image_error, "media_link": image_url}

            image_message_id = ""
            try:
                image_message_id = (image_res.get("messages") or [{}])[0].get("id", "") or ""
            except Exception:
                image_message_id = ""

            _guardar_salida(
                telefono=telefono,
                numero_asesor=numero_asesor,
                cliente=cliente,
                texto=f"[FILE:{filename}]",
                wa_message_id=image_message_id,
                raw={
                    "openai_model": "gpt-4.1",
                    "reply_to": wa_message_id_entrante,
                    "numero_asesor": numero_asesor,
                    "version_contexto": version_contexto,
                    "meta_type": "image",
                    "filename": filename,
                    "content_type": "image/jpeg",
                    "media_link": image_url,
                    "accion_ofrecida": "continuar_contexto",
                    "conversation_meta": {"accion_ofrecida": "continuar_contexto"},
                    "wa_response": image_res,
                    "image_error": image_error,
                },
                status_msg="accepted" if image_message_id else "failed",
            )

            image_results.append(image_res)
            if image_error:
                image_errors.append(image_error)

    pdf_res = None
    pdf_error = ""
    if enviar_pdf and version_contexto:
        data = CATALOGO_VEHICULOS[version_contexto]
        pdf_url = _build_pdf_url(data["pdf_relativo"])

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
            pdf_res = {"ok": False, "error": pdf_error, "document_link": pdf_url}

        pdf_message_id = ""
        try:
            pdf_message_id = (pdf_res.get("messages") or [{}])[0].get("id", "") or ""
        except Exception:
            pdf_message_id = ""

        _guardar_salida(
            telefono=telefono,
            numero_asesor=numero_asesor,
            cliente=cliente,
            texto=f"[FILE:{version_contexto}.pdf]",
            wa_message_id=pdf_message_id,
            raw={
                "openai_model": "gpt-4.1",
                "reply_to": wa_message_id_entrante,
                "numero_asesor": numero_asesor,
                "version_contexto": version_contexto,
                "meta_type": "document",
                "filename": f"{version_contexto.lower().replace(' ', '-')}.pdf",
                "content_type": "application/pdf",
                "document_link": pdf_url,
                "accion_ofrecida": "compartir_pdf",
                "conversation_meta": {"accion_ofrecida": "compartir_pdf"},
                "wa_response": pdf_res,
                "pdf_error": pdf_error,
            },
            status_msg="accepted" if pdf_message_id else "failed",
        )

    cambios = ["ultimo_contacto_at"]
    expediente.ultimo_contacto_at = timezone.now()

    if version_contexto and expediente.auto_interes != version_contexto:
        expediente.auto_interes = version_contexto
        cambios.append("auto_interes")

    if handoff_advisor and expediente.estado != "Seguimiento":
        expediente.estado = "Seguimiento"
        cambios.append("estado")

    cfg_linea = WHATSAPP_LINES.get(numero_asesor, {})
    agencia_linea = (cfg_linea.get("agencia") or "").strip()
    business_linea = (cfg_linea.get("business") or "Comerciales").strip()

    if agencia_linea and expediente.agencia != agencia_linea:
        expediente.agencia = agencia_linea
        cambios.append("agencia")
    if business_linea and expediente.business != business_linea:
        expediente.business = business_linea
        cambios.append("business")
    if expediente.canal_contacto != "WhatsApp":
        expediente.canal_contacto = "WhatsApp"
        cambios.append("canal_contacto")

    cambios.append("actualizado")
    expediente.save(update_fields=list(dict.fromkeys(cambios)))

    return {
        "ok": True,
        "telefono": telefono,
        "numero_asesor": numero_asesor,
        "cliente_id": cliente.id_cliente,
        "expediente_id": expediente.pk,
        "respuesta": respuesta_texto,
        "version_detectada": version_contexto,
        "pdf_enviado": enviar_pdf,
        "imagenes_enviadas": enviar_imagenes,
        "handoff_advisor": handoff_advisor,
        "accion_ofrecida": accion_ofrecida,
        "accion_ofrecida_previa": accion_ofrecida_previa,
        "detected_profile": detected_profile,
        "decision": raw_decision,
        "wa_response": wa_res,
        "pdf_response": pdf_res,
        "pdf_error": pdf_error,
        "image_responses": image_results,
        "image_errors": image_errors,
    }
