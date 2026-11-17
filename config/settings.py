
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)
# Lee variables desde .env si existe (no se versiona, ver .env.example)
environ.Env.read_env(BASE_DIR / ".env")


# --- Seguridad -------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-solo-para-desarrollo-local")
DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])


# --- Aplicaciones ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Apps propias del ecommerce 
    "apps.accounts",
    "apps.catalog",
    "apps.inventory",
    "apps.carts",
    "apps.orders",
    "apps.payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.catalog.context_processors.storefront_nav",
                "apps.carts.context_processors.cart_summary",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# --- Base de datos: PostgreSQL ------------------------------------

# PostgreSQL es la base oficial (T02/T03) y la única donde el bloqueo de
# filas de la reserva de stock funciona de verdad. Para desarrollar sin
# PostgreSQL instalado se puede poner DJANGO_DB_ENGINE=sqlite en el .env
# (el bloqueo concurrente no se prueba en SQLite).
if env("DJANGO_DB_ENGINE", default="postgresql") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", default="the_weekend_store"),
            "USER": env("POSTGRES_USER", default="weekend_store_user"),
            "PASSWORD": env("POSTGRES_PASSWORD", default="weekend_store_pass"),
            "HOST": env("POSTGRES_HOST", default="127.0.0.1"),
            "PORT": env("POSTGRES_PORT", default="5432"),
            "CONN_MAX_AGE": 60,
        }
    }


# --- Usuario personalizado y autenticación ------------------------

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "catalog:home"
LOGOUT_REDIRECT_URL = "catalog:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internacionalización ----------------------------------------------------

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Panama"
USE_I18N = True
USE_TZ = True


# --- Archivos estáticos y media ----------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# El almacenamiento con manifiesto exige `collectstatic`; en las pruebas
# (`manage.py test`) se usa el almacenamiento simple para no depender de él.
_STATICFILES_BACKEND = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if "test" in sys.argv
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)
STORAGES = {
    "staticfiles": {
        "BACKEND": _STATICFILES_BACKEND,
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Correo ( backend simple configurable) -------------------------------

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@theweekendstore.local")


# --- Pedidos y pagos (Etapa 3) -------------------------------------------------

# Único método de pago: PayPal Sandbox. No existe una alternativa local.
PAYMENT_GATEWAY = "paypal_sandbox"

# Minutos que se mantiene reservado el stock de un pedido pendiente de pago.
PAYMENT_WINDOW_MINUTES = env.int("PAYMENT_WINDOW_MINUTES", default=15)

# Credenciales del equipo, NUNCA las del proyecto de referencia. Solo Sandbox.
PAYPAL_ENV = env("PAYPAL_ENV", default="sandbox")
PAYPAL_CLIENT_ID = env("PAYPAL_CLIENT_ID", default="")
PAYPAL_CLIENT_SECRET = env("PAYPAL_CLIENT_SECRET", default="")
PAYPAL_RETURN_BASE_URL = env("PAYPAL_RETURN_BASE_URL", default="http://127.0.0.1:8000")
