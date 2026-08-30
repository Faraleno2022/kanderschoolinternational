from django.core.cache import cache
from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone
from eleves.models import Eleve
from synchronisation.mixins import SyncTrackedModel


class TypePeriodiciteAbonnement(models.Model):
    """Périodicité configurable pour les abonnements bus et cantine."""

    class Service(models.TextChoices):
        BUS = 'BUS', 'Bus scolaire'
        CANTINE = 'CANTINE', 'Cantine scolaire'

    service = models.CharField(max_length=10, choices=Service.choices, db_index=True)
    code = models.CharField(
        max_length=30,
        help_text="Code technique stable, par exemple MENSUEL ou ANNUEL.",
    )
    libelle = models.CharField(max_length=100)
    duree_mois = models.PositiveSmallIntegerField(
        default=0,
        help_text="Nombre de mois à ajouter automatiquement à la date de début.",
    )
    duree_jours = models.PositiveSmallIntegerField(
        default=0,
        help_text="Nombre de jours à ajouter après les mois (0 si non applicable).",
    )
    actif = models.BooleanField(default=True, db_index=True)
    ordre = models.PositiveSmallIntegerField(default=10)

    class Meta:
        ordering = ('service', 'ordre', 'libelle')
        verbose_name = "Type d'abonnement"
        verbose_name_plural = "Types d'abonnement"
        constraints = [
            models.UniqueConstraint(
                fields=('service', 'code'),
                name='bus_type_periodicite_service_code_unique',
            ),
        ]

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper().replace(' ', '_')
        super().save(*args, **kwargs)
        cache.delete(self.cache_key(self.service, self.code))

    def delete(self, *args, **kwargs):
        cache_key = self.cache_key(self.service, self.code)
        result = super().delete(*args, **kwargs)
        cache.delete(cache_key)
        return result

    @staticmethod
    def cache_key(service, code):
        return f'bus:periodicite:{service}:{code}'

    @classmethod
    def libelle_pour(cls, service, code, fallback=None):
        code = str(code or '')
        key = cls.cache_key(service, code)
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            label = cls.objects.filter(service=service, code=code).values_list('libelle', flat=True).first()
        except (OperationalError, ProgrammingError):
            label = None
        label = label or fallback or code or '-'
        cache.set(key, label, 60)
        return label

    @classmethod
    def libelles(cls, service, fallback_choices=()):
        labels = dict(fallback_choices)
        try:
            labels.update(cls.objects.filter(service=service).values_list('code', 'libelle'))
        except (OperationalError, ProgrammingError):
            pass
        return labels

    def __str__(self):
        return f'{self.libelle} ({self.get_service_display()})'


class TypeRepasCantine(models.Model):
    """Type de repas personnalisable depuis l'administration Django."""

    code = models.CharField(
        max_length=30,
        unique=True,
        help_text="Code technique stable, par exemple DEJEUNER ou REPAS_14H.",
    )
    libelle = models.CharField(max_length=100)
    heure_service = models.TimeField(null=True, blank=True)
    actif = models.BooleanField(default=True, db_index=True)
    ordre = models.PositiveSmallIntegerField(default=10)

    class Meta:
        ordering = ('ordre', 'libelle')
        verbose_name = 'Type de repas cantine'
        verbose_name_plural = 'Types de repas cantine'

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper().replace(' ', '_')
        super().save(*args, **kwargs)
        cache.delete(self.cache_key(self.code))

    def delete(self, *args, **kwargs):
        cache_key = self.cache_key(self.code)
        result = super().delete(*args, **kwargs)
        cache.delete(cache_key)
        return result

    @staticmethod
    def cache_key(code):
        return f'bus:type-repas:{code}'

    @classmethod
    def libelle_pour(cls, code, fallback=None):
        code = str(code or '')
        key = cls.cache_key(code)
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            label = cls.objects.filter(code=code).values_list('libelle', flat=True).first()
        except (OperationalError, ProgrammingError):
            label = None
        label = label or fallback or code or '-'
        cache.set(key, label, 60)
        return label

    def __str__(self):
        if self.heure_service:
            return f'{self.libelle} ({self.heure_service:%H:%M})'
        return self.libelle


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
    periodicite = models.CharField(
        max_length=30,
        default=Periodicite.MENSUEL,
        verbose_name="Type d'abonnement",
    )
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

    def get_periodicite_display(self):
        fallback = dict(self.Periodicite.choices).get(self.periodicite, self.periodicite)
        return TypePeriodiciteAbonnement.libelle_pour(
            TypePeriodiciteAbonnement.Service.BUS,
            self.periodicite,
            fallback,
        )

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
        REPAS_14H = 'REPAS_14H', 'Repas de 14 h'
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='abonnements_cantine')
    montant = models.DecimalField(max_digits=10, decimal_places=0, verbose_name="Montant (GNF)")
    reference_paiement = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name="Référence externe / n° reçu",
        help_text="Numéro du reçu, référence Mobile Money, chèque ou virement.",
    )
    periodicite = models.CharField(
        max_length=30,
        default=Periodicite.MENSUEL,
        verbose_name="Type d'abonnement",
    )
    type_repas = models.CharField(
        max_length=30,
        default=TypeRepas.DEJEUNER,
        verbose_name='Type de repas',
    )
    
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

    def get_periodicite_display(self):
        fallback = dict(self.Periodicite.choices).get(self.periodicite, self.periodicite)
        return TypePeriodiciteAbonnement.libelle_pour(
            TypePeriodiciteAbonnement.Service.CANTINE,
            self.periodicite,
            fallback,
        )

    def get_type_repas_display(self):
        fallback = dict(self.TypeRepas.choices).get(self.type_repas, self.type_repas)
        return TypeRepasCantine.libelle_pour(self.type_repas, fallback)
    
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
