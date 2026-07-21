import logging

from citas.models import normaliza_tel_mx
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from usuarios.authentication import SignedUserAuthentication

from .contacto import MetaAPIError, obtener_config_linea
from .plantillas_meta import (
    REGLAS_UTILITY,
    analizar_estructura_plantilla,
    crear_plantilla_meta,
    editar_plantilla_meta,
    eliminar_plantilla_meta,
    listar_plantillas_meta,
)
from .sett import WHATSAPP_LINES

logger = logging.getLogger(__name__)


def _request_value(request, key: str, default=""):
    """Obtiene un dato desde query params o desde el body JSON."""
    value = request.query_params.get(key, None)

    if value is not None:
        return value

    data = getattr(request, "data", {}) or {}

    if hasattr(data, "get"):
        return data.get(key, default)

    return default


def _normalizar_permiso(permiso) -> str:
    if isinstance(permiso, str):
        return permiso.strip().upper()

    return str(
        getattr(permiso, "codigo", "")
        or getattr(permiso, "nombre", "")
        or getattr(permiso, "name", "")
        or permiso
        or ""
    ).strip().upper()


def _usuario_es_admin(request) -> bool:
    """Reconoce administradores por rol, superusuario o permisos."""
    user = getattr(request, "user", None)

    if not user or not getattr(user, "is_authenticated", False):
        return False

    if bool(getattr(user, "is_superuser", False)):
        return True

    rol = getattr(user, "rol", None)
    nombre_rol = str(
        getattr(rol, "nombre", "")
        or getattr(rol, "name", "")
        or (rol if isinstance(rol, str) else "")
        or ""
    ).strip().lower()

    if nombre_rol in ("administrador", "admin"):
        return True

    permisos = getattr(user, "permisos", [])

    try:
        if hasattr(permisos, "all"):
            permisos = permisos.all()

        codigos = {_normalizar_permiso(item) for item in permisos or []}
        return bool({"ALL", "USUARIOS_ADMIN"} & codigos)
    except Exception:
        return False


def _primer_numero_asesor() -> str:
    return next(iter(WHATSAPP_LINES.keys()), "")


def _numero_usuario(request) -> str:
    user = getattr(request, "user", None)
    numero = normaliza_tel_mx(getattr(user, "telefono", "") or "") if user else ""
    return numero if numero in WHATSAPP_LINES else ""


def _get_cfg_request(request) -> tuple[dict, str]:
    """
    Resuelve la línea respetando la sesión:
    - administrador: puede seleccionar numero_asesor;
    - usuario normal: solamente su línea asignada;
    - compatibilidad Volvo: si existe una sola línea, usa esa línea.
    """
    numero_param = normaliza_tel_mx(_request_value(request, "numero_asesor", "") or "")
    numero_param = numero_param if numero_param in WHATSAPP_LINES else ""
    numero_usuario = _numero_usuario(request)

    if _usuario_es_admin(request):
        numero_asesor = numero_param or numero_usuario or _primer_numero_asesor()
    else:
        numero_asesor = numero_usuario

        if not numero_asesor and len(WHATSAPP_LINES) == 1:
            numero_asesor = numero_param or _primer_numero_asesor()

    if not numero_asesor:
        raise ValueError(
            "El usuario no tiene una línea de WhatsApp válida asignada en usuarios_volvo."
        )

    cfg = obtener_config_linea(numero_asesor=numero_asesor)
    return cfg, cfg["numero_asesor"]


def _linea_response(cfg: dict) -> dict:
    return {
        "key": cfg.get("key", ""),
        "asesor_digital": cfg.get("asesor_digital", ""),
        "agencia": cfg.get("agencia", ""),
        "business": cfg.get("business", ""),
        "phone_number_id": cfg.get("phone_number_id", ""),
        "waba_id": cfg.get("waba_id", ""),
    }


def _admin_denegado():
    return Response(
        {
            "ok": False,
            "error": "Solo un administrador puede crear, editar o eliminar plantillas.",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _response_meta_error(error: MetaAPIError, *, numero_asesor: str, tipo: str):
    payload = {
        "ok": False,
        "error": error.meta_message,
        "retryable": error.retryable,
        "meta": error.to_dict(),
        "numero_asesor": numero_asesor,
        "tipo": tipo,
    }

    if error.status_code == 429:
        http_status = status.HTTP_429_TOO_MANY_REQUESTS
    elif error.retryable:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif error.status_code == 400:
        http_status = status.HTTP_400_BAD_REQUEST
    else:
        http_status = status.HTTP_502_BAD_GATEWAY

    return Response(payload, status=http_status)


def _response_value_error(error: ValueError):
    analysis = getattr(error, "analysis", None)
    requiere_confirmacion = bool(
        analysis
        and (
            analysis.get("requiere_confirmacion")
            or analysis.get("requiere_confirmacion_marketing")
        )
    )

    return Response(
        {
            "ok": False,
            "error": str(error),
            "analysis": analysis,
            "requires_confirmation": requiere_confirmacion,
        },
        status=(
            status.HTTP_409_CONFLICT
            if requiere_confirmacion
            else status.HTTP_400_BAD_REQUEST
        ),
    )


@api_view(["GET", "POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def plantillas_whatsapp_admin_view(request):
    """
    GET  -> lista todos los estados de plantillas de la WABA.
    POST -> crea una plantilla y la envía a revisión de Meta.
    """
    try:
        cfg, numero_asesor = _get_cfg_request(request)
    except Exception as exc:
        return Response(
            {"ok": False, "error": str(exc), "items": []},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if request.method == "GET":
        try:
            items = listar_plantillas_meta(numero_asesor)

            return Response(
                {
                    "ok": True,
                    "numero_asesor": numero_asesor,
                    "linea": _linea_response(cfg),
                    "reglas_utility": REGLAS_UTILITY,
                    "items": items,
                },
                status=status.HTTP_200_OK,
            )
        except MetaAPIError as exc:
            return _response_meta_error(
                exc,
                numero_asesor=numero_asesor,
                tipo="template_list",
            )
        except Exception as exc:
            logger.exception(
                "ERROR LISTANDO PLANTILLAS META VOLVO | numero=%s error=%s",
                numero_asesor,
                exc,
            )
            return Response(
                {"ok": False, "error": str(exc), "items": []},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if not _usuario_es_admin(request):
        return _admin_denegado()

    try:
        resultado = crear_plantilla_meta(
            numero_asesor,
            dict(request.data or {}),
        )

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "mensaje": "Plantilla enviada a revisión de Meta.",
                **resultado,
            },
            status=status.HTTP_201_CREATED,
        )
    except MetaAPIError as exc:
        return _response_meta_error(
            exc,
            numero_asesor=numero_asesor,
            tipo="template_create",
        )
    except ValueError as exc:
        return _response_value_error(exc)
    except Exception as exc:
        logger.exception(
            "ERROR CREANDO PLANTILLA META VOLVO | numero=%s error=%s",
            numero_asesor,
            exc,
        )
        return Response(
            {"ok": False, "error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def analizar_plantilla_whatsapp_view(request):
    """Analiza estructura y riesgo sin modificar nada en Meta."""
    try:
        _, numero_asesor = _get_cfg_request(request)
        category = str(request.data.get("category") or "UTILITY").upper().strip()
        components = request.data.get("components")

        if components is None:
            components = []

        analysis = analizar_estructura_plantilla(components, category)

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "analysis": analysis,
            },
            status=status.HTTP_200_OK,
        )
    except Exception as exc:
        logger.exception("ERROR ANALIZANDO PLANTILLA VOLVO | error=%s", exc)
        return Response(
            {"ok": False, "error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["PATCH", "DELETE"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def plantilla_whatsapp_admin_detail_view(request, template_id: str):
    """Edita o elimina una plantilla que pertenece a la WABA seleccionada."""
    if not _usuario_es_admin(request):
        return _admin_denegado()

    try:
        _, numero_asesor = _get_cfg_request(request)
    except Exception as exc:
        return Response(
            {"ok": False, "error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    template_id = str(template_id or "").strip()

    if not template_id:
        return Response(
            {"ok": False, "error": "Falta template_id."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if request.method == "DELETE":
        name = str(
            request.query_params.get("name")
            or getattr(request, "data", {}).get("name")
            or ""
        ).strip()

        try:
            meta = eliminar_plantilla_meta(
                numero_asesor,
                template_id,
                name,
            )

            return Response(
                {
                    "ok": True,
                    "mensaje": "Plantilla eliminada correctamente.",
                    "meta": meta,
                },
                status=status.HTTP_200_OK,
            )
        except MetaAPIError as exc:
            return _response_meta_error(
                exc,
                numero_asesor=numero_asesor,
                tipo="template_delete",
            )
        except ValueError as exc:
            return _response_value_error(exc)
        except Exception as exc:
            logger.exception(
                "ERROR ELIMINANDO PLANTILLA META VOLVO | numero=%s template=%s error=%s",
                numero_asesor,
                template_id,
                exc,
            )
            return Response(
                {"ok": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        resultado = editar_plantilla_meta(
            numero_asesor,
            template_id,
            dict(request.data or {}),
        )

        return Response(
            {
                "ok": True,
                "numero_asesor": numero_asesor,
                "mensaje": "Cambios enviados a revisión de Meta.",
                **resultado,
            },
            status=status.HTTP_200_OK,
        )
    except MetaAPIError as exc:
        return _response_meta_error(
            exc,
            numero_asesor=numero_asesor,
            tipo="template_edit",
        )
    except ValueError as exc:
        return _response_value_error(exc)
    except Exception as exc:
        logger.exception(
            "ERROR EDITANDO PLANTILLA META VOLVO | numero=%s template=%s error=%s",
            numero_asesor,
            template_id,
            exc,
        )
        return Response(
            {"ok": False, "error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )