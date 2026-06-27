#usuarios/permissions.py
from rest_framework.permissions import BasePermission

class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        u = getattr(request, "user", None)
        if not u or not getattr(u, "rol", None):
            return False
        return (u.rol.nombre or "").strip().lower() == "administrador"
