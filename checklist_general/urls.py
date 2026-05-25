#checklist_general/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ChecklistGeneralCalidadViewSet

router = DefaultRouter()
router.register(r"checklists", ChecklistGeneralCalidadViewSet, basename="checklist-general")

urlpatterns = [
    path("api/", include(router.urls)),
]
