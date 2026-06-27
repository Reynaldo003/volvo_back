# trafico_piso/models.py
from django.conf import settings
from django.db import models


class TraficoPiso(models.Model):
    id_trafico = models.AutoField(primary_key=True)

    # Datos generales
    agencia = models.CharField(max_length=120, blank=True, default="")
    nombre_prospecto = models.CharField(max_length=200, blank=True, default="")
    codigo_postal = models.CharField(max_length=10, blank=True, default="")
    telefono = models.CharField(max_length=20, blank=True, default="", db_index=True)
    email = models.EmailField(blank=True, default="")
    asesor_ventas = models.CharField(max_length=200, blank=True, default="", db_index=True)
    motivo_ingreso = models.CharField(max_length=120, blank=True, default="")
    tipo_persona = models.CharField(max_length=40, blank=True, default="")

    # Intención de compra
    tiempo_compra = models.CharField(max_length=80, blank=True, default="")
    auto_suenos = models.CharField(max_length=120, blank=True, default="")
    deja_auto_cuenta = models.BooleanField(default=False)
    modelo_auto_cuenta = models.CharField(max_length=200, blank=True, default="")
    forma_capitalizacion = models.CharField(max_length=120, blank=True, default="")

    presupuesto_estimado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    enganche_presupuestado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
    )

    mensualidades_presupuestadas = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        default=0,
    )

    # Perfil financiero
    comprueba_ingresos = models.BooleanField(default=False)
    forma_comprobar_ingresos = models.CharField(max_length=120, blank=True, default="")

    # Perfil del prospecto
    motivo_compra = models.CharField(max_length=120, blank=True, default="")
    perfil_profesional = models.CharField(max_length=120, blank=True, default="")
    edad = models.PositiveSmallIntegerField(null=True, blank=True)
    cantidad_hijos = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    estado_civil = models.CharField(max_length=60, blank=True, default="")

    pasatiempos = models.JSONField(default=list, blank=True)

    comentarios = models.TextField(blank=True, default="")

    # Auditoría
    creado_por = models.ForeignKey(
        "usuarios.Usuario",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="traficos_piso_volvo_creados",
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trafico_piso_volvo"
        ordering = ["-id_trafico"]
        verbose_name = "Tráfico de piso Volvo"
        verbose_name_plural = "Tráfico de piso Volvo"
        indexes = [
            models.Index(fields=["telefono"]),
            models.Index(fields=["asesor_ventas"]),
            models.Index(fields=["agencia"]),
            models.Index(fields=["creado_en"]),
        ]

    def __str__(self):
        nombre = self.nombre_prospecto or "Prospecto"
        return f"{self.id_trafico} - {nombre}"