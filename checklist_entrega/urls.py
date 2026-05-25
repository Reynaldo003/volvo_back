from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ChecklistEntregaVehiculoViewSet

router = DefaultRouter()
router.register(r"entregas", ChecklistEntregaVehiculoViewSet, basename="checklist-entrega")

urlpatterns = [
    path("api/", include(router.urls)),
]
