"""
Modèles de la vie scolaire :
- Presence : pointage journalier de présence des élèves (par classe).
- Devoir + RemiseDevoir : suivi des devoirs donnés et de leur remise par élève.

Ces modèles n'héritent volontairement pas de SyncTrackedModel (comme
`eleves.VisiteMedicale`) afin de ne pas impacter la synchronisation offline
dans un premier temps.
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from eleves.models import Eleve, Classe


class Presence(models.Model):
    """Statut de présence d'un élève pour une journée donnée."""
    STATUT_PRESENT = 'PRESENT'
    STATUT_ABSENT = 'ABSENT'
    STATUT_RETARD = 'RETARD'
    STATUT_EXCUSE = 'EXCUSE'
    STATUT_CHOICES = [
        (STATUT_PRESENT, 'Présent'),
        (STATUT_ABSENT, 'Absent'),
        (STATUT_RETARD, 'En retard'),
        (STATUT_EXCUSE, 'Absence excusée'),
    ]

    eleve = models.ForeignKey(
        Eleve, on_delete=models.CASCADE, related_name='presences',
        verbose_name="Élève"
    )
    # Classe dénormalisée : facilite les rapports/pointages par classe et fige
    # la classe au moment du pointage (indépendant d'un futur changement).
    classe = models.ForeignKey(
        Classe, on_delete=models.CASCADE, related_name='presences',
        verbose_name="Classe"
    )
    date = models.DateField(verbose_name="Date", db_index=True)
    statut = models.CharField(
        max_length=10, choices=STATUT_CHOICES, default=STATUT_PRESENT,
        verbose_name="Statut"
    )
    motif = models.CharField(
        max_length=200, blank=True, verbose_name="Motif (absence / retard)"
    )
    saisi_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pointages_saisis'
    )
    date_saisie = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Présence"
        verbose_name_plural = "Présences"
        ordering = ['-date', 'eleve__nom', 'eleve__prenom']
        unique_together = ['eleve', 'date']
        indexes = [
            models.Index(fields=['classe', 'date']),
            models.Index(fields=['statut']),
        ]

    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.get_statut_display()} ({self.date:%d/%m/%Y})"

    @property
    def est_absence(self):
        """Une absence « comptabilisée » (les retards et absences excusées ne le sont pas)."""
        return self.statut == self.STATUT_ABSENT


class Devoir(models.Model):
    """Un devoir donné à une classe (cahier de textes)."""
    classe = models.ForeignKey(
        Classe, on_delete=models.CASCADE, related_name='devoirs',
        verbose_name="Classe"
    )
    matiere = models.CharField(
        max_length=100, blank=True, verbose_name="Matière"
    )
    titre = models.CharField(max_length=200, verbose_name="Titre du devoir")
    description = models.TextField(blank=True, verbose_name="Consignes / description")
    date_donne = models.DateField(
        default=timezone.localdate, verbose_name="Date de remise du sujet"
    )
    date_remise = models.DateField(verbose_name="À rendre le")
    fichier = models.FileField(
        upload_to='devoirs/', blank=True, null=True,
        verbose_name="Énoncé (fichier joint)"
    )
    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='devoirs_crees'
    )
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Devoir"
        verbose_name_plural = "Devoirs"
        ordering = ['-date_remise', '-date_creation']
        indexes = [
            models.Index(fields=['classe', 'date_remise']),
        ]

    def __str__(self):
        libelle = f"{self.matiere} — " if self.matiere else ""
        return f"{libelle}{self.titre} ({self.classe.nom})"

    @property
    def est_en_retard(self):
        """Échéance dépassée."""
        return self.date_remise < timezone.localdate()

    @property
    def nb_remis(self):
        return self.remises.filter(
            statut__in=[RemiseDevoir.STATUT_REMIS, RemiseDevoir.STATUT_EN_RETARD]
        ).count()

    @property
    def nb_total(self):
        return self.remises.count()


class RemiseDevoir(models.Model):
    """État de remise d'un devoir pour un élève donné."""
    STATUT_NON_REMIS = 'NON_REMIS'
    STATUT_REMIS = 'REMIS'
    STATUT_EN_RETARD = 'EN_RETARD'
    STATUT_DISPENSE = 'DISPENSE'
    STATUT_CHOICES = [
        (STATUT_NON_REMIS, 'Non remis'),
        (STATUT_REMIS, 'Remis'),
        (STATUT_EN_RETARD, 'Remis en retard'),
        (STATUT_DISPENSE, 'Dispensé'),
    ]

    devoir = models.ForeignKey(
        Devoir, on_delete=models.CASCADE, related_name='remises',
        verbose_name="Devoir"
    )
    eleve = models.ForeignKey(
        Eleve, on_delete=models.CASCADE, related_name='remises_devoirs',
        verbose_name="Élève"
    )
    statut = models.CharField(
        max_length=10, choices=STATUT_CHOICES, default=STATUT_NON_REMIS,
        verbose_name="Statut"
    )
    remarque = models.CharField(max_length=200, blank=True, verbose_name="Remarque")
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Remise de devoir"
        verbose_name_plural = "Remises de devoirs"
        ordering = ['eleve__nom', 'eleve__prenom']
        unique_together = ['devoir', 'eleve']

    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.get_statut_display()}"
