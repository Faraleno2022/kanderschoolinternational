"""Services financiers déclenchés par les transferts d'élèves."""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from eleves.models import GrilleTarifaire

from .allocation import (
    ALLOCATION_COMPONENTS,
    allocate_amount_sequentially,
    allocate_discounts,
    registration_kind_for_type,
)
from .models import EcheancierPaiement, Paiement, PaiementRemise


ZERO = Decimal('0')


def _decimal(value):
    return Decimal(str(value or 0))


def _total_du(echeancier):
    return sum(
        (_decimal(getattr(echeancier, due_field, 0)) for _, due_field, _ in ALLOCATION_COMPONENTS),
        ZERO,
    )


def _nature_frais(eleve, nouvelle_classe, *, changement_annee, changement_ecole, echeancier):
    """Détermine le tarif d'admission réellement applicable à la destination."""
    paiements_destination = (
        Paiement.objects.filter(
            eleve=eleve,
            annee_scolaire=nouvelle_classe.annee_scolaire,
            ecole_encaissement_id=nouvelle_classe.ecole_id,
            statut='VALIDE',
        )
        .select_related('type_paiement')
        .order_by('date_paiement', 'date_creation', 'pk')
    )
    for paiement in paiements_destination.iterator():
        nature = registration_kind_for_type(paiement.type_paiement)
        if nature == 'reinscription':
            return EcheancierPaiement.NATURE_REINSCRIPTION
        if nature == 'inscription':
            return EcheancierPaiement.NATURE_INSCRIPTION

    # Une autre école constitue une nouvelle admission. Dans la même école,
    # le passage à une nouvelle année est une réinscription.
    if changement_ecole:
        return EcheancierPaiement.NATURE_INSCRIPTION
    if changement_annee:
        return EcheancierPaiement.NATURE_REINSCRIPTION
    return getattr(
        echeancier, 'nature_frais', EcheancierPaiement.NATURE_INSCRIPTION,
    )


def _dates_echeancier(grille, annee_scolaire):
    try:
        annee_fin = int(str(annee_scolaire).split('-')[0]) + 1
    except (TypeError, ValueError, IndexError):
        aujourd_hui = timezone.localdate()
        annee_fin = aujourd_hui.year + (1 if aujourd_hui.month >= 9 else 0)
    aujourd_hui = timezone.localdate()
    return {
        'date_echeance_inscription': grille.date_echeance_inscription_defaut or aujourd_hui,
        'date_echeance_tranche_1': grille.date_echeance_tranche_1_defaut or date(annee_fin, 1, 15),
        'date_echeance_tranche_2': grille.date_echeance_tranche_2_defaut or date(annee_fin, 3, 15),
        'date_echeance_tranche_3': grille.date_echeance_tranche_3_defaut or date(annee_fin, 5, 15),
    }


def _appliquer_grille(echeancier, grille, nature_frais, *, reinitialiser_dates=False):
    echeancier.annee_scolaire = grille.annee_scolaire
    echeancier.nature_frais = nature_frais
    echeancier.frais_inscription_du = (
        grille.frais_reinscription
        if nature_frais == EcheancierPaiement.NATURE_REINSCRIPTION
        else grille.frais_inscription
    ) or ZERO
    echeancier.tranche_1_due = grille.tranche_1 or ZERO
    echeancier.tranche_2_due = grille.tranche_2 or ZERO
    echeancier.tranche_3_due = grille.tranche_3 or ZERO

    dates = _dates_echeancier(grille, grille.annee_scolaire)
    for champ, valeur in dates.items():
        date_configuree = getattr(grille, f'{champ}_defaut', None)
        if reinitialiser_dates or date_configuree or not getattr(echeancier, champ, None):
            setattr(echeancier, champ, valeur)


def _synchroniser_couverture(
    echeancier,
    *,
    ecole_id,
    conserver_saisie_manuelle,
):
    """Rejoue encaissements/remises sans modifier aucun paiement historique."""
    paiements = Paiement.objects.filter(
        eleve_id=echeancier.eleve_id,
        annee_scolaire=echeancier.annee_scolaire,
        ecole_encaissement_id=ecole_id,
        statut='VALIDE',
    )
    total_valide = _decimal(paiements.aggregate(total=Sum('montant'))['total'])
    total_saisi = sum(
        (_decimal(getattr(echeancier, paid_field, 0)) for _, _, paid_field in ALLOCATION_COMPONENTS),
        ZERO,
    )
    # Dès que des reçus existent, ils sont la source des encaissements.
    # Les cumuls de l'échéancier peuvent déjà inclure les remises : les
    # reprendre comme de l'argent versé compterait ces remises deux fois.
    encaissement = (
        total_saisi if conserver_saisie_manuelle and not paiements.exists()
        else total_valide
    )

    allocation, nouveaux_payes, credit = allocate_amount_sequentially(
        echeancier,
        encaissement,
        initial_paid={key: ZERO for key, _, _ in ALLOCATION_COMPONENTS},
    )
    for key, _due_field, paid_field in ALLOCATION_COMPONENTS:
        setattr(echeancier, paid_field, nouveaux_payes[key])

    remises = list(
        PaiementRemise.objects.filter(
            paiement__eleve_id=echeancier.eleve_id,
            paiement__annee_scolaire=echeancier.annee_scolaire,
            paiement__ecole_encaissement_id=ecole_id,
            paiement__statut='VALIDE',
        )
        .select_related('paiement')
        .order_by('paiement__date_paiement', 'paiement_id', 'pk')
    )
    soldes_apres_encaissement = {
        key: max(ZERO, _decimal(getattr(echeancier, due_field, 0)) - nouveaux_payes[key])
        for key, due_field, _paid_field in ALLOCATION_COMPONENTS
    }
    allocation_remises, _ = allocate_discounts(
        echeancier, remises, balances=soldes_apres_encaissement,
    )
    couverture = sum(allocation.values(), ZERO) + sum(allocation_remises.values(), ZERO)
    total_du = _total_du(echeancier)

    aujourd_hui = timezone.localdate()
    dates = {
        'inscription': echeancier.date_echeance_inscription,
        'tranche_1': echeancier.date_echeance_tranche_1,
        'tranche_2': echeancier.date_echeance_tranche_2,
        'tranche_3': echeancier.date_echeance_tranche_3,
    }
    exigible = ZERO
    exigible_couvert = ZERO
    for key, due_field, _paid_field in ALLOCATION_COMPONENTS:
        if dates[key] and dates[key] < aujourd_hui:
            exigible += _decimal(getattr(echeancier, due_field, 0))
            exigible_couvert += allocation[key] + allocation_remises[key]

    if total_du <= 0 or couverture >= total_du:
        echeancier.statut = 'PAYE_COMPLET'
    elif exigible > 0 and exigible_couvert < exigible:
        echeancier.statut = 'EN_RETARD'
    elif couverture <= 0:
        echeancier.statut = 'A_PAYER'
    else:
        echeancier.statut = 'PAYE_PARTIEL'

    return {
        'encaissements_valides': total_valide,
        'encaissements_conserves': encaissement,
        'remises_conservees': sum(
            (_decimal(item.montant_remise) for item in remises), ZERO,
        ),
        'credit_non_affecte': credit,
        'solde_restant': max(ZERO, total_du - couverture),
    }


@transaction.atomic
def reconcilier_transfert_classe(eleve, ancienne_classe, nouvelle_classe, *, cree_par=None):
    """Recalcule la scolarité cible et réalloue uniquement les fonds concernés.

    Même école et même année : les paiements/remises sont conservés et rejoués.
    Autre école : les anciens encaissements restent attribués à l'école source
    et ne réduisent pas la dette de l'école d'accueil.
    """
    ancienne_annee = ancienne_classe.annee_scolaire or ''
    nouvelle_annee = nouvelle_classe.annee_scolaire or ''
    changement_annee = ancienne_annee != nouvelle_annee
    changement_ecole = ancienne_classe.ecole_id != nouvelle_classe.ecole_id
    resultat = {
        'ancienne_annee': ancienne_annee,
        'nouvelle_annee': nouvelle_annee,
        'changement_annee': changement_annee,
        'changement_ecole': changement_ecole,
        'ancienne_ecole': ancienne_classe.ecole.nom,
        'nouvelle_ecole': nouvelle_classe.ecole.nom,
        'grille_manquante': False,
        'echeancier_cree': False,
        'echeancier_mis_a_jour': False,
        'ancien_total_du': ZERO,
        'nouveau_total_du': ZERO,
        'encaissements_valides': ZERO,
        'encaissements_conserves': ZERO,
        'remises_conservees': ZERO,
        'credit_non_affecte': ZERO,
        'solde_restant': ZERO,
    }

    grille = GrilleTarifaire.objects.filter(
        ecole_id=nouvelle_classe.ecole_id,
        niveau=nouvelle_classe.niveau,
        annee_scolaire=nouvelle_annee,
    ).first()
    if grille is None:
        resultat['grille_manquante'] = True
        return resultat

    ancien_echeancier = (
        EcheancierPaiement.objects.select_for_update().filter(
            eleve=eleve,
            annee_scolaire=ancienne_annee,
            ecole_reference_id=ancienne_classe.ecole_id,
        ).first()
    )
    if ancien_echeancier is not None:
        resultat['ancien_total_du'] = _total_du(ancien_echeancier)

    echeancier = (
        EcheancierPaiement.objects.select_for_update().filter(
            eleve=eleve,
            annee_scolaire=nouvelle_annee,
            ecole_reference_id=nouvelle_classe.ecole_id,
        ).first()
    )
    if echeancier is None:
        dates = _dates_echeancier(grille, nouvelle_annee)
        echeancier = EcheancierPaiement(
            eleve=eleve,
            ecole_reference_id=nouvelle_classe.ecole_id,
            classe_reference_id=nouvelle_classe.pk,
            cree_par=cree_par if getattr(cree_par, 'is_authenticated', False) else None,
            **dates,
        )
        resultat['echeancier_cree'] = True
    echeancier.classe_reference_id = nouvelle_classe.pk

    nature = _nature_frais(
        eleve,
        nouvelle_classe,
        changement_annee=changement_annee,
        changement_ecole=changement_ecole,
        echeancier=echeancier,
    )
    contexte_financier_nouveau = changement_annee or changement_ecole
    _appliquer_grille(
        echeancier,
        grille,
        nature,
        reinitialiser_dates=contexte_financier_nouveau,
    )
    couverture = _synchroniser_couverture(
        echeancier,
        ecole_id=nouvelle_classe.ecole_id,
        conserver_saisie_manuelle=not contexte_financier_nouveau,
    )
    echeancier.save()

    resultat.update(couverture)
    resultat['echeancier_mis_a_jour'] = True
    resultat['nouveau_total_du'] = _total_du(echeancier)
    resultat['echeancier_id'] = echeancier.pk
    return resultat
