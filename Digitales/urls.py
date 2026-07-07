#volvo
# Digitales/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ProspectosViewSet,
    bienvenido,
    campanas_meta_recientes,
    chats_list,
    contacto_por_telefono,
    contacto_updates,
    editar_mensaje_view,
    eliminacion_datos_meta_view,
    enviar_media_view,
    enviar_mensaje_view,
    enviar_plantilla_view,
    mark_read_view,
    mark_unread_view,
    media_proxy_view,
    plantillas_whatsapp_view,
    privacidad_meta_view,
    webhook,
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
    path("chats/mark-unread/", mark_unread_view),

    path("contacto/", contacto_por_telefono),
    path("contacto/updates/", contacto_updates),

    path("mensajes/enviar/", enviar_mensaje_view),
    path("mensajes/enviar-media/", enviar_media_view),
    path("mensajes/enviar-plantilla/", enviar_plantilla_view),
    path("mensajes/plantillas/", plantillas_whatsapp_view),
    path("mensajes/editar/", editar_mensaje_view),

    path("api/campanas-meta/", campanas_meta_recientes),
    path("api/", include(router.urls)),

    path("media/<str:media_id>/", media_proxy_view, name="digitales-media-proxy"),
]
