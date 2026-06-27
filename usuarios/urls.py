# usuarios/urls.py
from django.urls import path

from .views import (
    AuthRegisterView,
    AuthLoginView,
    AuthMeView,
    AdminRolesView,
    AdminPermisosCatalogView,
    AdminUsuariosCreateView,
)


urlpatterns = [
    path("register/", AuthRegisterView.as_view(), name="usuarios-register"),
    path("login/", AuthLoginView.as_view(), name="usuarios-login"),
    path("me/", AuthMeView.as_view(), name="usuarios-me"),

    path("admin/roles/", AdminRolesView.as_view(), name="usuarios-admin-roles"),
    path("admin/permisos/", AdminPermisosCatalogView.as_view(), name="usuarios-admin-permisos"),
    path("admin/crear/", AdminUsuariosCreateView.as_view(), name="usuarios-admin-crear"),
]