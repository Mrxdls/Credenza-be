"""
Django settings for Poornima Faculty Achievements & Accreditation Portal.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-poornima-portal-fallback-secret-key-2026')
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = ['*']

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
]
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
]

# Application definition
INSTALLED_APPS = [
    # Unfold must be defined before django.contrib.admin
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',
    'unfold.contrib.inlines',
    'unfold.contrib.import_export',
    'unfold.contrib.simple_history',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party libraries (Library-First approach)
    'rest_framework',
    'django_filters',
    'import_export',
    'simple_history',
    'corsheaders',
    'storages',

    # Local application modules
    'apps.tenants',
    'apps.accounts',
    'apps.activities',
    'apps.documents',
    'apps.core',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database Configuration (PostgreSQL / Cloudflare D1 / SQLite)
DB_ENGINE = os.getenv('DB_ENGINE', 'postgresql').lower()

if DB_ENGINE == 'd1':
    # Cloudflare D1 Serverless SQL Database
    try:
        import js  # Present in Cloudflare Worker Pyodide runtime
        DATABASES = {
            'default': {
                'ENGINE': 'django_cf.db.backends.d1',
                'NAME': 'DB',
                'CLOUDFLARE_BINDING': 'DB',
            }
        }
    except ImportError:
        # Running outside Cloudflare Workers (CPython/Local emulation)
        D1_SQLITE_PATH = os.getenv('D1_SQLITE_PATH', str(BASE_DIR / 'd1_local.sqlite3'))
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': D1_SQLITE_PATH,
            }
        }
elif DB_ENGINE == 'sqlite3':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'poornima_achievements'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'root'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 600,
        }
    }

# Custom User Model & Layered RBAC
AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.InstitutionalRBACBackend',
    'django.contrib.auth.backends.ModelBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media & Storage Engine (Local / Cloudflare R2 Object Storage)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'r2').lower()

# Cloudflare Infrastructure Credentials (loaded strictly from environment, never from DB)
CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
CLOUDFLARE_R2_BUCKET = os.getenv('CLOUDFLARE_R2_BUCKET', 'poornima-achievements-r2')
CLOUDFLARE_R2_ACCESS_KEY_ID = os.getenv('CLOUDFLARE_R2_ACCESS_KEY_ID', '')
CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.getenv('CLOUDFLARE_R2_SECRET_ACCESS_KEY', '')
CLOUDFLARE_R2_PUBLIC_DOMAIN = os.getenv('CLOUDFLARE_R2_PUBLIC_DOMAIN', '')
CLOUDFLARE_D1_DATABASE_ID = os.getenv('CLOUDFLARE_D1_DATABASE_ID', '')
CLOUDFLARE_D1_API_TOKEN = os.getenv('CLOUDFLARE_D1_API_TOKEN', '')

if STORAGE_BACKEND == 'r2' and CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_R2_ACCESS_KEY_ID and CLOUDFLARE_R2_SECRET_ACCESS_KEY:
    custom_domain = CLOUDFLARE_R2_PUBLIC_DOMAIN.replace('https://', '').replace('http://', '').strip('/') if CLOUDFLARE_R2_PUBLIC_DOMAIN else None
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "access_key": CLOUDFLARE_R2_ACCESS_KEY_ID,
                "secret_key": CLOUDFLARE_R2_SECRET_ACCESS_KEY,
                "bucket_name": CLOUDFLARE_R2_BUCKET,
                "endpoint_url": f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com",
                "region_name": "auto",
                "default_acl": "private",
                "signature_version": "s3v4",
                "querystring_auth": True,
                "querystring_expire": 3600,
                "custom_domain": custom_domain,
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security Hardening & Safe Cookie Protection
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Authentication Routing
LOGIN_URL = '/admin/login/'
LOGIN_REDIRECT_URL = '/admin/'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.core.authentication.CsrfExemptSessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        'apps.tenants.permissions.IsTenantActive',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'apps.core.pagination.StandardCursorPagination',
    'PAGE_SIZE': 25,
}

# Unfold Admin Customization
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

UNFOLD = {
    "SITE_TITLE": "Poornima Faculty Achievements Portal",
    "SITE_HEADER": "Poornima University | Accreditation Console",
    "SITE_SUBHEADER": "NAAC AQAR Criteria 3 & NIRF Intelligence Hub",
    "SITE_URL": "/",
    "DASHBOARD_CALLBACK": "apps.core.dashboard.dashboard_callback",
    "ACCOUNT": {
        "navigation": [
            {
                "title": _("My Profile"),
                "icon": "account_circle",
                "link": "/profile/",
            },
        ],
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": _("My Workspace"),
                "separator": True,
                "items": [
                    {
                        "title": _("My Profile"),
                        "icon": "account_circle",
                        "link": "/profile/",
                    },
                ],
            },
            {
                "title": _("Accreditation & Metrics"),
                "separator": True,
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                    {
                        "title": _("Faculty Achievements"),
                        "icon": "workspace_premium",
                        "link": reverse_lazy("admin:activities_activity_changelist"),
                    },
                    {
                        "title": _("Proof Documents"),
                        "icon": "attachment",
                        "link": reverse_lazy("admin:documents_activitydocument_changelist"),
                    },
                    {
                        "title": _("Bulk Import (Excel / ZIP)"),
                        "icon": "upload_file",
                        "link": reverse_lazy("admin:activities_activity_bulk_import"),
                        "permission": "apps.core.dashboard.is_coordinator_or_above",
                    },
                    {
                        "title": _("NAAC Criteria 3 Export"),
                        "icon": "file_download",
                        "link": reverse_lazy("admin:activities_activity_export"),
                        "permission": "apps.core.dashboard.is_coordinator_or_above",
                    },
                ],
            },
            {
                "title": _("Institutional Structure & RBAC"),
                "separator": True,
                "items": [
                    {
                        "title": _("Users & Faculty"),
                        "icon": "person",
                        "link": reverse_lazy("admin:accounts_user_changelist"),
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": _("Departments"),
                        "icon": "apartment",
                        "link": reverse_lazy("admin:accounts_department_changelist"),
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": _("Designations"),
                        "icon": "badge",
                        "link": reverse_lazy("admin:accounts_designation_changelist"),
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": _("Academic Sessions"),
                        "icon": "date_range",
                        "link": reverse_lazy("admin:activities_academicsession_changelist"),
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": _("Roles & Permissions"),
                        "icon": "admin_panel_settings",
                        "link": reverse_lazy("admin:accounts_role_changelist"),
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                ],
            },
            {
                "title": _("Platform & Multi-Tenancy (Super Admin)"),
                "separator": True,
                "items": [
                    {
                        "title": _("Institutional Tenants"),
                        "icon": "domain",
                        "link": reverse_lazy("admin:tenants_tenant_changelist"),
                        "permission": "apps.core.dashboard.is_superuser_only",
                    },
                    {
                        "title": _("System Configuration"),
                        "icon": "settings_suggest",
                        "link": reverse_lazy("admin:core_systemconfiguration_changelist"),
                        "permission": "apps.core.dashboard.is_superuser_only",
                    },
                ],
            },
        ],
    },
}

# ==========================================
# Email & SMTP Notification Configuration
# ==========================================
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend' if os.getenv('EMAIL_HOST_USER') else 'django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 't')
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', os.getenv('EMAIL_HOST_USER', 'noreply@poornima.edu'))
SERVER_EMAIL = DEFAULT_FROM_EMAIL


