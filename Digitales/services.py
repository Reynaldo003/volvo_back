#Digitales/services.py
from datetime import timedelta

from django.utils import timezone

from .models import MensajeWhatsApp
from .resumen_ia import generar_resumen_con_openai


def generar_y_guardar_resumen(*, expediente, fuente: str):
    mensajes = MensajeWhatsApp.objects.filter(
        telefono=expediente.cliente.telefono
    ).order_by("created_at")

    resumen = generar_resumen_con_openai(
        mensajes=mensajes,
        telefono=expediente.cliente.telefono,
    )

    expediente.resumen = resumen
    expediente.resumen_actualizado_at = timezone.now()
    expediente.resumen_fuente = fuente
    expediente.save(update_fields=[
        "resumen",
        "resumen_actualizado_at",
        "resumen_fuente",
        "actualizado",
    ])

    return resumen


def total_mensajes_telefono(telefono: str) -> int:
    return MensajeWhatsApp.objects.filter(telefono=telefono).count()


def debe_generar_resumen_al_llegar_a_6(*, telefono: str) -> bool:
    total = total_mensajes_telefono(telefono)
    return total == 6


def debe_generar_resumen_por_1h_sin_respuesta(*, expediente) -> bool:
    telefono = expediente.cliente.telefono

    total = MensajeWhatsApp.objects.filter(telefono=telefono).count()
    if total <= 6:
        return False

    ultimo_msg = (
        MensajeWhatsApp.objects
        .filter(telefono=telefono)
        .order_by("-created_at")
        .first()
    )
    if not ultimo_msg or not ultimo_msg.created_at:
        return False

    hace_una_hora = timezone.now() - timedelta(hours=1)
    if ultimo_msg.created_at > hace_una_hora:
        return False

    if expediente.resumen_actualizado_at and expediente.resumen_actualizado_at >= ultimo_msg.created_at:
        return False

    return True