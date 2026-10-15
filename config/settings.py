"""
Paymino backend settings. Everything environment-specific comes from env vars (see .env.example).
"""
import os
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path):
    """Tiny .env loader (no extra dependency). Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / '.env')


def env(key, default=''):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return env(key, str(default)).lower() in ('1', 'true', 'yes', 'on')


def env_list(key, default=''):
    return [x.strip() for x in env(key, default).split(',') if x.strip()]


DEBUG = env_bool('DEBUG', False)
SECRET_KEY = env('SECRET_KEY') or ('dev-insecure-secret-key-change-me' if DEBUG else '')
if not SECRET_KEY:
    raise RuntimeError('SECRET_KEY must be set when DEBUG is off.')

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')

# Public URLs
FRONTEND_URL = env('FRONTEND_URL', 'http://localhost:3000').rstrip('/')
API_PUBLIC_URL = env('API_PUBLIC_URL', 'http://localhost:8000').rstrip('/')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'core',
    'accounts',
    'catalog',
    'payments',
    'orders',
    'support',
    'adminapi',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'core.middleware.ApiOriginCheckMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


def _database_from_url(url: str):
    u = urlparse(url)
    if u.scheme in ('sqlite', 'sqlite3'):
        return {'ENGINE': 'django.db.backends.sqlite3', 'NAME': u.path.lstrip('/') or str(BASE_DIR / 'db.sqlite3')}
    if u.scheme in ('postgres', 'postgresql', 'pgsql'):
        return {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': u.path.lstrip('/'),
            'USER': unquote(u.username or ''),
            'PASSWORD': unquote(u.password or ''),
            'HOST': u.hostname or '',
            'PORT': str(u.port or ''),
            'CONN_MAX_AGE': 60,
        }
    raise RuntimeError(f'Unsupported DATABASE_URL scheme: {u.scheme}')


DATABASES = {'default': _database_from_url(env('DATABASE_URL', 'postgres://paymino:paymino@localhost:5432/paymino'))}

AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = []  # Persian validation lives in accounts.validators

LANGUAGE_CODE = 'fa'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(env('MEDIA_ROOT', str(BASE_DIR / 'media')))
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ------------------------------- Sessions -------------------------------
SESSION_COOKIE_NAME = 'pm_session'
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
SESSION_COOKIE_DOMAIN = env('SESSION_COOKIE_DOMAIN') or None  # e.g. .paymino.ir to share between site and api
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', API_PUBLIC_URL)  # for /django-admin/

# ------------------------------- CORS / origins -------------------------------
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', FRONTEND_URL)
CORS_ALLOW_CREDENTIALS = True
CORS_URLS_REGEX = r'^/api/.*$'
CORS_ALLOW_HEADERS = ['accept', 'content-type', 'idempotency-key', 'x-requested-with']
# Browser-origin check for state-changing API calls (replaces CSRF tokens for the cookie-based API)
API_ALLOWED_ORIGINS = set(CORS_ALLOWED_ORIGINS + [FRONTEND_URL, API_PUBLIC_URL])
# Development: accept the frontend on any local host/port (localhost:3000, 127.0.0.1:3001, ...)
LOCAL_ORIGIN_REGEX = r'^http://(localhost|127\.0\.0\.1)(:\d+)?$'
CORS_ALLOWED_ORIGIN_REGEXES = [LOCAL_ORIGIN_REGEX] if DEBUG else []
API_ALLOWED_ORIGIN_REGEX = LOCAL_ORIGIN_REGEX if DEBUG else None
TRUST_X_FORWARDED_FOR = env_bool('TRUST_X_FORWARDED_FOR', False)
if env_bool('BEHIND_PROXY', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ------------------------------- DRF -------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['core.auth.CookieSessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
    'EXCEPTION_HANDLER': 'core.errors.exception_handler',
    'UNAUTHENTICATED_USER': 'django.contrib.auth.models.AnonymousUser',
}

# ------------------------------- Cache (throttling) -------------------------------
REDIS_URL = env('REDIS_URL')
if REDIS_URL:
    _cache = {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}
elif DEBUG:
    _cache = {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}  # dev: no setup needed
else:
    # production without Redis: run `python manage.py createcachetable` once
    _cache = {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'paymino_cache'}
CACHES = {'default': _cache}

# ------------------------------- Email -------------------------------
EMAIL_BACKEND = env('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST')
EMAIL_PORT = int(env('EMAIL_PORT', '587'))
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', 'Paymino <no-reply@paymino.ir>')

PASSWORD_RESET_TIMEOUT = 30 * 60

# ------------------------------- Payments -------------------------------
# sandbox = fake invoices + dev simulator (never payable). plisio = real gateway.
PAYMENT_PROVIDER = env('PAYMENT_PROVIDER', 'sandbox')
SANDBOX_WEBHOOK_SECRET = env('SANDBOX_WEBHOOK_SECRET', 'dev-only-webhook-secret')
PLISIO_SECRET_KEY = env('PLISIO_SECRET_KEY')
PLISIO_API_BASE = env('PLISIO_API_BASE', 'https://api.plisio.net/api/v1')
# Lazy-expire real-gateway invoices only after this grace period (gateway's own expiry callback normally arrives first)
PLISIO_EXPIRY_GRACE_MINUTES = int(env('PLISIO_EXPIRY_GRACE_MINUTES', '60'))

if PAYMENT_PROVIDER == 'plisio' and not PLISIO_SECRET_KEY:
    raise RuntimeError('PLISIO_SECRET_KEY must be set when PAYMENT_PROVIDER=plisio.')
if not DEBUG and PAYMENT_PROVIDER == 'sandbox' and not env_bool('ALLOW_SANDBOX_IN_PRODUCTION', False):
    raise RuntimeError('PAYMENT_PROVIDER=sandbox is not allowed with DEBUG off.')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
APPEND_SLASH = False