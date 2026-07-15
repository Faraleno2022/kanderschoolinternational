"""
Django settings for ecole_moderne project.
"""

from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# =================== Base ===================
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_plain_env(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


def _env_list(name):
    return [value.strip() for value in os.environ.get(name, '').split(',') if value.strip()]


RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip()

# Charger .env si disponible
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")
else:
    _load_plain_env(BASE_DIR / ".env")

# =================== Clés et debug ===================
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-unsafe-key')
DEBUG_DEFAULT = 'false' if RENDER_EXTERNAL_HOSTNAME else 'true'
DEBUG = os.environ.get('DJANGO_DEBUG', DEBUG_DEFAULT).lower() == 'true'

# =================== Hôtes et CSRF ===================
if DEBUG:
    ALLOWED_HOSTS = ['*']  # Accepter tous les hôtes en développement
    CSRF_TRUSTED_ORIGINS = [
        'http://127.0.0.1:8000',
        'http://127.0.0.1:8001',
        'http://localhost:8000',
        'http://localhost:8001',
        'http://127.0.0.1:50148',
        'http://localhost:50148',
        'https://127.0.0.1:8000',
        'https://127.0.0.1:8001',
        'https://localhost:8000',
        'https://localhost:8001',
        'https://myschoolgn.space',
        'https://www.myschoolgn.space',
    ]
else:
    ALLOWED_HOSTS = [
        'gshadjakanfingdiane.pythonanywhere.com',
        'myschoolgn.pythonanywhere.com',
        'myschoolgn.space',
        'www.myschoolgn.space',
        'myschool-rn3d.onrender.com',
        'webapp-3123625.pythonanywhere.com',
        'kinderschoolinternational.com',
        'www.kinderschoolinternational.com',
    ] + _env_list('DJANGO_ALLOWED_HOSTS')
    if RENDER_EXTERNAL_HOSTNAME:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

    CSRF_TRUSTED_ORIGINS = [
        'https://gshadjakanfingdiane.pythonanywhere.com',
        'https://myschoolgn.pythonanywhere.com',
        'https://myschoolgn.space',
        'https://www.myschoolgn.space',
        'https://myschool-rn3d.onrender.com',
        'https://webapp-3123625.pythonanywhere.com',
        'https://kinderschoolinternational.com',
        'https://www.kinderschoolinternational.com',
    ] + _env_list('DJANGO_CSRF_TRUSTED_ORIGINS')
    if RENDER_EXTERNAL_HOSTNAME:
        CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')

# =================== Sécurité ===================
# Désactivé pour développement local
if DEBUG:
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    SECURE_CONTENT_TYPE_NOSNIFF = False
    SECURE_BROWSER_XSS_FILTER = False
    X_FRAME_OPTIONS = 'SAMEORIGIN'
    SECURE_REFERRER_POLICY = 'no-referrer-when-downgrade'
    
    CSRF_COOKIE_HTTPONLY = False
    SESSION_COOKIE_HTTPONLY = False
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'
    SESSION_EXPIRE_AT_BROWSER_CLOSE = False
    
    SECURE_PROXY_SSL_HEADER = None
    USE_X_FORWARDED_HOST = False
else:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    
    CSRF_COOKIE_HTTPONLY = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    CSRF_COOKIE_SAMESITE = 'Strict'
    SESSION_EXPIRE_AT_BROWSER_CLOSE = True
    
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True

# =================== Applications ===================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Applications de gestion scolaire
    'eleves',
    'paiements',
    'depenses',
    'salaires',
    'utilisateurs',
    'rapports',
    'administration',
    'bus',
    'notes',
    'abonnements',
    'synchronisation.apps.SynchronisationConfig',
    'axes',
]

# =================== Middleware ===================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Application stricte des permissions de menus (Profil.allowed_menus)
    'utilisateurs.middleware.MenuAccessMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Vérification licence : bloque l'accès web si essai/licence expiré
    'ecole_moderne.licence_middleware.LicenceMiddleware',
    # Protection anti brute-force
    'axes.middleware.AxesMiddleware',
]

# Ajouter middlewares d'optimisation images
if DEBUG:
    MIDDLEWARE += [
        'ecole_moderne.image_cache_middleware.ImageCacheMiddleware',
        'ecole_moderne.image_optimization_middleware.ImageOptimizationMiddleware',
    ]
else:
    MIDDLEWARE.append('ecole_moderne.image_optimization_middleware.ImageOptimizationMiddleware')
    MIDDLEWARE.insert(1, 'ecole_moderne.security_middleware.SecurityMiddleware')
    MIDDLEWARE.insert(3, 'ecole_moderne.security_middleware.SessionSecurityMiddleware')
    MIDDLEWARE.insert(5, 'ecole_moderne.security_middleware.CSRFSecurityMiddleware')
    MIDDLEWARE.append('ecole_moderne.security_middleware.CSPMiddleware')

# =================== Authentication Backends ===================
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# =================== Django-Axes (anti brute-force) ===================
from datetime import timedelta as _td_axes
AXES_FAILURE_LIMIT = 10             # Bloquer après 10 tentatives échouées
AXES_COOLOFF_TIME = _td_axes(minutes=30)  # Débloquer après 30 minutes (anti-verrouillage permanent)
AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']  # Bloquer par utilisateur + IP
AXES_RESET_ON_SUCCESS = True        # Réinitialiser le compteur après un login réussi
AXES_ENABLE_ADMIN = True            # Voir les tentatives dans l'admin Django
AXES_LOCKOUT_URL = '/utilisateurs/login/'  # Rediriger vers le login après blocage
AXES_LOCKOUT_TEMPLATE = 'utilisateurs/locked_out.html'
AXES_SENSITIVE_PARAMETERS = ['password']
# =================== URL admin personnalisable ===================
# Par defaut 'admin/'. En production, definir DJANGO_ADMIN_URL dans le .env
# (ex: DJANGO_ADMIN_URL=gestion-secrete-2026/) pour masquer l'admin aux robots.
# Le secret ne doit JAMAIS etre commite dans ce fichier (depot public).
ADMIN_URL_PATH = os.environ.get('DJANGO_ADMIN_URL', 'admin/').strip('/') + '/'

# Ne surveiller QUE les pages de login (ne pas bloquer les autres POST publics)
import re as _re
AXES_URL_REGEX = _re.compile(
    r'^/(utilisateurs/login|' + _re.escape(ADMIN_URL_PATH.rstrip('/')) + r'/login)/$'
)

# =================== Whitelist IP pour /admin/ (optionnelle) ===================
# Vide par defaut = aucune restriction supplementaire (comportement actuel inchange).
# Pour activer: definir la variable d'environnement ADMIN_WHITELIST_IPS avec une
# liste d'IP separees par des virgules (ex: "41.85.12.34,102.10.5.6").
ADMIN_WHITELIST_IPS = _env_list('ADMIN_WHITELIST_IPS')

ROOT_URLCONF = 'ecole_moderne.urls'

# =================== Annee scolaire ===================
# La nouvelle annee est proposee automatiquement apres cette date.
# Par defaut : 30 juin de l'annee de fin (ex: 2025-2026 -> 30/06/2026).
ANNEE_SCOLAIRE_FIN_MOIS = int(os.environ.get('ANNEE_SCOLAIRE_FIN_MOIS', '6'))
ANNEE_SCOLAIRE_FIN_JOUR = int(os.environ.get('ANNEE_SCOLAIRE_FIN_JOUR', '30'))

# =================== Templates ===================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'utilisateurs.context_processors.user_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'ecole_moderne.wsgi.application'

# =================== Base de données ===================

if DEBUG or not os.environ.get('DJANGO_DB_NAME'):
    # Utiliser SQLite en développement local
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    # Utiliser MySQL sur PythonAnywhere en production
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DJANGO_DB_NAME", "myschoolgn$myschooldb"),
            "USER": os.environ.get("DJANGO_DB_USER", "myschoolgn"),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ.get("DJANGO_DB_HOST", "myschoolgn.mysql.pythonanywhere-services.com"),
            "PORT": os.environ.get("DJANGO_DB_PORT", "3306"),
            "OPTIONS": {
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
                "charset": "utf8mb4",
                "connect_timeout": 10,      # Timeout connexion initiale
                "read_timeout": 30,         # Timeout lecture requête
                "write_timeout": 30,        # Timeout écriture
            },
            # PythonAnywhere MySQL wait_timeout = 300s → on reste sous ce seuil
            "CONN_MAX_AGE": 270,
        }
    }

# =================== Cache (vitesse maximale) ===================
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "myschool-cache-v1",
        "OPTIONS": {
            "MAX_ENTRIES": 2000,        # Nombre max d'entrées en mémoire
            "CULL_FREQUENCY": 4,        # Supprime 1/4 du cache quand MAX_ENTRIES atteint
        },
        "TIMEOUT": 600,                 # 10 minutes par défaut
    }
}

# Sessions stockées en DB + cache (1 requête DB au lieu de 2 par session)
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_AGE = 86400 * 7   # 7 jours (évite reconnexions fréquentes)

# =================== Auth & mots de passe ===================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = '/utilisateurs/login/'
LOGIN_REDIRECT_URL = '/eleves/'
LOGOUT_REDIRECT_URL = '/utilisateurs/login/'

# =================== Internationalisation ===================
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Conakry'
USE_I18N = True
USE_TZ = True

USE_THOUSAND_SEPARATOR = False
THOUSAND_SEPARATOR = ' '
NUMBER_GROUPING = 3
DEFAULT_CURRENCY = 'GNF'
DEFAULT_COUNTRY_CODE = '+224'

# =================== Static & Media ===================
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

if DEBUG:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# =================== Logging ===================
LOGS_DIR = BASE_DIR / 'logs'
os.makedirs(LOGS_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'}},
    'handlers': {
        'file': {'level': 'INFO', 'class': 'logging.FileHandler', 'filename': LOGS_DIR / 'django.log', 'formatter': 'verbose'},
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'},
    },
    'loggers': {
        'django.request': {'handlers': ['file', 'console'], 'level': 'ERROR', 'propagate': True},
    },
    'root': {'handlers': ['console', 'file'], 'level': 'INFO'},
}

# =================== Uploads ===================
# Les fichiers de plus de 5 Mo sont écrits temporairement sur disque afin de
# préserver la mémoire. La requête accepte jusqu'à 20 Mo pour permettre
# l'envoi d'une image de 15 Mo avec l'enveloppe multipart du formulaire.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

# =================== Intégrations externes ===================
TWILIO_ENABLED = os.getenv("TWILIO_ENABLED", "false").lower() in {"1", "true", "yes"}
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
PHONE_VERIFY_TTL_SECONDS = int(os.environ.get('PHONE_VERIFY_TTL_SECONDS', 4 * 3600))

# =================== Synchronisation offline/online ===================
MYSCHOOL_SYNC_SERVER_URL = os.environ.get('MYSCHOOL_SYNC_SERVER_URL', '').rstrip('/')
MYSCHOOL_SYNC_DEVICE_ID = os.environ.get('MYSCHOOL_SYNC_DEVICE_ID', '')
MYSCHOOL_SYNC_TOKEN = os.environ.get('MYSCHOOL_SYNC_TOKEN', '')
MYSCHOOL_SYNC_ADMIN_TOKEN = os.environ.get('MYSCHOOL_SYNC_ADMIN_TOKEN', '')
MYSCHOOL_SYNC_ECOLE_ID = os.environ.get('MYSCHOOL_SYNC_ECOLE_ID', '')

# =================== Configuration IA Chatbot ===================
# Token HuggingFace pour l'API IA (obtenir sur https://huggingface.co/settings/tokens)
HF_TOKEN = os.environ.get('HF_TOKEN', '')
# Modèle à utiliser (DeepSeek via HuggingFace Router)
HF_MODEL = os.environ.get('HF_MODEL', 'deepseek-ai/DeepSeek-R1')

# =================== Paramètres de sécurité ===================
BLOCK_SUPERUSER_PUBLIC_LOGIN = False
ADMIN_WHITELIST_IPS = [ip.strip() for ip in os.environ.get('ADMIN_WHITELIST_IPS', '').split(',') if ip.strip()]
MAX_CONNECTIONS_PER_IP = 10
IP_BLOCK_DURATION = 86400
MAX_LOGIN_ATTEMPTS = 5
LOGIN_BLOCK_DURATION = 300

# Code de vérification pour les suppressions et déverrouillages critiques.
# IMPORTANT : Définir via variable d'environnement, ne JAMAIS hardcoder dans le code source.
SECURITY_VERIFICATION_CODE = os.environ.get('SECURITY_VERIFICATION_CODE', '')
