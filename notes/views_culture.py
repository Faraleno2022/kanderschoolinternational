"""
Activités culturelles de l'école : gestion interne (CRUD) des activités
publiées sur la page publique du site (images + descriptions).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect

from utilisateurs.utils import user_is_admin, filter_by_user_school, user_school
from .models import ActiviteCulturelle
from .forms import ActiviteCulturelleForm


def _activites_accessibles(request):
    qs = ActiviteCulturelle.objects.select_related('ecole', 'cree_par')
    if not user_is_admin(request.user):
        qs = filter_by_user_school(qs, request.user, 'ecole')
    return qs


@login_required
def activites_culturelles(request):
    """Liste des activités culturelles avec gestion."""
    activites = _activites_accessibles(request)
    paginator = Paginator(activites, 12)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'titre_page': "Activités culturelles de l'école",
        'page_activites': page,
    }
    return render(request, 'notes/culture/liste.html', context)


@login_required
def ajouter_activite_culturelle(request):
    if request.method == 'POST':
        form = ActiviteCulturelleForm(request.POST, request.FILES)
        if form.is_valid():
            activite = form.save(commit=False)
            activite.cree_par = request.user
            activite.ecole = user_school(request.user)
            activite.save()
            messages.success(request, f"Activité « {activite.titre} » enregistrée.")
            return redirect('notes:activites_culturelles')
    else:
        form = ActiviteCulturelleForm()

    context = {
        'titre_page': 'Nouvelle activité culturelle',
        'form': form,
        'mode': 'ajout',
    }
    return render(request, 'notes/culture/form.html', context)


@login_required
def modifier_activite_culturelle(request, activite_id):
    activite = get_object_or_404(_activites_accessibles(request), id=activite_id)

    if request.method == 'POST':
        form = ActiviteCulturelleForm(request.POST, request.FILES, instance=activite)
        if form.is_valid():
            form.save()
            messages.success(request, "Activité mise à jour.")
            return redirect('notes:activites_culturelles')
    else:
        form = ActiviteCulturelleForm(instance=activite)

    context = {
        'titre_page': f'Modifier — {activite.titre}',
        'form': form,
        'activite': activite,
        'mode': 'modification',
    }
    return render(request, 'notes/culture/form.html', context)


@login_required
def supprimer_activite_culturelle(request, activite_id):
    activite = get_object_or_404(_activites_accessibles(request), id=activite_id)
    if request.method == 'POST':
        titre = activite.titre
        activite.delete()
        messages.success(request, f"Activité « {titre} » supprimée.")
    return redirect('notes:activites_culturelles')


@login_required
def basculer_publication_activite(request, activite_id):
    """Publier / masquer une activité sur le site public."""
    activite = get_object_or_404(_activites_accessibles(request), id=activite_id)
    if request.method == 'POST':
        activite.publie = not activite.publie
        activite.save(update_fields=['publie'])
        etat = "publiée sur le site" if activite.publie else "masquée du site"
        messages.success(request, f"Activité « {activite.titre} » {etat}.")
    return redirect('notes:activites_culturelles')
