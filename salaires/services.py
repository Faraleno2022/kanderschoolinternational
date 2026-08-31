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

from .models import (
    AvanceSalaire,
    DetailHeuresClasse,
    Enseignant,
    EtatSalaire,
    PeriodeSalaire,
    SourceHeuresSalaire,
)


HEURE = Decimal('0.01')
MONTANT = Decimal('0.01')
STATUTS_HEURES_PAYEES = ('PRESENT', 'RETARD', 'PERMISSION')


def arrondir_heures(valeur):
    return Decimal(valeur or 0).quantize(HEURE, rounding=ROUND_HALF_UP)


def arrondir_montant(valeur):
    return Decimal(valeur or 0).quantize(MONTANT, rounding=ROUND_HALF_UP)


def total_avances_a_deduire(enseignant, periode, *, exclure_avance=None):
    """Total des avances approuvées ou déjà déduites pour une paie."""
    avances = AvanceSalaire.objects.filter(
        enseignant=enseignant,
        periode=periode,
        statut__in=(AvanceSalaire.Statut.APPROUVEE, AvanceSalaire.Statut.DEDUITE),
    )
    if exclure_avance and exclure_avance.pk:
        avances = avances.exclude(pk=exclure_avance.pk)
    return arrondir_montant(avances.aggregate(total=Sum('montant'))['total'])


def plafond_avance_disponible(enseignant, periode, *, exclure_avance=None):
    """Montant encore disponible sans rendre le salaire net négatif."""
    etat = EtatSalaire.objects.filter(
        enseignant=enseignant,
        periode=periode,
    ).first()
    if etat:
        brut_disponible = (
            (etat.salaire_base or Decimal('0'))
            + (etat.primes or Decimal('0'))
            - (etat.deductions or Decimal('0'))
        )
    else:
        brut_disponible = enseignant.calculer_salaire_mensuel()
    deja_avance = total_avances_a_deduire(
        enseignant,
        periode,
        exclure_avance=exclure_avance,
    )
    return max(Decimal('0'), arrondir_montant(brut_disponible - deja_avance))


@transaction.atomic
def synchroniser_avances_etat(enseignant, periode):
    """Répercute les avances sur un état ouvert sans toucher à une paie validée."""
    etat = (
        EtatSalaire.objects.select_for_update()
        .filter(enseignant=enseignant, periode=periode)
        .first()
    )
    if etat is None or etat.valide or periode.cloturee:
        return etat, False
    montant = total_avances_a_deduire(enseignant, periode)
    if etat.montant_avances == montant:
        return etat, False
    etat.montant_avances = montant
    etat.save(update_fields={'montant_avances', 'salaire_net'})
    return etat, True


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
def calculer_etat_salaire(
    enseignant,
    periode,
    utilisateur,
    *,
    source_heures=None,
    heures_mensuelles=None,
):
    """Crée ou recalcule un état non validé et retourne ``(etat, modifie)``.

    Pour un enseignant au taux horaire, une saisie mensuelle explicite est
    conservée lors des recalculs généraux. Le passage explicite de
    ``source_heures=POINTAGE`` permet de revenir au cumul des pointages.
    """
    etat, cree = EtatSalaire.objects.select_for_update().get_or_create(
        enseignant=enseignant,
        periode=periode,
        defaults={
            'calcule_par': utilisateur,
            'salaire_base': Decimal('0'),
            'salaire_net': Decimal('0'),
            'source_heures': (
                SourceHeuresSalaire.POINTAGE
                if enseignant.est_taux_horaire
                else SourceHeuresSalaire.FIXE
            ),
        },
    )

    if etat.valide:
        return etat, False

    etat.details_heures.all().delete()
    etat.montant_avances = total_avances_a_deduire(enseignant, periode)

    if enseignant.est_taux_horaire:
        source = source_heures
        if source is None:
            source = (
                etat.source_heures
                if not cree and etat.source_heures == SourceHeuresSalaire.MENSUEL
                else SourceHeuresSalaire.POINTAGE
            )

        if source == SourceHeuresSalaire.MENSUEL:
            if heures_mensuelles is None:
                heures_mensuelles = (
                    etat.total_heures
                    if not cree
                    and etat.source_heures == SourceHeuresSalaire.MENSUEL
                    and etat.total_heures is not None
                    else enseignant.heures_mensuelles
                )
            total_heures = arrondir_heures(heures_mensuelles)
        else:
            source = SourceHeuresSalaire.POINTAGE
            total_heures = heures_reellement_travaillees(enseignant, periode)

        taux_horaire = enseignant.taux_horaire or Decimal('0')
        etat.total_heures = total_heures
        etat.taux_horaire_applique = taux_horaire
        etat.source_heures = source
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
        etat.source_heures = SourceHeuresSalaire.FIXE
        etat.salaire_base = salaire_fixe_proratise(enseignant, periode)
        etat.calcule_par = utilisateur
        etat.save()

    return etat, True


@transaction.atomic
def calculer_etats_salaire_periode(periode, utilisateur):
    """Regroupe et calcule les états de tous les enseignants éligibles.

    La fonction est idempotente : elle crée les états manquants et recalcule
    seulement les états encore ouverts. Un état validé reste intact.
    """
    periode = PeriodeSalaire.objects.select_for_update().get(pk=periode.pk)
    if periode.cloturee:
        raise ValueError("Impossible de calculer une période clôturée.")

    statistiques = {
        'enseignants': 0,
        'crees': 0,
        'recalcules': 0,
        'ignores': 0,
        'modifies': 0,
    }
    for enseignant in enseignants_eligibles(periode).select_for_update():
        statistiques['enseignants'] += 1
        existait = EtatSalaire.objects.filter(
            enseignant=enseignant,
            periode=periode,
        ).exists()
        _etat, modifie = calculer_etat_salaire(
            enseignant,
            periode,
            utilisateur,
        )
        if not modifie:
            statistiques['ignores'] += 1
            continue
        statistiques['modifies'] += 1
        cle = 'recalcules' if existait else 'crees'
        statistiques[cle] += 1

    return statistiques


def recalculer_etat_salaire_pour_date(enseignant, jour, utilisateur):
    """Synchronise immédiatement un pointage avec la paie du mois ouvert.

    Une saisie mensuelle globale déjà choisie reste prioritaire et un état
    validé n'est jamais modifié.
    """
    if not enseignant.est_taux_horaire:
        return None, False

    periode = PeriodeSalaire.objects.filter(
        ecole=enseignant.ecole,
        mois=jour.month,
        annee=jour.year,
        cloturee=False,
    ).first()
    if periode is None:
        return None, False

    etat = EtatSalaire.objects.filter(
        enseignant=enseignant,
        periode=periode,
    ).first()
    if etat and (
        etat.valide or etat.source_heures == SourceHeuresSalaire.MENSUEL
    ):
        return etat, False

    return calculer_etat_salaire(
        enseignant,
        periode,
        utilisateur,
        source_heures=SourceHeuresSalaire.POINTAGE,
    )
