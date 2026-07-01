# backend_volvo/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

def health_check(request):
    return JsonResponse(
        {
            "ok": True,
            "project": "backend_volvo",
            "message": "API CRM Volvo funcionando correctamente",
        }
    )

urlpatterns = [
    path("", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("usuarios/", include("usuarios.urls")),
    path("citas/", include("citas.urls")),
    path("trafico-piso/", include("trafico_piso.urls")),
    path("digitales/", include("Digitales.urls")),
    path("recepcion-volvo/", include("recepcion_volvo.urls")),
    path("checklist-entrega/", include("checklist_entrega.urls")),
    path("checklist-general/", include("checklist_general.urls")),
    path("campanas-meta/", include("meta_ads.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)