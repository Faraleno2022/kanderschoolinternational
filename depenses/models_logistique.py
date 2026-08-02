from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from synchronisation.mixins import SyncTrackedModel
from django.core.exceptions import ValidationError


class CategorieArticle(SyncTrackedModel):
    """Catégories d'articles logistiques"""
    TYPE_CHOICES = [
        ('FOURNITURE', 'Fournitures scolaires'),
        ('MOBILIER', 'Mobilier'),
        ('EQUIPEMENT', 'Équipement pédagogique'),
        ('UNIFORME', 'Uniformes'),
        ('MATERIEL_INFO', 'Matériel informatique'),
        ('INFRASTRUCTURE', 'Infrastructure'),
        ('AUTRE', 'Autre'),
    ]
    
    nom = models.CharField(max_length=100, verbose_name="Nom de la catégorie")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code")
    type_categorie = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    description = models.TextField(blank=True, verbose_name="Description")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    
    class Meta:
        verbose_name = "Catégorie d'article"
        verbose_name_plural = "Catégories d'articles"
        ordering = ['type_categorie', 'nom']
    
    def __str__(self):
        return f"{self.code} - {self.nom}"


class Article(SyncTrackedModel):
    """Articles en stock"""
    UNITE_CHOICES = [
        ('PIECE', 'Pièce'),
        ('BOITE', 'Boîte'),
        ('PAQUET', 'Paquet'),
        ('RAME', 'Rame'),
        ('CARTON', 'Carton'),
        ('UNITE', 'Unité'),
        ('KG', 'Kilogramme'),
        ('LITRE', 'Litre'),
        ('METRE', 'Mètre'),
    ]
    
    ETAT_CHOICES = [
        ('NEUF', 'Neuf'),
        ('BON', 'Bon état'),
        ('MOYEN', 'État moyen'),
        ('MAUVAIS', 'Mauvais état'),
        ('HORS_SERVICE', 'Hors service'),
    ]
    
    # Identification
    code_article = models.CharField(max_length=50, unique=True, verbose_name="Code article")
    nom = models.CharField(max_length=200, verbose_name="Nom de l'article")
    categorie = models.ForeignKey(CategorieArticle, on_delete=models.CASCADE, related_name='articles')
    
    # Description
    description = models.TextField(blank=True, verbose_name="Description")
    marque = models.CharField(max_length=100, blank=True, verbose_name="Marque")
    reference = models.CharField(max_length=100, blank=True, verbose_name="Référence")
    
    # Stock
    unite_mesure = models.CharField(max_length=20, choices=UNITE_CHOICES, default='PIECE', verbose_name="Unité de mesure")
    stock_actuel = models.IntegerField(default=0, verbose_name="Stock actuel")
    stock_minimum = models.IntegerField(default=0, verbose_name="Stock minimum")
    stock_maximum = models.IntegerField(default=0, verbose_name="Stock maximum")
    
    # Prix
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=0, default=Decimal('0'), verbose_name="Prix unitaire (GNF)")
    
    # État et localisation
    etat = models.CharField(max_length=20, choices=ETAT_CHOICES, default='NEUF', verbose_name="État")
    emplacement = models.CharField(max_length=200, blank=True, verbose_name="Emplacement")
    
    # Photo
    photo = models.ImageField(upload_to='logistique/articles/', blank=True, null=True, verbose_name="Photo")
    
    # Métadonnées
    actif = models.BooleanField(default=True, verbose_name="Actif")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"
        ordering = ['categorie', 'nom']
    
    def __str__(self):
        return f"{self.code_article} - {self.nom}"
    
    @property
    def valeur_stock(self):
        """Valeur totale du stock"""
        return self.stock_actuel * self.prix_unitaire
    
    @property
    def alerte_stock(self):
        """Vérifie si le stock est en dessous du minimum"""
        return self.stock_actuel <= self.stock_minimum
    
    @property
    def taux_stock(self):
        """Pourcentage de remplissage du stock"""
        if self.stock_maximum > 0:
            return (self.stock_actuel / self.stock_maximum) * 100
        return 0


class BienEtablissement(SyncTrackedModel):
    """Biens et infrastructures de l'établissement"""
    TYPE_CHOICES = [
        # Infrastructures
        ('SALLE_CLASSE', 'Salle de classe'),
        ('BUREAU', 'Bureau'),
        ('LABORATOIRE', 'Laboratoire'),
        ('BIBLIOTHEQUE', 'Bibliothèque'),
        ('TOILETTE', 'Toilette'),
        ('CANTINE', 'Cantine'),
        ('TERRAIN_SPORT', 'Terrain de sport'),
        ('COUR', 'Cour'),
        ('PARKING', 'Parking'),
        # Mobilier
        ('TABLE', 'Table(s)'),
        ('CHAISE', 'Chaise(s)'),
        ('ARMOIRE', 'Armoire'),
        ('ETAGERE', 'Étagère'),
        # Équipements
        ('CLIMATISEUR', 'Climatiseur'),
        ('ORDINATEUR', 'Ordinateur'),
        ('IMPRIMANTE', 'Imprimante'),
        ('PROJECTEUR', 'Projecteur'),
        # Matériel pédagogique
        ('TABLEAU', 'Tableau'),
        ('GLOBE_TERRESTRE', 'Globe terrestre'),
        ('CARTE', 'Carte géographique'),
        ('COMPAS', 'Compas'),
        ('MARQUEUR', 'Marqueur(s)'),
        ('EQUERRE', 'Équerre'),
        # Électricité
        ('AMPOULE', 'Ampoule(s)'),
        ('VENTILATEUR', 'Ventilateur'),
        # Autre
        ('AUTRE', 'Autre'),
    ]
    
    ETAT_CHOICES = [
        ('EXCELLENT', 'Excellent'),
        ('BON', 'Bon'),
        ('MOYEN', 'Moyen'),
        ('MAUVAIS', 'Mauvais'),
        ('HORS_SERVICE', 'Hors service'),
    ]
    
    # Identification
    code_bien = models.CharField(max_length=50, unique=True, verbose_name="Code du bien")
    ecole = models.ForeignKey(
        'eleves.Ecole', on_delete=models.CASCADE, related_name='biens_logistiques',
        null=True, blank=True, verbose_name="Établissement",
    )
    nom = models.CharField(max_length=200, verbose_name="Nom/Désignation")
    type_bien = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type de bien")
    marque = models.CharField(max_length=100, blank=True, verbose_name="Marque")

    # Suivi simplifié des quantités
    quantite_achetee = models.PositiveIntegerField(default=1, verbose_name="Quantité achetée")
    quantite_utilisee = models.PositiveIntegerField(default=0, verbose_name="Quantité utilisée")
    quantite_gate = models.PositiveIntegerField(default=0, verbose_name="Quantité gâtée/perdue")
    prix_achat_unitaire = models.DecimalField(
        max_digits=15, decimal_places=0, default=Decimal('0'),
        verbose_name="Prix d'achat unitaire (GNF)",
    )
    
    # Description
    description = models.TextField(blank=True, verbose_name="Description")
    localisation = models.CharField(max_length=200, verbose_name="Localisation")
    superficie = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Superficie (m²)")
    capacite = models.IntegerField(null=True, blank=True, verbose_name="Capacité (personnes/objets)")
    
    # État et valeur
    etat = models.CharField(max_length=20, choices=ETAT_CHOICES, default='BON', verbose_name="État")
    valeur_acquisition = models.DecimalField(max_digits=15, decimal_places=0, default=Decimal('0'), verbose_name="Valeur d'acquisition (GNF)")
    date_acquisition = models.DateField(null=True, blank=True, verbose_name="Date d'acquisition")
    
    # Maintenance
    date_derniere_maintenance = models.DateField(null=True, blank=True, verbose_name="Dernière maintenance")
    date_prochaine_maintenance = models.DateField(null=True, blank=True, verbose_name="Prochaine maintenance")
    
    # Photos et documents
    photo = models.ImageField(upload_to='logistique/biens/', blank=True, null=True, verbose_name="Photo")
    observations = models.TextField(blank=True, verbose_name="Observations")
    
    # Métadonnées
    actif = models.BooleanField(default=True, verbose_name="Actif")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Bien de l'établissement"
        verbose_name_plural = "Biens de l'établissement"
        ordering = ['type_bien', 'nom']
    
    def __str__(self):
        return f"{self.code_bien} - {self.nom}"
    
    @property
    def maintenance_requise(self):
        """Vérifie si une maintenance est requise"""
        if self.date_prochaine_maintenance:
            return timezone.now().date() >= self.date_prochaine_maintenance
        return False

    @property
    def quantite_disponible(self):
        return max(0, self.quantite_achetee - self.quantite_utilisee - self.quantite_gate)

    @property
    def valeur_achat_totale(self):
        return self.quantite_achetee * self.prix_achat_unitaire

    def clean(self):
        super().clean()
        consommee = (self.quantite_utilisee or 0) + (self.quantite_gate or 0)
        if consommee > (self.quantite_achetee or 0):
            raise ValidationError(
                "La quantité utilisée et la quantité gâtée ne peuvent pas dépasser la quantité achetée."
            )


class SuiviPapierRam(SyncTrackedModel):
    """Papier RAM remis par un élève ou argent payé en remplacement."""

    MODE_CHOICES = [
        ('PAPIER', 'Papier RAM remis'),
        ('ARGENT', 'Argent payé à la place'),
    ]

    ecole = models.ForeignKey(
        'eleves.Ecole', on_delete=models.CASCADE, related_name='suivis_papier_ram',
        verbose_name="Établissement",
    )
    eleve = models.ForeignKey(
        'eleves.Eleve', on_delete=models.CASCADE, related_name='suivis_papier_ram',
        verbose_name="Élève",
    )
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, verbose_name="Type de contribution")
    nombre_paquets = models.PositiveIntegerField(default=0, verbose_name="Nombre de paquets")
    montant_paye = models.DecimalField(
        max_digits=12, decimal_places=0, default=Decimal('0'),
        verbose_name="Montant payé (GNF)",
    )
    date_remise = models.DateField(default=timezone.localdate, verbose_name="Date")
    observations = models.TextField(blank=True, verbose_name="Observations")
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contribution papier RAM"
        verbose_name_plural = "Contributions papier RAM"
        ordering = ['-date_remise', '-date_creation']
        indexes = [
            models.Index(fields=['ecole', 'date_remise']),
            models.Index(fields=['eleve', 'mode']),
        ]

    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.get_mode_display()}"

    def clean(self):
        super().clean()
        if self.eleve_id and self.ecole_id:
            ecole_eleve_id = getattr(getattr(self.eleve, 'classe', None), 'ecole_id', None)
            if ecole_eleve_id != self.ecole_id:
                raise ValidationError("Élève et établissement incompatibles.")
        if self.mode == 'PAPIER':
            if not self.nombre_paquets:
                raise ValidationError({'nombre_paquets': "Indiquez au moins un paquet."})
            self.montant_paye = Decimal('0')
        elif self.mode == 'ARGENT':
            if not self.montant_paye or self.montant_paye <= 0:
                raise ValidationError({'montant_paye': "Indiquez le montant payé."})
            self.nombre_paquets = 0


class MouvementStock(SyncTrackedModel):
    """Mouvements d'entrée et sortie de stock"""
    TYPE_CHOICES = [
        ('ENTREE', 'Entrée'),
        ('SORTIE', 'Sortie'),
        ('AJUSTEMENT', 'Ajustement'),
        ('TRANSFERT', 'Transfert'),
        ('RETOUR', 'Retour'),
    ]
    
    MOTIF_CHOICES = [
        ('ACHAT', 'Achat'),
        ('DON', 'Don'),
        ('VENTE', 'Vente'),
        ('DISTRIBUTION', 'Distribution'),
        ('UTILISATION', 'Utilisation'),
        ('PERTE', 'Perte'),
        ('VOL', 'Vol'),
        ('CASSE', 'Casse'),
        ('PEREMPTION', 'Péremption'),
        ('INVENTAIRE', 'Inventaire'),
        ('AUTRE', 'Autre'),
    ]
    
    # Référence
    numero_mouvement = models.CharField(max_length=50, unique=True, verbose_name="N° mouvement")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='mouvements')
    
    # Type et motif
    type_mouvement = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type de mouvement")
    motif = models.CharField(max_length=20, choices=MOTIF_CHOICES, verbose_name="Motif")
    
    # Quantité
    quantite = models.IntegerField(verbose_name="Quantité")
    stock_avant = models.IntegerField(verbose_name="Stock avant")
    stock_apres = models.IntegerField(verbose_name="Stock après")
    
    # Prix (pour achats/ventes)
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True, verbose_name="Prix unitaire (GNF)")
    montant_total = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True, verbose_name="Montant total (GNF)")
    
    # Informations complémentaires
    date_mouvement = models.DateTimeField(default=timezone.now, verbose_name="Date du mouvement")
    destinataire = models.CharField(max_length=200, blank=True, verbose_name="Destinataire/Fournisseur")
    document_reference = models.CharField(max_length=100, blank=True, verbose_name="Document de référence")
    observations = models.TextField(blank=True, verbose_name="Observations")
    
    # Métadonnées
    date_creation = models.DateTimeField(auto_now_add=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Créé par")
    
    class Meta:
        verbose_name = "Mouvement de stock"
        verbose_name_plural = "Mouvements de stock"
        ordering = ['-date_mouvement']
    
    def __str__(self):
        return f"{self.numero_mouvement} - {self.article.nom} ({self.quantite} {self.article.unite_mesure})"
    
    def save(self, *args, **kwargs):
        # Calculer le montant total
        if self.prix_unitaire and self.quantite:
            self.montant_total = self.prix_unitaire * self.quantite
        
        # Mettre à jour le stock de l'article
        if not self.pk:  # Nouveau mouvement
            self.stock_avant = self.article.stock_actuel
            if self.type_mouvement == 'ENTREE':
                self.article.stock_actuel += self.quantite
            elif self.type_mouvement == 'SORTIE':
                self.article.stock_actuel -= self.quantite
            elif self.type_mouvement == 'AJUSTEMENT':
                self.article.stock_actuel = self.quantite
            self.stock_apres = self.article.stock_actuel
            self.article.save()
        
        super().save(*args, **kwargs)


class Inventaire(SyncTrackedModel):
    """Inventaires périodiques"""
    STATUT_CHOICES = [
        ('EN_COURS', 'En cours'),
        ('TERMINE', 'Terminé'),
        ('VALIDE', 'Validé'),
        ('ANNULE', 'Annulé'),
    ]
    
    # Identification
    numero_inventaire = models.CharField(max_length=50, unique=True, verbose_name="N° inventaire")
    date_inventaire = models.DateField(verbose_name="Date de l'inventaire")
    
    # Informations
    description = models.TextField(verbose_name="Description")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_COURS', verbose_name="Statut")
    
    # Résultats
    nombre_articles = models.IntegerField(default=0, verbose_name="Nombre d'articles")
    valeur_totale = models.DecimalField(max_digits=15, decimal_places=0, default=Decimal('0'), verbose_name="Valeur totale (GNF)")
    ecarts_detectes = models.IntegerField(default=0, verbose_name="Écarts détectés")
    
    # Métadonnées
    date_creation = models.DateTimeField(auto_now_add=True)
    date_validation = models.DateTimeField(null=True, blank=True, verbose_name="Date de validation")
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventaires_crees')
    valide_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventaires_valides')
    
    observations = models.TextField(blank=True, verbose_name="Observations")
    
    class Meta:
        verbose_name = "Inventaire"
        verbose_name_plural = "Inventaires"
        ordering = ['-date_inventaire']
    
    def __str__(self):
        return f"{self.numero_inventaire} - {self.date_inventaire.strftime('%d/%m/%Y')}"


class LigneInventaire(SyncTrackedModel):
    """Lignes de détail d'un inventaire"""
    inventaire = models.ForeignKey(Inventaire, on_delete=models.CASCADE, related_name='lignes')
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    
    # Quantités
    stock_theorique = models.IntegerField(verbose_name="Stock théorique")
    stock_physique = models.IntegerField(verbose_name="Stock physique")
    ecart = models.IntegerField(verbose_name="Écart")
    
    # Valeurs
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Prix unitaire (GNF)")
    valeur_theorique = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Valeur théorique (GNF)")
    valeur_physique = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Valeur physique (GNF)")
    
    observations = models.TextField(blank=True, verbose_name="Observations")
    
    class Meta:
        verbose_name = "Ligne d'inventaire"
        verbose_name_plural = "Lignes d'inventaire"
        unique_together = ['inventaire', 'article']
    
    def __str__(self):
        return f"{self.inventaire.numero_inventaire} - {self.article.nom}"
    
    def save(self, *args, **kwargs):
        # Calculer l'écart
        self.ecart = self.stock_physique - self.stock_theorique
        
        # Calculer les valeurs
        self.valeur_theorique = self.stock_theorique * self.prix_unitaire
        self.valeur_physique = self.stock_physique * self.prix_unitaire
        
        super().save(*args, **kwargs)
