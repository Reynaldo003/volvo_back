# trafico_piso/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TraficoPisoViewSet


router = DefaultRouter()
router.register(
    r"trafico-piso",
    TraficoPisoViewSet,
    basename="trafico-piso",
)


urlpatterns = [
    path("api/", include(router.urls)),
]