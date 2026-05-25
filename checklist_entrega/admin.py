from django.contrib import admin
from .models import ChecklistEntregaVehiculo, EvidenciaChecklistEntrega


class EvidenciaChecklistEntregaInline(admin.TabularInline):
    model = EvidenciaChecklistEntrega
    extra = 0
    readonly_fields = ("creado",)


@admin.register(ChecklistEntregaVehiculo)
class ChecklistEntregaVehiculoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cliente",
        "agencia",
        "placas",
        "vin",
        "modelo",
        "asesor_servicio",
        "entrega_terminada",
        "creado",
    )
    search_fields = (
        "cliente__nombre",
        "cliente__telefono",
        "placas",
        "vin",
        "modelo",
        "orden_servicio",
        "factura",
    )
    list_filter = ("agencia", "entrega_terminada", "creado")
    inlines = [EvidenciaChecklistEntregaInline]


@admin.register(EvidenciaChecklistEntrega)
class EvidenciaChecklistEntregaAdmin(admin.ModelAdmin):
    list_display = ("id", "entrega", "nombre", "creado")
    search_fields = ("nombre", "descripcion", "entrega__cliente__nombre")
