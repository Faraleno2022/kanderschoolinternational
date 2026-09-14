"""
Décorateurs de sécurité pour protéger les vues contre les attaques
"""
import functools
import logging
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model
from django.core.mail import mail_admins
from django.conf import settings
import time

from ecole_moderne.client_ip import get_client_ip

logger = logging.getLogger(__name__)
User = get_user_model()

def admin_required(view_func):
    """
    Décorateur pour restreindre l'accès aux administrateurs uniquement
    """
    @functools.wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff and not request.user.is_superuser:
            logger.warning(f"Tentative d'accès admin non autorisée par: {request.user.username}")
            return HttpResponseForbidden("Accès réservé aux administrateurs.")
        return view_func(request, *args, **kwargs)
    return wrapper

def require_school_object(model, pk_kwarg: str = 'pk', field_path: str = 'ecole'):
    """Décorateur qui impose que l'objet ciblé appartienne à l'école de l'utilisateur.

    - model: le modèle Django ciblé (ex: Paiement, Eleve, Classe)
    - pk_kwarg: nom du paramètre kwarg qui contient la clé primaire (ex: 'paiement_id', 'eleve_id')
    - field_path: chemin vers le champ `Ecole` depuis le modèle (ex: 'eleve__classe__ecole', 'classe__ecole')

    Comportement:
      - Seul le superuser a accès total à toutes les écoles
      - Pour les autres (y compris ADMIN d'école), on filtre le queryset via `filter_by_user_school`
      - Si l'objet n'est pas dans l'école de l'utilisateur ou n'existe pas -> Http404
    """
    from django.shortcuts import get_object_or_404
    from django.http import Http404
    from utilisateurs.utils import user_is_superadmin, filter_by_user_school

    def decorator(view_func):
        @functools.wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            obj_pk = kwargs.get(pk_kwarg)
            # Si aucune clé, laisser la vue gérer l'erreur
            if obj_pk is None:
                return view_func(request, *args, **kwargs)

            # Seul le superuser a accès complet à toutes les écoles
            if user_is_superadmin(request.user):
                return view_func(request, *args, **kwargs)

            # Restreindre le queryset de l'objet à l'école de l'utilisateur
            qs = filter_by_user_school(model.objects.all(), request.user, field_path)
            try:
                # Déclenchera 404 si l'objet n'appartient pas à l'école ou n'existe pas
                get_object_or_404(qs, pk=obj_pk)
            except Http404:
                client_ip = get_client_ip(request)
                logger.warning(
                    f"Accès cross-école refusé: user={getattr(request.user, 'id', None)} path={request.path} "
                    f"model={model.__name__} pk={obj_pk} field_path={field_path} ip={client_ip}"
                )
                raise

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator

def delete_permission_required(allowed_username="FELIXSUZANELENO", confirm_value="FELIXSUZANELENO", confirm_field="confirm_name"):
    """
    Décorateur pour restreindre toute opération de suppression à un seul utilisateur
    spécifique (par défaut 'FELIXSUZANELENO') et exiger une confirmation explicite
    du même nom en saisie.

    Comportement:
    - Si l'utilisateur courant n'est pas `allowed_username` -> 403
    - GET  -> affiche une page de confirmation avec champ texte à saisir
    - POST -> vérifie que request.POST[confirm_field] == confirm_value (casse stricte)

    La vue décorée ne doit contenir que la logique de suppression. Ce décorateur
    garantit que seule une requête POST confirmée atteint la vue.
    """
    from django.shortcuts import render
    from django.views.decorators.csrf import csrf_protect
    from django.utils.decorators import method_decorator

    def decorator(view_func):
        @functools.wraps(view_func)
        @login_required
        @csrf_protect
        def wrapper(request, *args, **kwargs):
            # Refuser tout utilisateur autre que celui autorisé
            if request.user.username != allowed_username:
                logger.warning(
                    f"Suppression refusée: user={request.user.username}, ip={get_client_ip(request)}"
                )
                return HttpResponseForbidden("Suppression réservée à l'administrateur principal.")

            # Confirmation requise
            if request.method == 'GET':
                context = {
                    'confirm_value': confirm_value,
                    'confirm_field': confirm_field,
                    'action_url': request.get_full_path(),
                    'username': request.user.username,
                }
                return render(request, 'administration/confirm_delete.html', context)

            if request.method == 'POST':
                provided = request.POST.get(confirm_field, '')
                if provided != confirm_value:
                    # Si AJAX, renvoyer un JSON 403
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'error': 'Confirmation invalide.'}, status=403)
                    context = {
                        'confirm_value': confirm_value,
                        'confirm_field': confirm_field,
                        'action_url': request.get_full_path(),
                        'username': request.user.username,
                        'error': "Le nom de confirmation est incorrect."
                    }
                    return render(request, 'administration/confirm_delete.html', context, status=403)

                # Confirmation réussie -> exécuter la vue de suppression
                return view_func(request, *args, **kwargs)

            # Toute autre méthode refusée
            return HttpResponseForbidden("Méthode non autorisée.")

        return wrapper
    return decorator

def rate_limit(max_requests=10, window=60):
    """
    Décorateur pour limiter le nombre de requêtes par utilisateur
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_authenticated:
                cache_key = f"rate_limit_user_{request.user.id}_{view_func.__name__}"
            else:
                client_ip = get_client_ip(request)
                cache_key = f"rate_limit_ip_{client_ip}_{view_func.__name__}"
            
            requests = cache.get(cache_key, 0)
            if requests >= max_requests:
                logger.warning(f"Rate limit dépassé pour {cache_key}")
                return HttpResponseForbidden("Trop de requêtes. Veuillez patienter.")
            
            cache.set(cache_key, requests + 1, window)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def secure_view(require_post=False, admin_only=False, rate_limit_requests=None):
    """
    Décorateur combiné pour sécuriser une vue
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        @login_required
        @csrf_protect
        def wrapper(request, *args, **kwargs):
            # Vérifier si admin requis
            if admin_only and not (request.user.is_staff or request.user.is_superuser):
                logger.warning(f"Accès admin refusé à: {request.user.username}")
                return HttpResponseForbidden("Accès réservé aux administrateurs.")
            
            # Vérifier la méthode HTTP
            if require_post and request.method != 'POST':
                return HttpResponseForbidden("Méthode non autorisée.")
            
            # Appliquer le rate limiting si spécifié
            if rate_limit_requests:
                cache_key = f"rate_limit_user_{request.user.id}_{view_func.__name__}"
                requests = cache.get(cache_key, 0)
                if requests >= rate_limit_requests:
                    logger.warning(f"Rate limit dépassé pour utilisateur: {request.user.username}")
                    return HttpResponseForbidden("Trop de requêtes. Veuillez patienter.")
                cache.set(cache_key, requests + 1, 60)
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def audit_log(action_type):
    """
    Décorateur pour enregistrer les actions sensibles
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            start_time = time.time()
            client_ip = get_client_ip(request)
            
            try:
                response = view_func(request, *args, **kwargs)
                
                # Log de l'action réussie
                logger.info(f"ACTION: {action_type} | USER: {getattr(request.user, 'username', 'Anonymous')} | "
                           f"IP: {client_ip} | STATUS: SUCCESS | TIME: {time.time() - start_time:.2f}s")
                
                return response
                
            except Exception as e:
                # Log de l'erreur
                logger.error(f"ACTION: {action_type} | USER: {getattr(request.user, 'username', 'Anonymous')} | "
                            f"IP: {client_ip} | STATUS: ERROR | ERROR: {str(e)} | TIME: {time.time() - start_time:.2f}s")
                raise
                
        return wrapper
    return decorator

def validate_permissions(required_permissions):
    """
    Décorateur pour vérifier les permissions spécifiques
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perms(required_permissions):
                logger.warning(f"Permissions insuffisantes pour {request.user.username}: {required_permissions}")
                return HttpResponseForbidden("Permissions insuffisantes.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def prevent_brute_force(max_attempts=5, lockout_time=300):
    """
    Décorateur pour prévenir les attaques par force brute
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            client_ip = get_client_ip(request)
            cache_key = f"brute_force_{client_ip}_{view_func.__name__}"
            
            attempts = cache.get(cache_key, 0)
            if attempts >= max_attempts:
                logger.warning(f"Tentative de force brute bloquée pour IP: {client_ip}")
                # Verrouiller temporairement tout le système (sauf page de login)
                try:
                    system_lock_seconds = getattr(settings, 'LOGIN_BLOCK_DURATION', 300)
                    cache.set('SYSTEM_LOCKED', True, system_lock_seconds)
                except Exception:
                    pass
                # Alerter les administrateurs
                try:
                    mail_admins(
                        subject="[SECURITY] Tentative de force brute détectée - SYSTÈME VERROUILLÉ",
                        message=(
                            f"Vue: {view_func.__name__}\n"
                            f"IP: {client_ip}\n"
                            f"Tentatives: {attempts}\n"
                            f"Durée de verrouillage: {getattr(settings, 'LOGIN_BLOCK_DURATION', 300)}s\n"
                        ),
                    )
                except Exception:
                    pass
                return HttpResponseForbidden("Trop de tentatives. Système temporairement verrouillé.")
            
            try:
                response = view_func(request, *args, **kwargs)
                
                # Si la vue réussit, réinitialiser le compteur
                if hasattr(response, 'status_code') and response.status_code == 200:
                    cache.delete(cache_key)
                
                return response
                
            except Exception as e:
                # Incrémenter le compteur en cas d'échec
                cache.set(cache_key, attempts + 1, lockout_time)
                raise
                
        return wrapper
    return decorator

def sanitize_input(view_func):
    """
    Décorateur pour nettoyer les entrées utilisateur
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method == 'POST':
            # Nettoyer les données POST
            cleaned_post = request.POST.copy()
            for key, value in cleaned_post.items():
                if isinstance(value, str):
                    # Supprimer les caractères dangereux
                    cleaned_value = sanitize_string(value)
                    cleaned_post[key] = cleaned_value
            
            request.POST = cleaned_post
        
        return view_func(request, *args, **kwargs)
    return wrapper


def sanitize_string(value):
    """
    Nettoie une chaîne de caractères des éléments dangereux
    """
    import re
    
    # Supprimer les balises HTML/JavaScript
    value = re.sub(r'<[^>]*>', '', value)
    
    # Supprimer les caractères de contrôle
    value = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
    
    # Échapper les caractères SQL dangereux
    dangerous_chars = ["'", '"', ';', '--', '/*', '*/', 'xp_', 'sp_']
    for char in dangerous_chars:
        value = value.replace(char, '')
    
    return value.strip()

def require_ajax(view_func):
    """
    Décorateur pour s'assurer qu'une vue n'est accessible que via AJAX
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            logger.warning(f"Tentative d'accès non-AJAX à une vue AJAX depuis IP: {get_client_ip(request)}")
            return HttpResponseForbidden("Cette vue n'est accessible que via AJAX.")
        return view_func(request, *args, **kwargs)
    return wrapper

def check_user_agent(view_func):
    """
    Décorateur pour vérifier le User-Agent
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        # Liste des User-Agents suspects
        suspicious_agents = ['sqlmap', 'nikto', 'nmap', 'masscan', 'nessus', 'openvas']
        
        if any(agent in user_agent for agent in suspicious_agents):
            client_ip = get_client_ip(request)
            logger.critical(f"User-Agent suspect détecté: {user_agent} depuis IP: {client_ip}")
            return HttpResponseForbidden("User-Agent non autorisé.")
        
        return view_func(request, *args, **kwargs)
    return wrapper
