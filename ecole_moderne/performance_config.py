"""
Configuration et utilitaires pour l'optimisation des performances
Système de cache intelligent et optimisations globales
"""
from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch, Q, Count, Sum, Case, When, IntegerField, DecimalField
from django.utils import timezone
from functools import wraps
import logging
from datetime import datetime, timedelta
from eleves.models import Eleve
from paiements.models import Paiement

logger = logging.getLogger(__name__)

# Configuration des TTL de cache (en secondes)
CACHE_TTL = {
    'user_school': 300,          # 5 minutes
    'classes_by_school': 600,    # 10 minutes
    'stats_dashboard': 120,      # 2 minutes
    'stats_eleves': 120,         # 2 minutes
    'stats_paiements': 180,      # 3 minutes
    'search_results': 30,        # 30 secondes
    'reports_data': 300,         # 5 minutes
    'user_permissions': 600,     # 10 minutes
    'school_config': 1800,       # 30 minutes
}

# Préfixes de clés de cache
CACHE_KEYS = {
    'user_school': 'user_school_{}',
    'classes_school': 'classes_ecole_{}',
    'stats_eleves': 'stats_eleves_{}',
    'stats_paiements': 'stats_paiements_{}',
    'stats_dashboard': 'stats_dashboard_{}',
    'search_responsable': 'search_resp_{}_{}',
    'user_permissions': 'user_perms_{}',
    'school_stats': 'school_stats_{}',
    'monthly_report': 'monthly_report_{}_{}',
    'daily_report': 'daily_report_{}_{}',
}

def cache_key(key_template, *args):
    """Génère une clé de cache formatée"""
    return key_template.format(*args)

def get_cached_or_set(cache_key, callable_func, ttl=300):
    """
    Récupère une valeur du cache ou l'exécute et la met en cache
    """
    result = cache.get(cache_key)
    if result is None:
        try:
            result = callable_func()
            cache.set(cache_key, result, ttl)
        except Exception as e:
            logger.error(f"Erreur lors du cache {cache_key}: {e}")
            result = callable_func()  # Fallback sans cache
    return result

def cache_view_result(cache_key_template, ttl=300):
    """
    Décorateur pour mettre en cache le résultat d'une vue
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Générer la clé de cache avec l'ID utilisateur
            key = cache_key_template.format(request.user.id, *args)
            
            # Vérifier le cache
            result = cache.get(key)
            if result is None:
                result = view_func(request, *args, **kwargs)
                cache.set(key, result, ttl)
            
            return result
        return wrapper
    return decorator

def invalidate_user_caches(user_id, patterns=None):
    """
    Invalide tous les caches liés à un utilisateur
    """
    if patterns is None:
        patterns = [
            f'user_school_{user_id}',
            f'stats_eleves_{user_id}',
            f'stats_paiements_{user_id}',
            f'stats_dashboard_{user_id}',
            f'user_perms_{user_id}',
        ]
    
    cache.delete_many(patterns)

def invalidate_school_caches(school_id):
    """
    Invalide tous les caches liés à une école
    """
    patterns = [
        f'classes_ecole_{school_id}',
        f'school_stats_{school_id}',
    ]
    cache.delete_many(patterns)

class OptimizedQueryMixin:
    """
    Mixin pour optimiser les requêtes courantes
    """
    
    @staticmethod
    def get_optimized_eleves_queryset(school=None):
        """Queryset optimisé pour les élèves"""
        qs = (
            Eleve.objects
            .select_related('classe', 'classe__ecole', 'responsable_principal', 'responsable_secondaire')
            .prefetch_related(
                Prefetch('paiements', queryset=Paiement.objects.select_related('type_paiement'))
            )
        )
        
        if school:
            qs = qs.filter(classe__ecole=school)
            
        return qs
    
    @staticmethod
    def get_optimized_paiements_queryset(school=None):
        """Queryset optimisé pour les paiements"""
        qs = (
            Paiement.objects
            .select_related(
                'eleve', 'eleve__classe', 'eleve__classe__ecole',
                'ecole_encaissement', 'classe_encaissement',
                'type_paiement', 'mode_paiement',
            )
            .prefetch_related('remises')
        )
        
        if school:
            qs = qs.filter(ecole_encaissement=school)
            
        return qs
    
    @staticmethod
    def get_aggregated_stats(queryset, date_field='date_creation'):
        """
        Calcule des statistiques agrégées optimisées
        """
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        return queryset.aggregate(
            total=Count('id'),
            today=Count(Case(When(**{f'{date_field}__date': today}, then=1))),
            week=Count(Case(When(**{f'{date_field}__gte': week_ago}, then=1))),
            month=Count(Case(When(**{f'{date_field}__gte': month_ago}, then=1))),
        )

def optimize_database_queries():
    """
    Optimisations générales de base de données
    """
    from django.db import connection
    
    # Suggestions d'index à créer manuellement
    suggested_indexes = [
        "CREATE INDEX IF NOT EXISTS idx_eleves_classe_ecole ON eleves_eleve(classe_id);",
        "CREATE INDEX IF NOT EXISTS idx_paiements_eleve ON paiements_paiement(eleve_id);",
        "CREATE INDEX IF NOT EXISTS idx_paiements_date ON paiements_paiement(date_paiement);",
        "CREATE INDEX IF NOT EXISTS idx_eleves_statut ON eleves_eleve(statut);",
        "CREATE INDEX IF NOT EXISTS idx_classes_ecole ON eleves_classe(ecole_id);",
        "CREATE INDEX IF NOT EXISTS idx_journal_user ON utilisateurs_journalactivite(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_journal_date ON utilisateurs_journalactivite(date_creation);",
    ]
    
    return suggested_indexes

class PerformanceMonitor:
    """
    Moniteur de performance pour identifier les goulots d'étranglement
    """
    
    @staticmethod
    def log_slow_query(query_time, query_description, threshold=1.0):
        """Log les requêtes lentes"""
        if query_time > threshold:
            logger.warning(f"Requête lente ({query_time:.2f}s): {query_description}")
    
    @staticmethod
    def monitor_view_performance(view_name):
        """Décorateur pour monitorer les performances d'une vue"""
        def decorator(view_func):
            @wraps(view_func)
            def wrapper(request, *args, **kwargs):
                start_time = datetime.now()
                
                try:
                    result = view_func(request, *args, **kwargs)
                    
                    execution_time = (datetime.now() - start_time).total_seconds()
                    PerformanceMonitor.log_slow_query(
                        execution_time, 
                        f"Vue {view_name} - User: {request.user.id}"
                    )
                    
                    return result
                    
                except Exception as e:
                    execution_time = (datetime.now() - start_time).total_seconds()
                    logger.error(f"Erreur dans {view_name} après {execution_time:.2f}s: {e}")
                    raise
                    
            return wrapper
        return decorator

# Configuration pour les vues les plus critiques
CRITICAL_VIEWS_CACHE_CONFIG = {
    'dashboard': {'ttl': 120, 'key': 'dashboard_{}'},
    'liste_eleves': {'ttl': 180, 'key': 'liste_eleves_{}_{}'},
    'liste_paiements': {'ttl': 180, 'key': 'liste_paiements_{}_{}'},
    'rapports_journalier': {'ttl': 300, 'key': 'rapport_jour_{}_{}'},
    'stats_ecole': {'ttl': 300, 'key': 'stats_ecole_{}'},
}

def get_critical_view_cache_config(view_name):
    """Récupère la configuration de cache pour une vue critique"""
    return CRITICAL_VIEWS_CACHE_CONFIG.get(view_name, {'ttl': 300, 'key': f'{view_name}_{{}}'})
