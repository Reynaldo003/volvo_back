#checklist_entrega/models.py
from pathlib import Path
import uuid

from django.db import models
from citas.models import ClienteComercial


def evidencia_checklist_entrega_upload_to(instance, filename):
    ext = Path(filename).suffix.lower()
    return f"volvo/checklist_entrega/evidencias/{instance.entrega_id}/{uuid.uuid4().hex}{ext}"


class ChecklistEntregaVehiculo(models.Model):
    METODO_WHATSAPP = "whatsapp"
    METODO_CORREO = "correo"
    METODO_LLAMADA = "llamada"

    METODOS_CONTACTO = (
        (METODO_WHATSAPP, "WhatsApp"),
        (METODO_CORREO, "Correo"),
        (METODO_LLAMADA, "Llamada"),
    )

    cliente = models.ForeignKey(
        ClienteComercial,
        db_column="id_cliente",
        on_delete=models.PROTECT,
        related_name="checklists_entrega_volvo",
    )

    agencia = models.CharField(max_length=120, default="Volvo", blank=True)
    asesor_servicio = models.CharField(max_length=200, default="", blank=True)
    tecnico_responsable = models.CharField(max_length=200, default="", blank=True)

    placas = models.CharField(max_length=40, default="", blank=True)
    vin = models.CharField(max_length=80, default="", blank=True)
    modelo = models.CharField(max_length=120, default="", blank=True)
    kilometraje = models.CharField(max_length=50, default="", blank=True)

    orden_servicio = models.CharField(max_length=80, default="", blank=True)
    factura = models.CharField(max_length=80, default="", blank=True)
    fecha_hora_entrega = models.DateTimeField(null=True, blank=True)

    metodo_contacto_preferido = models.CharField(
        max_length=30,
        choices=METODOS_CONTACTO,
        default=METODO_WHATSAPP,
        blank=True,
    )

    checklist = models.JSONField(default=dict, blank=True)
    observaciones = models.TextField(default="", blank=True)

    entrega_terminada = models.BooleanField(default=False)
    fecha_terminada = models.DateTimeField(null=True, blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "volvo_checklist_entrega"
        ordering = ["-creado"]

    def __str__(self):
        nombre = getattr(self.cliente, "nombre", "") or "Cliente"
        return f"Entrega {nombre} - {self.placas or self.vin or 'Sin unidad'}"


class EvidenciaChecklistEntrega(models.Model):
    entrega = models.ForeignKey(
        ChecklistEntregaVehiculo,
        db_column="id_entrega",
        on_delete=models.CASCADE,
        related_name="evidencias",
    )

    archivo = models.FileField(upload_to=evidencia_checklist_entrega_upload_to)
    nombre = models.CharField(max_length=255, default="", blank=True)
    descripcion = models.CharField(max_length=500, default="", blank=True)

    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "volvo_checklist_entrega_evidencias"
        ordering = ["-creado"]

    def __str__(self):
        return self.nombre or f"Evidencia {self.pk}"
