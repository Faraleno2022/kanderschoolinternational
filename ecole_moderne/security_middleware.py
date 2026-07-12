"""
Middleware de sécurité pour protéger l'application contre les attaques
"""
import logging
import time
from django.http import HttpResponseForbidden, HttpResponse
from django.template import loader
from django.core.cache import cache
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.core.exceptions import TooManyFieldsSent
from django.core.mail import mail_admins
import re

logger = logging.getLogger(__name__)

class SecurityMiddleware(MiddlewareMixin):
    """
    Middleware de sécurité avancé pour protéger contre diverses attaques
    """
    
    # Patterns d'attaques SQL Injection (plus stricts pour éviter les faux positifs)
    SQL_INJECTION_PATTERNS = [
        # Commentaires/terminaisons SQL dangereuses
        r"(--|;|/\*|\*/|%2D%2D|%3B)",
        # UNION SELECT (avec mots-clés)
        r"\bunion\b\s+\bselect\b",
        # EXEC sp (procédures stockées)
        r"\bexec\b(\s|\+)+(s|x)p\w+",
        # Opérations DML/DDL complètes
        r"\binsert\b\s+\binto\b",
        r"\bdelete\b\s+\bfrom\b",
        r"\bdrop\b\s+\btable\b",
        # Tentatives d'évasion classiques avec quotes entourant des mots-clés SQL
        r"(['\"])\s*\bor\b\s*\d\s*=\s*\d",
    ]
    
    # Patterns d'attaques XSS
    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe[^>]*>.*?</iframe>",
        r"<object[^>]*>.*?</object>",
        r"<embed[^>]*>.*?</embed>",
    ]
    
    # Patterns de Path Traversal
    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e%2f",
        r"%2e%2e\\",
        r"..%2f",
        r"..%5c",
    ]
    
    # User agents suspects
    SUSPICIOUS_USER_AGENTS = [
        'sqlmap',
        'nikto',
        'nmap',
        'masscan',
        'nessus',
        'openvas',
        'w3af',
        'burpsuite',
        'havij',
        'pangolin',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)
    
    def process_request(self, request):
        """
        Traite chaque requête pour détecter les tentatives d'attaque
        """
        client_ip = self.get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        # -2. Bloquer l'accès public à l'admin par IP (actif uniquement si
        #     ADMIN_WHITELIST_IPS contient au moins une IP ; sinon aucun effet,
        #     pour éviter de se verrouiller soi-même hors de l'admin).
        admin_prefix = '/' + getattr(settings, 'ADMIN_URL_PATH', 'admin/')
        try:
            path = request.path or ''
            whitelist = getattr(settings, 'ADMIN_WHITELIST_IPS', []) or []
            if path.startswith(admin_prefix) and whitelist:
                is_whitelisted = client_ip in whitelist
                if not (hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff):
                    if not is_whitelisted:
                        try:
                            template = loader.get_template('utilisateurs/admin_blocked.html')
                            html = template.render({
                                'message': "Accès administrateur interdit. Veuillez contacter l'administrateur du site.",
                                'contact_phone': '622613559',
                                'titre_page': 'Accès refusé'
                            }, request)
                            return HttpResponse(html, status=403)
                        except Exception:
                            return HttpResponseForbidden(
                                "Accès administrateur interdit. Veuillez consulter l'administrateur du système au 622613559."
                            )
        except Exception:
            pass

        # -1. Si le système est verrouillé (suite à bruteforce), bloquer tout
        try:
            if cache.get('SYSTEM_LOCKED', False):
                # Autoriser uniquement la page de login pour permettre une reprise manuelle
                if not path.startswith('/utilisateurs/login/'):
                    logger.critical("Système verrouillé: accès refusé à %s (IP %s)", path, client_ip)
                    return HttpResponseForbidden("Système temporairement verrouillé. Réessayez plus tard.")
        except Exception:
            pass
        
        # 0. Bypass sécurisé pour l'admin avec utilisateur staff authentifié
        try:
            if request.path.startswith(admin_prefix) and hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
                # On applique seulement rate limiting et blocage IP existant, pas de détection agressive
                if self.is_ip_blocked(client_ip):
                    logger.info(f"Accès admin refusé pour IP bloquée: {client_ip}")
                    return HttpResponseForbidden("Votre adresse IP a été bloquée.")
                self.increment_request_count(client_ip)
                return None
        except Exception:
            # En cas d'erreur inattendue, ne pas bloquer l'admin
            pass

        # 1. Vérifier le rate limiting
        if self.is_rate_limited(client_ip):
            logger.warning(f"Rate limit dépassé pour IP: {client_ip}")
            return HttpResponseForbidden("Trop de requêtes. Veuillez patienter.")
        
        # 2. Vérifier les User Agents suspects
        if self.is_suspicious_user_agent(user_agent):
            logger.warning(f"User Agent suspect détecté: {user_agent} depuis IP: {client_ip}")
            self.block_ip(client_ip, "User Agent suspect")
            return HttpResponseForbidden("Accès refusé.")
        
        # 3. Vérifier les tentatives d'injection SQL
        if self.detect_sql_injection(request):
            logger.critical(f"Tentative d'injection SQL détectée depuis IP: {client_ip}")
            self.block_ip(client_ip, "Injection SQL")
            return HttpResponseForbidden("Tentative d'attaque détectée.")
        
        # 4. Vérifier les tentatives XSS
        if self.detect_xss(request):
            logger.warning(f"Tentative XSS détectée depuis IP: {client_ip}")
            self.block_ip(client_ip, "Tentative XSS")
            return HttpResponseForbidden("Tentative d'attaque détectée.")
        
        # 5. Vérifier les tentatives de Path Traversal
        if self.detect_path_traversal(request):
            logger.warning(f"Tentative de Path Traversal détectée depuis IP: {client_ip}")
            self.block_ip(client_ip, "Path Traversal")
            return HttpResponseForbidden("Tentative d'attaque détectée.")
        
        # 6. Vérifier si l'IP est bloquée
        if self.is_ip_blocked(client_ip):
            logger.info(f"Accès refusé pour IP bloquée: {client_ip}")
            return HttpResponseForbidden("Votre adresse IP a été bloquée.")
        
        # 7. Incrémenter le compteur de requêtes
        self.increment_request_count(client_ip)
        
        return None
    
    def get_client_ip(self, request):
        """Obtient l'adresse IP réelle du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def is_rate_limited(self, ip):
        """Vérifie si l'IP dépasse la limite de requêtes"""
        cache_key = f"rate_limit_{ip}"
        requests = cache.get(cache_key, 0)
        return requests > 100  # Max 100 requêtes par minute
    
    def increment_request_count(self, ip):
        """Incrémente le compteur de requêtes pour une IP"""
        cache_key = f"rate_limit_{ip}"
        requests = cache.get(cache_key, 0)
        cache.set(cache_key, requests + 1, 60)  # Expire après 1 minute
    
    def is_suspicious_user_agent(self, user_agent):
        """Vérifie si le User Agent est suspect"""
        return any(suspicious in user_agent for suspicious in self.SUSPICIOUS_USER_AGENTS)
    
    def detect_sql_injection(self, request):
        """Détecte les tentatives d'injection SQL (requêtes et POST), sans pénaliser les apostrophes normales)"""
        # Vérifier dans la query string uniquement (pas tout le chemin)
        query = (request.META.get('QUERY_STRING') or '').lower()
        for pattern in self.SQL_INJECTION_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        
        # Vérifier dans les paramètres POST (valeurs texte)
        if request.method == 'POST':
            try:
                for key, value in request.POST.items():
                    if isinstance(value, str):
                        val = value.lower()
                        for pattern in self.SQL_INJECTION_PATTERNS:
                            if re.search(pattern, val, re.IGNORECASE):
                                return True
            except TooManyFieldsSent:
                logger.warning("[SECURITY] POST ignoré pour scan SQLi: trop de champs (TooManyFieldsSent)")
                return False
        
        return False
    
    def detect_xss(self, request):
        """Détecte les tentatives XSS"""
        # Vérifier dans l'URL
        full_path = request.get_full_path().lower()
        for pattern in self.XSS_PATTERNS:
            if re.search(pattern, full_path, re.IGNORECASE):
                return True
        
        # Vérifier dans les paramètres POST
        if request.method == 'POST':
            try:
                for key, value in request.POST.items():
                    if isinstance(value, str):
                        for pattern in self.XSS_PATTERNS:
                            if re.search(pattern, value.lower(), re.IGNORECASE):
                                return True
            except TooManyFieldsSent:
                # Si le formulaire contient trop de champs, ignorer l'analyse POST
                logger.warning("[SECURITY] POST ignoré pour scan XSS: trop de champs (TooManyFieldsSent)")
                return False
        
        return False
    
    def detect_path_traversal(self, request):
        """Détecte les tentatives de Path Traversal"""
        full_path = request.get_full_path()
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, full_path, re.IGNORECASE):
                return True
        return False
    
    def is_ip_blocked(self, ip):
        """Vérifie si une IP est bloquée"""
        cache_key = f"blocked_ip_{ip}"
        return cache.get(cache_key, False)
    
    def block_ip(self, ip, reason):
        """Bloque une IP (localhost bloquée brièvement pour éviter de verrouiller le dev)."""
        cache_key = f"blocked_ip_{ip}"
        # Ne pas bloquer durablement localhost
        if ip in ('127.0.0.1', '::1'):
            cache.set(cache_key, True, 300)  # 5 minutes en local
            logger.warning(f"IP locale {ip} temporairement bloquée (5 min) pour: {reason}")
            try:
                mail_admins("[SECURITY][DEV] IP locale bloquée", f"Raison: {reason}\nIP: {ip}")
            except Exception:
                pass
        else:
            cache.set(cache_key, True, 86400)  # 24 heures
            logger.critical(f"IP {ip} bloquée pour: {reason}")
            try:
                mail_admins("[SECURITY] IP bloquée", f"Raison: {reason}\nIP: {ip}")
            except Exception:
                pass


class SessionSecurityMiddleware(MiddlewareMixin):
    """
    Middleware pour sécuriser les sessions
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)
    
    def process_request(self, request):
        """
        Vérifie la sécurité des sessions
        """
        # Vérifier que l'utilisateur est disponible (après AuthenticationMiddleware)
        if hasattr(request, 'user') and request.user.is_authenticated:
            # Enforcer la vérification du téléphone pour la session
            try:
                path = request.path or ''
                # Routes exemptées
                admin_prefix = '/' + getattr(settings, 'ADMIN_URL_PATH', 'admin/')
                exempt = (
                    path.startswith('/utilisateurs/login/') or
                    path.startswith('/utilisateurs/logout/') or
                    path.startswith('/utilisateurs/verify-phone/') or
                    path.startswith(admin_prefix) or
                    path.startswith('/static/') or
                    path.startswith('/media/')
                )
                # TTL de re-vérification (configurable via settings)
                PHONE_VERIFY_TTL_SECONDS = getattr(settings, 'PHONE_VERIFY_TTL_SECONDS', 8 * 3600)
                verified = request.session.get('phone_verified', False)
                verified_at = request.session.get('phone_verified_at')
                # Vérifier expiration si déjà vérifié
                if verified and verified_at:
                    try:
                        age = time.time() - float(verified_at)
                        if age > PHONE_VERIFY_TTL_SECONDS:
                            # Expire la vérification
                            request.session['phone_verified'] = False
                            request.session['phone_verified_at'] = None
                            verified = False
                    except Exception:
                        # En cas de valeur inattendue, forcer une nouvelle vérification
                        request.session['phone_verified'] = False
                        request.session['phone_verified_at'] = None
                        verified = False

                if not exempt and not verified:
                    # Préserver la destination initiale
                    from django.urls import reverse
                    verify_url = reverse('utilisateurs:verify_phone')
                    return redirect(f"{verify_url}?next={path}")
            except Exception:
                # En cas d'erreur, ne pas bloquer l'utilisateur, continuer les autres contrôles
                pass
            # Vérifier l'inactivité de session
            if self.is_session_expired(request):
                logout(request)
                logger.info(f"Session expirée pour utilisateur: {request.user.username}")
                return redirect('utilisateurs:login')
            
            # Vérifier le changement d'IP (optionnel, peut causer des problèmes avec les proxies)
            if self.detect_session_hijacking(request):
                logout(request)
                logger.warning(f"Tentative de détournement de session détectée pour: {request.user.username}")
                return redirect('utilisateurs:login')
            
            # Mettre à jour le timestamp de dernière activité
            request.session['last_activity'] = time.time()
            request.session['user_ip'] = self.get_client_ip(request)
        
        return None
    
    def get_client_ip(self, request):
        """Obtient l'adresse IP réelle du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def is_session_expired(self, request):
        """Vérifie si la session a expiré (30 minutes d'inactivité)"""
        last_activity = request.session.get('last_activity')
        if last_activity:
            return time.time() - last_activity > 1800  # 30 minutes
        return False
    
    def detect_session_hijacking(self, request):
        """Détecte les tentatives de détournement de session"""
        session_ip = request.session.get('user_ip')
        current_ip = self.get_client_ip(request)
        
        # Si l'IP a changé, c'est suspect (désactivé par défaut)
        # return session_ip and session_ip != current_ip
        return False  # Désactivé pour éviter les faux positifs


class CSRFSecurityMiddleware(MiddlewareMixin):
    """
    Middleware pour renforcer la protection CSRF
    """
    
    def process_request(self, request):
        """
        Vérifie les en-têtes de sécurité CSRF
        """
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            # Vérifier l'en-tête Referer pour les requêtes sensibles
            referer = request.META.get('HTTP_REFERER')
            if not referer or not self.is_same_origin(request, referer):
                logger.warning(f"Requête CSRF suspecte sans Referer valide depuis IP: {self.get_client_ip(request)}")
        
        return None
    
    def get_client_ip(self, request):
        """Obtient l'adresse IP réelle du client"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def is_same_origin(self, request, referer):
        """Vérifie si le referer provient du même domaine"""
        from urllib.parse import urlparse
        
        request_host = request.get_host()
        referer_host = urlparse(referer).netloc
        
        return request_host == referer_host


class CSPMiddleware(MiddlewareMixin):
    """
    Middleware ajoutant des en-têtes de sécurité forts (CSP, Permissions-Policy, COOP/COEP).
    Compatible avec les templates existants (autorise le CSS inline minimal et les fonts/images statiques).
    """

    def process_response(self, request, response):
        try:
            # Politique CSP restrictive mais compatible
            # - default-src 'self'
            # - scripts/styles principalement locaux, style inline autorisé pour Bootstrap
            # - images depuis 'self' + data: (logos encodés), fonts depuis self et data:
            # Autoriser CDN utilisés par base.html
            script_src = [
                "'self'",
                "'unsafe-inline'",
                "https://cdn.jsdelivr.net",
            ]
            style_src = [
                "'self'",
                "'unsafe-inline'",
                "https://cdn.jsdelivr.net",
                "https://cdnjs.cloudflare.com",
            ]
            font_src = [
                "'self'",
                "data:",
                "https://cdnjs.cloudflare.com",
            ]
            img_src = [
                "'self'",
                "data:",
                "https:",
            ]
            csp = [
                "default-src 'self'",
                f"script-src {' '.join(script_src)}",
                f"style-src {' '.join(style_src)}",
                f"img-src {' '.join(img_src)}",
                f"font-src {' '.join(font_src)}",
                "connect-src 'self'",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
            ]
            response['Content-Security-Policy'] = '; '.join(csp)

            # Permissions-Policy: désactiver capteurs non utilisés
            response['Permissions-Policy'] = (
                "geolocation=(), microphone=(), camera=(self), usb=(), payment=(), fullscreen=(self)"
            )

            # Cross-Origin policies pour isolation
            response['Cross-Origin-Opener-Policy'] = 'same-origin'
            response['Cross-Origin-Embedder-Policy'] = 'require-corp'

            # X-XSS-Protection est obsolète mais inoffensif sur anciens navigateurs
            response['X-XSS-Protection'] = '1; mode=block'

            return response
        except Exception:
            return response
