# usuarios/serializers.py
from django.contrib.auth.hashers import make_password, check_password
from django.core import signing
from rest_framework import serializers

from .models import Usuario, Rol


DEALERS_VALIDOS = [
    "Volvo",
]


def separar_nombre_completo(nombre_completo: str):
    partes = (nombre_completo or "").strip().split()

    if not partes:
        return "", ""

    if len(partes) == 1:
        return partes[0], ""

    nombre = partes[0]
    apellidos = " ".join(partes[1:])

    return nombre, apellidos


class UsuarioRegisterSerializer(serializers.Serializer):
    nombreCompleto = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    nombre = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    apellidos = serializers.CharField(
        max_length=70,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    usuario = serializers.CharField(max_length=10)
    correo = serializers.EmailField(max_length=255)
    contrasena = serializers.CharField(write_only=True)
    confirmarContrasena = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    agencia = serializers.ChoiceField(choices=DEALERS_VALIDOS)
    telefono = serializers.CharField(
        max_length=15,
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate_usuario(self, value):
        value = (value or "").strip()

        if Usuario.objects.filter(usuario__iexact=value).exists():
            raise serializers.ValidationError("Ese usuario ya existe.")

        return value

    def validate_correo(self, value):
        value = (value or "").strip().lower()

        if Usuario.objects.filter(correo__iexact=value).exists():
            raise serializers.ValidationError("Ese correo ya existe.")

        return value

    def validate(self, attrs):
        contrasena = attrs.get("contrasena") or ""
        confirmar = attrs.get("confirmarContrasena")

        if confirmar is not None and confirmar != contrasena:
            raise serializers.ValidationError({
                "confirmarContrasena": "Las contraseñas no coinciden."
            })

        nombre_completo = attrs.get("nombreCompleto") or ""
        nombre = attrs.get("nombre") or ""
        apellidos = attrs.get("apellidos") or ""

        if nombre_completo and not nombre:
            nombre, apellidos_desde_completo = separar_nombre_completo(nombre_completo)
            attrs["nombre"] = nombre
            attrs["apellidos"] = apellidos or apellidos_desde_completo

        if not (attrs.get("nombre") or "").strip():
            raise serializers.ValidationError({
                "nombre": "El nombre es obligatorio."
            })

        return attrs

    def create(self, validated_data):
        validated_data.pop("nombreCompleto", None)
        validated_data.pop("confirmarContrasena", None)

        rol_empleado = (
            Rol.objects.filter(nombre__iexact="Empleado").first()
            or Rol.objects.filter(nombre__iexact="Asesor Digital").first()
            or Rol.objects.filter(id_rol=2).first()
        )

        if not rol_empleado:
            raise serializers.ValidationError(
                "No existe un rol por defecto. Crea 'Empleado' o 'Asesor Digital' en roles_volvo."
            )

        usuario = Usuario.objects.create(
            nombre=(validated_data.get("nombre") or "").strip(),
            apellidos=(validated_data.get("apellidos") or "").strip(),
            usuario=(validated_data.get("usuario") or "").strip(),
            correo=(validated_data.get("correo") or "").strip().lower(),
            contrasena=make_password(validated_data["contrasena"]),
            rol=rol_empleado,
            agencia=validated_data["agencia"],
            telefono=(validated_data.get("telefono") or "").strip() or None,
        )

        return usuario


class UsuarioLoginSerializer(serializers.Serializer):
    usuario = serializers.CharField()
    contrasena = serializers.CharField(write_only=True)

    def validate(self, attrs):
        usuario = (attrs.get("usuario") or "").strip()
        contrasena = attrs.get("contrasena") or ""

        user = (
            Usuario.objects
            .filter(usuario__iexact=usuario)
            .select_related("rol")
            .first()
        )

        if not user:
            raise serializers.ValidationError("Usuario o contraseña inválidos.")

        if not check_password(contrasena, user.contrasena):
            raise serializers.ValidationError("Usuario o contraseña inválidos.")

        attrs["user"] = user
        return attrs


class AdminUsuarioCreateSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=50)
    apellidos = serializers.CharField(
        max_length=70,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    usuario = serializers.CharField(max_length=10)
    correo = serializers.EmailField(max_length=255)
    contrasena = serializers.CharField(write_only=True)
    agencia = serializers.ChoiceField(choices=DEALERS_VALIDOS)
    telefono = serializers.CharField(
        max_length=15,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    id_rol = serializers.IntegerField()

    def validate_usuario(self, value):
        value = (value or "").strip()

        if Usuario.objects.filter(usuario__iexact=value).exists():
            raise serializers.ValidationError("Ese usuario ya existe.")

        return value

    def validate_correo(self, value):
        value = (value or "").strip().lower()

        if Usuario.objects.filter(correo__iexact=value).exists():
            raise serializers.ValidationError("Ese correo ya existe.")

        return value

    def validate_id_rol(self, value):
        if not Rol.objects.filter(id_rol=value).exists():
            raise serializers.ValidationError("Rol inválido.")

        return value

    def create(self, validated_data):
        rol = Rol.objects.get(id_rol=validated_data["id_rol"])

        usuario = Usuario.objects.create(
            nombre=(validated_data.get("nombre") or "").strip(),
            apellidos=(validated_data.get("apellidos") or "").strip(),
            usuario=(validated_data.get("usuario") or "").strip(),
            correo=(validated_data.get("correo") or "").strip().lower(),
            contrasena=make_password(validated_data["contrasena"]),
            rol=rol,
            agencia=validated_data["agencia"],
            telefono=(validated_data.get("telefono") or "").strip() or None,
        )

        return usuario


def generar_token_usuario(id_usuario: int) -> str:
    signer = signing.TimestampSigner()
    return signer.sign(str(id_usuario))