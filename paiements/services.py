"""Services financiers déclenchés par les transferts d'élèves."""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from eleves.models import GrilleTarifaire

from .allocation import (
    ALLOCATION_COMPONENTS,
    registration_kind_for_type,
)
from .models import EcheancierPaiement, Paiement
from .soldes import appliquer_couverture_echeancier, couverture_reelle


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
    )
    total_valide, total_remises = couverture_reelle(
        echeancier.eleve_id, echeancier.annee_scolaire, ecole_id,
    )
    total_valide, total_remises = _decimal(total_valide), _decimal(total_remises)
    # Seuls les anciens dossiers sans aucun reçu gardent leur saisie manuelle.
    # Un reçu annulé ou en attente ne doit pas rétablir un ancien cumul.
    encaissement = total_valide
    if conserver_saisie_manuelle and not paiements.exists():
        encaissement = sum(
            (_decimal(getattr(echeancier, paid_field, 0)) for _, _, paid_field in ALLOCATION_COMPONENTS),
            ZERO,
        )

    couverture = encaissement + total_remises
    appliquer_couverture_echeancier(echeancier, couverture, enregistrer=False)
    total_du = _total_du(echeancier)
    # Le crédit signale l'argent encaissé au-delà du tarif net ; une remise
    # seule ne devient pas un montant à rembourser.
    credit = max(ZERO, encaissement - max(ZERO, total_du - total_remises))
    return {
        'encaissements_valides': total_valide,
        'encaissements_conserves': encaissement,
        'remises_conservees': total_remises,
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
