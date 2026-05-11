# usuarios/views.py
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .authentication import SignedUserAuthentication
from .models import Usuario, Rol
from .permissions import IsAdminRole
from .serializers import (
    UsuarioRegisterSerializer,
    UsuarioLoginSerializer,
    AdminUsuarioCreateSerializer,
    generar_token_usuario,
)


def permisos_por_rol(nombre_rol: str):
    rol = (nombre_rol or "").strip().lower()

    if rol == "administrador":
        return [
            "ALL",
            "USUARIOS_ADMIN",
            "CRM_DIGITALES",
            "CRM_VENTAS",
            "CRM_FINANCIEROS",
            "CRM_POSTVENTA",
            "CRM_RRHH",
        ]

    if rol in ("asesor general", "asesor comercial"):
        return [
            "CRM_DIGITALES",
            "CRM_VENTAS",
        ]

    if rol == "hostess":
        return ["CRM_VENTAS"]

    if rol == "asesor digital":
        return ["CRM_DIGITALES"]

    if rol in ("asesor ventas", "asesor de ventas"):
        return ["CRM_VENTAS"]

    if rol == "contador":
        return ["CRM_FINANCIEROS"]

    if rol == "postventa":
        return ["CRM_POSTVENTA"]

    if rol == "recursos humanos":
        return ["CRM_RRHH"]

    if rol == "empleado":
        return ["CRM_DIGITALES"]

    return []


def serializar_usuario_sesion(usuario: Usuario):
    return {
        "id_usuario": usuario.id_usuario,
        "nombre": usuario.nombre,
        "apellidos": usuario.apellidos,
        "usuario": usuario.usuario,
        "correo": usuario.correo,
        "rol": usuario.rol.nombre if usuario.rol else "",
        "agencia": usuario.agencia,
        "telefono": usuario.telefono,
        "permisos": permisos_por_rol(usuario.rol.nombre if usuario.rol else ""),
    }


class AuthRegisterView(APIView):
    def post(self, request):
        serializer = UsuarioRegisterSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        usuario = serializer.save()

        return Response(
            {
                "id_usuario": usuario.id_usuario,
                "usuario": usuario.usuario,
                "correo": usuario.correo,
                "rol": usuario.rol.nombre if usuario.rol else "",
                "agencia": usuario.agencia,
            },
            status=status.HTTP_201_CREATED,
        )


class AuthLoginView(APIView):
    def post(self, request):
        serializer = UsuarioLoginSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {"detail": "Credenciales inválidas."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        usuario = serializer.validated_data["user"]
        token = generar_token_usuario(usuario.id_usuario)

        return Response(
            {
                "token": token,
                "user": serializar_usuario_sesion(usuario),
            },
            status=status.HTTP_200_OK,
        )


class AuthMeView(APIView):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(serializar_usuario_sesion(request.user))


class AdminRolesView(APIView):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        roles = Rol.objects.all().order_by("id_rol")

        data = [
            {
                "id_rol": rol.id_rol,
                "nombre": rol.nombre,
                "descripcion": rol.descripcion,
            }
            for rol in roles
        ]

        return Response(data)


class AdminPermisosCatalogView(APIView):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        data = [
            {
                "clave": "CRM_DIGITALES",
                "descripcion": "Acceso al módulo de prospectos digitales",
            },
            {
                "clave": "CRM_VENTAS",
                "descripcion": "Acceso al módulo de ventas y gestión comercial",
            },
            {
                "clave": "CRM_FINANCIEROS",
                "descripcion": "Acceso al módulo financiero",
            },
            {
                "clave": "CRM_POSTVENTA",
                "descripcion": "Acceso al módulo de postventa",
            },
            {
                "clave": "CRM_RRHH",
                "descripcion": "Acceso al módulo de recursos humanos",
            },
            {
                "clave": "USUARIOS_ADMIN",
                "descripcion": "Administración de usuarios",
            },
            {
                "clave": "ALL",
                "descripcion": "Acceso total del sistema",
            },
        ]

        return Response(data)


class AdminUsuariosCreateView(APIView):
    authentication_classes = [SignedUserAuthentication]
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        serializer = AdminUsuarioCreateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        usuario = serializer.save()

        return Response(
            {
                "id_usuario": usuario.id_usuario,
                "usuario": usuario.usuario,
                "correo": usuario.correo,
                "rol": usuario.rol.nombre if usuario.rol else "",
                "agencia": usuario.agencia,
                "telefono": usuario.telefono,
            },
            status=status.HTTP_201_CREATED,
        )