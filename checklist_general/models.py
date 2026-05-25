from pathlib import Path
import uuid

from django.db import models
from citas.models import ClienteComercial


def evidencia_checklist_general_upload_to(instance, filename):
    ext = Path(filename).suffix.lower()
    return f"volvo/checklist_general/evidencias/{instance.checklist_id}/{uuid.uuid4().hex}{ext}"


class ChecklistGeneralCalidad(models.Model):
    cliente = models.ForeignKey(
        ClienteComercial,
        db_column="id_cliente",
        on_delete=models.PROTECT,
        related_name="checklists_generales_volvo",
    )

    agencia = models.CharField(max_length=120, default="Volvo", blank=True)
    asesor_servicio = models.CharField(max_length=200, default="", blank=True)
    tecnico_inspector = models.CharField(max_length=200, default="", blank=True)
    gerente_servicio = models.CharField(max_length=200, default="", blank=True)
    pst = models.CharField(max_length=200, default="", blank=True)

    placas = models.CharField(max_length=40, default="", blank=True)
    vin = models.CharField(max_length=80, default="", blank=True)
    modelo = models.CharField(max_length=120, default="", blank=True)
    kilometraje = models.CharField(max_length=50, default="", blank=True)
    orden_servicio = models.CharField(max_length=80, default="", blank=True)

    fecha_hora_revision = models.DateTimeField(null=True, blank=True)

    requiere_prueba_manejo = models.BooleanField(default=True)
    fecha_prueba = models.DateField(null=True, blank=True)
    hora_prueba = models.TimeField(null=True, blank=True)
    kilometraje_inicial = models.CharField(max_length=50, default="", blank=True)
    kilometraje_final = models.CharField(max_length=50, default="", blank=True)

    checklist = models.JSONField(default=dict, blank=True)
    observaciones = models.TextField(default="", blank=True)

    checklist_terminado = models.BooleanField(default=False)
    fecha_terminado = models.DateTimeField(null=True, blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "volvo_checklist_general"
        ordering = ["-creado"]

    def __str__(self):
        nombre = getattr(self.cliente, "nombre", "") or "Cliente"
        return f"Calidad {nombre} - {self.placas or self.vin or 'Sin unidad'}"


class EvidenciaChecklistGeneral(models.Model):
    checklist = models.ForeignKey(
        ChecklistGeneralCalidad,
        db_column="id_checklist",
        on_delete=models.CASCADE,
        related_name="evidencias",
    )

    archivo = models.FileField(upload_to=evidencia_checklist_general_upload_to)
    nombre = models.CharField(max_length=255, default="", blank=True)
    descripcion = models.CharField(max_length=500, default="", blank=True)

    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "volvo_checklist_general_evidencias"
        ordering = ["-creado"]

    def __str__(self):
        return self.nombre or f"Evidencia {self.pk}"
