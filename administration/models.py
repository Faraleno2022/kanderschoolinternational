from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.utils import timezone

try:
    from django.db.models import JSONField
except ImportError:
    from django.contrib.postgres.fields import JSONField

User = get_user_model()


class SystemLog(models.Model):
    """Journal des actions administratives importantes"""
    
    ACTION_CHOICES = [
        ('DELETE', 'Suppression'),
        ('SUPPRESSION_DEFINITIVE', 'Suppression définitive'),
        ('RESET', 'Réinitialisation'),
        ('BACKUP', 'Sauvegarde'),
        ('RESTORE', 'Restauration'),
        ('LOGIN', 'Connexion admin'),
        ('ERROR', 'Erreur système'),
    ]
    
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, db_index=True)
    description = models.TextField()
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    details = JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Log système'
        verbose_name_plural = 'Logs système'
    
    def __str__(self):
        return f"{self.action} - {self.timestamp.strftime('%d/%m/%Y %H:%M')} - {self.user or 'Système'}"


class ObjetSupprime(models.Model):
    """Corbeille générique des objets supprimés depuis l'administration.

    L'objet est sérialisé avant sa suppression, ce qui permet de le
    restaurer plus tard avec sa clé primaire et toutes ses valeurs.
    """

    model_label = models.CharField(max_length=120, db_index=True, verbose_name="Modèle")
    object_pk = models.CharField(max_length=64, db_index=True, verbose_name="Identifiant")
    object_repr = models.CharField(max_length=250, verbose_name="Objet")
    donnees = JSONField(default=dict, blank=True, verbose_name="Données sérialisées")
    supprime_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='objets_supprimes', verbose_name="Supprimé par",
    )
    supprime_le = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Supprimé le")
    restaure = models.BooleanField(default=False, db_index=True, verbose_name="Restauré")
    restaure_le = models.DateTimeField(null=True, blank=True, verbose_name="Restauré le")

    class Meta:
        ordering = ['-supprime_le', '-id']
        verbose_name = "Objet dans la corbeille"
        verbose_name_plural = "Corbeille des suppressions"

    def __str__(self):
        return f"{self.model_label} #{self.object_pk} — {self.object_repr}"

    @transaction.atomic
    def restaurer(self):
        """Recrée l'objet à partir des données sérialisées."""
        import json

        from django.core import serializers

        if self.restaure or not self.donnees:
            return False
        for obj in serializers.deserialize('json', json.dumps(self.donnees)):
            obj.save()
        self.restaure = True
        self.restaure_le = timezone.now()
        self.save(update_fields=['restaure', 'restaure_le'])
        return True


class MaintenanceMode(models.Model):
    """Mode maintenance du système"""
    
    is_active = models.BooleanField(default=False)
    message = models.TextField(
        default="Le système est en maintenance. Veuillez réessayer plus tard.",
        help_text="Message affiché aux utilisateurs"
    )
    allowed_users = models.ManyToManyField(
        User, 
        blank=True,
        help_text="Utilisateurs autorisés pendant la maintenance"
    )
    activated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='maintenance_activated'
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Mode maintenance'
        verbose_name_plural = 'Mode maintenance'
    
    def __str__(self):
        status = "Actif" if self.is_active else "Inactif"
        return f"Mode maintenance - {status}"
    
    def save(self, *args, **kwargs):
        if self.is_active and not self.activated_at:
            self.activated_at = timezone.now()
        super().save(*args, **kwargs)
