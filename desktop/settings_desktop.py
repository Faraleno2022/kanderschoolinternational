"""
Settings Django pour la version desktop offline (SQLite, localhost).
Importe tous les settings de base et surcharge uniquement ce qui change.
"""
import sys
import os
from pathlib import Path

# ── Importer TOUS les settings de base ──
from ecole_moderne.settings import *  # noqa: F401, F403

# ── Répertoire racine de l'application ──
if getattr(sys, 'frozen', False):
    # Exécution via PyInstaller
    APP_DIR = Path(sys.executable).resolve().parent
else:
    # Exécution en développement
    APP_DIR = Path(__file__).resolve().parent.parent

# ── Répertoire données utilisateur (PRÉSERVÉ lors des mises à jour) ──
DATA_DIR = APP_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)

# ── Base de données SQLite (offline) ──
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
    }
}

# ── Mode debug activé pour le serveur de dev ──
DEBUG = True

# ── Hôtes autorisés (localhost uniquement) ──
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8080',
    'http://localhost:8080',
]

# ── Sécurité relaxée pour localhost ──
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

# ── Fichiers statiques ──
STATIC_ROOT = APP_DIR / 'staticfiles'
STATICFILES_DIRS = [APP_DIR / 'static']
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# ── Fichiers média (dans le dossier data pour préservation) ──
MEDIA_ROOT = DATA_DIR / 'media'
(DATA_DIR / 'media').mkdir(exist_ok=True)

# ── Logs dans data/ ──
LOGS_DIR = DATA_DIR / 'logs'
os.makedirs(LOGS_DIR, exist_ok=True)
LOGGING['handlers']['file']['filename'] = str(LOGS_DIR / 'django.log')

# ── Désactiver les services externes (mode offline) ──
TWILIO_ENABLED = False
HF_TOKEN = ''

# ── Validation de mot de passe simplifiée pour usage local ──
AUTH_PASSWORD_VALIDATORS = []

# ── Clé secrète locale ──
from ecole_moderne.runtime_secret import load_or_create_secret

SECRET_KEY = load_or_create_secret(DATA_DIR / ".secret_key")

# ── Marquer le mode offline pour les templates ──
# Ajouter un context processor pour injecter is_offline=True
def _offline_context(request):
    return {'is_offline': True}

TEMPLATES[0]['OPTIONS']['context_processors'].append(
    'desktop.settings_desktop._offline_context'
)
