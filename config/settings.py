
import sys
from pathlib import Path

import dj_database_url
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent


# Security and environment
SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-change-me-in-production",
)

DEBUG = config(
    "DEBUG",
    default=False,
    cast=bool,
)

ALLOWED_HOSTS = config(
    "DJANGO_ALLOWED_HOSTS",
    default="localhost,127.0.0.1,mitattendance.onrender.com",
    cast=Csv(),
)

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://mitattendance.onrender.com",
    cast=Csv(),
)


# Applications
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "meetings",
]


# Middleware
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

WSGI_APPLICATION = "config.wsgi.application"


# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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


# Database: Render PostgreSQL in production, SQLite locally if
# no PostgreSQL configuration has been supplied.
DATABASE_URL = config(
    "DATABASE_URL",
    default="",
)

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=60,
            ssl_require=config(
                "DB_SSL_REQUIRE",
                default=not DEBUG,
                cast=bool,
            ),
        )
    }
else:
    local_db_name = config("DB_NAME", default="")

    if local_db_name:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": local_db_name,
                "USER": config("DB_USER", default="postgres"),
                "PASSWORD": config("DB_PASSWORD", default=""),
                "HOST": config("DB_HOST", default="localhost"),
                "PORT": config("DB_PORT", default="5432"),
                "CONN_MAX_AGE": 60,
                "OPTIONS": {
                    "connect_timeout": 10,
                },
            }
        }
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }


# Custom user model
AUTH_USER_MODEL = "accounts.User"


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# Faster password hashing during automated tests only
if "test" in sys.argv[1:]:
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]


# Authentication redirects
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"


# Internationalization
LANGUAGE_CODE = "en-us"

TIME_ZONE = config(
    "TIME_ZONE",
    default="Africa/Lagos",
)

USE_I18N = True
USE_TZ = True


# Static files and WhiteNoise
STATIC_URL = "static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedStaticFilesStorage"
        ),
    },
}


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Attendance configuration
ATTENDANCE_PAGE_SIZE = config(
    "ATTENDANCE_PAGE_SIZE",
    default=25,
    cast=int,
)

AUTO_FINALIZE_AFTER_MINUTES = config(
    "AUTO_FINALIZE_AFTER_MINUTES",
    default=0,
    cast=int,
)


# Session and browser security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SESSION_COOKIE_AGE = 60 * 60 * 12

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"


# HTTPS settings for production
if not DEBUG:
    SECURE_SSL_REDIRECT = config(
        "SECURE_SSL_REDIRECT",
        default=True,
        cast=bool,
    )

    if SECURE_SSL_REDIRECT:
        SECURE_PROXY_SSL_HEADER = (
            "HTTP_X_FORWARDED_PROTO",
            "https",
        )

        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True

        SECURE_HSTS_SECONDS = config(
            "SECURE_HSTS_SECONDS",
            default=31536000,
            cast=int,
        )

        SECURE_HSTS_INCLUDE_SUBDOMAINS = True


# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": (
                "%(asctime)s %(levelname)s "
                "%(name)s: %(message)s"
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": config(
            "LOG_LEVEL",
            default="INFO",
        ),
    },
}
