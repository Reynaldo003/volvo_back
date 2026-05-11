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

    # Auth / usuarios
    path("usuarios/", include("usuarios.urls")),

    # Gestión comercial
    path("citas/", include("citas.urls")),
    path("trafico-piso/", include("trafico_piso.urls")),

    # Digitales / WhatsApp
    path("digitales/", include("Digitales.urls")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)