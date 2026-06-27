# Digitales/atribucion_meta.py

import json
import requests

from django.utils import timezone

from .models import CampanaMeta, MapeoFuenteMeta
from .sett import GRAPH_VERSION

try:
    from .sett import META_ADS_ACCESS_TOKEN
except ImportError:
    META_ADS_ACCESS_TOKEN = ""


def obtener_referencia_meta(mensaje_whatsapp: dict) -> dict:
    """
    Extrae la referencia de anuncio/post enviada por WhatsApp Cloud API.
    Normalmente viene como mensaje_whatsapp["referral"].
    """
    if not isinstance(mensaje_whatsapp, dict):
        return {}

    referencia = mensaje_whatsapp.get("referral") or {}

    if not referencia:
        contexto = mensaje_whatsapp.get("context") or {}
        if isinstance(contexto, dict):
            referencia = contexto.get("referral") or {}

    if not isinstance(referencia, dict):
        return {}

    return referencia


def limpiar_id(valor) -> str:
    return str(valor or "").strip()


def convertir_bigint(valor):
    texto = limpiar_id(valor)

    if not texto or not texto.isdigit():
        return None

    try:
        return int(texto)
    except (TypeError, ValueError, OverflowError):
        return None


def armar_nombre_pauta(*, sucursal: str = "", nombre_campana: str = "") -> str:
    sucursal = str(sucursal or "").strip()
    nombre_campana = str(nombre_campana or "").strip()

    if sucursal and nombre_campana:
        return f"{sucursal} - {nombre_campana}"

    return nombre_campana or sucursal


def buscar_campana_por_id_campana(id_campana):
    id_campana_int = convertir_bigint(id_campana)

    if id_campana_int is None:
        return None

    try:
        return (
            CampanaMeta.objects.using("sqlserver")
            .filter(id_campana=id_campana_int)
            .only("id_campana", "sucursal", "nombre_campana")
            .first()
        )
    except Exception as error:
        print(
            "ERROR BUSCANDO EN campanas_meta:",
            {
                "id_campana": id_campana,
                "error": str(error),
            },
        )
        return None


def buscar_mapeo_por_id_fuente(id_fuente: str):
    id_fuente = limpiar_id(id_fuente)

    if not id_fuente:
        return None

    try:
        return (
            MapeoFuenteMeta.objects.using("sqlserver")
            .filter(id_fuente=id_fuente)
            .first()
        )
    except Exception as error:
        print(
            "ERROR BUSCANDO EN mapeo_fuentes_meta:",
            {
                "id_fuente": id_fuente,
                "error": str(error),
            },
        )
        return None


def guardar_mapeo_fuente_meta(
    *,
    id_fuente: str,
    tipo_fuente: str,
    id_campana=None,
    nombre_campana: str = "",
    id_anuncio=None,
    nombre_anuncio: str = "",
    id_conjunto=None,
    nombre_conjunto: str = "",
    sucursal: str = "",
    respuesta_meta: dict | None = None,
):
    id_fuente = limpiar_id(id_fuente)
    tipo_fuente = limpiar_id(tipo_fuente) or "desconocido"

    if not id_fuente:
        return None

    ahora = timezone.now()

    valores = {
        "tipo_fuente": tipo_fuente,
        "id_campana": convertir_bigint(id_campana),
        "nombre_campana": str(nombre_campana or "").strip(),
        "id_anuncio": convertir_bigint(id_anuncio),
        "nombre_anuncio": str(nombre_anuncio or "").strip(),
        "id_conjunto": convertir_bigint(id_conjunto),
        "nombre_conjunto": str(nombre_conjunto or "").strip(),
        "sucursal": str(sucursal or "").strip(),
        "respuesta_meta": json.dumps(respuesta_meta or {}, ensure_ascii=False),
        "actualizado_en": ahora,
    }

    try:
        obj, _ = MapeoFuenteMeta.objects.using("sqlserver").update_or_create(
            id_fuente=id_fuente,
            defaults=valores,
        )
        return obj
    except Exception as error:
        print(
            "ERROR GUARDANDO mapeo_fuentes_meta:",
            {
                "id_fuente": id_fuente,
                "tipo_fuente": tipo_fuente,
                "error": str(error),
            },
        )
        return None


def consultar_anuncio_meta(id_anuncio: str) -> dict:
    """
    Consulta Meta Marketing API usando el ID del anuncio.

    Si referral.source_type = "ad", normalmente referral.source_id es el ad_id.
    """
    id_anuncio = limpiar_id(id_anuncio)

    if not id_anuncio:
        return {
            "ok": False,
            "motivo": "sin_id_anuncio",
        }

    if not META_ADS_ACCESS_TOKEN:
        return {
            "ok": False,
            "motivo": "sin_meta_ads_access_token",
        }

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{id_anuncio}"

    parametros = {
        "access_token": META_ADS_ACCESS_TOKEN,
        "fields": "id,name,campaign_id,adset_id,campaign{name},adset{name}",
    }

    try:
        respuesta = requests.get(url, params=parametros, timeout=20)

        if respuesta.status_code >= 400:
            return {
                "ok": False,
                "motivo": "error_meta_ads",
                "status_code": respuesta.status_code,
                "detalle": respuesta.text,
            }

        data = respuesta.json()

        return {
            "ok": True,
            "data": data,
        }

    except requests.RequestException as error:
        return {
            "ok": False,
            "motivo": "error_conexion_meta_ads",
            "detalle": str(error),
        }


def resolver_pauta_desde_mapeo(id_fuente: str) -> dict:
    mapeo = buscar_mapeo_por_id_fuente(id_fuente)

    if not mapeo:
        return {
            "ok": False,
            "motivo": "mapeo_no_encontrado",
        }

    pauta = armar_nombre_pauta(
        sucursal=mapeo.sucursal,
        nombre_campana=mapeo.nombre_campana,
    )

    if not pauta:
        return {
            "ok": False,
            "motivo": "mapeo_sin_nombre_campana",
        }

    return {
        "ok": True,
        "motivo": "pauta_resuelta_desde_mapeo",
        "id_fuente": mapeo.id_fuente,
        "tipo_fuente": mapeo.tipo_fuente,
        "id_campana": mapeo.id_campana,
        "nombre_campana": mapeo.nombre_campana,
        "pauta": pauta,
    }


def resolver_pauta_desde_campana_directa(id_fuente: str, tipo_fuente: str) -> dict:
    """
    Fallback: si por alguna razón id_fuente coincide con id_campana,
    lo resolvemos directo contra campanas_meta.
    """
    campana = buscar_campana_por_id_campana(id_fuente)

    if not campana:
        return {
            "ok": False,
            "motivo": "no_coincide_con_id_campana",
        }

    pauta = armar_nombre_pauta(
        sucursal=campana.sucursal,
        nombre_campana=campana.nombre_campana,
    )

    guardar_mapeo_fuente_meta(
        id_fuente=id_fuente,
        tipo_fuente=tipo_fuente or "campaign",
        id_campana=campana.id_campana,
        nombre_campana=campana.nombre_campana,
        sucursal=campana.sucursal,
        respuesta_meta={
            "origen": "campanas_meta",
            "id_campana": campana.id_campana,
            "nombre_campana": campana.nombre_campana,
            "sucursal": campana.sucursal,
        },
    )

    return {
        "ok": True,
        "motivo": "pauta_resuelta_desde_campanas_meta",
        "id_fuente": id_fuente,
        "tipo_fuente": tipo_fuente,
        "id_campana": campana.id_campana,
        "nombre_campana": campana.nombre_campana,
        "pauta": pauta,
    }


def resolver_pauta_desde_meta_ads(id_fuente: str, tipo_fuente: str) -> dict:
    """
    Resuelve cuando WhatsApp manda source_type='ad'.

    Flujo:
    id_fuente -> ad_id -> campaign_id -> campanas_meta -> nombre final.
    """
    if tipo_fuente != "ad":
        return {
            "ok": False,
            "motivo": "tipo_fuente_no_resoluble_por_anuncio",
            "tipo_fuente": tipo_fuente,
        }

    respuesta_anuncio = consultar_anuncio_meta(id_fuente)

    if not respuesta_anuncio.get("ok"):
        return respuesta_anuncio

    anuncio = respuesta_anuncio.get("data") or {}

    id_anuncio = anuncio.get("id") or id_fuente
    nombre_anuncio = anuncio.get("name") or ""

    id_campana = anuncio.get("campaign_id") or ""
    campana_meta = anuncio.get("campaign") or {}
    nombre_campana_meta_api = campana_meta.get("name") or ""

    id_conjunto = anuncio.get("adset_id") or ""
    conjunto_meta = anuncio.get("adset") or {}
    nombre_conjunto = conjunto_meta.get("name") or ""

    campana_bd = buscar_campana_por_id_campana(id_campana)

    if campana_bd:
        nombre_campana_final = campana_bd.nombre_campana
        sucursal_final = campana_bd.sucursal
    else:
        nombre_campana_final = nombre_campana_meta_api
        sucursal_final = ""

    pauta = armar_nombre_pauta(
        sucursal=sucursal_final,
        nombre_campana=nombre_campana_final,
    )

    if not pauta:
        return {
            "ok": False,
            "motivo": "anuncio_sin_campana_resoluble",
            "id_fuente": id_fuente,
            "respuesta_meta": anuncio,
        }

    guardar_mapeo_fuente_meta(
        id_fuente=id_fuente,
        tipo_fuente=tipo_fuente,
        id_campana=id_campana,
        nombre_campana=nombre_campana_final,
        id_anuncio=id_anuncio,
        nombre_anuncio=nombre_anuncio,
        id_conjunto=id_conjunto,
        nombre_conjunto=nombre_conjunto,
        sucursal=sucursal_final,
        respuesta_meta=anuncio,
    )

    return {
        "ok": True,
        "motivo": "pauta_resuelta_desde_meta_ads",
        "id_fuente": id_fuente,
        "tipo_fuente": tipo_fuente,
        "id_campana": id_campana,
        "nombre_campana": nombre_campana_final,
        "id_anuncio": id_anuncio,
        "nombre_anuncio": nombre_anuncio,
        "pauta": pauta,
    }


def aplicar_pauta_desde_referencia_meta(*, expediente, mensaje_whatsapp: dict) -> dict:
    """
    Función principal para usar en el webhook.

    No rompe el webhook si algo falla.
    No pisa una pauta ya capturada.
    Guarda diagnóstico para que puedas revisarlo en MensajeWhatsApp.raw.
    """
    if not expediente:
        return {
            "ok": False,
            "motivo": "sin_expediente",
        }

    referencia = obtener_referencia_meta(mensaje_whatsapp)

    if not referencia:
        return {
            "ok": False,
            "motivo": "sin_referencia_meta",
        }

    id_fuente = limpiar_id(referencia.get("source_id"))
    tipo_fuente = limpiar_id(referencia.get("source_type"))

    if not id_fuente:
        return {
            "ok": False,
            "motivo": "sin_id_fuente",
            "referencia": referencia,
        }

    if (expediente.pauta or "").strip():
        return {
            "ok": True,
            "motivo": "pauta_ya_existia",
            "id_fuente": id_fuente,
            "tipo_fuente": tipo_fuente,
            "pauta": expediente.pauta,
            "referencia": referencia,
        }

    resultado = resolver_pauta_desde_mapeo(id_fuente)

    if not resultado.get("ok"):
        resultado = resolver_pauta_desde_campana_directa(id_fuente, tipo_fuente)

    if not resultado.get("ok"):
        resultado = resolver_pauta_desde_meta_ads(id_fuente, tipo_fuente)

    if not resultado.get("ok"):
        resultado["id_fuente"] = id_fuente
        resultado["tipo_fuente"] = tipo_fuente
        resultado["referencia"] = referencia
        return resultado

    pauta = resultado.get("pauta") or ""

    if pauta:
        expediente.pauta = pauta
        expediente.save(update_fields=["pauta", "actualizado"])

    resultado["referencia"] = referencia
    return resultado