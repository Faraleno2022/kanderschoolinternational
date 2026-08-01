"""
Vues sécurisées pour l'authentification avec protection contre les attaques
"""
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.translation import gettext as _
from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.views.generic import View
from django.db import OperationalError, transaction, connection
import logging
import time
from datetime import datetime, timedelta
from django.urls import reverse

logger = logging.getLogger(__name__)

# ====== Paramètres de sécurité login ======
# Nombre max de tentatives avant blocage
MAX_LOGIN_ATTEMPTS = 3
# Durée de blocage en secondes (30 minutes)
BLOCK_DURATION_SECONDS = 1800
# Message personnalisé demandé par le client
LOCKOUT_MESSAGE = (
    "Trop de tentatives de connexion. Contactez l'administrateur FARA LENO AU +224622613559."
)

def get_client_ip(request):
    """Obtient l'adresse IP réelle du client"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def is_ip_blocked(ip, username=None):
    """Vérifie si une IP ou un couple IP+username est bloqué."""
    # Blocage global IP
    if cache.get(f"blocked_login_{ip}", False):
        return True
    # Blocage ciblé IP+username
    if username:
        return cache.get(f"blocked_login_{ip}_{username.lower()}", False)
    return False

def block_ip(ip, duration=300):
    """Bloque une IP pour une durée donnée (helper rétro-compatible)."""
    cache_key = f"blocked_login_{ip}"
    cache.set(cache_key, True, duration)
    logger.warning(f"IP {ip} bloquée pour tentatives de connexion répétées")

def block_ip_username(ip, username, duration=900):
    """Bloque un couple IP+username pour une durée donnée (par défaut 15 min)."""
    if not username:
        return block_ip(ip, duration)
    cache_key = f"blocked_login_{ip}_{username.lower()}"
    cache.set(cache_key, True, duration)
    logger.warning(f"Blocage IP+username activé: {ip} / {username}")

def get_failed_attempts(ip, username=None):
    """Obtient le nombre de tentatives échouées pour une IP ou IP+username."""
    if username:
        key = f"failed_login_{ip}_{username.lower()}"
    else:
        key = f"failed_login_{ip}"
    return cache.get(key, 0)

def increment_failed_attempts(ip, username=None, ttl=900):
    """Incrémente le compteur de tentatives échouées (IP+username si fourni)."""
    if username:
        cache_key = f"failed_login_{ip}_{username.lower()}"
    else:
        cache_key = f"failed_login_{ip}"
    attempts = cache.get(cache_key, 0) + 1
    cache.set(cache_key, attempts, ttl)  # TTL des tentatives
    return attempts

def reset_failed_attempts(ip, username=None):
    """Remet à zéro le compteur de tentatives échouées (IP+username si fourni)."""
    if username:
        cache.delete(f"failed_login_{ip}_{username.lower()}")
    cache.delete(f"failed_login_{ip}")

@ensure_csrf_cookie
@csrf_protect
@never_cache
def secure_login(request):
    """
    Vue de connexion sécurisée avec protection contre la force brute
    """
    client_ip = get_client_ip(request)
    
    # Vérifier si l'IP est bloquée (pré-POST)
    if is_ip_blocked(client_ip):
        logger.warning(f"Tentative de connexion depuis IP bloquée: {client_ip}")
        unlock_qs = f"?ip={client_ip}"
        return render(request, 'utilisateurs/locked_out.html', {
            'error': LOCKOUT_MESSAGE,
            'unlock_path': reverse('utilisateurs:admin_verify') + unlock_qs,
        })
    
    # Ne jamais utiliser un next qui pointe vers /admin/* pour des utilisateurs publics
    unsafe_next = request.GET.get('next') or ''
    if unsafe_next.startswith('/admin/'):
        # Cas spécifique demandé: /login/?next=/admin/password_reset/
        if unsafe_next.startswith('/admin/password_reset'):
            return render(request, 'utilisateurs/login.html', {
                'error': "Contactez l'administrateur FARA LENO AU +224622613559.",
                'blocked': True,
            })
        # Pour toute autre cible admin, on ignore simplement et n'expose pas cette destination
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        # Validation basique
        if not username or not password:
            messages.error(request, 'Nom d\'utilisateur et mot de passe requis.')
            return render(request, 'utilisateurs/login.html')
        
        # Limiter la longueur des champs pour éviter les attaques DoS
        if len(username) > 150 or len(password) > 128:
            logger.warning(f"Tentative de connexion avec champs trop longs depuis IP: {client_ip}")
            messages.error(request, 'Données invalides.')
            return render(request, 'utilisateurs/login.html')

        # Interdire la connexion aux comptes administrateurs (superuser) via cette page
        # sauf si désactivé via settings.BLOCK_SUPERUSER_PUBLIC_LOGIN=False,
        # en mode DEBUG (développement local), ou si l'admin a été vérifié via admin_verify
        admin_verified_session = bool(request.session.get('admin_verified'))
        if getattr(settings, 'BLOCK_SUPERUSER_PUBLIC_LOGIN', True) and not settings.DEBUG and not admin_verified_session:
            try:
                UserModel = get_user_model()
                target_user = UserModel.objects.filter(username__iexact=username).only('is_superuser').first()
            except Exception:
                target_user = None
            if target_user and getattr(target_user, 'is_superuser', False):
                logger.warning(f"Tentative de connexion sur compte administrateur refusée: {username} depuis IP: {client_ip}")
                # Incrémenter quand même le compteur pour éviter brute-force sur admin
                attempts = increment_failed_attempts(client_ip, username=username, ttl=BLOCK_DURATION_SECONDS)
                if attempts >= MAX_LOGIN_ATTEMPTS:
                    block_ip_username(client_ip, username, duration=BLOCK_DURATION_SECONDS)
                messages.error(request, LOCKOUT_MESSAGE)
                return render(request, 'utilisateurs/login.html')

        # Vérifier un éventuel blocage ciblé IP+username
        if is_ip_blocked(client_ip, username=username):
            logger.warning(f"Tentative de connexion depuis IP+username bloqués: {client_ip} / {username}")
            unlock_qs = f"?ip={client_ip}&username={username}"
            return render(request, 'utilisateurs/locked_out.html', {
                'error': LOCKOUT_MESSAGE,
                'unlock_path': reverse('utilisateurs:admin_verify') + unlock_qs,
            })

        # Authentification
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if user.is_active:
                # Vérifier si le profil utilisateur est validé par l'administrateur
                profil = getattr(user, 'profil', None)
                if profil and not profil.is_validated and not user.is_superuser:
                    messages.error(request, 'Votre compte est en attente de validation par un administrateur. Vous serez notifié par email dès validation.')
                    logger.warning(f"Tentative de connexion sur compte non validé: {username} depuis IP: {client_ip}")
                    return render(request, 'utilisateurs/login.html')
                
                # Connexion réussie
                login(request, user)
                reset_failed_attempts(client_ip, username=username)
                # Nettoyer le flag de vérification admin pour ne pas le conserver au-delà de la connexion
                try:
                    request.session['admin_verified'] = False
                except Exception:
                    pass
                
                # Log de connexion réussie
                logger.info(f"Connexion réussie: {username} depuis IP: {client_ip}")
                
                # Redirection sécurisée
                next_url = request.GET.get('next')
                # Ignorer toute redirection vers /admin/*
                if next_url and next_url.startswith('/') and not next_url.startswith('/admin/'):
                    return redirect(next_url)
                return redirect('eleves:liste_eleves')
            else:
                messages.error(request, 'Compte désactivé.')
                logger.warning(f"Tentative de connexion sur compte désactivé: {username} depuis IP: {client_ip}")
        else:
            # Échec de connexion
            attempts = increment_failed_attempts(client_ip, username=username, ttl=900)

            logger.warning(f"Échec de connexion: {username} depuis IP: {client_ip} (tentative {attempts})")

            # Bloquer après le nombre maximum de tentatives
            if attempts >= MAX_LOGIN_ATTEMPTS:
                block_ip_username(client_ip, username, duration=BLOCK_DURATION_SECONDS)
                messages.error(request, LOCKOUT_MESSAGE)
                # Afficher la page de verrouillage qui tente de fermer la fenêtre
                unlock_qs = f"?ip={client_ip}&username={username}"
                return render(request, 'utilisateurs/locked_out.html', {
                    'error': LOCKOUT_MESSAGE,
                    'unlock_path': reverse('utilisateurs:admin_verify') + unlock_qs,
                })
            else:
                # Message discret sans indiquer le nombre restant
                messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
    
    return render(request, 'utilisateurs/login.html')

@login_required
def secure_logout(request):
    """
    Déconnexion sécurisée avec nettoyage de session
    """
    username = request.user.username
    client_ip = get_client_ip(request)
    
    # Log de déconnexion
    logger.info(f"Déconnexion: {username} depuis IP: {client_ip}")
    
    # Déconnexion et nettoyage de session
    logout(request)
    request.session.flush()
    
    messages.success(request, 'Vous avez été déconnecté avec succès.')
    return redirect('utilisateurs:login')

@ensure_csrf_cookie
@csrf_protect
@never_cache
def admin_verify(request):
    """
    Affiche un formulaire public demandant le code administrateur. Tant que le code correct
    n'est pas saisi (défini via SECURITY_VERIFICATION_CODE dans .env), le formulaire de
    connexion ne sera pas affiché (redirigé ici).
    Quand le code est bon, marque la session comme vérifiée et retourne vers la page login.
    """
    # Pré-remplir IP/username depuis la query
    ip_q = (request.GET.get('ip') or '').strip()
    username_q = (request.GET.get('username') or '').strip()

    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()
        # Récupérer ip/username depuis POST si fournis
        ip_p = (request.POST.get('ip') or '').strip()
        username_p = (request.POST.get('username') or '').strip().lower()
        ip_val = ip_p or ip_q
        username_val = username_p or username_q

        from django.conf import settings as django_settings
        expected_code = django_settings.SECURITY_VERIFICATION_CODE
        if expected_code and code == expected_code:
            # Nettoyer les verrous pour ip/username si disponibles
            cleared = 0
            try:
                keys = []
                if ip_val and username_val:
                    keys = [
                        f'failed_login_{ip_val}',
                        f'failed_login_{ip_val}_{username_val}',
                        f'blocked_login_{ip_val}',
                        f'blocked_login_{ip_val}_{username_val}',
                    ]
                elif ip_val:
                    keys = [
                        f'failed_login_{ip_val}',
                        f'blocked_login_{ip_val}',
                    ]
                elif username_val:
                    try:
                        for k in list(getattr(cache, '_cache', {}).keys()):
                            if isinstance(k, str) and (k.endswith(f'_{username_val}') or k.startswith('failed_login_') or k.startswith('blocked_login_')):
                                keys.append(k)
                    except Exception:
                        pass
                for k in set(keys):
                    try:
                        if cache.get(k) is not None:
                            cache.delete(k)
                            cleared += 1
                    except Exception:
                        pass
            except Exception:
                pass

            # Marquer la session comme vérifiée et retourner au login
            request.session['admin_verified'] = True
            messages.success(request, "Vérification administrateur réussie. Vous pouvez vous connecter.")
            return redirect('utilisateurs:login')
        else:
            messages.error(request, "Code de vérification invalide. Veuillez réessayer.")
            # Repasser ip/username au template pour conservations des champs cachés
            return render(request, 'utilisateurs/admin_verify.html', {
                'ip': ip_q,
                'username': username_q,
            })

    return render(request, 'utilisateurs/admin_verify.html', {
        'ip': ip_q,
        'username': username_q,
    })

@method_decorator([csrf_protect, never_cache], name='dispatch')
class SecurePasswordChangeView(View):
    """
    Vue sécurisée pour changer le mot de passe
    """
    
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('utilisateurs:login')
        
        return render(request, 'utilisateurs/change_password.html')
    
    def post(self, request):
        if not request.user.is_authenticated:
            return redirect('utilisateurs:login')
        
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        # Validation
        if not all([current_password, new_password, confirm_password]):
            messages.error(request, 'Tous les champs sont requis.')
            return render(request, 'utilisateurs/change_password.html')
        
        if new_password != confirm_password:
            messages.error(request, 'Les nouveaux mots de passe ne correspondent pas.')
            return render(request, 'utilisateurs/change_password.html')
        
        if len(new_password) < 12:
            messages.error(request, 'Le mot de passe doit contenir au moins 12 caractères.')
            return render(request, 'utilisateurs/change_password.html')
        
        # Vérifier le mot de passe actuel
        if not request.user.check_password(current_password):
            client_ip = get_client_ip(request)
            logger.warning(f"Tentative de changement de mot de passe avec mauvais mot de passe actuel: {request.user.username} depuis IP: {client_ip}")
            messages.error(request, 'Mot de passe actuel incorrect.')
            return render(request, 'utilisateurs/change_password.html')
        
        # Changer le mot de passe avec retries pour éviter les verrous SQLite
        last_error = None
        for attempt in range(3):
            try:
                with transaction.atomic():
                    request.user.set_password(new_password)
                    request.user.save()
                last_error = None
                break
            except OperationalError as e:
                last_error = e
                # Retente uniquement si c'est un verrou SQLite
                if 'locked' in str(e).lower() or 'database is locked' in str(e).lower():
                    # Fermer la connexion et attendre un peu avant de retenter
                    try:
                        connection.close()
                    except Exception:
                        pass
                    time.sleep(1 + attempt)
                    continue
                else:
                    break
        if last_error:
            logger.error(f"Erreur lors de l'enregistrement du nouveau mot de passe pour {request.user.username}: {last_error}")
            messages.error(request, "Impossible d'enregistrer le nouveau mot de passe pour le moment. Veuillez réessayer.")
            return render(request, 'utilisateurs/change_password.html')
        
        # Log du changement
        client_ip = get_client_ip(request)
        logger.info(f"Changement de mot de passe réussi: {request.user.username} depuis IP: {client_ip}")
        
        messages.success(request, 'Mot de passe changé avec succès. Veuillez vous reconnecter.')
        
        # Déconnecter l'utilisateur pour qu'il se reconnecte
        logout(request)
        return redirect('utilisateurs:login')

def security_dashboard(request):
    """
    Tableau de bord de sécurité pour les administrateurs
    """
    if not request.user.is_staff:
        return HttpResponseForbidden("Accès réservé aux administrateurs.")
    
    # Statistiques de sécurité
    stats = {
        'blocked_ips': len([key for key in cache._cache.keys() if key.startswith('blocked_')]),
        'failed_attempts': len([key for key in cache._cache.keys() if key.startswith('failed_login_')]),
        'active_sessions': len([key for key in cache._cache.keys() if key.startswith('session_')]),
    }
    
    is_locked = cache.get('SYSTEM_LOCKED', False)
    remaining_seconds = 0
    try:
        if is_locked:
            until_ts = cache.get('SYSTEM_LOCKED_UNTIL')
            if until_ts:
                import time as _t
                remaining_seconds = max(0, int(float(until_ts) - _t.time()))
    except Exception:
        remaining_seconds = 0
    return render(request, 'administration/security_dashboard.html', {
        'stats': stats,
        'is_locked': is_locked,
        'remaining_seconds': remaining_seconds,
    })

@login_required
@csrf_protect
@never_cache
def security_lockdown(request):
    """Active le verrouillage d'urgence du système (SYSTEM_LOCKED)."""
    if not request.user.is_staff:
        return HttpResponseForbidden("Accès réservé aux administrateurs.")
    if request.method != 'POST':
        return HttpResponseForbidden("Méthode non autorisée.")
    try:
        duration = int(request.POST.get('duration', '300'))
    except Exception:
        duration = 300
    cache.set('SYSTEM_LOCKED', True, duration)
    try:
        cache.set('SYSTEM_LOCKED_UNTIL', time.time() + duration, duration)
    except Exception:
        pass
    messages.error(request, f"Verrouillage d'urgence activé pour {duration} secondes.")
    return redirect('utilisateurs:security_dashboard')

@login_required
@csrf_protect
@never_cache
def security_clear_login_lock(request):
    """
    Nettoie le verrouillage de connexion (compteurs d'échecs et flags de blocage)
    pour une IP et/ou un nom d'utilisateur. Réservé staff.
    """
    if not request.user.is_staff:
        return HttpResponseForbidden("Accès réservé aux administrateurs.")
    if request.method != 'POST':
        return HttpResponseForbidden("Méthode non autorisée.")

    ip = (request.POST.get('ip') or '').strip()
    username = (request.POST.get('username') or '').strip().lower()

    if not ip and not username:
        messages.error(request, "Veuillez fournir au moins une IP ou un nom d'utilisateur.")
        return redirect('utilisateurs:security_dashboard')

    cleared = 0
    keys = []
    try:
        if ip and username:
            keys = [
                f'failed_login_{ip}',
                f'failed_login_{ip}_{username}',
                f'blocked_login_{ip}',
                f'blocked_login_{ip}_{username}',
                # Blocage 24h posé par SecurityMiddleware (SQLi/XSS/UA suspect)
                f'blocked_ip_{ip}',
                f'rate_limit_{ip}',
            ]
        elif ip:
            keys = [
                f'failed_login_{ip}',
                f'blocked_login_{ip}',
                # Blocage 24h posé par SecurityMiddleware (SQLi/XSS/UA suspect)
                f'blocked_ip_{ip}',
                f'rate_limit_{ip}',
            ]
        else:
            # username seul: tenter de purger les clés exposées par le backend
            try:
                for k in list(getattr(cache, '_cache', {}).keys()):
                    if isinstance(k, str) and (k.endswith(f'_{username}') or k.startswith('failed_login_') or k.startswith('blocked_login_')):
                        keys.append(k)
            except Exception:
                pass

        for k in set(keys):
            try:
                if cache.get(k) is not None:
                    cache.delete(k)
                    cleared += 1
            except Exception:
                pass
    except Exception as e:
        messages.error(request, f"Erreur lors du nettoyage: {e}")
        return redirect('utilisateurs:security_dashboard')

    if cleared:
        messages.success(request, f"Blocage(s) nettoyé(s): {cleared} clé(s) supprimée(s).")
    else:
        messages.info(request, "Aucune entrée de blocage trouvée pour ces critères.")
    return redirect('utilisateurs:security_dashboard')

@login_required
@csrf_protect
@never_cache
def security_unlock(request):
    """Désactive le verrouillage d'urgence du système (SYSTEM_LOCKED)."""
    if not request.user.is_staff:
        return HttpResponseForbidden("Accès réservé aux administrateurs.")
    if request.method != 'POST':
        return HttpResponseForbidden("Méthode non autorisée.")
    cache.delete('SYSTEM_LOCKED')
    cache.delete('SYSTEM_LOCKED_UNTIL')
    messages.success(request, "Verrouillage d'urgence désactivé. Le système est à nouveau accessible.")
    return redirect('utilisateurs:security_dashboard')

@login_required
@csrf_protect
@never_cache
def verify_phone(request):
    """
    Étape de vérification du numéro de téléphone après connexion.
    L'utilisateur doit saisir le numéro exactement tel qu'enregistré dans son profil.
    Exemple de format attendu (validé par le modèle Profil): +224XXXXXXXXX
    """
    profil = getattr(request.user, 'profil', None)
    if not profil or not profil.telephone:
        messages.error(request, _("Aucun numéro de téléphone n'est enregistré sur votre profil. Contactez l'administrateur FARA LENO AU +224622613559."))
        return redirect('utilisateurs:logout')

    # Si déjà vérifié pour la session courante, on passe
    if request.session.get('phone_verified'):
        next_url = request.GET.get('next')
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('eleves:liste_eleves')

    if request.method == 'POST':
        numero = (request.POST.get('telephone') or '').strip()
        # On compare strictement au numéro du profil
        if numero == profil.telephone:
            request.session['phone_verified'] = True
            request.session['phone_verified_at'] = time.time()
            messages.success(request, _('Vérification du téléphone réussie.'))
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('eleves:liste_eleves')
        else:
            messages.error(request, _("Le numéro saisi ne correspond pas à celui enregistré."))

    return render(request, 'utilisateurs/verify_phone.html', {
        'telephone_masque': profil.telephone[:-3] + '***' if profil.telephone and len(profil.telephone) > 3 else '***',
        'next': request.GET.get('next', ''),
    })

def check_session_security(request):
    """
    Vérifie la sécurité de la session actuelle
    """
    if not request.user.is_authenticated:
        return redirect('utilisateurs:login')
    
    # Vérifier l'âge de la session
    session_start = request.session.get('session_start')
    if not session_start:
        request.session['session_start'] = time.time()
        session_start = request.session['session_start']
    
    session_age = time.time() - session_start
    
    # Forcer la reconnexion après 8 heures
    if session_age > 28800:  # 8 heures
        logger.info(f"Session expirée pour {request.user.username} (durée: {session_age/3600:.1f}h)")
        logout(request)
        messages.info(request, 'Votre session a expiré. Veuillez vous reconnecter.')
        return redirect('utilisateurs:login')
    
    return None  # Session valide


def password_reset_info(request):
    """
    Page d'information pour la réinitialisation du mot de passe.
    Ne propose pas de formulaire, indique seulement de contacter l'administrateur.
    """
    return render(request, 'utilisateurs/password_reset_info.html', {
        'message': "Contactez l'administrateur FARA LENO AU +224622613559 pour réinitialiser votre mot de passe.",
    })


@login_required
@csrf_protect
@never_cache
def admin_unlock(request):
    """
    Formulaire de vérification pour administrateur afin de réactiver un compte bloqué.
    Le code est défini via SECURITY_VERIFICATION_CODE dans .env. En cas de validation,
    supprime les verrous (failed_login_*, blocked_login_*) pour l'IP et/ou l'utilisateur saisis.
    Réservé aux utilisateurs staff.
    """
    if not request.user.is_staff:
        return HttpResponseForbidden("Accès réservé aux administrateurs.")

    context = {}
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()
        ip = (request.POST.get('ip') or '').strip()
        username = (request.POST.get('username') or '').strip().lower()

        # Valider le code de vérification
        from django.conf import settings as django_settings
        expected_code = django_settings.SECURITY_VERIFICATION_CODE
        if not expected_code or code != expected_code:
            messages.error(request, "Code de vérification invalide.")
            context.update({'prefill_ip': ip, 'prefill_username': username})
            return render(request, 'utilisateurs/admin_unlock.html', context)

        # Nettoyer les verrous comme dans security_clear_login_lock
        cleared = 0
        keys = []
        try:
            if ip and username:
                keys = [
                    f'failed_login_{ip}',
                    f'failed_login_{ip}_{username}',
                    f'blocked_login_{ip}',
                    f'blocked_login_{ip}_{username}',
                    # Blocage 24h posé par SecurityMiddleware (SQLi/XSS/UA suspect)
                    f'blocked_ip_{ip}',
                    f'rate_limit_{ip}',
                ]
            elif ip:
                keys = [
                    f'failed_login_{ip}',
                    f'blocked_login_{ip}',
                    # Blocage 24h posé par SecurityMiddleware (SQLi/XSS/UA suspect)
                    f'blocked_ip_{ip}',
                    f'rate_limit_{ip}',
                ]
            elif username:
                try:
                    for k in list(getattr(cache, '_cache', {}).keys()):
                        if isinstance(k, str) and (k.endswith(f'_{username}') or k.startswith('failed_login_') or k.startswith('blocked_login_')):
                            keys.append(k)
                except Exception:
                    pass
            else:
                messages.error(request, "Veuillez fournir au moins une IP ou un nom d'utilisateur.")
                return render(request, 'utilisateurs/admin_unlock.html')

            for k in set(keys):
                try:
                    if cache.get(k) is not None:
                        cache.delete(k)
                        cleared += 1
                except Exception:
                    pass
        except Exception as e:
            messages.error(request, f"Erreur lors du nettoyage: {e}")
            return render(request, 'utilisateurs/admin_unlock.html')

        messages.success(request, f"Déverrouillage réussi. Clé(s) supprimée(s): {cleared}.")
        return redirect('utilisateurs:security_dashboard')

    # GET: Pré-remplir depuis la query string si fournie
    ip_q = (request.GET.get('ip') or '').strip()
    username_q = (request.GET.get('username') or '').strip()
    if ip_q or username_q:
        context.update({'prefill_ip': ip_q, 'prefill_username': username_q})
    return render(request, 'utilisateurs/admin_unlock.html', context)
