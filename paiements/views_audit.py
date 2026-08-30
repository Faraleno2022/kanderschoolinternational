"""Registre consultable des modifications, annulations et suppressions."""

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from .audit import historique_paiements_pour_utilisateur


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


@login_required
def historique_operations_paiements(request):
    queryset = historique_paiements_pour_utilisateur(request.user)
    query = (request.GET.get('q') or '').strip()
    operation = (request.GET.get('operation') or '').strip().upper()
    date_debut = _parse_date(request.GET.get('date_debut'))
    date_fin = _parse_date(request.GET.get('date_fin'))

    if query:
        queryset = queryset.filter(
            Q(numero_recu__icontains=query) | Q(eleve__icontains=query)
            | Q(motif__icontains=query) | Q(utilisateur__username__icontains=query)
            | Q(utilisateur__first_name__icontains=query)
            | Q(utilisateur__last_name__icontains=query)
        )
    if date_debut:
        queryset = queryset.filter(date_modification__date__gte=date_debut)
    if date_fin:
        queryset = queryset.filter(date_modification__date__lte=date_fin)

    if operation == 'SUPPRESSION':
        queryset = queryset.filter(donnees_apres={})
    elif operation == 'ANNULATION':
        queryset = queryset.filter(donnees_apres__statut='ANNULE')
    elif operation == 'MODIFICATION':
        queryset = queryset.exclude(donnees_apres={}).exclude(donnees_apres__statut='ANNULE')
    else:
        operation = ''

    page_obj = Paginator(queryset.order_by('-date_modification', '-pk'), 40).get_page(request.GET.get('page'))
    return render(request, 'paiements/historique_operations.html', {
        'titre_page': 'Modifications et suppressions de paiements',
        'page_obj': page_obj, 'q': query, 'operation': operation,
        'date_debut': date_debut.isoformat() if date_debut else '',
        'date_fin': date_fin.isoformat() if date_fin else '',
    })
