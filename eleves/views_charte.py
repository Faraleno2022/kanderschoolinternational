import os
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from ecole_moderne.theme import (
    DEFAULT_PALETTE,
    FIELD_MAP,
    extract_palette_from_logo,
    get_school_palette,
)
from utilisateurs.models import Profil
from utilisateurs.utils import user_is_admin, user_is_superadmin, user_school

from .forms_charte import CharteGraphiqueEcoleForm
from .models import Ecole


def _ecole_autorisee(request, ecole_id=None):
    if not user_is_admin(request.user):
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier la charte graphique.")

    if ecole_id:
        try:
            ecole_id = int(ecole_id)
        except (TypeError, ValueError):
            raise Http404("École introuvable.")

    if user_is_superadmin(request.user):
        queryset = Ecole.objects.all()
        if not ecole_id:
            ecole_associee = user_school(request.user)
            if ecole_associee:
                return ecole_associee
            return queryset.order_by('nom').first()

    ecole_utilisateur = user_school(request.user)
    queryset = Ecole.objects.filter(pk=getattr(ecole_utilisateur, 'pk', None))
    if not ecole_id:
        return ecole_utilisateur
    return get_object_or_404(queryset, pk=ecole_id)


def _url_charte(ecole):
    base = reverse('eleves:charte_graphique')
    return f"{base}?{urlencode({'ecole': ecole.pk})}" if ecole else base


def _invalider_caches_ecole(ecole):
    user_ids = Profil.objects.filter(ecole=ecole).values_list('user_id', flat=True)
    cache.delete_many([f'user_school_{user_id}' for user_id in user_ids])


@login_required
@require_http_methods(['GET', 'POST'])
def charte_graphique(request):
    requested_id = request.POST.get('ecole_id') or request.GET.get('ecole')
    ecole = _ecole_autorisee(request, requested_id)
    if ecole is None:
        messages.warning(request, "Créez d'abord une école avant de définir sa charte graphique.")
        return redirect('eleves:creer_ecole')

    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        with transaction.atomic():
            ecole = Ecole.objects.select_for_update().get(pk=ecole.pk)
            if action == 'reset':
                for key, field_name in FIELD_MAP.items():
                    setattr(ecole, field_name, DEFAULT_PALETTE[key])
                ecole.afficher_filigrane = True
                ecole.opacite_filigrane = DEFAULT_PALETTE['watermark_opacity']
                ecole.save(update_fields=[
                    *FIELD_MAP.values(), 'afficher_filigrane', 'opacite_filigrane',
                ])
                messages.success(request, 'La charte graphique par défaut a été restaurée.')
            elif action == 'extract_logo':
                logo_path = getattr(getattr(ecole, 'logo', None), 'path', None)
                if not logo_path or not os.path.exists(logo_path):
                    messages.error(request, "Ajoutez d'abord un logo valide à cette école.")
                    return redirect(_url_charte(ecole))
                extracted = extract_palette_from_logo(logo_path)
                for field_name, value in extracted.items():
                    setattr(ecole, field_name, value)
                ecole.save(update_fields=list(extracted))
                messages.success(request, 'Les couleurs principales ont été extraites du logo. Vérifiez puis enregistrez la palette.')
            else:
                form = CharteGraphiqueEcoleForm(request.POST, instance=ecole)
                if form.is_valid():
                    form.save()
                    messages.success(request, 'La charte graphique a été enregistrée et appliquée aux interfaces et documents.')
                else:
                    return render(request, 'eleves/charte_graphique.html', {
                        'form': form,
                        'ecole': ecole,
                        'ecoles': Ecole.objects.order_by('nom') if user_is_superadmin(request.user) else None,
                        'charte_graphique': get_school_palette(ecole),
                        'titre_page': 'Charte graphique',
                    })
        _invalider_caches_ecole(ecole)
        return redirect(_url_charte(ecole))

    return render(request, 'eleves/charte_graphique.html', {
        'form': CharteGraphiqueEcoleForm(instance=ecole),
        'ecole': ecole,
        'ecoles': Ecole.objects.order_by('nom') if user_is_superadmin(request.user) else None,
        'charte_graphique': get_school_palette(ecole),
        'titre_page': 'Charte graphique',
    })

