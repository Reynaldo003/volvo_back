#citas/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from citas.models import Cita
from Digitales.models import ExpedienteDigital

def _recalcular_ultima_cita(cliente_id: int):
    exp = ExpedienteDigital.objects.filter(cliente_id=cliente_id).first()

    if not exp:
        return

    latest = (
        Cita.objects
        .filter(cliente_id=cliente_id)
        .order_by("-fecha_hora_cita", "-id")
        .first()
    )

    if not latest:
        exp.ultima_cita_id = None
        exp.ultima_cita_agendada = None
        exp.asistencia = False
        exp.save(update_fields=["ultima_cita", "ultima_cita_agendada", "asistencia", "actualizado"])
        return

    exp.ultima_cita_id = latest.id
    exp.ultima_cita_agendada = latest.fecha_hora_cita
    exp.asistencia = bool(latest.asistencia)
    exp.save(update_fields=["ultima_cita", "ultima_cita_agendada", "asistencia", "actualizado"])


@receiver(post_save, sender=Cita)
def cita_post_save(sender, instance: Cita, **kwargs):
    _recalcular_ultima_cita(instance.cliente_id)


@receiver(post_delete, sender=Cita)
def cita_post_delete(sender, instance: Cita, **kwargs):
    _recalcular_ultima_cita(instance.cliente_id)