"""
Optimiseur de requêtes pour améliorer les performances
"""
from django.db.models import Prefetch, Q, Count, Sum, Case, When, IntegerField, DecimalField
from django.core.cache import cache
from django.utils import timezone
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class QueryOptimizer:
    """
    Classe utilitaire pour optimiser les requêtes courantes
    """
    
    @staticmethod
    def get_optimized_eleves(school=None, with_payments=False, with_classes=True):
        """
        Queryset optimisé pour les élèves avec relations pré-chargées
        """
        from eleves.models import Eleve
        
        qs = Eleve.objects.select_related('classe', 'responsable_principal')
        
        if with_classes:
            qs = qs.select_related('classe__ecole')
        
        if with_payments:
            from paiements.models import Paiement
            qs = qs.prefetch_related(
                Prefetch(
                    'paiements',
                    queryset=Paiement.objects.select_related('type_paiement', 'mode_paiement')
                )
            )
        
        if school:
            qs = qs.filter(classe__ecole=school)
        
        return qs
    
    @staticmethod
    def get_optimized_paiements(school=None, with_eleves=True, with_remises=False):
        """
        Queryset optimisé pour les paiements
        """
        from paiements.models import Paiement
        
        qs = Paiement.objects.select_related('type_paiement', 'mode_paiement')
        
        if with_eleves:
            qs = qs.select_related('eleve', 'eleve__classe', 'eleve__classe__ecole')
        
        if with_remises:
            qs = qs.prefetch_related('remises')
        
        if school:
            qs = qs.filter(eleve__classe__ecole=school)
        
        return qs
    
    @staticmethod
    def get_dashboard_stats(user, use_cache=True):
        """
        Statistiques optimisées pour le dashboard
        """
        cache_key = f'dashboard_stats_{user.id}'
        
        if use_cache:
            stats = cache.get(cache_key)
            if stats:
                return stats
        
        from eleves.models import Eleve, Ecole
        from paiements.models import Paiement
        from django.contrib.auth.models import User
        from utilisateurs.utils import user_is_admin, user_school
        
        # Filtrage par école si nécessaire
        school = None
        if not user_is_admin(user):
            school = user_school(user)
        
        # Requêtes optimisées avec agrégation
        today = timezone.now().date()
        month_start = today.replace(day=1)
        
        # Stats élèves
        eleves_qs = Eleve.objects.all()
        if school:
            eleves_qs = eleves_qs.filter(classe__ecole=school)
        
        eleves_stats = eleves_qs.aggregate(
            total=Count('id'),
            actifs=Count(Case(When(statut='ACTIF', then=1))),
            nouveaux_mois=Count(Case(When(date_inscription__gte=month_start, then=1)))
        )
        
        # Stats paiements
        paiements_qs = Paiement.objects.all()
        if school:
            paiements_qs = paiements_qs.filter(eleve__classe__ecole=school)
        
        paiements_stats = paiements_qs.aggregate(
            total=Count('id'),
            valides=Count(Case(When(statut='VALIDE', then=1))),
            montant_total=Sum(Case(When(statut='VALIDE', then='montant'), default=0)),
            mois_count=Count(Case(When(date_paiement__gte=month_start, then=1))),
            mois_montant=Sum(Case(When(
                Q(date_paiement__gte=month_start) & Q(statut='VALIDE'), 
                then='montant'
            ), default=0))
        )
        
        stats = {
            'eleves': eleves_stats,
            'paiements': paiements_stats,
            'generated_at': timezone.now()
        }
        
        if use_cache:
            cache.set(cache_key, stats, 300)  # 5 minutes
        
        return stats
    
    @staticmethod
    def get_payment_summary(school=None, use_cache=True):
        """
        Résumé optimisé des paiements
        """
        cache_key = f'payment_summary_{school.id if school else "all"}'
        
        if use_cache:
            summary = cache.get(cache_key)
            if summary:
                return summary
        
        from paiements.models import Paiement, EcheancierPaiement
        from django.db.models import F, Value, DecimalField
        from django.db.models.functions import Coalesce
        
        # Requête optimisée pour les paiements
        paiements_qs = QueryOptimizer.get_optimized_paiements(school, with_eleves=True)
        
        # Agrégations complexes
        summary = paiements_qs.aggregate(
            total_paiements=Count('id'),
            montant_total=Sum(Case(When(statut='VALIDE', then='montant'), default=0)),
            en_attente_count=Count(Case(When(statut='EN_ATTENTE', then=1))),
            en_attente_montant=Sum(Case(When(statut='EN_ATTENTE', then='montant'), default=0)),
            rejetes_count=Count(Case(When(statut='REJETE', then=1))),
        )
        
        # Calculs d'échéancier si nécessaire
        if school:
            echeancier_qs = EcheancierPaiement.objects.filter(eleve__classe__ecole=school)
        else:
            echeancier_qs = EcheancierPaiement.objects.all()
        
        echeancier_stats = echeancier_qs.aggregate(
            du_total=Sum(
                Coalesce(F('tranche_1_due'), Value(0)) +
                Coalesce(F('tranche_2_due'), Value(0)) +
                Coalesce(F('tranche_3_due'), Value(0))
            )
        )
        
        summary.update(echeancier_stats)
        summary['generated_at'] = timezone.now()
        
        if use_cache:
            cache.set(cache_key, summary, 180)  # 3 minutes
        
        return summary
    
    @staticmethod
    def get_school_classes(school, use_cache=True):
        """
        Classes d'une école avec cache
        """
        cache_key = f'school_classes_{school.id}'
        
        if use_cache:
            classes = cache.get(cache_key)
            if classes:
                return classes
        
        from eleves.models import Classe
        
        classes = list(
            Classe.objects.filter(ecole=school)
            .select_related('ecole')
            .prefetch_related('eleves')
            .annotate(nb_eleves=Count('eleves'))
        )
        
        if use_cache:
            cache.set(cache_key, classes, 600)  # 10 minutes
        
        return classes
    
    @staticmethod
    def invalidate_caches(patterns):
        """
        Invalide plusieurs caches en une fois
        """
        cache.delete_many(patterns)
        logger.info(f"Invalidated {len(patterns)} cache keys")
    
    @staticmethod
    def warm_up_cache(user):
        """
        Pré-charge les caches importants pour un utilisateur
        """
        try:
            # Dashboard stats
            QueryOptimizer.get_dashboard_stats(user, use_cache=True)
            
            # École utilisateur
            from utilisateurs.utils import user_school, user_is_admin
            if not user_is_admin(user):
                school = user_school(user)
                if school:
                    QueryOptimizer.get_school_classes(school, use_cache=True)
                    QueryOptimizer.get_payment_summary(school, use_cache=True)
            
            logger.info(f"Cache warmed up for user {user.id}")
        except Exception as e:
            logger.error(f"Error warming up cache for user {user.id}: {e}")

class PaginationOptimizer:
    """
    Optimiseur pour la pagination
    """
    
    @staticmethod
    def optimize_pagination(queryset, page, per_page=20):
        """Pagine une requête, y compris vide, avec un décompte à jour."""
        from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

        # Paginator mémorise déjà count pour cette requête. Un cache partagé
        # peut périmer après écriture et str(queryset.none().query) lève une erreur.
        paginator = Paginator(queryset, per_page)
        try:
            page_obj = paginator.page(page)
        except (EmptyPage, PageNotAnInteger):
            page_obj = paginator.page(1)
        return page_obj, paginator
