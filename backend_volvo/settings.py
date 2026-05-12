# backend_volvo/settings.py
from pathlib import Path


# ============================================================
# RUTAS BASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

SECRET_KEY = "django-insecure-volvo-cambia-esta-secret-key-en-produccion"

DEBUG = True

ALLOWED_HOSTS = [
    "crmvolvo.grupoautomotrizryr.com",
    "grupoautomotrizryr.com",
    "localhost",
    "127.0.0.1",
    "trafico-piso-volvo.vercel.app",
]


# URLs públicas del proyecto Volvo
BACKEND_PUBLIC_URL = "http://crmvolvo.grupoautomotrizryr.com/"
FRONTEND_PUBLIC_URL = "https://grupoautomotrizryr.com/crm_volvo/"

CRM_MARCA = "VOLVO"
CRM_FRONT_BASE_PATH = "/crm_volvo/"


# ============================================================
# APPS
# ============================================================

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Terceros
    "rest_framework",
    "corsheaders",

    # Apps propias
    "usuarios",
    "citas.apps.CitasConfig",
    "Digitales",
    "trafico_piso",
]


# ============================================================
# MIDDLEWARE
# ============================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # CORS debe ir antes de CommonMiddleware
    "corsheaders.middleware.CorsMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",

    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",

    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ============================================================
# URLS / WSGI
# ============================================================

ROOT_URLCONF = "backend_volvo.urls"

WSGI_APPLICATION = "backend_volvo.wsgi.application"


# ============================================================
# TEMPLATES
# ============================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ============================================================
# BASE DE DATOS POSTGRESQL
# ============================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "crm_volvo",
        "USER": "israel",
        "PASSWORD": "CRMR&R2026@",
#        "HOST": "127.0.0.1",
        "HOST": "191.96.31.18",
        "PORT": "5432",
    },
}


# ============================================================
# VALIDACIÓN DE CONTRASEÑAS
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ============================================================
# INTERNACIONALIZACIÓN
# ============================================================

LANGUAGE_CODE = "es-mx"

TIME_ZONE = "America/Mexico_City"

USE_I18N = True

# Lo dejamos en False para que Django guarde y lea fechas sin convertirlas a UTC.
USE_TZ = False


# ============================================================
# ARCHIVOS ESTÁTICOS Y MEDIA
# ============================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# DJANGO REST FRAMEWORK
# ============================================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "usuarios.authentication.SignedUserAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
}


# ============================================================
# CORS / CSRF
# ============================================================

# Importante:
# CORS usa solo dominio/origen, no rutas.
# Por eso aquí va https://grupoautomotrizryr.com
# y NO https://grupoautomotrizryr.com/crm_volvo/
CORS_ALLOWED_ORIGINS = [
    "https://grupoautomotrizryr.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://trafico-piso-volvo.vercel.app",
]

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    "https://grupoautomotrizryr.com",
    "http://crmvolvo.grupoautomotrizryr.com",
    "https://crmvolvo.grupoautomotrizryr.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://trafico-piso-volvo.vercel.app",
]


# ============================================================
# SEGURIDAD / PROXY
# ============================================================

USE_X_FORWARDED_HOST = True

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

X_FRAME_OPTIONS = "DENY"

APPEND_SLASH = True

# Como tu API está planteada en HTTP:
# http://crmvolvo.grupoautomotrizryr.com/
# dejamos estas cookies sin secure por ahora.
#
# Cuando el API ya tenga HTTPS, cambia ambos a True.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"


# ============================================================
# PRIMARY KEYS
# ============================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ============================================================
# LOGGING BÁSICO
# ============================================================

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}