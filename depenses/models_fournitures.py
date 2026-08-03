from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from synchronisation.mixins import SyncTrackedModel


class ProduitFourniture(SyncTrackedModel):
    """Produit vendu par la boutique de fournitures d'un établissement."""

    UNITE_CHOICES = [
        ('PIECE', 'Pièce'),
        ('PAQUET', 'Paquet'),
        ('BOITE', 'Boîte'),
        ('CARTON', 'Carton'),
        ('UNITE', 'Unité'),
    ]

    ecole = models.ForeignKey(
        'eleves.Ecole',
        on_delete=models.CASCADE,
        related_name='produits_fournitures',
        verbose_name='Établissement',
    )
    nom = models.CharField(max_length=150, verbose_name='Produit')
    description = models.TextField(blank=True, verbose_name='Description')
    unite = models.CharField(
        max_length=10,
        choices=UNITE_CHOICES,
        default='PIECE',
        verbose_name='Unité',
    )
    quantite_stock = models.PositiveIntegerField(
        default=0,
        verbose_name='Quantité mise en stock',
        help_text='Quantité totale approvisionnée. Le reste est calculé après les ventes.',
    )
    prix_achat_unitaire = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name="Prix d'achat unitaire (GNF)",
    )
    prix_vente_unitaire = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Prix de vente unitaire (GNF)',
    )
    seuil_alerte = models.PositiveIntegerField(
        default=5,
        verbose_name='Seuil d’alerte',
    )
    actif = models.BooleanField(default=True, verbose_name='Actif')
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='produits_fournitures_crees',
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Produit de fourniture scolaire'
        verbose_name_plural = 'Produits de fournitures scolaires'
        ordering = ['nom']
        constraints = [
            models.UniqueConstraint(
                fields=['ecole', 'nom'],
                name='uniq_produit_fourniture_par_ecole',
            ),
        ]
        indexes = [
            models.Index(fields=['ecole', 'actif']),
            models.Index(fields=['ecole', 'nom']),
        ]

    def __str__(self):
        return f'{self.nom} - {self.ecole.nom}'

    @property
    def quantite_vendue(self):
        annotated = getattr(self, 'quantite_vendue_calc', None)
        if annotated is not None:
            return int(annotated or 0)
        return int(
            self.ventes.filter(statut=VenteFourniture.STATUT_CONFIRMEE)
            .aggregate(total=Sum('quantite'))['total']
            or 0
        )

    @property
    def quantite_restante(self):
        return max(0, int(self.quantite_stock or 0) - self.quantite_vendue)

    @property
    def valeur_stock_restante(self):
        return Decimal(self.quantite_restante) * (self.prix_achat_unitaire or Decimal('0'))

    @property
    def en_alerte(self):
        return self.quantite_restante <= int(self.seuil_alerte or 0)

    def clean(self):
        super().clean()
        if self.pk and self.quantite_stock < self.quantite_vendue:
            raise ValidationError({
                'quantite_stock': (
                    f'La quantité en stock ne peut pas être inférieure aux '
                    f'{self.quantite_vendue} unité(s) déjà vendue(s).'
                )
            })


class VenteFourniture(SyncTrackedModel):
    """Vente historisée d'un produit de fourniture scolaire."""

    STATUT_CONFIRMEE = 'CONFIRMEE'
    STATUT_ANNULEE = 'ANNULEE'
    STATUT_CHOICES = [
        (STATUT_CONFIRMEE, 'Confirmée'),
        (STATUT_ANNULEE, 'Annulée'),
    ]

    produit = models.ForeignKey(
        ProduitFourniture,
        on_delete=models.PROTECT,
        related_name='ventes',
        verbose_name='Produit',
    )
    quantite = models.PositiveIntegerField(verbose_name='Quantité vendue')
    prix_achat_unitaire = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name="Prix d'achat unitaire (GNF)",
    )
    prix_vente_unitaire = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Prix de vente unitaire (GNF)',
    )
    montant_achat = models.DecimalField(
        max_digits=18,
        decimal_places=0,
        default=Decimal('0'),
        verbose_name="Coût d'achat (GNF)",
    )
    montant_vente = models.DecimalField(
        max_digits=18,
        decimal_places=0,
        default=Decimal('0'),
        verbose_name='Montant vendu (GNF)',
    )
    solde = models.DecimalField(
        max_digits=18,
        decimal_places=0,
        default=Decimal('0'),
        verbose_name='Solde / marge brute (GNF)',
    )
    acheteur = models.CharField(
        max_length=150,
        blank=True,
        verbose_name='Acheteur / bénéficiaire',
    )
    date_vente = models.DateField(default=timezone.localdate, verbose_name='Date de vente')
    observations = models.TextField(blank=True, verbose_name='Observations')
    statut = models.CharField(
        max_length=10,
        choices=STATUT_CHOICES,
        default=STATUT_CONFIRMEE,
        verbose_name='Statut',
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ventes_fournitures_creees',
    )
    annulee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ventes_fournitures_annulees',
    )
    date_annulation = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Vente de fourniture scolaire'
        verbose_name_plural = 'Ventes de fournitures scolaires'
        ordering = ['-date_vente', '-date_creation']
        indexes = [
            models.Index(fields=['produit', 'statut']),
            models.Index(fields=['date_vente', 'statut']),
        ]

    def __str__(self):
        return f'{self.produit.nom} × {self.quantite} ({self.date_vente:%d/%m/%Y})'

    def clean(self):
        super().clean()
        if not self.quantite or self.quantite <= 0:
            raise ValidationError({'quantite': 'La quantité vendue doit être supérieure à zéro.'})
        if self.produit_id and self.pk is None and self.quantite > self.produit.quantite_restante:
            raise ValidationError({
                'quantite': (
                    f'Stock insuffisant : {self.produit.quantite_restante} unité(s) disponible(s).'
                )
            })

    def save(self, *args, **kwargs):
        quantite = Decimal(self.quantite or 0)
        self.montant_achat = quantite * (self.prix_achat_unitaire or Decimal('0'))
        self.montant_vente = quantite * (self.prix_vente_unitaire or Decimal('0'))
        self.solde = self.montant_vente - self.montant_achat
        super().save(*args, **kwargs)
