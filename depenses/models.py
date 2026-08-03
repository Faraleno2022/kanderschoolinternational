from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
from synchronisation.mixins import SyncTrackedModel

class CategorieDepense(SyncTrackedModel):
    """Modèle pour les catégories de dépenses"""
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom de la catégorie")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    code = models.CharField(max_length=10, unique=True, verbose_name="Code")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    
    class Meta:
        verbose_name = "Catégorie de dépense"
        verbose_name_plural = "Catégories de dépenses"
    
    def __str__(self):
        return f"{self.code} - {self.nom}"

class Fournisseur(SyncTrackedModel):
    """Modèle pour les fournisseurs"""
    TYPE_CHOICES = [
        ('ENTREPRISE', 'Entreprise'),
        ('PARTICULIER', 'Particulier'),
        ('ADMINISTRATION', 'Administration'),
    ]
    
    nom = models.CharField(max_length=200, verbose_name="Nom du fournisseur")
    type_fournisseur = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    adresse = models.TextField(verbose_name="Adresse")
    telephone = models.CharField(max_length=20, verbose_name="Téléphone")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    
    # Informations bancaires
    numero_compte = models.CharField(max_length=50, blank=True, null=True, verbose_name="Numéro de compte")
    banque = models.CharField(max_length=100, blank=True, null=True, verbose_name="Banque")
    
    # Informations fiscales
    numero_nif = models.CharField(max_length=20, blank=True, null=True, verbose_name="Numéro NIF")
    numero_rccm = models.CharField(max_length=20, blank=True, null=True, verbose_name="Numéro RCCM")
    
    actif = models.BooleanField(default=True, verbose_name="Actif")
    date_creation = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Fournisseur"
        verbose_name_plural = "Fournisseurs"
        ordering = ['nom']
    
    def __str__(self):
        return self.nom

class Depense(SyncTrackedModel):
    """Modèle principal pour les dépenses"""
    STATUT_CHOICES = [
        ('BROUILLON', 'Brouillon'),
        ('EN_ATTENTE', 'En attente de validation'),
        ('VALIDEE', 'Validée'),
        ('PAYEE', 'Payée'),
        ('REJETEE', 'Rejetée'),
        ('ANNULEE', 'Annulée'),
    ]
    
    TYPE_CHOICES = [
        ('FONCTIONNEMENT', 'Fonctionnement'),
        ('INVESTISSEMENT', 'Investissement'),
        ('PERSONNEL', 'Personnel'),
        ('MAINTENANCE', 'Maintenance'),
        ('AUTRE', 'Autre'),
    ]
    
    # Références
    numero_facture = models.CharField(max_length=50, verbose_name="Numéro de facture")
    categorie = models.ForeignKey(CategorieDepense, on_delete=models.CASCADE, related_name='depenses')
    fournisseur = models.ForeignKey(Fournisseur, on_delete=models.CASCADE, related_name='depenses')
    
    # Informations de la dépense
    libelle = models.CharField(max_length=200, verbose_name="Libellé")
    description = models.TextField(verbose_name="Description")
    type_depense = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type de dépense")
    
    # Montants
    montant_ht = models.DecimalField(
        max_digits=12, decimal_places=0, default=Decimal('0'),
        verbose_name="Montant HT (GNF)"
    )
    taux_tva = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0'),
        verbose_name="Taux TVA (%)"
    )
    montant_tva = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'),
        verbose_name="Montant TVA (GNF)"
    )
    montant_ttc = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'),
        verbose_name="Montant TTC (GNF)"
    )
    
    # Dates
    date_facture = models.DateField(verbose_name="Date de facture")
    date_echeance = models.DateField(verbose_name="Date d'échéance")
    date_paiement = models.DateField(null=True, blank=True, verbose_name="Date de paiement")
    
    # Statut et validation
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='BROUILLON', verbose_name="Statut")
    observations = models.TextField(blank=True, null=True, verbose_name="Observations")
    
    # Métadonnées
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='depenses_creees'
    )
    valide_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='depenses_validees'
    )
    date_validation = models.DateTimeField(null=True, blank=True, verbose_name="Date de validation")
    
    class Meta:
        verbose_name = "Dépense"
        verbose_name_plural = "Dépenses"
        ordering = ['-date_facture', '-date_creation']
        unique_together = ['numero_facture', 'fournisseur']
    
    def __str__(self):
        return f"{self.numero_facture} - {self.libelle} - {self.montant_ttc:,.0f} GNF"
    
    def save(self, *args, **kwargs):
        from decimal import ROUND_HALF_UP
        # Calcul automatique de la TVA et du TTC avec précision Decimal
        if self.montant_ht and self.taux_tva:
            self.montant_tva = ((self.montant_ht * self.taux_tva) / Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            self.montant_ttc = self.montant_ht + self.montant_tva
        elif self.montant_ht:
            self.montant_tva = Decimal('0')
            self.montant_ttc = self.montant_ht
        super().save(*args, **kwargs)
    
    @property
    def est_en_retard(self):
        from datetime import date
        return self.date_echeance < date.today() and self.statut not in ['PAYEE', 'ANNULEE']

class PieceJustificative(SyncTrackedModel):
    """Modèle pour les pièces justificatives des dépenses"""
    TYPE_CHOICES = [
        ('FACTURE', 'Facture'),
        ('RECU', 'Reçu'),
        ('BON_COMMANDE', 'Bon de commande'),
        ('BON_LIVRAISON', 'Bon de livraison'),
        ('DEVIS', 'Devis'),
        ('AUTRE', 'Autre'),
    ]
    
    depense = models.ForeignKey(Depense, on_delete=models.CASCADE, related_name='pieces_justificatives')
    type_piece = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type de pièce")
    nom_fichier = models.CharField(max_length=200, verbose_name="Nom du fichier")
    fichier = models.FileField(upload_to='depenses/pieces/', verbose_name="Fichier")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    
    date_upload = models.DateTimeField(auto_now_add=True, verbose_name="Date d'upload")
    uploade_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Pièce justificative"
        verbose_name_plural = "Pièces justificatives"
    
    def __str__(self):
        return f"{self.depense.numero_facture} - {self.get_type_piece_display()}"

class BudgetAnnuel(SyncTrackedModel):
    """Modèle pour la gestion du budget annuel par catégorie"""
    annee = models.PositiveIntegerField(verbose_name="Année")
    categorie = models.ForeignKey(CategorieDepense, on_delete=models.CASCADE, related_name='budgets')
    
    # Montants budgétaires
    budget_prevu = models.DecimalField(
        max_digits=12, decimal_places=0, default=Decimal('0'),
        verbose_name="Budget prévu (GNF)"
    )
    budget_engage = models.DecimalField(
        max_digits=12, decimal_places=0, default=Decimal('0'),
        verbose_name="Budget engagé (GNF)"
    )
    budget_consomme = models.DecimalField(
        max_digits=12, decimal_places=0, default=Decimal('0'),
        verbose_name="Budget consommé (GNF)"
    )
    
    # Métadonnées
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Budget annuel"
        verbose_name_plural = "Budgets annuels"
        unique_together = ['annee', 'categorie']
        ordering = ['-annee', 'categorie__nom']
    
    def __str__(self):
        return f"Budget {self.annee} - {self.categorie.nom}"
    
    @property
    def budget_disponible(self):
        return self.budget_prevu - self.budget_engage
    
    @property
    def taux_consommation(self):
        if self.budget_prevu > 0:
            return (self.budget_consomme / self.budget_prevu) * 100
        return 0
    
    @property
    def taux_engagement(self):
        if self.budget_prevu > 0:
            return (self.budget_engage / self.budget_prevu) * 100
        return 0

class HistoriqueDepense(SyncTrackedModel):
    """Modèle pour l'historique des modifications des dépenses"""
    ACTION_CHOICES = [
        ('CREATION', 'Création'),
        ('MODIFICATION', 'Modification'),
        ('VALIDATION', 'Validation'),
        ('PAIEMENT', 'Paiement'),
        ('REJET', 'Rejet'),
        ('ANNULATION', 'Annulation'),
    ]
    
    depense = models.ForeignKey(Depense, on_delete=models.CASCADE, related_name='historique')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="Action")
    description = models.TextField(verbose_name="Description")
    ancien_statut = models.CharField(max_length=20, blank=True, null=True, verbose_name="Ancien statut")
    nouveau_statut = models.CharField(max_length=20, blank=True, null=True, verbose_name="Nouveau statut")
    
    date_action = models.DateTimeField(auto_now_add=True, verbose_name="Date de l'action")
    utilisateur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Historique dépense"
        verbose_name_plural = "Historiques dépenses"
        ordering = ['-date_action']
    
    def __str__(self):
        return f"{self.depense.numero_facture} - {self.get_action_display()} ({self.date_action.strftime('%d/%m/%Y')})"


# Importer les modèles de logistique et bibliothèque
from .models_logistique import (
    CategorieArticle, Article, BienEtablissement, MouvementStock,
    Inventaire, LigneInventaire, SuiviPapierRam
)
from .models_bibliotheque import (
    CategorieLivre, Livre, Emprunt, Reservation,
    HistoriqueLivre, ParametreBibliotheque
)
from .models_fournitures import ProduitFourniture, VenteFourniture
