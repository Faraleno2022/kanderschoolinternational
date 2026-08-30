from django.db import models
from django.utils import timezone
from eleves.models import Eleve
from synchronisation.mixins import SyncTrackedModel


class AbonnementBus(SyncTrackedModel):
    class Statut(models.TextChoices):
        ACTIF = 'ACTIF', 'Actif'
        EXPIRE = 'EXPIRE', 'Expiré'
        SUSPENDU = 'SUSPENDU', 'Suspendu'

    class Periodicite(models.TextChoices):
        MENSUEL = 'MENSUEL', 'Mensuel'
        ANNUEL = 'ANNUEL', 'Annuel'
        TRANCHE_1 = 'T1', "1ère Tranche"
        TRANCHE_2 = 'T2', "2ème Tranche"
        TRANCHE_3 = 'T3', "3ème Tranche"

    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='abonnements_bus')
    montant = models.DecimalField(max_digits=10, decimal_places=0)
    reference_paiement = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name="Référence externe / n° reçu",
        help_text="Numéro du reçu, référence Mobile Money, chèque ou virement.",
    )
    periodicite = models.CharField(max_length=10, choices=Periodicite.choices, default=Periodicite.MENSUEL)
    date_debut = models.DateField(default=timezone.localdate)
    date_expiration = models.DateField(db_index=True)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.ACTIF, db_index=True)

    # Alertes / relances
    alerte_avant_jours = models.PositiveIntegerField(default=7)
    derniere_relance = models.DateTimeField(null=True, blank=True)

    # Infos logistiques
    zone = models.CharField(max_length=100, blank=True)
    itineraire = models.CharField(max_length=200, blank=True)
    point_arret = models.CharField(max_length=150, blank=True)

    # Contact relance
    contact_parent = models.CharField(max_length=100, blank=True)

    observations = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Abonnement bus'
        verbose_name_plural = 'Abonnements bus'
        indexes = [
            models.Index(fields=['eleve', 'statut']),
            models.Index(fields=['eleve', 'date_expiration']),
            models.Index(fields=['statut', 'date_expiration']),
        ]

    def __str__(self):
        return f"Bus: {self.eleve} ({self.get_periodicite_display()})"

    @property
    def est_proche_expiration(self) -> bool:
        if not self.date_expiration:
            return False
        today = timezone.localdate()
        delta = (self.date_expiration - today).days
        return 0 <= delta <= (self.alerte_avant_jours or 7)

    @property
    def est_expire(self) -> bool:
        if not self.date_expiration:
            return False
        return timezone.localdate() > self.date_expiration


class AbonnementCantine(SyncTrackedModel):
    """Modèle pour gérer les abonnements à la cantine scolaire"""
    
    class Statut(models.TextChoices):
        ACTIF = 'ACTIF', 'Actif'
        EXPIRE = 'EXPIRE', 'Expiré'
        SUSPENDU = 'SUSPENDU', 'Suspendu'
    
    class Periodicite(models.TextChoices):
        JOURNALIER = 'JOURNALIER', 'Journalier'
        HEBDOMADAIRE = 'HEBDOMADAIRE', 'Hebdomadaire'
        MENSUEL = 'MENSUEL', 'Mensuel'
        TRIMESTRIEL = 'TRIMESTRIEL', 'Trimestriel'
        ANNUEL = 'ANNUEL', 'Annuel'
    
    class TypeRepas(models.TextChoices):
        DEJEUNER = 'DEJEUNER', 'Déjeuner uniquement'
        GOUTER = 'GOUTER', 'Goûter uniquement'
        COMPLET = 'COMPLET', 'Déjeuner + Goûter'
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='abonnements_cantine')
    montant = models.DecimalField(max_digits=10, decimal_places=0, verbose_name="Montant (GNF)")
    reference_paiement = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name="Référence externe / n° reçu",
        help_text="Numéro du reçu, référence Mobile Money, chèque ou virement.",
    )
    periodicite = models.CharField(max_length=15, choices=Periodicite.choices, default=Periodicite.MENSUEL)
    type_repas = models.CharField(max_length=10, choices=TypeRepas.choices, default=TypeRepas.DEJEUNER)
    
    date_debut = models.DateField(default=timezone.localdate, verbose_name="Date de début")
    date_expiration = models.DateField(db_index=True, verbose_name="Date d'expiration")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.ACTIF, db_index=True)
    
    # Alertes / relances
    alerte_avant_jours = models.PositiveIntegerField(default=7, verbose_name="Alerte avant (jours)")
    derniere_relance = models.DateTimeField(null=True, blank=True, verbose_name="Dernière relance")
    
    # Régime alimentaire et allergies
    regime_alimentaire = models.CharField(
        max_length=100, 
        blank=True, 
        verbose_name="Régime alimentaire",
        help_text="Ex: Végétarien, Sans porc, Halal, etc."
    )
    allergies = models.TextField(blank=True, verbose_name="Allergies alimentaires")
    
    # Contact relance
    contact_parent = models.CharField(max_length=100, blank=True, verbose_name="Contact parent")
    
    observations = models.TextField(blank=True, verbose_name="Observations")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Abonnement cantine'
        verbose_name_plural = 'Abonnements cantine'
        indexes = [
            models.Index(fields=['eleve', 'statut']),
            models.Index(fields=['eleve', 'date_expiration']),
            models.Index(fields=['statut', 'date_expiration']),
        ]
    
    def __str__(self):
        return f"Cantine: {self.eleve} ({self.get_periodicite_display()})"
    
    @property
    def est_proche_expiration(self) -> bool:
        """Vérifie si l'abonnement est proche de l'expiration"""
        if not self.date_expiration:
            return False
        today = timezone.localdate()
        delta = (self.date_expiration - today).days
        return 0 <= delta <= (self.alerte_avant_jours or 7)
    
    @property
    def est_expire(self) -> bool:
        """Vérifie si l'abonnement est expiré"""
        if not self.date_expiration:
            return False
        return timezone.localdate() > self.date_expiration
    
    @property
    def jours_restants(self) -> int:
        """Retourne le nombre de jours restants avant expiration"""
        if not self.date_expiration:
            return 0
        today = timezone.localdate()
        delta = (self.date_expiration - today).days
        return max(0, delta)
