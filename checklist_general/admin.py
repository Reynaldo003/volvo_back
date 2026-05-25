from django.contrib import admin
from .models import ChecklistGeneralCalidad, EvidenciaChecklistGeneral


class EvidenciaChecklistGeneralInline(admin.TabularInline):
    model = EvidenciaChecklistGeneral
    extra = 0
    readonly_fields = ("creado",)


@admin.register(ChecklistGeneralCalidad)
class ChecklistGeneralCalidadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cliente",
        "agencia",
        "placas",
        "vin",
        "modelo",
        "tecnico_inspector",
        "checklist_terminado",
        "creado",
    )
    search_fields = (
        "cliente__nombre",
        "cliente__telefono",
        "placas",
        "vin",
        "modelo",
        "orden_servicio",
    )
    list_filter = ("agencia", "checklist_terminado", "requiere_prueba_manejo", "creado")
    inlines = [EvidenciaChecklistGeneralInline]


@admin.register(EvidenciaChecklistGeneral)
class EvidenciaChecklistGeneralAdmin(admin.ModelAdmin):
    list_display = ("id", "checklist", "nombre", "creado")
    search_fields = ("nombre", "descripcion", "checklist__cliente__nombre")
