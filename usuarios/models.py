# usuarios/models.py
from django.db import models


class Rol(models.Model):
    id_rol = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=200)

    class Meta:
        db_table = "roles_volvo"
        managed = False

    def __str__(self):
        return self.nombre


class Usuario(models.Model):
    id_usuario = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=50)
    apellidos = models.CharField(max_length=70, blank=True, null=True)
    usuario = models.CharField(max_length=10)
    correo = models.EmailField(max_length=255)
    contrasena = models.CharField(max_length=255)
    rol = models.ForeignKey(
        Rol,
        db_column="rol",
        on_delete=models.PROTECT,
    )
    agencia = models.CharField(max_length=100)
    telefono = models.CharField(max_length=15, null=True)

    class Meta:
        db_table = "usuarios_volvo"
        managed = True

    def __str__(self):
        return f"{self.nombre} {self.apellidos or ''}".strip()

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False