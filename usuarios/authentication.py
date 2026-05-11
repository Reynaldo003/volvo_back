# usuarios/authentication.py
from django.core import signing
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import Usuario

class SignedUserAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None

        token = auth.replace("Bearer ", "").strip()
        signer = signing.TimestampSigner()

        try:
            unsigned = signer.unsign(token, max_age=60 * 60 * 24 * 7)  # 7 días
            id_usuario = int(unsigned)
        except signing.SignatureExpired:
            raise AuthenticationFailed("Token expirado.")
        except Exception:
            raise AuthenticationFailed("Token inválido.")

        user = Usuario.objects.filter(id_usuario=id_usuario).select_related("rol").first()
        if not user:
            raise AuthenticationFailed("Usuario no existe.")

        # DRF espera (user, auth)
        return (user, token)
