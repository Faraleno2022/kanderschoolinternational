"""
Middleware de vérification de licence et d'intégrité — MySchoolGN
Bloque l'accès web si l'essai ou la licence est expiré,
ou si les fichiers de l'application ont été modifiés.
Cache de 5 minutes pour la performance (lecture fichier minimale).
"""
import time
from django.conf import settings
from django.http import HttpResponse
from django.contrib import messages


# ─── Cache en mémoire (évite une lecture de fichier à chaque requête) ─────────
_license_cache = {'valid': None, 'checked_at': 0, 'days_left': 0, 'trial': False}
_integrity_cache = {'valid': None, 'checked_at': 0, 'reason': ''}
_CACHE_TTL = 300   # 5 minutes
_INTEGRITY_TTL = 600  # 10 minutes


def _check_license_cached() -> dict:
    global _license_cache
    now = time.time()
    if now - _license_cache['checked_at'] > _CACHE_TTL or _license_cache['valid'] is None:
        try:
            import license_manager
            status = license_manager.check_license_or_trial()
            _license_cache = {
                'valid':      status.get('valid', False),
                'trial':      status.get('trial', False),
                'days_left':  status.get('days_left', 0),
                'checked_at': now,
            }
        except Exception:
            _license_cache = {'valid': True, 'trial': False,
                              'days_left': 999, 'checked_at': now}
    return _license_cache


# ─── Page de blocage intégrée ──────────────────────────────────────────────────
_BLOCKED_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MySchoolGN — Licence expirée</title>
<style>
  body {{ font-family: Arial, sans-serif; background: #1a3a5c;
          display: flex; align-items: center; justify-content: center;
          min-height: 100vh; margin: 0; }}
  .card {{ background: white; border-radius: 12px; padding: 48px 40px;
            max-width: 480px; width: 90%; text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3); }}
  h1 {{ color: #c0392b; font-size: 1.6rem; margin-bottom: 8px; }}
  .icon {{ font-size: 4rem; margin-bottom: 16px; }}
  p {{ color: #555; line-height: 1.6; }}
  .reason {{ background: #fdf2f2; border: 1px solid #f5c6cb; border-radius: 6px;
              padding: 12px 16px; color: #c0392b; font-weight: bold; margin: 20px 0; }}
  .contact {{ background: #eaf4fb; border-radius: 6px; padding: 12px 16px;
               color: #1a5276; margin-top: 16px; }}
  .btn {{ display: inline-block; margin-top: 20px; padding: 12px 28px;
           background: #1a3a5c; color: white; text-decoration: none;
           border-radius: 6px; font-weight: bold; }}
  .btn:hover {{ background: #0d2438; }}
  small {{ color: #aaa; display: block; margin-top: 20px; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x1F512;</div>
  <h1>Accès bloqué</h1>
  <p>Votre accès à <strong>MySchoolGN</strong> est suspendu.</p>
  <div class="reason">{reason}</div>
  <a href="/activer/" class="btn">&#x1F511; J'ai une clé — Activer ma licence</a>
  <div class="contact">
    Pour obtenir une licence, contactez l'administrateur :<br>
    <strong>FARA LENO AU +224622613559</strong>
  </div>
  <small>L'activation est immédiate dès saisie de la clé.</small>
</div>
</body>
</html>"""


def _check_integrity_cached() -> dict:
    global _integrity_cache
    now = time.time()
    if now - _integrity_cache['checked_at'] > _INTEGRITY_TTL or _integrity_cache['valid'] is None:
        try:
            import integrity_check
            result = integrity_check.verify()
            _integrity_cache = {
                'valid': result.get('valid', True),
                'reason': result.get('reason', ''),
                'checked_at': now,
            }
        except ImportError:
            _integrity_cache = {'valid': True, 'reason': 'dev_mode', 'checked_at': now}
        except Exception:
            _integrity_cache = {'valid': True, 'reason': '', 'checked_at': now}
    return _integrity_cache


# ─── Page de blocage intégrité ────────────────────────────────────────────────
_TAMPERED_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MySchoolGN — Application corrompue</title>
<style>
  body {{ font-family: Arial, sans-serif; background: #2c0b0e;
          display: flex; align-items: center; justify-content: center;
          min-height: 100vh; margin: 0; }}
  .card {{ background: white; border-radius: 12px; padding: 48px 40px;
            max-width: 480px; width: 90%; text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3); }}
  h1 {{ color: #c0392b; font-size: 1.6rem; margin-bottom: 8px; }}
  .icon {{ font-size: 4rem; margin-bottom: 16px; }}
  p {{ color: #555; line-height: 1.6; }}
  .reason {{ background: #fdf2f2; border: 1px solid #f5c6cb; border-radius: 6px;
              padding: 12px 16px; color: #c0392b; font-weight: bold; margin: 20px 0; }}
  .contact {{ background: #eaf4fb; border-radius: 6px; padding: 12px 16px;
               color: #1a5276; margin-top: 16px; }}
  small {{ color: #aaa; display: block; margin-top: 20px; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x1F6A8;</div>
  <h1>Application corrompue</h1>
  <p>Des fichiers de <strong>MySchoolGN</strong> ont été modifiés.<br>
     L'application ne peut pas fonctionner en toute sécurité.</p>
  <div class="reason">Modification non autorisée détectée</div>
  <div class="contact">
    Veuillez réinstaller l'application depuis le programme officiel<br>
    ou contactez l'administrateur <strong>FARA LENO AU +224622613559</strong>
  </div>
  <small>Code erreur : INTEGRITY_VIOLATION</small>
</div>
</body>
</html>"""


class LicenceMiddleware:
    """
    Vérifie la licence/essai et l'intégrité à chaque requête.
    Retourne une page 403 bloquante si expiré ou si fichiers modifiés.
    """

    EXEMPT_PREFIXES = (
        '/static/', '/media/', '/favicon', '/utilisateurs/login/',
        '/activer/', '/admin/', '/api/v1/license/', '/api/v1/sync/', '/rapport-scolaire/',
    )
    EXEMPT_EXACT = {
        '/',
        '/index/',
        '/robots.txt',
        '/sitemap.xml',
        '/fonctionnalites/',
        '/tarifs/',
        '/contact/',
        '/demo/',
        '/utilisateurs/login/',
        '/activer/',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Défense en profondeur : même si ce middleware était ajouté par une
        # ancienne configuration serveur, aucune vérification de licence ne doit
        # s'exécuter sur le site web de production.
        if not getattr(settings, 'LICENCE_ENFORCEMENT_ENABLED', False):
            return self.get_response(request)

        path = request.path

        # Ressources statiques et login toujours accessibles
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return self.get_response(request)
        if path in self.EXEMPT_EXACT:
            return self.get_response(request)

        # Vérification intégrité (avec cache 10 min)
        integrity = _check_integrity_cached()
        if not integrity['valid']:
            return HttpResponse(
                _TAMPERED_HTML, status=403,
                content_type='text/html; charset=utf-8'
            )

        # Vérification licence (avec cache 5 min)
        status = _check_license_cached()

        if not status['valid']:
            if status.get('trial'):
                reason = "Votre période d'essai gratuit de 30 jours est expirée."
            else:
                reason = "Votre licence a expiré ou est invalide."
            html = _BLOCKED_HTML.format(reason=reason)
            return HttpResponse(html, status=403, content_type='text/html; charset=utf-8')

        # Rappel dans les 7 derniers jours
        if status.get('days_left', 999) <= 7:
            session_key = '_myschool_lic_warn'
            if not request.session.get(session_key):
                messages.warning(
                    request,
                    f"Votre {'essai' if status.get('trial') else 'licence'} "
                    f"expire dans {status['days_left']} jour(s). "
                    "Contactez l'administrateur FARA LENO AU +224622613559."
                )
                request.session[session_key] = True

        return self.get_response(request)
