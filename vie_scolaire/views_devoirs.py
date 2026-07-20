"""
Module Suivi des devoirs : enregistrement des devoirs par classe et suivi
de la remise par élève.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from eleves.models import Classe, Eleve
from eleves.utils_annee import get_annee_active
from utilisateurs.utils import user_is_superadmin, user_school, filter_by_user_school

from .models import Devoir, RemiseDevoir
from .forms import DevoirForm


def _classes_accessibles(request):
    qs = Classe.objects.select_related('ecole').all()
    if not user_is_superadmin(request.user):
        qs = filter_by_user_school(qs, request.user, 'ecole')
    ecole = user_school(request.user)
    annee = get_annee_active(request, ecole) if ecole else None
    if annee:
        qs = qs.filter(annee_scolaire=annee)
    return qs.order_by('niveau', 'nom')


def _devoirs_accessibles(request):
    qs = Devoir.objects.select_related('classe', 'classe__ecole', 'cree_par')
    if not user_is_superadmin(request.user):
        qs = filter_by_user_school(qs, request.user, 'classe__ecole')
    return qs


def _matieres_suggestions(request):
    """Matières déjà utilisées (pour l'autocomplétion du formulaire)."""
    return list(
        _devoirs_accessibles(request)
        .exclude(matiere='')
        .values_list('matiere', flat=True)
        .distinct()
        .order_by('matiere')
    )


@login_required
def liste_devoirs(request):
    """Liste des devoirs, filtrable par classe ; sépare à venir / échus."""
    classes = list(_classes_accessibles(request))
    classe_id = request.GET.get('classe')
    devoirs = _devoirs_accessibles(request)

    classe_selection = None
    if classe_id:
        classe_selection = get_object_or_404(_classes_accessibles(request), id=classe_id)
        devoirs = devoirs.filter(classe=classe_selection)

    aujourd_hui = timezone.localdate()
    devoirs = devoirs.prefetch_related('remises')

    a_venir, echus = [], []
    for d in devoirs:
        (a_venir if d.date_remise >= aujourd_hui else echus).append(d)
    a_venir.sort(key=lambda d: d.date_remise)

    context = {
        'titre_page': 'Suivi des devoirs',
        'classes': classes,
        'classe_selection': classe_selection,
        'devoirs_a_venir': a_venir,
        'devoirs_echus': echus,
        'aujourd_hui': aujourd_hui,
    }
    return render(request, 'vie_scolaire/devoirs/liste.html', context)


@login_required
def ajouter_devoir(request):
    classes_qs = _classes_accessibles(request)
    if request.method == 'POST':
        form = DevoirForm(request.POST, request.FILES, classes_qs=classes_qs)
        if form.is_valid():
            devoir = form.save(commit=False)
            devoir.cree_par = request.user
            devoir.save()
            # Initialiser les remises (NON_REMIS) pour les élèves actifs de la classe
            eleves = Eleve.objects.filter(classe=devoir.classe, statut='ACTIF')
            RemiseDevoir.objects.bulk_create([
                RemiseDevoir(devoir=devoir, eleve=e) for e in eleves
            ])
            messages.success(request, f"Devoir « {devoir.titre} » créé.")
            return redirect('vie_scolaire:suivi_devoir', devoir_id=devoir.id)
    else:
        form = DevoirForm(classes_qs=classes_qs, initial={'date_donne': timezone.localdate()})

    context = {
        'titre_page': 'Nouveau devoir',
        'form': form,
        'matieres_suggestions': _matieres_suggestions(request),
    }
    return render(request, 'vie_scolaire/devoirs/form.html', context)


@login_required
def modifier_devoir(request, devoir_id):
    devoir = get_object_or_404(_devoirs_accessibles(request), id=devoir_id)
    classes_qs = _classes_accessibles(request)
    if request.method == 'POST':
        form = DevoirForm(request.POST, request.FILES, instance=devoir, classes_qs=classes_qs)
        if form.is_valid():
            form.save()
            # Créer les remises manquantes si la classe a changé / de nouveaux élèves
            eleves = Eleve.objects.filter(classe=devoir.classe, statut='ACTIF')
            existants = set(devoir.remises.values_list('eleve_id', flat=True))
            manquants = [RemiseDevoir(devoir=devoir, eleve=e) for e in eleves if e.id not in existants]
            if manquants:
                RemiseDevoir.objects.bulk_create(manquants)
            messages.success(request, "Devoir mis à jour.")
            return redirect('vie_scolaire:suivi_devoir', devoir_id=devoir.id)
    else:
        form = DevoirForm(instance=devoir, classes_qs=classes_qs)

    context = {
        'titre_page': f"Modifier — {devoir.titre}",
        'form': form,
        'devoir': devoir,
        'matieres_suggestions': _matieres_suggestions(request),
    }
    return render(request, 'vie_scolaire/devoirs/form.html', context)


@login_required
def supprimer_devoir(request, devoir_id):
    devoir = get_object_or_404(_devoirs_accessibles(request), id=devoir_id)
    if request.method == 'POST':
        titre = devoir.titre
        devoir.delete()
        messages.success(request, f"Devoir « {titre} » supprimé.")
        return redirect('vie_scolaire:liste_devoirs')
    context = {'titre_page': 'Supprimer le devoir', 'devoir': devoir}
    return render(request, 'vie_scolaire/devoirs/supprimer.html', context)


@login_required
def suivi_devoir(request, devoir_id):
    """Suivi de la remise du devoir par élève."""
    devoir = get_object_or_404(_devoirs_accessibles(request), id=devoir_id)
    eleves = Eleve.objects.filter(classe=devoir.classe, statut='ACTIF').order_by('nom', 'prenom')

    if request.method == 'POST':
        existantes = {r.eleve_id: r for r in devoir.remises.all()}
        valides = dict(RemiseDevoir.STATUT_CHOICES)
        with transaction.atomic():
            for eleve in eleves:
                statut = request.POST.get(f'statut_{eleve.id}', RemiseDevoir.STATUT_NON_REMIS)
                if statut not in valides:
                    statut = RemiseDevoir.STATUT_NON_REMIS
                remarque = (request.POST.get(f'remarque_{eleve.id}', '') or '').strip()[:200]
                remise = existantes.get(eleve.id)
                if remise:
                    remise.statut = statut
                    remise.remarque = remarque
                    remise.save(update_fields=['statut', 'remarque', 'date_maj'])
                else:
                    RemiseDevoir.objects.create(
                        devoir=devoir, eleve=eleve, statut=statut, remarque=remarque
                    )
        messages.success(request, "Suivi des remises enregistré.")
        return redirect('vie_scolaire:suivi_devoir', devoir_id=devoir.id)

    existantes = {r.eleve_id: r for r in devoir.remises.all()}
    lignes = []
    for eleve in eleves:
        r = existantes.get(eleve.id)
        lignes.append({
            'eleve': eleve,
            'statut': r.statut if r else RemiseDevoir.STATUT_NON_REMIS,
            'remarque': r.remarque if r else '',
        })

    nb_remis = sum(1 for l in lignes if l['statut'] in (RemiseDevoir.STATUT_REMIS, RemiseDevoir.STATUT_EN_RETARD))
    context = {
        'titre_page': f"Suivi — {devoir.titre}",
        'devoir': devoir,
        'lignes': lignes,
        'statuts': RemiseDevoir.STATUT_CHOICES,
        'nb_remis': nb_remis,
        'nb_total': len(lignes),
    }
    return render(request, 'vie_scolaire/devoirs/suivi.html', context)
