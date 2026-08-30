"""Lecture sécurisée et agrégation du registre des corrections de caisse."""

from datetime import date

from django.db.models import Q

from utilisateurs.utils import user_is_superadmin, user_school

from .models import HistoriqueModificationPaiement


PERIODES_AUDIT = ('today', 'week', 'month', 'year')


def historique_paiements_pour_utilisateur(user):
    queryset = HistoriqueModificationPaiement.objects.select_related(
        'paiement', 'paiement__ecole_encaissement', 'utilisateur',
    )
    if user_is_superadmin(user):
        return queryset
    school = user_school(user)
    if school is None:
        return queryset.none()
    # Après une suppression définitive, `paiement` vaut NULL. L'instantané
    # JSON est donc indispensable pour conserver l'isolation entre écoles.
    return queryset.filter(
        Q(paiement__ecole_encaissement_id=school.pk)
        | Q(donnees_avant__ecole_encaissement_id=school.pk)
        | Q(donnees_apres__ecole_encaissement_id=school.pk)
    ).distinct()


def bornes_periodes_audit(today):
    return {
        'today': today,
        'week': today.fromordinal(today.toordinal() - today.weekday()),
        'month': today.replace(day=1),
        'year': date(today.year, 1, 1),
    }


def statistiques_operations_paiements(user, today):
    starts = bornes_periodes_audit(today)
    stats = {
        period: {
            'montant_modifie': 0,
            'nombre_modifications': 0,
            'montant_supprime': 0,
            'nombre_suppressions': 0,
            'montant_annule': 0,
            'nombre_annulations': 0,
            'impact_net': 0,
        }
        for period in PERIODES_AUDIT
    }
    events = historique_paiements_pour_utilisateur(user).filter(
        date_modification__date__gte=starts['year'],
        date_modification__date__lte=today,
    )
    for event in events.iterator():
        event_date = event.date_modification.date()
        operation = event.type_operation
        for period, start in starts.items():
            if event_date < start:
                continue
            row = stats[period]
            row['impact_net'] += int(event.impact_financier)
            if operation == 'SUPPRESSION':
                row['montant_supprime'] += int(event.montant_avant)
                row['nombre_suppressions'] += 1
            elif operation == 'ANNULATION':
                row['montant_annule'] += int(event.montant_avant)
                row['nombre_annulations'] += 1
            else:
                volume = int(event.volume_montant_modifie)
                if volume:
                    row['montant_modifie'] += volume
                    row['nombre_modifications'] += 1
    return stats
