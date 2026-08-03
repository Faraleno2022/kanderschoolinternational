from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from eleves.models import Eleve
from datetime import timedelta
from synchronisation.mixins import SyncTrackedModel


class CategorieLivre(SyncTrackedModel):
    """Catégories de livres"""
    nom = models.CharField(max_length=100, verbose_name="Nom de la catégorie")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code")
    description = models.TextField(blank=True, verbose_name="Description")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    
    class Meta:
        verbose_name = "Catégorie de livre"
        verbose_name_plural = "Catégories de livres"
        ordering = ['nom']
    
    def __str__(self):
        return f"{self.code} - {self.nom}"


class Livre(SyncTrackedModel):
    """Livres de la bibliothèque"""
    ETAT_CHOICES = [
        ('NEUF', 'Neuf'),
        ('TRES_BON', 'Très bon état'),
        ('BON', 'Bon état'),
        ('MOYEN', 'État moyen'),
        ('MAUVAIS', 'Mauvais état'),
        ('HORS_SERVICE', 'Hors service'),
    ]
    
    STATUT_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('EMPRUNTE', 'Emprunté'),
        ('RESERVE', 'Réservé'),
        ('PERDU', 'Perdu'),
        ('EN_REPARATION', 'En réparation'),
        ('RETIRE', 'Retiré'),
    ]
    
    # Identification
    code_livre = models.CharField(max_length=50, unique=True, verbose_name="Code du livre")
    isbn = models.CharField(max_length=20, blank=True, verbose_name="ISBN")
    titre = models.CharField(max_length=300, verbose_name="Titre")
    auteur = models.CharField(max_length=200, verbose_name="Auteur")
    categorie = models.ForeignKey(CategorieLivre, on_delete=models.CASCADE, related_name='livres')
    
    # Informations éditoriales
    editeur = models.CharField(max_length=200, blank=True, verbose_name="Éditeur")
    annee_publication = models.PositiveIntegerField(null=True, blank=True, verbose_name="Année de publication")
    edition = models.CharField(max_length=50, blank=True, verbose_name="Édition")
    langue = models.CharField(max_length=50, default='Français', verbose_name="Langue")
    nombre_pages = models.PositiveIntegerField(null=True, blank=True, verbose_name="Nombre de pages")
    
    # Description
    resume = models.TextField(blank=True, verbose_name="Résumé")
    mots_cles = models.CharField(max_length=300, blank=True, verbose_name="Mots-clés")
    
    # Localisation et état
    emplacement = models.CharField(max_length=100, verbose_name="Emplacement (rayon/étagère)")
    etat = models.CharField(max_length=20, choices=ETAT_CHOICES, default='BON', verbose_name="État")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='DISPONIBLE', verbose_name="Statut")
    
    # Gestion
    nombre_exemplaires = models.PositiveIntegerField(default=1, verbose_name="Nombre d'exemplaires")
    exemplaires_disponibles = models.PositiveIntegerField(default=1, verbose_name="Exemplaires disponibles")
    prix_acquisition = models.DecimalField(max_digits=10, decimal_places=0, null=True, blank=True, verbose_name="Prix d'acquisition (GNF)")
    date_acquisition = models.DateField(null=True, blank=True, verbose_name="Date d'acquisition")
    
    # Photo de couverture
    couverture = models.ImageField(upload_to='bibliotheque/couvertures/', blank=True, null=True, verbose_name="Couverture")
    
    # Métadonnées
    actif = models.BooleanField(default=True, verbose_name="Actif")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Livre"
        verbose_name_plural = "Livres"
        ordering = ['titre']
    
    def __str__(self):
        return f"{self.code_livre} - {self.titre}"
    
    @property
    def est_disponible(self):
        """Vérifie si le livre est disponible pour emprunt"""
        return self.statut == 'DISPONIBLE' and self.exemplaires_disponibles > 0
    
    @property
    def taux_disponibilite(self):
        """Pourcentage d'exemplaires disponibles"""
        if self.nombre_exemplaires > 0:
            return (self.exemplaires_disponibles / self.nombre_exemplaires) * 100
        return 0


class Emprunt(SyncTrackedModel):
    """Emprunts de livres"""
    STATUT_CHOICES = [
        ('EN_COURS', 'En cours'),
        ('RETOURNE', 'Retourné'),
        ('EN_RETARD', 'En retard'),
        ('PERDU', 'Perdu'),
        ('ANNULE', 'Annulé'),
    ]
    
    # Référence
    numero_emprunt = models.CharField(max_length=50, unique=True, verbose_name="N° emprunt")
    livre = models.ForeignKey(Livre, on_delete=models.CASCADE, related_name='emprunts')
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='emprunts_livres')
    
    # Dates
    date_emprunt = models.DateField(default=timezone.now, verbose_name="Date d'emprunt")
    date_retour_prevue = models.DateField(verbose_name="Date de retour prévue")
    date_retour_effectif = models.DateField(null=True, blank=True, verbose_name="Date de retour effectif")
    
    # Statut
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_COURS', verbose_name="Statut")
    
    # Pénalités
    jours_retard = models.IntegerField(default=0, verbose_name="Jours de retard")
    montant_penalite = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name="Montant pénalité (GNF)")
    penalite_payee = models.BooleanField(default=False, verbose_name="Pénalité payée")
    
    # Observations
    observations_emprunt = models.TextField(blank=True, verbose_name="Observations à l'emprunt")
    observations_retour = models.TextField(blank=True, verbose_name="Observations au retour")
    etat_livre_emprunt = models.CharField(max_length=20, blank=True, verbose_name="État du livre à l'emprunt")
    etat_livre_retour = models.CharField(max_length=20, blank=True, verbose_name="État du livre au retour")
    
    # Métadonnées
    date_creation = models.DateTimeField(auto_now_add=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='emprunts_crees')
    traite_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='emprunts_traites')
    
    class Meta:
        verbose_name = "Emprunt"
        verbose_name_plural = "Emprunts"
        ordering = ['-date_emprunt']
    
    def __str__(self):
        return f"{self.numero_emprunt} - {self.livre.titre} ({self.eleve})"
    
    @property
    def est_en_retard(self):
        """Vérifie si l'emprunt est en retard"""
        if self.statut == 'EN_COURS':
            return timezone.now().date() > self.date_retour_prevue
        return False
    
    @property
    def jours_restants(self):
        """Nombre de jours restants avant la date de retour"""
        if self.statut == 'EN_COURS':
            delta = (self.date_retour_prevue - timezone.now().date()).days
            return max(0, delta)
        return 0
    
    def calculer_penalite(self, tarif_journalier=1000):
        """Calcule la pénalité de retard"""
        if self.date_retour_effectif and self.date_retour_effectif > self.date_retour_prevue:
            self.jours_retard = (self.date_retour_effectif - self.date_retour_prevue).days
            self.montant_penalite = self.jours_retard * tarif_journalier
        elif self.est_en_retard:
            self.jours_retard = (timezone.now().date() - self.date_retour_prevue).days
            self.montant_penalite = self.jours_retard * tarif_journalier
    
    def save(self, *args, **kwargs):
        # Calculer la date de retour prévue si non définie (14 jours par défaut)
        if not self.date_retour_prevue:
            self.date_retour_prevue = self.date_emprunt + timedelta(days=14)
        
        # Mettre à jour le statut si en retard
        if self.statut == 'EN_COURS' and self.est_en_retard:
            self.statut = 'EN_RETARD'
        
        # Calculer la pénalité
        self.calculer_penalite()
        
        super().save(*args, **kwargs)


class Reservation(SyncTrackedModel):
    """Réservations de livres"""
    STATUT_CHOICES = [
        ('EN_ATTENTE', 'En attente'),
        ('DISPONIBLE', 'Disponible'),
        ('EMPRUNTEE', 'Empruntée'),
        ('ANNULEE', 'Annulée'),
        ('EXPIREE', 'Expirée'),
    ]
    
    # Référence
    numero_reservation = models.CharField(max_length=50, unique=True, verbose_name="N° réservation")
    livre = models.ForeignKey(Livre, on_delete=models.CASCADE, related_name='reservations')
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='reservations_livres')
    
    # Dates
    date_reservation = models.DateTimeField(default=timezone.now, verbose_name="Date de réservation")
    date_expiration = models.DateTimeField(verbose_name="Date d'expiration")
    date_notification = models.DateTimeField(null=True, blank=True, verbose_name="Date de notification")
    date_mise_disponible = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date de mise à disposition",
    )
    date_traitement = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date de traitement",
    )
    
    # Statut
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_ATTENTE', verbose_name="Statut")
    
    # Observations
    observations = models.TextField(blank=True, verbose_name="Observations")
    exemplaire_bloque = models.BooleanField(
        default=False,
        verbose_name="Exemplaire mis de côté",
        help_text="Indique qu'un exemplaire disponible est réservé physiquement pour l'élève.",
    )
    
    # Métadonnées
    date_creation = models.DateTimeField(auto_now_add=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    traitee_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations_bibliotheque_traitees',
    )
    emprunt = models.OneToOneField(
        Emprunt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservation_source',
        verbose_name="Emprunt créé",
    )
    
    class Meta:
        verbose_name = "Réservation"
        verbose_name_plural = "Réservations"
        ordering = ['-date_reservation']
        indexes = [
            models.Index(fields=['statut', 'date_expiration']),
            models.Index(fields=['livre', 'statut', 'date_reservation']),
        ]
    
    def __str__(self):
        return f"{self.numero_reservation} - {self.livre.titre} ({self.eleve})"
    
    @property
    def est_expiree(self):
        """Vérifie si la réservation est expirée"""
        return (
            self.statut in {'EN_ATTENTE', 'DISPONIBLE'}
            and timezone.now() >= self.date_expiration
        )

    @property
    def jours_restants(self):
        """Nombre de jours avant l'expiration de la réservation active."""
        if self.statut not in {'EN_ATTENTE', 'DISPONIBLE'}:
            return 0
        secondes = (self.date_expiration - timezone.now()).total_seconds()
        if secondes <= 0:
            return 0
        return max(1, int((secondes + 86399) // 86400))

    @property
    def rang_attente(self):
        """Position dans la file d'attente du livre."""
        if self.statut != 'EN_ATTENTE':
            return None
        return Reservation.objects.filter(
            livre=self.livre,
            statut='EN_ATTENTE',
            date_reservation__lt=self.date_reservation,
        ).count() + 1
    
    def save(self, *args, **kwargs):
        # Définir la date d'expiration (7 jours par défaut)
        if not self.date_expiration:
            self.date_expiration = timezone.now() + timedelta(days=7)
        
        super().save(*args, **kwargs)


class HistoriqueLivre(SyncTrackedModel):
    """Historique des actions sur les livres"""
    ACTION_CHOICES = [
        ('ACQUISITION', 'Acquisition'),
        ('EMPRUNT', 'Emprunt'),
        ('RETOUR', 'Retour'),
        ('RESERVATION', 'Réservation'),
        ('REPARATION', 'Réparation'),
        ('PERTE', 'Perte'),
        ('RETRAIT', 'Retrait'),
        ('MODIFICATION', 'Modification'),
    ]
    
    livre = models.ForeignKey(Livre, on_delete=models.CASCADE, related_name='historique')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="Action")
    description = models.TextField(verbose_name="Description")
    
    date_action = models.DateTimeField(auto_now_add=True, verbose_name="Date de l'action")
    utilisateur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Historique livre"
        verbose_name_plural = "Historiques livres"
        ordering = ['-date_action']
    
    def __str__(self):
        return f"{self.livre.titre} - {self.get_action_display()} ({self.date_action.strftime('%d/%m/%Y')})"


class ParametreBibliotheque(SyncTrackedModel):
    """Paramètres de la bibliothèque"""
    # Durées
    duree_emprunt_defaut = models.PositiveIntegerField(default=14, verbose_name="Durée d'emprunt par défaut (jours)")
    duree_reservation_defaut = models.PositiveIntegerField(default=7, verbose_name="Durée de réservation par défaut (jours)")
    
    # Limites
    nombre_emprunts_max = models.PositiveIntegerField(default=3, verbose_name="Nombre max d'emprunts simultanés")
    nombre_reservations_max = models.PositiveIntegerField(default=2, verbose_name="Nombre max de réservations simultanées")
    
    # Pénalités
    penalite_retard_journalier = models.DecimalField(max_digits=10, decimal_places=0, default=1000, verbose_name="Pénalité de retard par jour (GNF)")
    penalite_perte = models.DecimalField(max_digits=10, decimal_places=0, default=50000, verbose_name="Pénalité pour perte (GNF)")
    penalite_degradation = models.DecimalField(max_digits=10, decimal_places=0, default=25000, verbose_name="Pénalité pour dégradation (GNF)")
    
    # Notifications
    rappel_avant_echeance = models.PositiveIntegerField(default=3, verbose_name="Rappel avant échéance (jours)")
    
    # Métadonnées
    date_modification = models.DateTimeField(auto_now=True)
    modifie_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Paramètre bibliothèque"
        verbose_name_plural = "Paramètres bibliothèque"
    
    def __str__(self):
        return "Paramètres de la bibliothèque"
