"""Synchronise les soldes après une écriture, y compris une suppression en lot."""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Paiement, PaiementRemise, EcheancierPaiement
from .soldes import recalculer_echeancier


def _recalculer(paiement):
    for echeancier in EcheancierPaiement.objects.filter(
        eleve_id=paiement.eleve_id,
        annee_scolaire=paiement.annee_scolaire,
        ecole_reference_id=paiement.ecole_encaissement_id,
    ):
        recalculer_echeancier(echeancier)


@receiver(post_save, sender=Paiement)
@receiver(post_delete, sender=Paiement)
def synchroniser_paiement(sender, instance, raw=False, **kwargs):
    if not raw:
        _recalculer(instance)


@receiver(post_save, sender=PaiementRemise)
@receiver(post_delete, sender=PaiementRemise)
def synchroniser_remise(sender, instance, raw=False, **kwargs):
    if not raw:
        paiement = Paiement.objects.filter(pk=instance.paiement_id).first()
        if paiement:
            _recalculer(paiement)
