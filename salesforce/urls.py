# salesforce/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import OportunidadViewSet, ProspectoViewSet, TareaViewSet

app_name = "salesforce"

router = DefaultRouter()
router.register("oportunidades", OportunidadViewSet, basename="oportunidades")
router.register("prospectos", ProspectoViewSet, basename="prospectos")
router.register("tareas", TareaViewSet, basename="tareas")

urlpatterns = [
    path("api/", include(router.urls)),
]