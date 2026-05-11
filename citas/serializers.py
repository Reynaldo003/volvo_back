# citas/serializers.py
from rest_framework import serializers
from .models import (
    ClienteComercial,
    Cita,
    RegistroPiso,
    PruebaManejo,
    EvidenciaPruebaManejo,
    Entregas,
    normaliza_tel_mx,
)


class ClienteComercialSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClienteComercial
        fields = "__all__"


def obtener_o_crear_cliente(*, nombre, telefono, correo) -> ClienteComercial:
    telefono = normaliza_tel_mx(telefono)
    if not telefono:
        raise serializers.ValidationError({"telefono": "El teléfono es requerido y debe ser válido."})

    cliente, _ = ClienteComercial.objects.get_or_create(
        telefono=telefono,
        defaults={
            "nombre": (nombre or "").strip(),
            "correo": (correo or "").strip(),
        },
    )

    cambios = False

    if nombre is not None and nombre.strip() and (cliente.nombre or "").strip() != nombre.strip():
        cliente.nombre = nombre.strip()
        cambios = True

    if correo is not None and (cliente.correo or "").strip() != (correo or "").strip():
        cliente.correo = (correo or "").strip()
        cambios = True

    if cambios:
        cliente.save(update_fields=["nombre", "correo", "actualizado_en"])

    return cliente


class BaseConClienteInputMixin(serializers.ModelSerializer):
    # Entrada opcional para crear/ligar cliente sin mandar cliente_id
    nombre = serializers.CharField(write_only=True, required=False, allow_blank=True)
    telefono = serializers.CharField(write_only=True, required=False, allow_blank=True)
    correo = serializers.CharField(write_only=True, required=False, allow_blank=True)

    # Salida
    cliente = ClienteComercialSerializer(read_only=True)

    # Entrada por ID
    cliente_id = serializers.PrimaryKeyRelatedField(
        source="cliente",
        queryset=ClienteComercial.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    def _resolver_cliente(self, validated_data):
        cliente = validated_data.get("cliente")
        if cliente:
            return cliente

        nombre = validated_data.pop("nombre", "")
        telefono = validated_data.pop("telefono", "")
        correo = validated_data.pop("correo", "")

        telefono = (telefono or "").strip()
        if not telefono:
            raise serializers.ValidationError({
                "cliente_id": "Envía cliente_id o envía al menos teléfono para crear/unir el cliente."
            })

        return obtener_o_crear_cliente(
            nombre=nombre,
            telefono=telefono,
            correo=correo,
        )

    def create(self, validated_data):
        validated_data["cliente"] = self._resolver_cliente(validated_data)

        # limpiar campos que no existen en el modelo
        validated_data.pop("nombre", None)
        validated_data.pop("telefono", None)
        validated_data.pop("correo", None)

        return super().create(validated_data)

    def update(self, instance, validated_data):
        nombre = validated_data.pop("nombre", None)
        telefono = validated_data.pop("telefono", None)
        correo = validated_data.pop("correo", None)

        if nombre is not None or correo is not None:
            cliente = instance.cliente
            cambios = False

            if nombre is not None and nombre.strip():
                cliente.nombre = nombre.strip()
                cambios = True

            if correo is not None:
                cliente.correo = (correo or "").strip()
                cambios = True

            # Aquí no cambiamos el teléfono para evitar merges accidentales de clientes.
            # Si luego quieres permitirlo, se hace con una lógica más controlada.
            if telefono is not None and telefono.strip():
                pass

            if cambios:
                cliente.save(update_fields=["nombre", "correo", "actualizado_en"])

        if "cliente" in validated_data:
            instance.cliente = validated_data["cliente"]

        return super().update(instance, validated_data)


class CitaSerializer(BaseConClienteInputMixin):
    class Meta:
        model = Cita
        fields = "__all__"


class RegistroPisoSerializer(BaseConClienteInputMixin):
    class Meta:
        model = RegistroPiso
        fields = "__all__"


class EvidenciaPruebaManejoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenciaPruebaManejo
        fields = "__all__"
        read_only_fields = ["nombre_original", "tipo_mime", "tamano_bytes", "creado_en"]

    def create(self, validated_data):
        archivo = validated_data.get("archivo")
        if archivo:
            validated_data["nombre_original"] = getattr(archivo, "name", "") or ""
            validated_data["tipo_mime"] = getattr(archivo, "content_type", "") or ""
            validated_data["tamano_bytes"] = getattr(archivo, "size", 0) or 0
        return super().create(validated_data)


class PruebaManejoSerializer(BaseConClienteInputMixin):
    evidencias = EvidenciaPruebaManejoSerializer(many=True, read_only=True)

    class Meta:
        model = PruebaManejo
        fields = "__all__"


class EntregasSerializer(BaseConClienteInputMixin):
    class Meta:
        model = Entregas
        fields = "__all__"