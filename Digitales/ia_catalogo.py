# Volvo
# Digitales/ia_catalogo.py
from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from usuarios.authentication import SignedUserAuthentication

from .models import CatalogoVehiculos

logger = logging.getLogger(__name__)


def _int_o_none(valor):
    if valor in (None, ""):
        return None

    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


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


def _serializar_vehiculo(item: CatalogoVehiculos) -> dict[str, Any]:
    return {
        "id": item.id,
        "marca": item.marca,
        "modelo": item.modelo,
        "ano": item.ano,
        "version": item.version,
        "precio_lista": item.precio_lista,
        "precio_contado": item.precio_contado,
        "precio_financiado": item.precio_financiado,
        "resumen": item.resumen,
        "ficha_tecnica": item.ficha_tecnica,
        "url_ficha_tecnica": item.url_ficha_tecnica,
        "imagenes": item.imagenes or [],
        "videos": item.videos or [],
        "ultima_actualizacion": (
            item.ultima_actualizacion.isoformat()
            if item.ultima_actualizacion
            else None
        ),
        "activo": item.activo,
        "creado": item.creado.isoformat() if item.creado else None,
    }


def obtener_catalogo_activo_para_ia(limite: int = 80) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite or 80), 300))

    items = (
        CatalogoVehiculos.objects
        .filter(activo=True, marca__iexact="Volvo")
        .order_by("modelo", "ano", "version")[:limite]
    )

    return [_serializar_vehiculo(item) for item in items]


def buscar_vehiculos_para_ia(texto: str, limite: int = 10) -> list[dict[str, Any]]:
    texto = str(texto or "").strip()

    if not texto:
        return []

    limite = max(1, min(int(limite or 10), 50))

    items = (
        CatalogoVehiculos.objects
        .filter(activo=True, marca__iexact="Volvo")
        .filter(
            Q(modelo__icontains=texto)
            | Q(version__icontains=texto)
            | Q(resumen__icontains=texto)
        )
        .order_by("modelo", "ano", "version")[:limite]
    )

    return [_serializar_vehiculo(item) for item in items]


def _lista_texto_o_vacia(valor) -> list[str]:
    if valor in (None, ""):
        return []

    if isinstance(valor, list):
        return [
            str(item or "").strip()
            for item in valor
            if str(item or "").strip()
        ]

    if isinstance(valor, str):
        return [
            linea.strip()
            for linea in valor.splitlines()
            if linea.strip()
        ]

    raise ValueError("El valor debe ser una lista o texto separado por líneas.")


def _fecha_o_none(valor):
    if valor in (None, ""):
        return None

    if all(hasattr(valor, attr) for attr in ("year", "month", "day")):
        return valor

    fecha = parse_date(str(valor).strip()[:10])

    if not fecha:
        raise ValueError("ultima_actualizacion debe tener formato YYYY-MM-DD.")

    return fecha


def _aplicar_payload_vehiculo(
    item: CatalogoVehiculos,
    data: dict[str, Any],
) -> CatalogoVehiculos:
    # Este módulo pertenece exclusivamente al CRM Volvo.
    item.marca = "Volvo"

    for campo in ("modelo", "version", "resumen", "url_ficha_tecnica"):
        if campo in data:
            setattr(item, campo, str(data.get(campo) or "").strip())

    if "ano" in data:
        ano = _int_o_none(data.get("ano"))

        if not ano:
            raise ValueError("El año es obligatorio y debe ser numérico.")

        item.ano = ano

    for campo in ("precio_lista", "precio_contado", "precio_financiado"):
        if campo in data:
            setattr(item, campo, _int_o_none(data.get(campo)))

    if "ficha_tecnica" in data:
        ficha = data.get("ficha_tecnica")

        if ficha in (None, ""):
            item.ficha_tecnica = {}
        elif isinstance(ficha, dict):
            item.ficha_tecnica = ficha
        else:
            raise ValueError("ficha_tecnica debe ser un objeto JSON válido.")

    if "imagenes" in data:
        item.imagenes = _lista_texto_o_vacia(data.get("imagenes"))

    if "videos" in data:
        item.videos = _lista_texto_o_vacia(data.get("videos"))

    if "ultima_actualizacion" in data:
        item.ultima_actualizacion = _fecha_o_none(
            data.get("ultima_actualizacion")
        )

    if "activo" in data:
        item.activo = _bool_seguro(data.get("activo"), default=item.activo)

    return item


def _respuesta_error_catalogo(exc: Exception, *, contexto: str, payload=None):
    logger.exception(
        "ERROR CATÁLOGO VOLVO | contexto=%s | payload=%s | error=%s",
        contexto,
        payload,
        str(exc),
    )

    if isinstance(exc, IntegrityError):
        return Response(
            {
                "ok": False,
                "error": "Ya existe un vehículo con la misma marca, modelo, año y versión.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, (ValueError, TypeError, ValidationError)):
        return Response(
            {
                "ok": False,
                "error": str(exc),
                "tipo": exc.__class__.__name__,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, DatabaseError):
        return Response(
            {
                "ok": False,
                "error": "Error de base de datos al guardar el vehículo.",
                "detalle": str(exc),
                "tipo": exc.__class__.__name__,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(
        {
            "ok": False,
            "error": "Error inesperado al procesar el catálogo.",
            "detalle": str(exc),
            "tipo": exc.__class__.__name__,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@api_view(["GET", "POST"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def catalogo_vehiculos_list(request):
    if request.method == "GET":
        modelo = str(request.query_params.get("modelo") or "").strip()
        activo_param = str(request.query_params.get("activo", "true")).strip().lower()

        try:
            limite = int(request.query_params.get("limit", 300))
        except (TypeError, ValueError):
            limite = 300

        limite = max(1, min(limite, 1000))

        items = CatalogoVehiculos.objects.filter(marca__iexact="Volvo")

        if activo_param not in ("todos", "all", "*", ""):
            items = items.filter(
                activo=activo_param not in ("0", "false", "no", "inactivo")
            )

        if modelo:
            items = items.filter(
                Q(modelo__icontains=modelo)
                | Q(version__icontains=modelo)
            )

        items = items.order_by("modelo", "ano", "version")[:limite]

        return Response(
            {
                "ok": True,
                "items": [_serializar_vehiculo(item) for item in items],
            }
        )

    data = request.data or {}

    if not str(data.get("modelo") or "").strip():
        return Response(
            {"ok": False, "error": "Falta modelo."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not str(data.get("ano") or "").strip():
        return Response(
            {"ok": False, "error": "Falta año."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        with transaction.atomic():
            item = _aplicar_payload_vehiculo(CatalogoVehiculos(), data)
            item.full_clean()
            item.save()

        return Response(
            {
                "ok": True,
                "item": _serializar_vehiculo(item),
            },
            status=status.HTTP_201_CREATED,
        )
    except Exception as exc:
        return _respuesta_error_catalogo(
            exc,
            contexto="crear",
            payload=dict(data),
        )


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@authentication_classes([SignedUserAuthentication])
@permission_classes([IsAuthenticated])
def catalogo_vehiculo_detail(request, vehiculo_id: int):
    item = CatalogoVehiculos.objects.filter(
        id=vehiculo_id,
        marca__iexact="Volvo",
    ).first()

    if not item:
        return Response(
            {
                "ok": False,
                "error": "Vehículo no encontrado.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "GET":
        return Response(
            {
                "ok": True,
                "item": _serializar_vehiculo(item),
            }
        )

    try:
        if request.method in ("PATCH", "PUT"):
            with transaction.atomic():
                item = _aplicar_payload_vehiculo(item, request.data or {})
                item.full_clean()
                item.save()

            return Response(
                {
                    "ok": True,
                    "item": _serializar_vehiculo(item),
                }
            )

        item.activo = False
        item.save(update_fields=["activo"])

        return Response(
            {
                "ok": True,
                "mensaje": "Vehículo desactivado correctamente.",
            }
        )
    except Exception as exc:
        return _respuesta_error_catalogo(
            exc,
            contexto=f"detalle:{vehiculo_id}",
            payload=dict(request.data or {}),
        )