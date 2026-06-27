from django.db import models
from django.utils import timezone
from citas.models import ClienteComercial, normaliza_tel_mx


class ExpedienteDigital(models.Model):
    cliente = models.OneToOneField(
        ClienteComercial,
        db_column="id_cliente",
        on_delete=models.PROTECT,
        related_name="expediente_digital_volvo",
    )

    agencia = models.CharField(max_length=120, blank=True, default="")
    business = models.CharField(max_length=120, blank=True, default="")
    canal_contacto = models.CharField(max_length=120, blank=True, default="")
    pauta = models.CharField(max_length=500, blank=True, default="")
    estado = models.CharField(max_length=120, blank=True, default="")
    auto_interes = models.CharField(max_length=255, blank=True, default="")
    enganche_monto = models.PositiveIntegerField(null=True, blank=True)
    presupuesto_mensual = models.PositiveIntegerField(null=True, blank=True)
    buro_estado = models.CharField(max_length=30, blank=True, default="")
    forma_pago = models.CharField(max_length=30, blank=True, default="")
    tipo_cliente = models.CharField(max_length=30, blank=True, default="")
    plazo_compra = models.CharField(max_length=120, blank=True, default="")
    uso_vehiculo = models.CharField(max_length=255, blank=True, default="")
    comprobacion_ingresos = models.CharField(max_length=200, blank=True, default="")
    asesor_digital = models.CharField(max_length=200, blank=True, default="")
    asesor_ventas = models.CharField(max_length=200, blank=True, default="")
    comentarios = models.TextField(max_length=2000, blank=True, default="")
    primer_contacto_at = models.DateTimeField(null=True, blank=True)
    ultimo_contacto_at = models.DateTimeField(null=True, blank=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    resumen = models.TextField(blank=True, default="")
    resumen_actualizado_at = models.DateTimeField(null=True, blank=True)
    resumen_fuente = models.CharField(max_length=30, blank=True, default="")

    ultima_cita = models.ForeignKey(
        "citas.Cita",
        db_column="id_ultima_cita",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    ultima_cita_agendada = models.DateTimeField(null=True, blank=True)
    asistencia = models.BooleanField(default=False)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "expediente_digital_volvo"
        managed = True

    def touch_ultimo_contacto(self, when=None, save_now=False):
        when = when or timezone.now()

        if not self.primer_contacto_at:
            self.primer_contacto_at = when

        self.ultimo_contacto_at = when

        if save_now:
            self.save(
                update_fields=[
                    "primer_contacto_at",
                    "ultimo_contacto_at",
                    "actualizado",
                ]
            )

    def mark_read(self, when=None):
        when = when or timezone.now()
        self.last_read_at = when
        self.save(update_fields=["last_read_at", "actualizado"])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ExpedienteDigital #{self.cliente_id} - {self.cliente.telefono}"


class MensajeWhatsApp(models.Model):
    class Direccion(models.TextChoices):
        IN = "in", "Entrante"
        OUT = "out", "Saliente"

    telefono = models.CharField(max_length=32, db_index=True)
    numero_asesor = models.CharField(max_length=15)

    cliente = models.ForeignKey(
        ClienteComercial,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mensajes_whatsapp_volvo",
    )

    direction = models.CharField(max_length=3, choices=Direccion.choices)
    body = models.TextField(blank=True, default="")
    wa_message_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    status = models.CharField(max_length=30, blank=True, default="sent")

    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "digitales_mensajes_volvo"
        managed = True
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["telefono", "numero_asesor", "created_at"]),
            models.Index(fields=["numero_asesor", "created_at"]),
            models.Index(fields=["wa_message_id"]),
        ]

    def save(self, *args, **kwargs):
        self.telefono = normaliza_tel_mx(self.telefono)
        self.numero_asesor = normaliza_tel_mx(self.numero_asesor)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.direction} {self.telefono} {self.numero_asesor} {self.created_at:%Y-%m-%d %H:%M}"


class LecturaWhatsApp(models.Model):
    expediente = models.ForeignKey(
        ExpedienteDigital,
        on_delete=models.CASCADE,
        related_name="lecturas_whatsapp_volvo",
    )

    numero_asesor = models.CharField(max_length=15, db_index=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "digitales_lecturas_whatsapp_volvo"
        managed = True
        unique_together = [("expediente", "numero_asesor")]
        indexes = [
            models.Index(fields=["expediente", "numero_asesor"]),
            models.Index(fields=["numero_asesor", "last_read_at"]),
        ]

    def touch(self, when=None):
        self.last_read_at = when or timezone.now()
        self.save(update_fields=["last_read_at", "updated_at"])


class CampanaMeta(models.Model):
    id_campana = models.BigIntegerField(primary_key=True)
    id_concesionaria = models.IntegerField()
    sucursal = models.CharField(max_length=100)
    nombre_campana = models.CharField(max_length=500)
    inicio_campana = models.DateField(null=True, blank=True)
    fin_campana = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "campanas_meta"
        managed = False


class MapeoFuenteMeta(models.Model):
    id_fuente = models.CharField(
        max_length=120,
        primary_key=True,
        db_column="id_fuente",
    )
    tipo_fuente = models.CharField(max_length=30)
    id_campana = models.BigIntegerField(null=True, blank=True)
    nombre_campana = models.CharField(max_length=500, blank=True, default="")
    id_anuncio = models.BigIntegerField(null=True, blank=True)
    nombre_anuncio = models.CharField(max_length=500, blank=True, default="")
    id_conjunto = models.BigIntegerField(null=True, blank=True)
    nombre_conjunto = models.CharField(max_length=500, blank=True, default="")
    sucursal = models.CharField(max_length=100, blank=True, default="")
    respuesta_meta = models.TextField(blank=True, default="")
    creado_en = models.DateTimeField(null=True, blank=True)
    actualizado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mapeo_fuentes_meta"
        managed = False