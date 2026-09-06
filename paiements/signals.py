"""Synchronise les soldes après une écriture, y compris une suppression en lot."""
from decimal import Decimal

from django.db.models.signals import pre_save, post_save, post_delete
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


@receiver(pre_save, sender=Paiement)
def memoriser_contexte_paiement(sender, instance, raw=False, **kwargs):
    instance._ancien_contexte_financier = None
    if not raw and instance.pk:
        instance._ancien_contexte_financier = Paiement.objects.filter(pk=instance.pk).values_list(
            'eleve_id', 'annee_scolaire', 'ecole_encaissement_id',
        ).first()


@receiver(post_save, sender=Paiement)
@receiver(post_delete, sender=Paiement)
def synchroniser_paiement(sender, instance, raw=False, **kwargs):
    if not raw:
        _recalculer(instance)
        ancien = getattr(instance, '_ancien_contexte_financier', None)
        actuel = (instance.eleve_id, instance.annee_scolaire, instance.ecole_encaissement_id)
        if kwargs.get('signal') is post_save and ancien and ancien != actuel:
            for echeancier in EcheancierPaiement.objects.filter(
                eleve_id=ancien[0], annee_scolaire=ancien[1], ecole_reference_id=ancien[2],
            ):
                recalculer_echeancier(echeancier)
        # Le paiement en attente ne suffit pas : un encaissement positif doit
        # être validé dans l'école et l'année actuelles du dossier.
        if kwargs.get('signal') is post_save and instance.statut == 'VALIDE' and Decimal(str(instance.montant or 0)) > 0:
            from eleves.models import Eleve
            eleve = Eleve.objects.filter(
                pk=instance.eleve_id, statut='ATTENTE_PAIEMENT', est_dans_corbeille=False,
                classe__ecole_id=instance.ecole_encaissement_id,
                classe__annee_scolaire=instance.annee_scolaire,
            ).first()
            if eleve:
                eleve.statut = 'ACTIF'
                eleve.save(update_fields=['statut', 'date_modification'])
                if 'eleve' in instance._state.fields_cache:
                    instance.eleve.statut = 'ACTIF'


@receiver(post_save, sender=PaiementRemise)
@receiver(post_delete, sender=PaiementRemise)
def synchroniser_remise(sender, instance, raw=False, **kwargs):
    if not raw:
        paiement = Paiement.objects.filter(pk=instance.paiement_id).first()
        if paiement:
            _recalculer(paiement)
