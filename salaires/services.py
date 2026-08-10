"""Règles de calcul du moteur de paie.

Les enseignants au forfait sont payés au prorata de leur date d'embauche.
Les enseignants du secondaire sont payés sur les heures réellement pointées
pendant la période. Les affectations servent à ventiler ces heures par classe.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q, Sum

from .models import DetailHeuresClasse, Enseignant, EtatSalaire


HEURE = Decimal('0.01')
MONTANT = Decimal('0.01')
STATUTS_HEURES_PAYEES = ('PRESENT', 'RETARD', 'PERMISSION')


def arrondir_heures(valeur):
    return Decimal(valeur or 0).quantize(HEURE, rounding=ROUND_HALF_UP)


def arrondir_montant(valeur):
    return Decimal(valeur or 0).quantize(MONTANT, rounding=ROUND_HALF_UP)


def bornes_periode(periode):
    premier_jour = date(periode.annee, periode.mois, 1)
    dernier_jour = date(
        periode.annee,
        periode.mois,
        monthrange(periode.annee, periode.mois)[1],
    )
    return premier_jour, dernier_jour


def enseignants_eligibles(periode):
    """Enseignants actifs déjà embauchés à la fin de la période."""
    _, dernier_jour = bornes_periode(periode)
    return Enseignant.objects.filter(
        ecole=periode.ecole,
        statut='ACTIF',
        date_embauche__lte=dernier_jour,
    ).order_by('nom', 'prenoms')


def heures_reellement_travaillees(enseignant, periode):
    premier_jour, dernier_jour = bornes_periode(periode)
    total = enseignant.presences.filter(
        date__range=(premier_jour, dernier_jour),
        statut__in=STATUTS_HEURES_PAYEES,
    ).aggregate(total=Sum('heures_travaillees'))['total']
    return arrondir_heures(total)


def affectations_de_la_periode(enseignant, periode):
    """Affectations dont les dates chevauchent la période de paie.

    Une affectation clôturée reste utilisable pour un calcul historique.
    Une affectation désactivée sans date de fin est ignorée.
    """
    premier_jour, dernier_jour = bornes_periode(periode)
    return (
        enseignant.affectations
        .filter(date_debut__lte=dernier_jour)
        .filter(Q(date_fin__isnull=True) | Q(date_fin__gte=premier_jour))
        .filter(Q(actif=True) | Q(date_fin__isnull=False))
        .select_related('classe')
        .order_by('classe__nom', 'id')
    )


def heures_prevues_par_affectation(enseignant, periode):
    premier_jour, dernier_jour = bornes_periode(periode)
    jours_periode = Decimal((dernier_jour - premier_jour).days + 1)
    lignes = []

    for affectation in affectations_de_la_periode(enseignant, periode):
        debut = max(premier_jour, affectation.date_debut)
        fin = min(dernier_jour, affectation.date_fin or dernier_jour)
        jours_couverts = Decimal((fin - debut).days + 1)
        prorata = jours_couverts / jours_periode
        heures_prevues = (
            (affectation.heures_par_semaine or Decimal('0'))
            * periode.nombre_semaines
            * prorata
        )
        lignes.append((affectation, heures_prevues))

    return lignes


def repartir_heures(total_heures, lignes_prevues):
    """Ventile le total réel proportionnellement aux heures prévues.

    Le reliquat d'arrondi est placé sur la dernière affectation afin que la
    somme des détails reste exactement égale au total de l'état de salaire.
    """
    total_heures = arrondir_heures(total_heures)
    total_prevu = sum((heures for _, heures in lignes_prevues), Decimal('0'))
    if not lignes_prevues or total_prevu <= 0:
        return []

    reste = total_heures
    repartition = []
    for index, (affectation, heures_prevues) in enumerate(lignes_prevues):
        if index == len(lignes_prevues) - 1:
            heures_realisees = reste
        else:
            heures_realisees = arrondir_heures(
                total_heures * heures_prevues / total_prevu
            )
            reste -= heures_realisees
        repartition.append(
            (affectation, arrondir_heures(heures_prevues), heures_realisees)
        )

    return repartition


def salaire_fixe_proratise(enseignant, periode):
    premier_jour, dernier_jour = bornes_periode(periode)
    if enseignant.date_embauche > dernier_jour:
        return Decimal('0.00')

    premier_jour_paye = max(premier_jour, enseignant.date_embauche)
    jours_payes = Decimal((dernier_jour - premier_jour_paye).days + 1)
    jours_periode = Decimal((dernier_jour - premier_jour).days + 1)
    return arrondir_montant(
        (enseignant.salaire_fixe or Decimal('0')) * jours_payes / jours_periode
    )


@transaction.atomic
def calculer_etat_salaire(enseignant, periode, utilisateur):
    """Crée ou recalcule un état non validé et retourne ``(etat, modifie)``."""
    etat, _ = EtatSalaire.objects.select_for_update().get_or_create(
        enseignant=enseignant,
        periode=periode,
        defaults={
            'calcule_par': utilisateur,
            'salaire_base': Decimal('0'),
            'salaire_net': Decimal('0'),
        },
    )

    if etat.valide:
        return etat, False

    etat.details_heures.all().delete()

    if enseignant.est_taux_horaire:
        total_heures = heures_reellement_travaillees(enseignant, periode)
        taux_horaire = enseignant.taux_horaire or Decimal('0')
        etat.total_heures = total_heures
        etat.taux_horaire_applique = taux_horaire
        etat.salaire_base = arrondir_montant(total_heures * taux_horaire)
        etat.calcule_par = utilisateur
        etat.save()

        lignes_prevues = heures_prevues_par_affectation(enseignant, periode)
        for affectation, heures_prevues, heures_realisees in repartir_heures(
            total_heures, lignes_prevues
        ):
            DetailHeuresClasse.objects.create(
                etat_salaire=etat,
                affectation_classe=affectation,
                heures_prevues=heures_prevues,
                heures_realisees=heures_realisees,
                taux_horaire_applique=taux_horaire,
            )
    else:
        etat.total_heures = None
        etat.taux_horaire_applique = None
        etat.salaire_base = salaire_fixe_proratise(enseignant, periode)
        etat.calcule_par = utilisateur
        etat.save()

    return etat, True
