# citas/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClienteComercialViewSet,
    CitasViewSet,
    RegistroPisoViewSet,
    PruebasManejoViewSet,
    EvidenciasPruebaManejoViewSet,
    EntregasViewSet,
)

router = DefaultRouter()
router.register(r"clientes-comerciales", ClienteComercialViewSet, basename="clientes-comerciales")
router.register(r"citas", CitasViewSet, basename="citas")
router.register(r"registro-piso", RegistroPisoViewSet, basename="registro-piso")
router.register(r"pruebas-manejo", PruebasManejoViewSet, basename="pruebas-manejo")
router.register(r"evidencias-pruebas", EvidenciasPruebaManejoViewSet, basename="evidencias-pruebas")
router.register(r"entregas", EntregasViewSet, basename="entregas")

urlpatterns = [
    path("api/", include(router.urls)),
]