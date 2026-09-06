"""Répartition individuelle des élèves entre sections d'une même classe."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .models import Classe, Eleve
from .views_nouvelle_annee import _extraire_base_et_lettre
from utilisateurs.utils import filter_by_user_school


def _famille(classe):
    base = _extraire_base_et_lettre(classe.nom)[0]
    base = {'PS': 'PETITE SECTION', 'MS': 'MOYENNE SECTION', 'GS': 'GRANDE SECTION'}.get(base, base)
    return classe.ecole_id, classe.annee_scolaire, classe.niveau, base


def _autorise(user):
    profil = getattr(user, 'profil', None)
    return (user.is_superuser or user.is_staff
            or user.groups.filter(name__in=['Administrateurs', 'Directeurs', 'Comptables']).exists()
            or getattr(profil, 'peut_importer_eleves', False)
            or getattr(profil, 'role', '') in ['ADMIN', 'DIRECTEUR', 'COMPTABLE'])


@login_required
@require_http_methods(['GET', 'POST'])
def repartir_eleves(request):
    if not _autorise(request.user):
        return HttpResponseForbidden("Vous n'avez pas la permission de répartir les élèves.")
    eleves = filter_by_user_school(
        Eleve.objects.filter(est_dans_corbeille=False), request.user, 'classe__ecole',
    ).select_related('classe', 'classe__ecole')
    classes = filter_by_user_school(Classe.objects.all(), request.user).order_by('nom')

    if request.method == 'POST':
        if not all(request.POST.get(champ, '').isdigit() for champ in ('eleve_id', 'classe_id')):
            return HttpResponseBadRequest("Sélectionnez un élève et une classe valides.")
        with transaction.atomic():
            eleve = get_object_or_404(eleves.select_for_update(), pk=request.POST.get('eleve_id'))
            cible = get_object_or_404(classes, pk=request.POST.get('classe_id'))
            if _famille(eleve.classe) != _famille(cible):
                messages.error(request, "Choisissez une section de la même classe, école et année scolaire.")
            else:
                if eleve.classe_id != cible.pk:
                    eleve.classe = cible
                    eleve._conserver_matricule = True
                    eleve._current_user = request.user
                    eleve.save()
                messages.success(request, f"{eleve.nom_complet} : affectation enregistrée dans {cible.nom}.")
                if request.POST.get('action') == 'payer':
                    return redirect('paiements:ajouter_paiement_eleve', eleve_id=eleve.pk)
        return redirect(request.get_full_path())

    lot = request.GET.get('lot', '')
    if lot == 'dernier':
        eleves = eleves.filter(pk__in=request.session.get('derniers_eleves_importes', []))
    elif request.GET.get('statut', 'attente') != 'tous':
        eleves = eleves.filter(statut='ATTENTE_PAIEMENT')
    recherche = request.GET.get('q', '').strip()
    if recherche:
        eleves = eleves.filter(Q(nom__icontains=recherche) | Q(prenom__icontains=recherche)
                               | Q(matricule__icontains=recherche))
    familles = {}
    for classe in classes:
        familles.setdefault(_famille(classe), []).append(classe)
    page = Paginator(eleves.order_by('nom', 'prenom', 'pk'), 25).get_page(request.GET.get('page'))
    for eleve in page:
        eleve.sections_disponibles = familles.get(_famille(eleve.classe), [])
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'eleves/repartir_eleves.html', {
        'page_obj': page, 'lot': lot, 'q': recherche, 'query_params': params.urlencode(),
        'statut_filtre': request.GET.get('statut', 'attente'),
    })
