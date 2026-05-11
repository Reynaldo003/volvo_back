#Digitales/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    bienvenido,
    webhook,
    privacidad_meta_view,
    eliminacion_datos_meta_view,
    chats_list,
    contacto_por_telefono,
    enviar_mensaje_view,
    enviar_plantilla_view,
    enviar_media_view,
    mark_read_view,
    ProspectosViewSet,
    campanas_meta_recientes,
    contacto_updates,
    editar_mensaje_view,
    media_proxy_view,
    generar_resumen_prospecto_view,
    plantillas_whatsapp_view,
)

router = DefaultRouter()
router.register(r"prospectos", ProspectosViewSet, basename="prospectos")

urlpatterns = [
    path("bienvenido/", bienvenido),
    path("webhook/", webhook),

    path("privacidad-meta/", privacidad_meta_view),
    path("eliminacion-datos-meta/", eliminacion_datos_meta_view),

    path("chats/", chats_list),
    path("chats/mark-read/", mark_read_view),
    path("contacto/", contacto_por_telefono),
    path("contacto/updates/", contacto_updates),

    path("mensajes/enviar/", enviar_mensaje_view),
    path("mensajes/enviar-media/", enviar_media_view),
    path("mensajes/enviar-plantilla/", enviar_plantilla_view),
    path("mensajes/plantillas/", plantillas_whatsapp_view),
    path("mensajes/editar/", editar_mensaje_view),

    path("api/", include(router.urls)),
    path("api/campanas-meta/", campanas_meta_recientes),
    path("api/prospectos/<int:prospecto_id>/generar-resumen/", generar_resumen_prospecto_view),
    path("media/<str:media_id>/", media_proxy_view, name="digitales-media-proxy"),
]