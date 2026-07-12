"""
Vues publiques du site vitrine (sans authentification).
"""
from django.core.paginator import Paginator
from django.shortcuts import render


def _activites_publiees():
    from notes.models import ActiviteCulturelle
    return ActiviteCulturelle.objects.filter(publie=True)


def home(request):
    """Page d'accueil publique, avec les dernières activités culturelles publiées."""
    try:
        activites = list(_activites_publiees()[:6])
    except Exception:
        activites = []
    return render(request, 'home.html', {'activites_culturelles': activites})


def activites_publiques(request):
    """Page publique listant toutes les activités culturelles publiées."""
    try:
        # Évaluer la requête ici : le Paginator interroge la base paresseusement,
        # et on veut retomber sur une liste vide si la table n'existe pas encore.
        activites = list(_activites_publiees())
    except Exception:
        activites = []
    paginator = Paginator(activites, 9)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'public/activites.html', {'page_activites': page})
