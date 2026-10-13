"""Cau hinh backend SGU. SQLite cho phat trien; SQL Server cho trien khai."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR.parent))

SECRET_KEY = os.environ.get("UCTP_SECRET_KEY", "dev-only-change-before-deploy")
DEBUG = os.environ.get("UCTP_DEBUG", "0") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("UCTP_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "school",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("UCTP_DB_ENGINE") == "mssql":
    DATABASES = {"default": {
        "ENGINE": "mssql",
        "NAME": os.environ["UCTP_DB_NAME"],
        "USER": os.environ.get("UCTP_DB_USER", ""),
        "PASSWORD": os.environ.get("UCTP_DB_PASSWORD", ""),
        "HOST": os.environ.get("UCTP_DB_HOST", "localhost"),
        "PORT": os.environ.get("UCTP_DB_PORT", ""),
        "OPTIONS": {"driver": os.environ.get("UCTP_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")},
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                             "NAME": os.environ.get("UCTP_SQLITE_PATH", str(BASE_DIR / "db.sqlite3"))}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/portal/"
