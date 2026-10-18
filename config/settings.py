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
cors_extra = [o.strip() for o in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
] + cors_extra

csrf_extra = [o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'https://*.vercel.app',
    'https://*.trycloudflare.com',
] + csrf_extra

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

# Database Configuration (DB_ENGINE from environment: 'd1' / 'sqlite3' or 'postgresql')
DB_ENGINE = os.getenv('DB_ENGINE', 'postgresql').lower()

if DB_ENGINE in ('d1', 'sqlite3', 'sqlite'):
    # Cloudflare D1 / SQLite Engine
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
        # Running outside Cloudflare Workers (CPython / Vercel / Local)
        if os.getenv('VERCEL'):
            tmp_db = '/tmp/db.sqlite3'
            bundled_db = BASE_DIR / 'db.sqlite3'
            if not os.path.exists(tmp_db) and bundled_db.exists():
                import shutil
                shutil.copyfile(str(bundled_db), tmp_db)
            sqlite_path = os.getenv('D1_SQLITE_PATH', tmp_db)
        else:
            sqlite_path = os.getenv('D1_SQLITE_PATH', str(BASE_DIR / 'db.sqlite3'))

        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': sqlite_path,
            }
        }
else:
    # PostgreSQL Configuration
    DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
    if DATABASE_URL:
        from urllib.parse import urlparse, parse_qs, unquote
        _url = urlparse(DATABASE_URL)
        _options = {}
        _query_params = parse_qs(_url.query)
        if 'sslmode' in _query_params:
            _options['sslmode'] = _query_params['sslmode'][0]
        elif os.getenv('DB_SSLMODE'):
            _options['sslmode'] = os.getenv('DB_SSLMODE')
        elif _url.hostname not in ('localhost', '127.0.0.1', None):
            _options['sslmode'] = 'require'

        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': _url.path.lstrip('/'),
                'USER': unquote(_url.username or ''),
                'PASSWORD': unquote(_url.password or ''),
                'HOST': _url.hostname,
                'PORT': str(_url.port or 5432),
                'CONN_MAX_AGE': int(os.getenv('CONN_MAX_AGE', '0' if os.getenv('VERCEL') else '600')),
                'OPTIONS': _options,
            }
        }
    else:
        _db_options = {}
        if os.getenv('DB_SSLMODE'):
            _db_options['sslmode'] = os.getenv('DB_SSLMODE')
        elif os.getenv('DB_HOST', 'localhost') not in ('localhost', '127.0.0.1'):
            _db_options['sslmode'] = 'require'

        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': os.getenv('DB_NAME', 'poornima_achievements'),
                'USER': os.getenv('DB_USER', 'postgres'),
                'PASSWORD': os.getenv('DB_PASSWORD', 'root'),
                'HOST': os.getenv('DB_HOST', 'localhost'),
                'PORT': os.getenv('DB_PORT', '5432'),
                'CONN_MAX_AGE': int(os.getenv('CONN_MAX_AGE', '0' if os.getenv('VERCEL') else '600')),
                'OPTIONS': _db_options,
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

# Media & Storage Engine (Local / Cloudflare R2 / AWS S3 Object Storage)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
PUBLIC_MEDIA_URL = os.getenv('PUBLIC_MEDIA_URL', MEDIA_URL)

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
elif STORAGE_BACKEND == 's3' and os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "access_key": os.getenv('AWS_ACCESS_KEY_ID'),
                "secret_key": os.getenv('AWS_SECRET_ACCESS_KEY'),
                "bucket_name": os.getenv('AWS_S3_BUCKET', 'faculty-achivements-data'),
                "region_name": os.getenv('AWS_REGION', 'ap-south-1'),
                "default_acl": "private",
                "signature_version": "s3v4",
                "querystring_auth": True,
                "querystring_expire": int(os.getenv('AWS_S3_PRESIGNED_EXPIRY', '3600')),
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

# Security Hardening & Safe Cookie Protection (Vercel & Cloudflare Edge Compatible)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
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
UNFOLD = {
    "SITE_TITLE": "Poornima Faculty Achievements Portal",
    "SITE_HEADER": "Poornima University | Accreditation Console",
    "SITE_SUBHEADER": "NAAC AQAR Criteria 3 & NIRF Intelligence Hub",
    "SITE_URL": "/",
    "DASHBOARD_CALLBACK": "apps.core.dashboard.dashboard_callback",
    "ACCOUNT": {
        "navigation": [
            {
                "title": "My Profile",
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
                "title": "My Workspace",
                "separator": True,
                "items": [
                    {
                        "title": "My Profile",
                        "icon": "account_circle",
                        "link": "/profile/",
                    },
                ],
            },
            {
                "title": "Accreditation & Metrics",
                "separator": True,
                "items": [
                    {
                        "title": "Dashboard",
                        "icon": "dashboard",
                        "link": "/admin/",
                    },
                    {
                        "title": "Faculty Achievements",
                        "icon": "workspace_premium",
                        "link": "/admin/activities/activity/",
                    },
                    {
                        "title": "Proof Documents",
                        "icon": "attachment",
                        "link": "/admin/documents/activitydocument/",
                    },
                    {
                        "title": "Bulk Import (Excel / ZIP)",
                        "icon": "upload_file",
                        "link": "/admin/activities/activity/bulk-import/",
                        "permission": "apps.core.dashboard.is_coordinator_or_above",
                    },
                    {
                        "title": "NAAC Criteria 3 Export",
                        "icon": "file_download",
                        "link": "/admin/activities/activity/export/",
                        "permission": "apps.core.dashboard.is_coordinator_or_above",
                    },
                ],
            },
            {
                "title": "Institutional Structure & RBAC",
                "separator": True,
                "items": [
                    {
                        "title": "Users & Faculty",
                        "icon": "person",
                        "link": "/admin/accounts/user/",
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": "Departments",
                        "icon": "apartment",
                        "link": "/admin/accounts/department/",
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": "Designations",
                        "icon": "badge",
                        "link": "/admin/accounts/designation/",
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": "Academic Sessions",
                        "icon": "date_range",
                        "link": "/admin/activities/academicsession/",
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                    {
                        "title": "Roles & Permissions",
                        "icon": "admin_panel_settings",
                        "link": "/admin/accounts/role/",
                        "permission": "apps.core.dashboard.is_admin_or_hod",
                    },
                ],
            },
            {
                "title": "Platform & Multi-Tenancy (Super Admin)",
                "separator": True,
                "items": [
                    {
                        "title": "Institutional Tenants",
                        "icon": "domain",
                        "link": "/admin/tenants/tenant/",
                        "permission": "apps.core.dashboard.is_superuser_only",
                    },
                    {
                        "title": "System Configuration",
                        "icon": "settings_suggest",
                        "link": "/admin/core/systemconfiguration/",
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


