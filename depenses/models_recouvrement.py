"""Modèles du module Recouvrement.

Regroupe les enregistrements simples saisis au quotidien (cuisine, documents,
versements) et les abonnements informatiques des élèves. Chaque modèle porte
son école pour que le cloisonnement par établissement reste possible même
quand l'agent qui a saisi la ligne change d'affectation.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from eleves.models import Ecole, Eleve
from synchronisation.mixins import SyncTrackedModel


class OperationRecouvrement(SyncTrackedModel):
    """Base commune aux opérations simples : date, montant, observation."""

    date = models.DateField(
        default=timezone.localdate, db_index=True,
        verbose_name="Date"
    )
    montant = models.DecimalField(
        max_digits=12, decimal_places=0, default=Decimal('0'),
        verbose_name="Montant (GNF)"
    )
    observation = models.TextField(blank=True, default='', verbose_name="Observation")

    ecole = models.ForeignKey(
        Ecole, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name="École"
    )
    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name="Créé par"
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-date', '-date_creation']


class DepenseCuisine(OperationRecouvrement):
    """Dépense engagée pour la cuisine de l'établissement."""

    designation = models.CharField(max_length=200, verbose_name="Désignation")

    class Meta(OperationRecouvrement.Meta):
        abstract = False
        verbose_name = "Dépense de cuisine"
        verbose_name_plural = "Dépenses de cuisine"

    def __str__(self):
        return f"{self.date:%d/%m/%Y} - {self.designation} - {self.montant:,.0f} GNF"

    @property
    def libelle(self) -> str:
        """Colonne principale, nommée pareil dans les trois registres simples."""
        return self.designation


class DepenseDocument(OperationRecouvrement):
    """Dépense liée aux documents (impressions, fournitures administratives…)."""

    designation = models.CharField(max_length=200, verbose_name="Désignation")

    class Meta(OperationRecouvrement.Meta):
        abstract = False
        verbose_name = "Dépense de document"
        verbose_name_plural = "Dépenses de documents"

    def __str__(self):
        return f"{self.date:%d/%m/%Y} - {self.designation} - {self.montant:,.0f} GNF"

    @property
    def libelle(self) -> str:
        return self.designation


class Versement(OperationRecouvrement):
    """Versement d'espèces effectué vers une banque, un coffre ou la direction."""

    lieu_versement = models.CharField(max_length=200, verbose_name="Lieu de versement")

    class Meta(OperationRecouvrement.Meta):
        abstract = False
        verbose_name = "Versement"
        verbose_name_plural = "Versements"

    def __str__(self):
        return f"{self.date:%d/%m/%Y} - {self.lieu_versement} - {self.montant:,.0f} GNF"

    @property
    def libelle(self) -> str:
        return self.lieu_versement


class AbonnementInformatique(SyncTrackedModel):
    """Abonnement d'un élève à la salle informatique.

    Le statut n'est pas stocké : il se déduit des dates, ce qui évite d'avoir
    à repasser sur la base chaque nuit pour marquer les abonnements échus.
    """

    ALERTE_JOURS_DEFAUT = 7

    eleve = models.ForeignKey(
        Eleve, on_delete=models.CASCADE,
        related_name='abonnements_informatique', verbose_name="Élève"
    )
    date = models.DateField(
        default=timezone.localdate, db_index=True,
        verbose_name="Date d'enregistrement"
    )
    montant = models.DecimalField(
        max_digits=12, decimal_places=0, default=Decimal('0'),
        verbose_name="Montant de l'abonnement (GNF)"
    )
    date_debut = models.DateField(default=timezone.localdate, verbose_name="Début de l'abonnement")
    date_fin = models.DateField(db_index=True, verbose_name="Fin de l'abonnement")
    alerte_avant_jours = models.PositiveIntegerField(
        default=ALERTE_JOURS_DEFAUT, verbose_name="Alerte avant (jours)"
    )
    observation = models.TextField(blank=True, default='', verbose_name="Observation")

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name="Créé par"
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonnement informatique"
        verbose_name_plural = "Abonnements informatique"
        ordering = ['-date_fin', 'eleve__nom']
        indexes = [
            models.Index(fields=['eleve', 'date_fin']),
        ]

    def __str__(self):
        return f"Informatique: {self.eleve} ({self.date_debut:%d/%m/%Y} → {self.date_fin:%d/%m/%Y})"

    @property
    def numero_carte(self) -> str:
        """Identifiant lisible imprimé sur la carte d'abonnement."""
        return f"INFO-{self.pk:05d}" if self.pk else "INFO-....."

    @property
    def jours_restants(self) -> int:
        """Jours restants avant la fin (négatif si l'abonnement est échu)."""
        if not self.date_fin:
            return 0
        return (self.date_fin - timezone.localdate()).days

    @property
    def est_expire(self) -> bool:
        return bool(self.date_fin) and timezone.localdate() > self.date_fin

    @property
    def est_proche_expiration(self) -> bool:
        """Vrai dans la fenêtre d'alerte, l'abonnement étant encore valide."""
        if not self.date_fin or self.est_expire:
            return False
        return self.jours_restants <= (self.alerte_avant_jours or self.ALERTE_JOURS_DEFAUT)

    @property
    def statut(self) -> str:
        if self.est_expire:
            return 'EXPIRE'
        if self.est_proche_expiration:
            return 'BIENTOT'
        return 'ACTIF'

    @property
    def statut_libelle(self) -> str:
        return {
            'EXPIRE': 'Expiré',
            'BIENTOT': 'Expire bientôt',
            'ACTIF': 'Actif',
        }[self.statut]

    @property
    def statut_couleur(self) -> str:
        """Classe Bootstrap associée au statut, pour les badges."""
        return {'EXPIRE': 'danger', 'BIENTOT': 'warning', 'ACTIF': 'success'}[self.statut]
