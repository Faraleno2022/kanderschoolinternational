"""Remise à plat des soldes d'un échéancier depuis les encaissements validés.

Le calcul part toujours de la couverture réelle (paiements validés + remises)
plutôt que d'ajuster les cumuls existants : c'est ce qui le rend idempotent et
lui permet de corriger un échéancier déjà faussé, au lieu de propager l'erreur.

Le contexte vient de l'échéancier lui-même — année et école de référence — et
jamais de la classe actuelle de l'élève, qui change lors d'un transfert.
"""

from datetime import date

from django.db.models import Sum
from django.utils import timezone

from .models import EcheancierPaiement, Paiement, PaiementRemise


CHAMPS_ALLOCATION = (
    ('frais_inscription_paye', 'frais_inscription_du'),
    ('tranche_1_payee', 'tranche_1_due'),
    ('tranche_2_payee', 'tranche_2_due'),
    ('tranche_3_payee', 'tranche_3_due'),
)

CHAMPS_ECHEANCE = (
    ('date_echeance_inscription', 'frais_inscription_du'),
    ('date_echeance_tranche_1', 'tranche_1_due'),
    ('date_echeance_tranche_2', 'tranche_2_due'),
    ('date_echeance_tranche_3', 'tranche_3_due'),
)


def couverture_reelle(eleve_id, annee_scolaire, ecole_id):
    """Retourne (paiements_validés, remises_validées) sans double comptage SQL."""
    paiement_total = (
        Paiement.objects
        .filter(
            eleve_id=eleve_id, statut='VALIDE',
            annee_scolaire=annee_scolaire, ecole_encaissement_id=ecole_id,
        )
        .aggregate(total=Sum('montant'))
        .get('total') or 0
    )
    remise_total = (
        PaiementRemise.objects
        .filter(
            paiement__eleve_id=eleve_id, paiement__statut='VALIDE',
            paiement__annee_scolaire=annee_scolaire,
            paiement__ecole_encaissement_id=ecole_id,
        )
        .aggregate(total=Sum('montant_remise'))
        .get('total') or 0
    )
    return int(paiement_total or 0), int(remise_total or 0)


def _exigible_a_ce_jour(echeancier, aujourdhui):
    """Somme des postes dont l'échéance est déjà passée."""
    return sum(
        int(getattr(echeancier, champ_du, 0) or 0)
        for champ_echeance, champ_du in CHAMPS_ECHEANCE
        if getattr(echeancier, champ_echeance, None)
        and getattr(echeancier, champ_echeance) < aujourdhui
    )


def _statut_pour(total_du, paye_effectif, exigible):
    if total_du <= 0 or paye_effectif >= total_du:
        return 'PAYE_COMPLET'
    if exigible > 0 and paye_effectif < exigible:
        return 'EN_RETARD'
    if paye_effectif <= 0:
        return 'A_PAYER'
    return 'PAYE_PARTIEL'


def recalculer_echeancier(echeancier, *, enregistrer=True):
    """Réaligne un échéancier sur sa couverture réelle.

    Retourne les champs corrigés sous la forme ``{champ: (avant, après)}``,
    vide si l'échéancier était déjà juste. ``enregistrer=False`` permet de
    mesurer l'écart sans y toucher.
    """
    sum_paiements, sum_remises = couverture_reelle(
        echeancier.eleve_id, echeancier.annee_scolaire,
        echeancier.ecole_reference_id,
    )
    couverture = max(0, sum_paiements + sum_remises)

    total_du = sum(
        int(getattr(echeancier, champ_du, 0) or 0)
        for _champ_paye, champ_du in CHAMPS_ALLOCATION
    )
    aujourdhui = timezone.localdate() if hasattr(timezone, 'localdate') else date.today()
    exigible = _exigible_a_ce_jour(echeancier, aujourdhui)
    statut = _statut_pour(total_du, min(couverture, total_du), exigible)

    corrections = {}
    restant = couverture
    for champ_paye, champ_du in CHAMPS_ALLOCATION:
        du = max(0, int(getattr(echeancier, champ_du, 0) or 0))
        # Un échéancier soldé affiche chaque poste à son dû, même si la
        # couverture le dépasse : le surplus est un crédit, pas une tranche.
        nouveau = du if statut == 'PAYE_COMPLET' else min(du, max(0, restant))
        restant -= min(du, max(0, restant))

        ancien = int(getattr(echeancier, champ_paye, 0) or 0)
        if nouveau != ancien:
            corrections[champ_paye] = (ancien, nouveau)
            setattr(echeancier, champ_paye, nouveau)

    if echeancier.statut != statut:
        corrections['statut'] = (echeancier.statut, statut)
        echeancier.statut = statut

    if corrections and enregistrer:
        echeancier.save()
    return corrections


def echeanciers_a_recalculer(annee_scolaire=None, ecole_id=None):
    """Échéanciers candidats, du plus ancien au plus récent."""
    queryset = EcheancierPaiement.objects.select_related(
        'eleve', 'ecole_reference',
    ).order_by('annee_scolaire', 'eleve_id', 'pk')
    if annee_scolaire:
        queryset = queryset.filter(annee_scolaire=annee_scolaire)
    if ecole_id:
        queryset = queryset.filter(ecole_reference_id=ecole_id)
    return queryset
