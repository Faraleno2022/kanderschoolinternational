"""
Module Infirmerie : suivi de l'état de santé des élèves.
Tableau de bord pour l'infirmière, fiche santé par élève, saisie des visites.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from utilisateurs.utils import user_is_admin, filter_by_user_school
from .models import Eleve, VisiteMedicale
from .forms import VisiteMedicaleForm


def _eleves_accessibles(request):
    qs = Eleve.objects.filter(statut='ACTIF').select_related('classe', 'classe__ecole')
    if not user_is_admin(request.user):
        qs = filter_by_user_school(qs, request.user, 'classe__ecole')
    return qs


def _visites_accessibles(request):
    qs = VisiteMedicale.objects.select_related('eleve', 'eleve__classe', 'cree_par')
    if not user_is_admin(request.user):
        qs = filter_by_user_school(qs, request.user, 'eleve__classe__ecole')
    return qs


@login_required
def infirmerie_dashboard(request):
    """Tableau de bord de l'infirmerie : visites récentes, alertes médicales, recherche."""
    visites = _visites_accessibles(request)
    eleves = _eleves_accessibles(request)

    aujourd_hui = timezone.localdate()
    debut_semaine = aujourd_hui - timedelta(days=aujourd_hui.weekday())

    stats = {
        'visites_aujourd_hui': visites.filter(date_visite__date=aujourd_hui).count(),
        'visites_semaine': visites.filter(date_visite__date__gte=debut_semaine).count(),
        'en_observation': visites.filter(statut='EN_OBSERVATION').count(),
        'eleves_avec_alertes': eleves.filter(
            Q(allergies__isnull=False) & ~Q(allergies='') |
            Q(maladies_chroniques__isnull=False) & ~Q(maladies_chroniques='')
        ).count(),
    }

    # Recherche d'élève
    recherche = request.GET.get('q', '').strip()
    resultats_recherche = None
    if recherche:
        resultats_recherche = eleves.filter(
            Q(prenom__icontains=recherche) |
            Q(nom__icontains=recherche) |
            Q(matricule__icontains=recherche)
        ).order_by('prenom', 'nom')[:20]

    # Élèves à surveiller (allergies ou maladies chroniques renseignées)
    eleves_a_surveiller = eleves.filter(
        Q(allergies__isnull=False) & ~Q(allergies='') |
        Q(maladies_chroniques__isnull=False) & ~Q(maladies_chroniques='') |
        Q(traitement_en_cours__isnull=False) & ~Q(traitement_en_cours='')
    ).order_by('prenom', 'nom')[:30]

    # Dernières visites (paginées)
    paginator = Paginator(visites, 20)
    page_visites = paginator.get_page(request.GET.get('page'))

    context = {
        'titre_page': 'Infirmerie — Suivi santé des élèves',
        'stats': stats,
        'page_visites': page_visites,
        'recherche': recherche,
        'resultats_recherche': resultats_recherche,
        'eleves_a_surveiller': eleves_a_surveiller,
    }
    return render(request, 'eleves/infirmerie/dashboard.html', context)


@login_required
def sante_eleve(request, eleve_id):
    """Fiche santé d'un élève : informations médicales + historique des visites."""
    eleve = get_object_or_404(_eleves_accessibles(request), id=eleve_id)
    visites = eleve.visites_medicales.select_related('cree_par').all()

    context = {
        'titre_page': f'Fiche santé — {eleve.nom_complet}',
        'eleve': eleve,
        'visites': visites,
    }
    return render(request, 'eleves/infirmerie/sante_eleve.html', context)


@login_required
def ajouter_visite(request, eleve_id):
    """Enregistrer un passage à l'infirmerie pour un élève."""
    eleve = get_object_or_404(_eleves_accessibles(request), id=eleve_id)

    if request.method == 'POST':
        form = VisiteMedicaleForm(request.POST)
        if form.is_valid():
            visite = form.save(commit=False)
            visite.eleve = eleve
            visite.cree_par = request.user
            visite.save()
            messages.success(request, f"Visite enregistrée pour {eleve.nom_complet}.")
            return redirect('eleves:sante_eleve', eleve_id=eleve.id)
    else:
        form = VisiteMedicaleForm(initial={
            'date_visite': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        })

    context = {
        'titre_page': f'Nouvelle visite — {eleve.nom_complet}',
        'eleve': eleve,
        'form': form,
        'mode': 'ajout',
    }
    return render(request, 'eleves/infirmerie/visite_form.html', context)


@login_required
def modifier_visite(request, visite_id):
    """Modifier une visite existante."""
    visite = get_object_or_404(_visites_accessibles(request), id=visite_id)
    eleve = visite.eleve

    if request.method == 'POST':
        form = VisiteMedicaleForm(request.POST, instance=visite)
        if form.is_valid():
            form.save()
            messages.success(request, "Visite mise à jour.")
            return redirect('eleves:sante_eleve', eleve_id=eleve.id)
    else:
        form = VisiteMedicaleForm(instance=visite)

    context = {
        'titre_page': f'Modifier la visite — {eleve.nom_complet}',
        'eleve': eleve,
        'form': form,
        'mode': 'modification',
    }
    return render(request, 'eleves/infirmerie/visite_form.html', context)


@login_required
def supprimer_visite(request, visite_id):
    """Supprimer une visite (confirmation via POST)."""
    visite = get_object_or_404(_visites_accessibles(request), id=visite_id)
    eleve_id = visite.eleve_id
    if request.method == 'POST':
        visite.delete()
        messages.success(request, "Visite supprimée.")
    return redirect('eleves:sante_eleve', eleve_id=eleve_id)
