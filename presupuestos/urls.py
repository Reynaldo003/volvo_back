from django.urls import path

from .views import (
    MatrizPresupuestosListView,
    MatrizPresupuestosRefListView,
)


urlpatterns = [
    path(
        "api/presupuestos/",
        MatrizPresupuestosListView.as_view(),
        name="matriz-presupuestos",
    ),
    path(
        "api/referencias/",
        MatrizPresupuestosRefListView.as_view(),
        name="matriz-presupuestos-ref",
    ),
]