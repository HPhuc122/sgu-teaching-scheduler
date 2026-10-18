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
    "school.access_middleware.UnitAccessMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
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

# Operator configuration only; the interface has one quality scheduling action.
QUALITY_SEARCH_BUDGET_SECONDS = float(os.environ.get("UCTP_QUALITY_BUDGET_SECONDS", "60"))
QUALITY_SEARCH_SEED = int(os.environ.get("UCTP_QUALITY_SEED", "42"))
QUALITY_SEARCH_MAX_STARTS = 3
# Fixed-window cap; budget-aware admission uses this as its base allocation and
# can extend it when model + solver fit within protected downstream reserves.
QUALITY_CP_REFINEMENT_SECONDS = float(os.environ.get("UCTP_QUALITY_CP_REFINEMENT_SECONDS", "5"))
QUALITY_CP_MIN_SOLVE_SECONDS = float(os.environ.get("UCTP_QUALITY_CP_MIN_SOLVE_SECONDS", "1"))
# Budget-aware admission. The session-rate prior is calibrated conservatively
# from the simulated 18-run study; an explicit profile can supply observations.
QUALITY_CP_BUILD_PROFILE = os.environ.get("UCTP_QUALITY_CP_BUILD_PROFILE") or None
QUALITY_CP_MODEL_SECONDS_PER_SESSION = float(os.environ.get("UCTP_QUALITY_CP_MODEL_SECONDS_PER_SESSION", "0.04"))
QUALITY_CP_ESTIMATE_SAFETY_FACTOR = float(os.environ.get("UCTP_QUALITY_CP_ESTIMATE_SAFETY_FACTOR", "1.25"))
QUALITY_GD_RESERVE_SECONDS = float(os.environ.get("UCTP_QUALITY_GD_RESERVE_SECONDS", "1"))
# Cooperative headroom for mandatory audits and completion; not a hard I/O SLA.
QUALITY_AUDIT_RESERVE_SECONDS = float(os.environ.get("UCTP_QUALITY_AUDIT_RESERVE_SECONDS", "0.5"))
# Extra GD trajectories run only after the initial starts have had their turn.
QUALITY_GD_EXTRA_PATHS = int(os.environ.get("UCTP_QUALITY_GD_EXTRA_PATHS", "9"))
QUALITY_GD_EXTRA_PATH_SECONDS = float(os.environ.get("UCTP_QUALITY_GD_EXTRA_PATH_SECONDS", "2"))
QUALITY_GD_EXTRA_ITERATIONS = int(os.environ.get("UCTP_QUALITY_GD_EXTRA_ITERATIONS", "30000"))
QUALITY_GD_STAGNATION_ITERATIONS = int(os.environ.get("UCTP_QUALITY_GD_STAGNATION_ITERATIONS", "6000"))
QUALITY_GD_STALE_ROUNDS = int(os.environ.get("UCTP_QUALITY_GD_STALE_ROUNDS", "2"))
QUALITY_GD_MIN_PATH_SECONDS = float(os.environ.get("UCTP_QUALITY_GD_MIN_PATH_SECONDS", "0.1"))
