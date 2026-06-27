#checklist_general/serializers.py
import json

from django.db import transaction
from rest_framework import serializers

from citas.models import ClienteComercial, normaliza_tel_mx
from .constants import CHECKLIST_GENERAL_IDS
from .models import ChecklistGeneralCalidad, EvidenciaChecklistGeneral


class ClienteComercialMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClienteComercial
        fields = ("id_cliente", "nombre", "telefono", "correo")


class EvidenciaChecklistGeneralSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = EvidenciaChecklistGeneral
        fields = ("id", "nombre", "descripcion", "archivo", "url", "creado")
        read_only_fields = ("id", "archivo", "url", "creado")

    def get_url(self, obj):
        if not obj.archivo:
            return ""
        try:
            url = obj.archivo.url
        except Exception:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class ChecklistGeneralCalidadSerializer(serializers.ModelSerializer):
    cliente = ClienteComercialMiniSerializer(read_only=True)
    evidencias = EvidenciaChecklistGeneralSerializer(many=True, read_only=True)

    cliente_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    nombre = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    telefono = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    correo = serializers.EmailField(write_only=True, required=False, allow_blank=True, default="")

    checklist_json = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    evidencias_existentes_json = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    evidencias_nuevas_descripciones_json = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    delete_evidencia_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = ChecklistGeneralCalidad
        fields = (
            "id",
            "cliente",
            "cliente_id",
            "nombre",
            "telefono",
            "correo",
            "agencia",
            "asesor_servicio",
            "tecnico_inspector",
            "gerente_servicio",
            "pst",
            "placas",
            "vin",
            "modelo",
            "kilometraje",
            "orden_servicio",
            "fecha_hora_revision",
            "requiere_prueba_manejo",
            "fecha_prueba",
            "hora_prueba",
            "kilometraje_inicial",
            "kilometraje_final",
            "checklist",
            "observaciones",
            "checklist_terminado",
            "fecha_terminado",
            "evidencias",
            "checklist_json",
            "evidencias_existentes_json",
            "evidencias_nuevas_descripciones_json",
            "delete_evidencia_ids",
            "creado",
            "actualizado",
        )
        read_only_fields = (
            "id",
            "cliente",
            "evidencias",
            "checklist_terminado",
            "fecha_terminado",
            "creado",
            "actualizado",
        )

    def _parse_json(self, raw, campo, default):
        if raw in (None, "", []):
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            raise serializers.ValidationError({campo: f"El campo {campo} debe ser JSON válido."})

    def _normalizar_checklist(self, raw_checklist):
        data = self._parse_json(raw_checklist, "checklist_json", {})

        if not isinstance(data, dict):
            raise serializers.ValidationError({"checklist_json": "El checklist debe ser un objeto JSON."})

        estados_validos = {"ok", "observacion", "na"}
        limpio = {}

        for key, value in data.items():
            key = str(key).strip()
            if key not in CHECKLIST_GENERAL_IDS:
                continue
            if not isinstance(value, dict):
                continue

            estado = str(value.get("estado") or "").strip().lower()
            comentario = str(value.get("comentario") or "").strip()

            if not estado and not comentario:
                continue

            if estado and estado not in estados_validos:
                raise serializers.ValidationError({"checklist_json": f"Estado inválido en {key}."})

            limpio[key] = {"estado": estado, "comentario": comentario}

        return limpio

    def _normalizar_evidencias_existentes(self, raw):
        data = self._parse_json(raw, "evidencias_existentes_json", [])
        if not isinstance(data, list):
            raise serializers.ValidationError({"evidencias_existentes_json": "Debe ser una lista."})

        evidencias = []
        for item in data:
            if not isinstance(item, dict):
                continue
            evidencia_id = item.get("id")
            if not evidencia_id:
                continue
            evidencias.append({
                "id": int(evidencia_id),
                "descripcion": str(item.get("descripcion") or "").strip(),
            })
        return evidencias

    def _normalizar_descripciones_nuevas(self, raw):
        data = self._parse_json(raw, "evidencias_nuevas_descripciones_json", [])
        if not isinstance(data, list):
            return []
        return [str(x or "").strip() for x in data]

    def _resolver_cliente(self, validated_data):
        cliente_id = validated_data.pop("cliente_id", None)
        nombre = validated_data.pop("nombre", "")
        telefono = validated_data.pop("telefono", "")
        correo = validated_data.pop("correo", "")

        if cliente_id:
            try:
                cliente = ClienteComercial.objects.get(pk=cliente_id)
            except ClienteComercial.DoesNotExist:
                raise serializers.ValidationError({"cliente_id": "El cliente indicado no existe."})

            cambios = False

            if nombre is not None and nombre.strip() != (cliente.nombre or ""):
                cliente.nombre = nombre.strip()
                cambios = True
            if correo is not None and correo.strip() != (cliente.correo or ""):
                cliente.correo = correo.strip()
                cambios = True
            if telefono:
                telefono_normalizado = normaliza_tel_mx(telefono)
                if not telefono_normalizado:
                    raise serializers.ValidationError({"telefono": "Teléfono inválido."})
                if telefono_normalizado != cliente.telefono:
                    existe = ClienteComercial.objects.filter(telefono=telefono_normalizado).exclude(pk=cliente.pk).exists()
                    if existe:
                        raise serializers.ValidationError({"telefono": "Ya existe otro cliente con ese teléfono."})
                    cliente.telefono = telefono_normalizado
                    cambios = True

            if cambios:
                cliente.save()
            return cliente

        telefono_normalizado = normaliza_tel_mx(telefono)
        if not telefono_normalizado:
            raise serializers.ValidationError({"telefono": "El teléfono es requerido y debe ser válido."})

        cliente, _ = ClienteComercial.objects.get_or_create(
            telefono=telefono_normalizado,
            defaults={"nombre": nombre.strip(), "correo": correo.strip()},
        )

        cambios = False
        if nombre and cliente.nombre != nombre.strip():
            cliente.nombre = nombre.strip()
            cambios = True
        if correo is not None and cliente.correo != correo.strip():
            cliente.correo = correo.strip()
            cambios = True
        if cambios:
            cliente.save()
        return cliente

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")

        archivos = []
        if request is not None and hasattr(request.FILES, "getlist"):
            archivos = request.FILES.getlist("evidencias_nuevas")

        for archivo in archivos:
            if archivo.size > 50 * 1024 * 1024:
                raise serializers.ValidationError({"evidencias_nuevas": f"El archivo {archivo.name} supera 50MB."})
            content_type = getattr(archivo, "content_type", "") or ""

            es_imagen = content_type.startswith("image/")
            es_video = content_type.startswith("video/")

            if not es_imagen and not es_video:
                raise serializers.ValidationError({
                    "evidencias_nuevas": "Solo se permiten imágenes o videos."
                })
            
        raw_checklist = None
        raw_existentes = None
        raw_desc_nuevas = None
        delete_ids = attrs.get("delete_evidencia_ids", [])

        if request is not None and hasattr(request.data, "get"):
            raw_checklist = request.data.get("checklist_json", None)
            raw_existentes = request.data.get("evidencias_existentes_json", None)
            raw_desc_nuevas = request.data.get("evidencias_nuevas_descripciones_json", None)

        if raw_checklist is None:
            raw_checklist = attrs.get("checklist_json", None)
        if raw_existentes is None:
            raw_existentes = attrs.get("evidencias_existentes_json", None)
        if raw_desc_nuevas is None:
            raw_desc_nuevas = attrs.get("evidencias_nuevas_descripciones_json", None)

        if request is not None and hasattr(request.data, "getlist"):
            raw_delete_ids = request.data.getlist("delete_evidencia_ids")
            if raw_delete_ids:
                delete_ids = raw_delete_ids

        attrs["_checklist_recibido"] = raw_checklist is not None
        attrs["_checklist_limpio"] = self._normalizar_checklist(raw_checklist) if raw_checklist is not None else {}
        attrs["_evidencias_existentes"] = self._normalizar_evidencias_existentes(raw_existentes)
        attrs["_evidencias_nuevas"] = archivos
        attrs["_evidencias_nuevas_descripciones"] = self._normalizar_descripciones_nuevas(raw_desc_nuevas)
        attrs["_delete_evidencia_ids"] = [int(x) for x in delete_ids or [] if str(x).strip()]

        return attrs

    def _crear_evidencias(self, checklist, archivos, descripciones=None):
        descripciones = descripciones or []
        for index, archivo in enumerate(archivos):
            EvidenciaChecklistGeneral.objects.create(
                checklist=checklist,
                archivo=archivo,
                nombre=getattr(archivo, "name", "") or "imagen",
                descripcion=descripciones[index] if index < len(descripciones) else "",
            )

    def _actualizar_evidencias_existentes(self, checklist, evidencias):
        for item in evidencias:
            EvidenciaChecklistGeneral.objects.filter(checklist=checklist, id=item["id"]).update(
                descripcion=item["descripcion"],
            )

    @transaction.atomic
    def create(self, validated_data):
        evidencias_nuevas = validated_data.pop("_evidencias_nuevas", [])
        desc_nuevas = validated_data.pop("_evidencias_nuevas_descripciones", [])
        evidencias_existentes = validated_data.pop("_evidencias_existentes", [])
        delete_ids = validated_data.pop("_delete_evidencia_ids", [])
        checklist = validated_data.pop("_checklist_limpio", {})
        validated_data.pop("_checklist_recibido", None)

        validated_data.pop("checklist_json", None)
        validated_data.pop("evidencias_existentes_json", None)
        validated_data.pop("evidencias_nuevas_descripciones_json", None)
        validated_data.pop("delete_evidencia_ids", None)

        cliente = self._resolver_cliente(validated_data)
        obj = ChecklistGeneralCalidad.objects.create(cliente=cliente, checklist=checklist, **validated_data)

        if delete_ids:
            obj.evidencias.filter(id__in=delete_ids).delete()

        self._crear_evidencias(obj, evidencias_nuevas, desc_nuevas)
        self._actualizar_evidencias_existentes(obj, evidencias_existentes)
        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        evidencias_nuevas = validated_data.pop("_evidencias_nuevas", [])
        desc_nuevas = validated_data.pop("_evidencias_nuevas_descripciones", [])
        evidencias_existentes = validated_data.pop("_evidencias_existentes", [])
        delete_ids = validated_data.pop("_delete_evidencia_ids", [])
        checklist = validated_data.pop("_checklist_limpio", {})
        checklist_recibido = validated_data.pop("_checklist_recibido", False)

        validated_data.pop("checklist_json", None)
        validated_data.pop("evidencias_existentes_json", None)
        validated_data.pop("evidencias_nuevas_descripciones_json", None)
        validated_data.pop("delete_evidencia_ids", None)

        usar_cliente = any(campo in validated_data for campo in ["cliente_id", "nombre", "telefono", "correo"])
        if usar_cliente:
            instance.cliente = self._resolver_cliente(validated_data)

        campos = [
            "agencia",
            "asesor_servicio",
            "tecnico_inspector",
            "gerente_servicio",
            "pst",
            "placas",
            "vin",
            "modelo",
            "kilometraje",
            "orden_servicio",
            "fecha_hora_revision",
            "requiere_prueba_manejo",
            "fecha_prueba",
            "hora_prueba",
            "kilometraje_inicial",
            "kilometraje_final",
            "observaciones",
        ]

        for campo in campos:
            if campo in validated_data:
                setattr(instance, campo, validated_data[campo])

        if checklist_recibido:
            instance.checklist = checklist

        instance.save()

        if delete_ids:
            instance.evidencias.filter(id__in=delete_ids).delete()
        self._actualizar_evidencias_existentes(instance, evidencias_existentes)
        if evidencias_nuevas:
            self._crear_evidencias(instance, evidencias_nuevas, desc_nuevas)

        return instance
