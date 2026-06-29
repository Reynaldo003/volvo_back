# citas/models.py
from django.db import models
from django.core.exceptions import ValidationError


def normaliza_tel_mx(raw: str) -> str:
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    if not digits:
        return ""
    if len(digits) == 10:
        return "52" + digits
    if len(digits) == 12 and digits.startswith("52"):
        return digits
    return ""

class ClienteComercial(models.Model):
    id_cliente = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=200, blank=True, default="")
    telefono = models.CharField(max_length=32, db_index=True, unique=True)
    correo = models.EmailField(blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clientes_comerciales_volvo"
        managed = True

    def save(self, *args, **kwargs):
        self.telefono = normaliza_tel_mx(self.telefono)

        if not self.telefono:
            raise ValidationError({
                "telefono": "Teléfono inválido. Debe tener 10 dígitos o 12 dígitos iniciando con 52."
            })

        super().save(*args, **kwargs)

    def __str__(self):
        base = (self.nombre or "").strip() or "Cliente"
        return f"{base} ({self.telefono})".strip()


class Cita(models.Model):
    cliente = models.ForeignKey(
        ClienteComercial,
        db_column="id_cliente",
        on_delete=models.PROTECT,
        related_name="citas",
    )

    agencia = models.CharField(max_length=120, blank=True, default="")
    auto_interes = models.CharField(max_length=255, blank=True, default="")
    fecha_hora_cita = models.DateTimeField(null=True, blank=True)
    asistencia = models.BooleanField(default=False)

    tipo_cita = models.CharField(max_length=120, blank=True, default="")
    fuente_prospeccion = models.CharField(max_length=120, blank=True, default="")
    asesor_digital = models.CharField(max_length=200, blank=True, default="")
    asesor_piso = models.CharField(max_length=200, blank=True, default="")
    comentarios = models.CharField(max_length=2000, blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "citas_volvo"
        managed = True

    def __str__(self):
        return f"Cita #{self.id} - {self.cliente.telefono}"


class RegistroPiso(models.Model):
    cliente = models.ForeignKey(
        ClienteComercial,
        db_column="id_cliente",
        on_delete=models.PROTECT,
        related_name="registros_piso",
    )

    agencia = models.CharField(max_length=120, blank=True, default="")
    auto_interes = models.CharField(max_length=255, blank=True, default="")
    fecha_hora_cita = models.DateTimeField(null=True, blank=True)

    asistencia = models.BooleanField(default=False)
    be_back = models.BooleanField(default=False)
    fuente_prospeccion = models.CharField(max_length=120, blank=True, default="")
    asesor_piso = models.CharField(max_length=200, blank=True, default="")

    folio = models.CharField(max_length=200, blank=True, default="")
    tipo_venta = models.CharField(max_length=200, blank=True, default="")
    estado_ingreso = models.CharField(max_length=120, blank=True, default="")
    comentarios_cliente = models.CharField(max_length=2000, blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "registro_piso_volvo"
        managed = True

    def __str__(self):
        return f"Piso #{self.id} - {self.cliente.telefono}"


def ruta_evidencia_prueba(instance, filename: str) -> str:
    cliente_id = instance.prueba_manejo.cliente_id or "sin_cliente"
    prueba_id = instance.prueba_manejo_id or "sin_prueba"

    return f"clientes_comerciales_volvo/{cliente_id}/pruebas/{prueba_id}/{filename}"


class PruebaManejo(models.Model):
    cliente = models.ForeignKey(
        ClienteComercial,
        db_column="id_cliente",
        on_delete=models.PROTECT,
        related_name="pruebas_manejo",
    )

    agencia = models.CharField(max_length=120, blank=True, default="")
    auto_interes = models.CharField(max_length=255, blank=True, default="")
    fecha_hora_cita = models.DateTimeField(null=True, blank=True)
    asistencia = models.BooleanField(default=False)

    num_serie = models.CharField(max_length=200, blank=True, default="")
    asesor_piso = models.CharField(max_length=200, blank=True, default="")
    comentarios_cliente = models.CharField(max_length=2000, blank=True, default="")
    folio_salida = models.CharField(max_length=200, blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pruebas_manejo_volvo"
        managed = True

    def __str__(self):
        return f"Prueba #{self.id} - {self.cliente.telefono}"


class EvidenciaPruebaManejo(models.Model):
    prueba_manejo = models.ForeignKey(
        PruebaManejo,
        db_column="id_prueba_manejo",
        on_delete=models.CASCADE,
        related_name="evidencias",
    )

    archivo = models.FileField(upload_to=ruta_evidencia_prueba)
    nombre_original = models.CharField(max_length=255, blank=True, default="")
    tipo_mime = models.CharField(max_length=120, blank=True, default="")
    tamano_bytes = models.BigIntegerField(default=0)

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evidencias_prueba_manejo_volvo"
        managed = True

    def __str__(self):
        return f"Evidencia #{self.id} - Prueba {self.prueba_manejo_id}"


class Entregas(models.Model):
    cliente = models.ForeignKey(
        ClienteComercial,
        db_column="id_cliente",
        on_delete=models.PROTECT,
        related_name="entregas",
    )

    agencia = models.CharField(max_length=120, blank=True, default="")
    vin = models.CharField(max_length=2000, blank=True, default="")
    modelo_version = models.CharField(max_length=255, blank=True, default="")
    fecha_hora_entrega = models.DateTimeField(null=True, blank=True)
    entrega_reportada = models.BooleanField(default=False)
    asesor_ventas = models.CharField(max_length=200, blank=True, default="")
    preparada_por = models.CharField(max_length=2000, blank=True, default="")
    id_cliente_sf_nadin = models.CharField(max_length=2000, blank=True, default="")
    id_cliente_sf_dms = models.CharField(max_length=2000, blank=True, default="")
    comentarios = models.CharField(max_length=2000, blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "entregas_volvo"
        managed = True

    def __str__(self):
        return f"Entrega #{self.id} - {self.cliente.telefono}"