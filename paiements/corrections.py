"""Recalcul du tarif d'admission lors de la correction d'un reçu."""

from decimal import Decimal

from django.core.exceptions import ValidationError

from eleves.models import GrilleTarifaire
from .allocation import payment_type_plan
from .models import EcheancierPaiement


def preparer_correction_admission(paiement, ancien_type, ancien_montant):
    """Prépare le nouveau tarif sans écrire avant validation du formulaire.

    Les remises de scolarité restent acquises : seul le poste admission
    change. Une saisie explicite du net ou un versement partiel est conservé.
    Le contexte est celui du reçu, même après un transfert de l'élève.
    """
    avant = payment_type_plan(ancien_type)
    apres = payment_type_plan(paiement.type_paiement)
    if (not avant['registration_kind'] or not apres['registration_kind']
            or avant['registration_kind'] == apres['registration_kind']):
        return None
    echeancier = EcheancierPaiement.objects.select_related('classe_reference').filter(
        eleve_id=paiement.eleve_id, annee_scolaire=paiement.annee_scolaire,
        ecole_reference_id=paiement.ecole_encaissement_id,
    ).first()
    classe = echeancier.classe_reference if echeancier else None
    classe = classe or paiement.classe_historique
    grille = GrilleTarifaire.objects.filter(
        ecole_id=paiement.ecole_encaissement_id,
        annee_scolaire=paiement.annee_scolaire,
        niveau=classe.niveau if classe else None,
    ).first()
    if not echeancier or not grille:
        raise ValidationError(
            "Impossible de recalculer l'admission : l'échéancier ou la grille "
            "tarifaire de l'année et de l'école du reçu est manquant."
        )
    ancien_tarif = getattr(grille, 'frais_' + avant['registration_kind'])
    nouveau_tarif = getattr(grille, 'frais_' + apres['registration_kind'])
    deductions = sum((ligne.montant_remise for ligne in paiement.remises.all()
                      if ligne.deduite_du_paiement), Decimal('0'))
    ancien_brut = ancien_montant + deductions
    total_avant = ancien_tarif + sum(
        (getattr(echeancier, f'tranche_{n}_due') for n in avant['tranches']),
        Decimal('0'),
    )
    if paiement.montant == ancien_montant and ancien_brut == total_avant:
        total_apres = nouveau_tarif + sum(
            (getattr(echeancier, f'tranche_{n}_due') for n in apres['tranches']),
            Decimal('0'),
        )
        if deductions > total_apres:
            raise ValidationError("Les remises dépassent le nouveau tarif du reçu.")
        paiement.montant = total_apres - deductions
    echeancier.nature_frais = apres['registration_kind'].upper()
    echeancier.frais_inscription_du = nouveau_tarif
    return echeancier
