from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Sum
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import datetime, date, timedelta
from decimal import Decimal
import uuid

from .models_bibliotheque import (
    CategorieLivre, Livre, Emprunt, Reservation,
    HistoriqueLivre, ParametreBibliotheque
)
from eleves.models import Eleve
from utilisateurs.utils import user_school


RESERVATION_ACTIVE_STATUSES = ('EN_ATTENTE', 'DISPONIBLE')
LIVRE_OPERATIONAL_STATUSES = ('DISPONIBLE', 'EMPRUNTE', 'RESERVE')


def _livres_bibliotheque(user):
    livres = Livre.objects.select_related('categorie', 'cree_par', 'cree_par__profil')
    ecole = user_school(user)
    if ecole:
        livres = livres.filter(cree_par__profil__ecole=ecole)
    return livres


def _eleves_bibliotheque(user):
    eleves = Eleve.objects.select_related('classe', 'classe__ecole')
    ecole = user_school(user)
    if ecole:
        eleves = eleves.filter(classe__ecole=ecole)
    return eleves


def _reservations_bibliotheque(user):
    reservations = Reservation.objects.select_related(
        'livre', 'eleve', 'eleve__classe', 'eleve__classe__ecole',
        'cree_par', 'traitee_par', 'emprunt',
    )
    ecole = user_school(user)
    if ecole:
        reservations = reservations.filter(eleve__classe__ecole=ecole)
    return reservations


def _parametres_bibliotheque():
    return ParametreBibliotheque.objects.first()


def _duree_reservation():
    params = _parametres_bibliotheque()
    return max(1, params.duree_reservation_defaut if params else 7)


def _generer_numero_reservation():
    return f"RES-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def _generer_numero_emprunt():
    return f"EMP-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def _synchroniser_statut_livre(livre):
    """Synchronise le statut synthétique sans toucher aux livres hors service."""
    if livre.statut not in LIVRE_OPERATIONAL_STATUSES:
        return
    if livre.exemplaires_disponibles > 0:
        livre.statut = 'DISPONIBLE'
    elif Reservation.objects.filter(
        livre=livre,
        statut='DISPONIBLE',
        exemplaire_bloque=True,
    ).exists():
        livre.statut = 'RESERVE'
    else:
        livre.statut = 'EMPRUNTE'


def _promouvoir_reservations_en_attente(livre, utilisateur=None):
    """Met de côté chaque exemplaire libre pour la file d'attente, dans l'ordre."""
    maintenant = timezone.now()
    duree = _duree_reservation()
    promotions = 0
    while livre.exemplaires_disponibles > 0:
        reservation = Reservation.objects.select_for_update().filter(
            livre=livre,
            statut='EN_ATTENTE',
            date_expiration__gt=maintenant,
        ).order_by('date_reservation', 'pk').first()
        if reservation is None:
            break
        livre.exemplaires_disponibles -= 1
        reservation.statut = 'DISPONIBLE'
        reservation.exemplaire_bloque = True
        reservation.date_mise_disponible = maintenant
        reservation.date_expiration = maintenant + timedelta(days=duree)
        reservation.save()
        HistoriqueLivre.objects.create(
            livre=livre,
            action='RESERVATION',
            description=(
                f'Exemplaire disponible pour {reservation.eleve} - '
                f'{reservation.numero_reservation}'
            ),
            utilisateur=utilisateur,
        )
        promotions += 1
    _synchroniser_statut_livre(livre)
    livre.save()
    return promotions


def _expirer_reservations(queryset, utilisateur=None):
    """Expire les réservations échues et réattribue les exemplaires libérés."""
    ids = list(queryset.filter(
        statut__in=RESERVATION_ACTIVE_STATUSES,
        date_expiration__lte=timezone.now(),
    ).values_list('pk', flat=True))
    if not ids:
        return 0

    with transaction.atomic():
        reservations = Reservation.objects.select_for_update().filter(pk__in=ids)
        for reservation in reservations:
            livre = Livre.objects.select_for_update().get(pk=reservation.livre_id)
            if reservation.exemplaire_bloque:
                livre.exemplaires_disponibles = min(
                    livre.nombre_exemplaires,
                    livre.exemplaires_disponibles + 1,
                )
            reservation.statut = 'EXPIREE'
            reservation.exemplaire_bloque = False
            reservation.date_traitement = timezone.now()
            reservation.traitee_par = utilisateur
            reservation.save()
            _promouvoir_reservations_en_attente(livre, utilisateur)
    return len(ids)


@login_required
def dashboard_bibliotheque(request):
    """Dashboard principal de la bibliothèque"""
    from utilisateurs.utils import user_school

    ecole = user_school(request.user)

    # Filtres de base par école
    livres_qs = Livre.objects.filter(actif=True)
    emprunts_qs = Emprunt.objects.all()
    reservations_qs = Reservation.objects.all()
    if ecole:
        livres_qs = livres_qs.filter(cree_par__profil__ecole=ecole)
        # Emprunts/réservations : filtrer par l'école de l'élève (appartenance
        # métier fiable, cree_par pouvant être vide sur les imports)
        emprunts_qs = emprunts_qs.filter(eleve__classe__ecole=ecole)
        reservations_qs = reservations_qs.filter(eleve__classe__ecole=ecole)

    # Statistiques générales
    total_livres = livres_qs.count()
    total_exemplaires = livres_qs.aggregate(
        total=Sum('nombre_exemplaires')
    )['total'] or 0

    livres_disponibles = livres_qs.filter(
        statut='DISPONIBLE',
        exemplaires_disponibles__gt=0
    ).count()

    # Emprunts
    emprunts_en_cours = emprunts_qs.filter(statut='EN_COURS').count()
    emprunts_en_retard = emprunts_qs.filter(statut='EN_RETARD').count()

    # Réservations
    reservations_actives = reservations_qs.filter(
        statut__in=['EN_ATTENTE', 'DISPONIBLE']
    ).count()

    # Pénalités à recouvrer
    penalites_total = emprunts_qs.filter(
        penalite_payee=False,
        montant_penalite__gt=0
    ).aggregate(total=Sum('montant_penalite'))['total'] or 0

    # Derniers emprunts
    derniers_emprunts = emprunts_qs.select_related(
        'livre', 'eleve', 'cree_par'
    ).order_by('-date_emprunt')[:10]

    # Livres les plus empruntés
    livres_populaires = livres_qs.annotate(
        nb_emprunts=Count('emprunts')
    ).order_by('-nb_emprunts')[:10]

    # Répartition par catégorie
    repartition_categories = CategorieLivre.objects.annotate(
        nb_livres=Count('livres')
    ).filter(actif=True)
    
    context = {
        'titre_page': 'Dashboard Bibliothèque',
        'total_livres': total_livres,
        'total_exemplaires': total_exemplaires,
        'livres_disponibles': livres_disponibles,
        'emprunts_en_cours': emprunts_en_cours,
        'emprunts_en_retard': emprunts_en_retard,
        'reservations_actives': reservations_actives,
        'penalites_total': penalites_total,
        'derniers_emprunts': derniers_emprunts,
        'livres_populaires': livres_populaires,
        'repartition_categories': repartition_categories,
    }
    
    return render(request, 'depenses/bibliotheque/dashboard.html', context)


@login_required
def catalogue_livres(request):
    """Catalogue des livres"""
    from utilisateurs.utils import user_school

    # Filtres
    q = request.GET.get('q', '')
    categorie_id = request.GET.get('categorie', '')
    statut = request.GET.get('statut', '')
    langue = request.GET.get('langue', '')

    livres = Livre.objects.select_related('categorie').filter(actif=True)
    # Sécurité : filtrer par école
    ecole = user_school(request.user)
    if ecole:
        livres = livres.filter(cree_par__profil__ecole=ecole)
    
    if q:
        livres = livres.filter(
            Q(code_livre__icontains=q) |
            Q(isbn__icontains=q) |
            Q(titre__icontains=q) |
            Q(auteur__icontains=q) |
            Q(editeur__icontains=q) |
            Q(mots_cles__icontains=q)
        )
    
    if categorie_id:
        livres = livres.filter(categorie_id=categorie_id)
    
    if statut:
        livres = livres.filter(statut=statut)
    
    if langue:
        livres = livres.filter(langue=langue)
    
    categories = CategorieLivre.objects.filter(actif=True)
    
    context = {
        'titre_page': 'Catalogue de Livres',
        'livres': livres,
        'categories': categories,
        'q': q,
        'categorie_id': categorie_id,
        'statut': statut,
        'langue': langue,
    }
    
    return render(request, 'depenses/bibliotheque/catalogue.html', context)


def _generer_code_livre():
    """Génère un code séquentiel du type LIV-YYYYMMDD-0001."""
    today = date.today()
    base = f"LIV-{today.strftime('%Y%m%d')}"
    dernier = Livre.objects.filter(
        code_livre__startswith=base
    ).order_by('-code_livre').first()
    if dernier:
        try:
            num = int(dernier.code_livre.split('-')[-1]) + 1
        except (ValueError, IndexError):
            num = 1
    else:
        num = 1
    return f"{base}-{num:04d}"


@login_required
def ajouter_livre(request):
    """Ajouter un livre au catalogue"""
    from .forms import LivreForm

    if request.method == 'POST':
        form = LivreForm(request.POST, request.FILES)
        if form.is_valid():
            livre = form.save(commit=False)
            livre.cree_par = request.user
            if not livre.code_livre:
                livre.code_livre = _generer_code_livre()
            # Aligner les exemplaires disponibles sur le total à la création
            livre.exemplaires_disponibles = livre.nombre_exemplaires
            livre.statut = 'DISPONIBLE'
            livre.save()
            messages.success(request, f'Livre « {livre.titre} » ajouté au catalogue.')
            return redirect('depenses:catalogue_livres')
        else:
            messages.error(request, "Veuillez corriger les erreurs du formulaire.")
    else:
        form = LivreForm()

    context = {
        'titre_page': 'Ajouter un livre',
        'form': form,
        'mode': 'ajout',
    }
    return render(request, 'depenses/bibliotheque/form_livre.html', context)


@login_required
def modifier_livre(request, livre_id):
    """Modifier un livre du catalogue"""
    from .forms import LivreForm
    from utilisateurs.utils import user_school

    livre = get_object_or_404(Livre, pk=livre_id)
    # Sécurité : école
    ecole = user_school(request.user)
    if ecole:
        livre_profil = getattr(getattr(livre, 'cree_par', None), 'profil', None)
        if livre_profil and livre_profil.ecole != ecole:
            messages.error(request, "Accès refusé : ce livre n'appartient pas à votre école.")
            return redirect('depenses:catalogue_livres')

    if request.method == 'POST':
        ancien_total = livre.nombre_exemplaires
        form = LivreForm(request.POST, request.FILES, instance=livre)
        if form.is_valid():
            livre = form.save(commit=False)
            # Ajuster les exemplaires disponibles selon la variation du total
            delta = livre.nombre_exemplaires - ancien_total
            livre.exemplaires_disponibles = max(0, livre.exemplaires_disponibles + delta)
            livre.save()
            messages.success(request, f'Livre « {livre.titre} » mis à jour.')
            return redirect('depenses:catalogue_livres')
        else:
            messages.error(request, "Veuillez corriger les erreurs du formulaire.")
    else:
        form = LivreForm(instance=livre)

    context = {
        'titre_page': f'Modifier — {livre.titre}',
        'form': form,
        'livre': livre,
        'mode': 'modification',
    }
    return render(request, 'depenses/bibliotheque/form_livre.html', context)


@login_required
def supprimer_livre(request, livre_id):
    """Retirer un livre du catalogue (désactivation)"""
    from utilisateurs.utils import user_school

    livre = get_object_or_404(Livre, pk=livre_id)
    ecole = user_school(request.user)
    if ecole:
        livre_profil = getattr(getattr(livre, 'cree_par', None), 'profil', None)
        if livre_profil and livre_profil.ecole != ecole:
            messages.error(request, "Accès refusé : ce livre n'appartient pas à votre école.")
            return redirect('depenses:catalogue_livres')

    if request.method == 'POST':
        titre = livre.titre
        # Empêcher la suppression s'il y a des emprunts en cours
        if Emprunt.objects.filter(livre=livre, statut='EN_COURS').exists():
            messages.error(request, f"Impossible de supprimer « {titre} » : des emprunts sont en cours.")
            return redirect('depenses:catalogue_livres')
        livre.actif = False
        livre.save(update_fields=['actif'])
        messages.success(request, f'Livre « {titre} » retiré du catalogue.')
    return redirect('depenses:catalogue_livres')


@login_required
def gestion_categories_livres(request):
    """Liste et création des catégories de livres"""
    from .forms import CategorieLivreForm

    if request.method == 'POST':
        form = CategorieLivreForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Catégorie de livre créée avec succès.')
            return redirect('depenses:gestion_categories_livres')
        else:
            messages.error(request, "Veuillez corriger les erreurs du formulaire.")
    else:
        form = CategorieLivreForm()

    categories = CategorieLivre.objects.annotate(
        nb_livres=Count('livres')
    ).order_by('nom')

    context = {
        'titre_page': 'Catégories de livres',
        'form': form,
        'categories': categories,
    }
    return render(request, 'depenses/bibliotheque/categories_livres.html', context)


@login_required
def modifier_categorie_livre(request, categorie_id):
    """Modifier une catégorie de livre"""
    from .forms import CategorieLivreForm

    categorie = get_object_or_404(CategorieLivre, pk=categorie_id)
    if request.method == 'POST':
        form = CategorieLivreForm(request.POST, instance=categorie)
        if form.is_valid():
            form.save()
            messages.success(request, 'Catégorie mise à jour.')
            return redirect('depenses:gestion_categories_livres')
        else:
            messages.error(request, "Veuillez corriger les erreurs du formulaire.")
    else:
        form = CategorieLivreForm(instance=categorie)

    categories = CategorieLivre.objects.annotate(
        nb_livres=Count('livres')
    ).order_by('nom')

    context = {
        'titre_page': f'Modifier la catégorie — {categorie.nom}',
        'form': form,
        'categories': categories,
        'categorie_edit': categorie,
    }
    return render(request, 'depenses/bibliotheque/categories_livres.html', context)


@login_required
def supprimer_categorie_livre(request, categorie_id):
    """Supprimer une catégorie de livre (si aucun livre associé)"""
    categorie = get_object_or_404(CategorieLivre, pk=categorie_id)
    if request.method == 'POST':
        if categorie.livres.exists():
            messages.error(
                request,
                f"Impossible de supprimer « {categorie.nom} » : des livres y sont rattachés."
            )
        else:
            nom = categorie.nom
            categorie.delete()
            messages.success(request, f'Catégorie « {nom} » supprimée.')
    return redirect('depenses:gestion_categories_livres')


@login_required
def liste_emprunts(request):
    """Liste des emprunts"""
    from utilisateurs.utils import user_school

    # Filtres
    statut = request.GET.get('statut', '')
    eleve_id = request.GET.get('eleve', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    emprunts = Emprunt.objects.select_related(
        'livre', 'eleve', 'eleve__classe', 'cree_par'
    ).all()
    # Sécurité : filtrer par l'école de l'élève
    ecole = user_school(request.user)
    if ecole:
        emprunts = emprunts.filter(eleve__classe__ecole=ecole)

    if statut:
        emprunts = emprunts.filter(statut=statut)
    
    if eleve_id:
        emprunts = emprunts.filter(eleve_id=eleve_id)
    
    if date_debut:
        emprunts = emprunts.filter(date_emprunt__gte=date_debut)
    
    if date_fin:
        emprunts = emprunts.filter(date_emprunt__lte=date_fin)
    
    context = {
        'titre_page': 'Emprunts',
        'emprunts': emprunts,
        'statut': statut,
        'eleve_id': eleve_id,
        'date_debut': date_debut,
        'date_fin': date_fin,
    }
    
    return render(request, 'depenses/bibliotheque/liste_emprunts.html', context)


@login_required
def creer_emprunt(request):
    """Créer un emprunt"""
    from utilisateurs.utils import user_school
    from django.db import transaction

    ecole = user_school(request.user)

    if request.method == 'POST':
        livre_id = request.POST.get('livre')
        eleve_id = request.POST.get('eleve')
        try:
            duree_jours = int(request.POST.get('duree_jours', 14))
        except (ValueError, TypeError):
            duree_jours = 14

        livre = get_object_or_404(Livre, pk=livre_id)
        eleve = get_object_or_404(Eleve.objects.select_related('classe', 'classe__ecole'), pk=eleve_id)

        # Sécurité : vérifier que le livre et l'élève appartiennent à l'école
        if ecole:
            livre_profil = getattr(getattr(livre, 'cree_par', None), 'profil', None)
            if livre_profil and livre_profil.ecole != ecole:
                messages.error(request, "Accès refusé : ce livre n'appartient pas à votre école.")
                return redirect('depenses:creer_emprunt')
            if eleve.classe and eleve.classe.ecole != ecole:
                messages.error(request, "Accès refusé : cet élève n'appartient pas à votre école.")
                return redirect('depenses:creer_emprunt')

        # Vérifier le nombre d'emprunts de l'élève
        params = ParametreBibliotheque.objects.first()
        if params:
            emprunts_actifs = Emprunt.objects.filter(
                eleve=eleve,
                statut='EN_COURS'
            ).count()

            if emprunts_actifs >= params.nombre_emprunts_max:
                messages.error(
                    request,
                    f'L\'élève a déjà atteint le nombre maximum d\'emprunts ({params.nombre_emprunts_max}).'
                )
                return redirect('depenses:creer_emprunt')

        with transaction.atomic():
            # Verrouiller le livre pour éviter la race condition sur les exemplaires
            livre_locked = Livre.objects.select_for_update().get(pk=livre.pk)

            # Vérifier la disponibilité (après verrouillage)
            if not livre_locked.est_disponible:
                messages.error(request, 'Ce livre n\'est pas disponible.')
                return redirect('depenses:creer_emprunt')

            # Créer l'emprunt
            today = date.today()
            prefix = f"EMP-{today.strftime('%Y%m%d')}"
            last_emp = Emprunt.objects.filter(
                numero_emprunt__startswith=prefix
            ).order_by('-numero_emprunt').first()

            if last_emp:
                last_num = int(last_emp.numero_emprunt.split('-')[-1])
                numero_emprunt = f"{prefix}-{last_num + 1:04d}"
            else:
                numero_emprunt = f"{prefix}-0001"

            emprunt = Emprunt.objects.create(
                numero_emprunt=numero_emprunt,
                livre=livre_locked,
                eleve=eleve,
                date_emprunt=today,
                date_retour_prevue=today + timedelta(days=duree_jours),
                etat_livre_emprunt=livre_locked.etat,
                cree_par=request.user
            )

            # Mettre à jour le livre
            livre_locked.exemplaires_disponibles -= 1
            if livre_locked.exemplaires_disponibles == 0:
                livre_locked.statut = 'EMPRUNTE'
            livre_locked.save()

            # Historique
            HistoriqueLivre.objects.create(
                livre=livre_locked,
                action='EMPRUNT',
                description=f'Emprunté par {eleve} - {numero_emprunt}',
                utilisateur=request.user
            )

        messages.success(request, f'Emprunt créé avec succès. N° {numero_emprunt}')
        return redirect('depenses:liste_emprunts')

    livres = Livre.objects.filter(actif=True, statut='DISPONIBLE')
    eleves = Eleve.objects.filter(statut='ACTIF').select_related('classe')
    # Sécurité : filtrer par école
    if ecole:
        livres = livres.filter(cree_par__profil__ecole=ecole)
        eleves = eleves.filter(classe__ecole=ecole)
    params = ParametreBibliotheque.objects.first()

    context = {
        'titre_page': 'Nouvel Emprunt',
        'livres': livres,
        'eleves': eleves,
        'params': params,
    }

    return render(request, 'depenses/bibliotheque/form_emprunt.html', context)


@login_required
def retourner_livre(request, emprunt_id):
    """Retourner un livre"""
    from utilisateurs.utils import user_school
    from django.db import transaction

    emprunt = get_object_or_404(
        Emprunt.objects.select_related('livre', 'eleve', 'eleve__classe', 'eleve__classe__ecole'),
        pk=emprunt_id
    )

    # Sécurité : vérifier l'appartenance à l'école
    ecole = user_school(request.user)
    if ecole and emprunt.eleve.classe and emprunt.eleve.classe.ecole != ecole:
        messages.error(request, "Accès refusé : cet emprunt n'appartient pas à votre école.")
        return redirect('depenses:liste_emprunts')

    if request.method == 'POST':
        etat_retour = request.POST.get('etat_retour')
        observations = request.POST.get('observations', '')

        with transaction.atomic():
            # Verrouiller l'emprunt pour éviter le double retour
            emprunt_locked = Emprunt.objects.select_for_update().get(pk=emprunt.pk)

            if emprunt_locked.statut == 'RETOURNE':
                messages.warning(request, 'Ce livre a déjà été retourné.')
                return redirect('depenses:liste_emprunts')

            # Mettre à jour l'emprunt
            emprunt_locked.date_retour_effectif = date.today()
            emprunt_locked.etat_livre_retour = etat_retour
            emprunt_locked.observations_retour = observations
            emprunt_locked.statut = 'RETOURNE'
            emprunt_locked.traite_par = request.user

            # Calculer les pénalités
            params = ParametreBibliotheque.objects.first()
            if params:
                emprunt_locked.calculer_penalite(params.penalite_retard_journalier)
            else:
                emprunt_locked.calculer_penalite()

            emprunt_locked.save()

            # Mettre à jour le livre (verrouillé aussi)
            livre = Livre.objects.select_for_update().get(pk=emprunt_locked.livre_id)
            livre.exemplaires_disponibles = min(
                livre.nombre_exemplaires,
                livre.exemplaires_disponibles + 1,
            )
            livre.etat = etat_retour
            livre.save()

            # L'exemplaire retourné est proposé automatiquement à la première
            # réservation en attente, dans l'ordre chronologique.
            _promouvoir_reservations_en_attente(livre, request.user)

            # Historique
            HistoriqueLivre.objects.create(
                livre=livre,
                action='RETOUR',
                description=f'Retourné par {emprunt_locked.eleve} - {emprunt_locked.numero_emprunt}',
                utilisateur=request.user
            )

        if emprunt_locked.montant_penalite > 0:
            messages.warning(
                request,
                f'Livre retourné. Pénalité de retard : {emprunt_locked.montant_penalite:,.0f} GNF'
            )
        else:
            messages.success(request, 'Livre retourné avec succès.')

        return redirect('depenses:liste_emprunts')

    context = {
        'titre_page': 'Retour de Livre',
        'emprunt': emprunt,
    }

    return render(request, 'depenses/bibliotheque/retour_livre.html', context)


@login_required
def liste_reservations(request):
    """Tableau de bord et liste filtrable des réservations."""
    scope = _reservations_bibliotheque(request.user)
    expirees = _expirer_reservations(scope, request.user)
    if expirees:
        messages.info(request, f'{expirees} réservation(s) expirée(s) automatiquement.')

    statut = (request.GET.get('statut') or '').strip()
    q = (request.GET.get('q') or '').strip()
    reservations = _reservations_bibliotheque(request.user)
    if statut:
        reservations = reservations.filter(statut=statut)
    if q:
        reservations = reservations.filter(
            Q(numero_reservation__icontains=q)
            | Q(livre__titre__icontains=q)
            | Q(livre__code_livre__icontains=q)
            | Q(eleve__nom__icontains=q)
            | Q(eleve__prenom__icontains=q)
            | Q(eleve__matricule__icontains=q)
        )

    stats_scope = _reservations_bibliotheque(request.user)
    stats = {
        'total': stats_scope.count(),
        'en_attente': stats_scope.filter(statut='EN_ATTENTE').count(),
        'disponibles': stats_scope.filter(statut='DISPONIBLE').count(),
        'empruntees': stats_scope.filter(statut='EMPRUNTEE').count(),
        'terminees': stats_scope.filter(statut__in=['ANNULEE', 'EXPIREE']).count(),
    }
    page_obj = Paginator(
        reservations.order_by('-date_reservation', '-pk'), 30
    ).get_page(request.GET.get('page'))

    context = {
        'titre_page': 'Réservations',
        'reservations': page_obj,
        'page_obj': page_obj,
        'stats': stats,
        'statut': statut,
        'q': q,
    }

    return render(request, 'depenses/bibliotheque/liste_reservations.html', context)


@login_required
def creer_reservation(request):
    """Crée une réservation et bloque immédiatement un exemplaire libre."""
    params = _parametres_bibliotheque()
    duree_defaut = _duree_reservation()

    if request.method == 'POST':
        livre = get_object_or_404(
            _livres_bibliotheque(request.user).filter(actif=True),
            pk=request.POST.get('livre'),
        )
        eleve = get_object_or_404(
            _eleves_bibliotheque(request.user).filter(statut='ACTIF'),
            pk=request.POST.get('eleve'),
        )
        observations = (request.POST.get('observations') or '').strip()
        try:
            duree = int(request.POST.get('duree_jours') or duree_defaut)
        except (TypeError, ValueError):
            duree = duree_defaut
        duree = max(1, min(duree, 60))

        if livre.statut not in LIVRE_OPERATIONAL_STATUSES:
            messages.error(request, "Ce livre ne peut pas être réservé dans son état actuel.")
            return redirect('depenses:creer_reservation')

        scope = _reservations_bibliotheque(request.user)
        _expirer_reservations(scope.filter(eleve=eleve), request.user)

        with transaction.atomic():
            livre = Livre.objects.select_for_update().get(pk=livre.pk)
            if Reservation.objects.select_for_update().filter(
                livre=livre,
                eleve=eleve,
                statut__in=RESERVATION_ACTIVE_STATUSES,
            ).exists():
                messages.error(request, "Cet élève a déjà une réservation active pour ce livre.")
                return redirect('depenses:creer_reservation')

            maximum = params.nombre_reservations_max if params else 2
            actives = Reservation.objects.select_for_update().filter(
                eleve=eleve,
                statut__in=RESERVATION_ACTIVE_STATUSES,
            ).count()
            if actives >= maximum:
                messages.error(
                    request,
                    f"Cet élève a atteint la limite de {maximum} réservation(s) active(s).",
                )
                return redirect('depenses:creer_reservation')

            maintenant = timezone.now()
            disponible = livre.exemplaires_disponibles > 0
            reservation = Reservation.objects.create(
                numero_reservation=_generer_numero_reservation(),
                livre=livre,
                eleve=eleve,
                date_expiration=maintenant + timedelta(days=duree),
                date_mise_disponible=maintenant if disponible else None,
                statut='DISPONIBLE' if disponible else 'EN_ATTENTE',
                exemplaire_bloque=disponible,
                observations=observations,
                cree_par=request.user,
            )
            if disponible:
                livre.exemplaires_disponibles -= 1
            _synchroniser_statut_livre(livre)
            livre.save()
            HistoriqueLivre.objects.create(
                livre=livre,
                action='RESERVATION',
                description=f'Réservé par {eleve} - {reservation.numero_reservation}',
                utilisateur=request.user,
            )

        if disponible:
            messages.success(request, "Réservation créée : un exemplaire a été mis de côté.")
        else:
            messages.success(request, "Réservation ajoutée à la file d’attente.")
        return redirect('depenses:liste_reservations')

    context = {
        'titre_page': 'Nouvelle réservation',
        'livres': _livres_bibliotheque(request.user).filter(
            actif=True,
            statut__in=LIVRE_OPERATIONAL_STATUSES,
        ).order_by('titre'),
        'eleves': _eleves_bibliotheque(request.user).filter(
            statut='ACTIF'
        ).order_by('nom', 'prenom'),
        'params': params,
        'duree_defaut': duree_defaut,
        'livre_selectionne': request.GET.get('livre', ''),
        'eleve_selectionne': request.GET.get('eleve', ''),
    }
    return render(request, 'depenses/bibliotheque/form_reservation.html', context)


@login_required
@require_POST
def notifier_reservation(request, reservation_id):
    reservation = get_object_or_404(
        _reservations_bibliotheque(request.user), pk=reservation_id
    )
    if reservation.statut != 'DISPONIBLE':
        messages.error(request, "Seule une réservation disponible peut être notifiée.")
    else:
        reservation.date_notification = timezone.now()
        reservation.traitee_par = request.user
        reservation.save()
        messages.success(request, "La notification de l’élève a été enregistrée.")
    return redirect('depenses:liste_reservations')


@login_required
@require_POST
def annuler_reservation(request, reservation_id):
    visible = get_object_or_404(
        _reservations_bibliotheque(request.user), pk=reservation_id
    )
    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().select_related(
            'livre', 'eleve'
        ).get(
            pk=visible.pk,
        )
        if reservation.statut not in RESERVATION_ACTIVE_STATUSES:
            messages.warning(request, "Cette réservation est déjà terminée.")
            return redirect('depenses:liste_reservations')

        livre = Livre.objects.select_for_update().get(pk=reservation.livre_id)
        if reservation.exemplaire_bloque:
            livre.exemplaires_disponibles = min(
                livre.nombre_exemplaires,
                livre.exemplaires_disponibles + 1,
            )
        reservation.statut = 'ANNULEE'
        reservation.exemplaire_bloque = False
        reservation.date_traitement = timezone.now()
        reservation.traitee_par = request.user
        reservation.save()
        _promouvoir_reservations_en_attente(livre, request.user)
        HistoriqueLivre.objects.create(
            livre=livre,
            action='RESERVATION',
            description=f'Réservation annulée - {reservation.numero_reservation}',
            utilisateur=request.user,
        )
    messages.success(request, "La réservation a été annulée et le stock réattribué.")
    return redirect('depenses:liste_reservations')


@login_required
@require_POST
def emprunter_reservation(request, reservation_id):
    """Transforme atomiquement une réservation disponible en emprunt."""
    scope = _reservations_bibliotheque(request.user)
    _expirer_reservations(scope.filter(pk=reservation_id), request.user)

    visible = get_object_or_404(
        _reservations_bibliotheque(request.user), pk=reservation_id
    )
    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().select_related(
            'livre', 'eleve'
        ).get(
            pk=visible.pk,
        )
        if reservation.statut != 'DISPONIBLE':
            messages.error(request, "Cette réservation n’est pas disponible pour l’emprunt.")
            return redirect('depenses:liste_reservations')

        params = _parametres_bibliotheque()
        maximum = params.nombre_emprunts_max if params else 3
        emprunts_actifs = Emprunt.objects.select_for_update().filter(
            eleve=reservation.eleve,
            statut__in=['EN_COURS', 'EN_RETARD'],
        )
        if emprunts_actifs.count() >= maximum:
            messages.error(request, f"L’élève a atteint la limite de {maximum} emprunt(s).")
            return redirect('depenses:liste_reservations')
        if emprunts_actifs.filter(livre=reservation.livre).exists():
            messages.error(request, "L’élève possède déjà un emprunt actif de ce livre.")
            return redirect('depenses:liste_reservations')

        livre = Livre.objects.select_for_update().get(pk=reservation.livre_id)
        # Compatibilité avec d'anciennes réservations DISPONIBLE qui ne
        # mémorisaient pas encore la mise de côté d'un exemplaire.
        if not reservation.exemplaire_bloque:
            if livre.exemplaires_disponibles <= 0:
                messages.error(request, "Aucun exemplaire n’est actuellement disponible.")
                return redirect('depenses:liste_reservations')
            livre.exemplaires_disponibles -= 1

        aujourd_hui = timezone.localdate()
        duree = params.duree_emprunt_defaut if params else 14
        emprunt = Emprunt.objects.create(
            numero_emprunt=_generer_numero_emprunt(),
            livre=livre,
            eleve=reservation.eleve,
            date_emprunt=aujourd_hui,
            date_retour_prevue=aujourd_hui + timedelta(days=max(1, duree)),
            etat_livre_emprunt=livre.etat,
            cree_par=request.user,
        )
        reservation.statut = 'EMPRUNTEE'
        reservation.exemplaire_bloque = False
        reservation.emprunt = emprunt
        reservation.date_traitement = timezone.now()
        reservation.traitee_par = request.user
        reservation.save()
        _synchroniser_statut_livre(livre)
        livre.save()
        HistoriqueLivre.objects.create(
            livre=livre,
            action='EMPRUNT',
            description=(
                f'Réservation convertie en emprunt pour {reservation.eleve} - '
                f'{emprunt.numero_emprunt}'
            ),
            utilisateur=request.user,
        )

    messages.success(request, f"Réservation convertie en emprunt : {emprunt.numero_emprunt}.")
    return redirect('depenses:liste_emprunts')


def calculer_stats_emprunts(emprunts, aujourdhui=None):
    """
    Calcule les statistiques d'un queryset d'emprunts, pénalités comprises.

    Les pénalités stockées en base ne sont recalculées qu'au save() de l'emprunt :
    un emprunt en retard jamais re-sauvegardé garde 0. On évalue donc ici le
    complément dû à la date du jour pour les emprunts non encore retournés.
    """
    if aujourdhui is None:
        aujourdhui = date.today()

    # Pénalités déjà enregistrées en base
    penalites_enregistrees = emprunts.aggregate(
        total=Sum('montant_penalite')
    )['total'] or Decimal('0')

    params = ParametreBibliotheque.objects.first()
    tarif_journalier = Decimal(str(params.penalite_retard_journalier)) if params else Decimal('1000')

    en_retard_qs = emprunts.filter(
        statut__in=['EN_COURS', 'EN_RETARD'],
        date_retour_effectif__isnull=True,
        date_retour_prevue__lt=aujourdhui,
    )

    penalites_en_cours = Decimal('0')
    for date_prevue, montant_stocke in en_retard_qs.values_list(
        'date_retour_prevue', 'montant_penalite'
    ):
        jours_retard = (aujourdhui - date_prevue).days
        montant_reel = Decimal(jours_retard) * tarif_journalier
        # Ne compter que le complément non encore enregistré
        ecart = montant_reel - (montant_stocke or Decimal('0'))
        if ecart > 0:
            penalites_en_cours += ecart

    return {
        'total_emprunts': emprunts.count(),
        'emprunts_retournes': emprunts.filter(statut='RETOURNE').count(),
        'emprunts_en_cours': emprunts.filter(statut='EN_COURS').count(),
        'emprunts_en_retard': en_retard_qs.count(),
        'penalites_enregistrees': penalites_enregistrees,
        'penalites_en_cours': penalites_en_cours,
        'total_penalites': penalites_enregistrees + penalites_en_cours,
    }


@login_required
def statistiques_bibliotheque(request):
    """Statistiques de la bibliothèque"""
    from utilisateurs.utils import user_school

    ecole = user_school(request.user)

    # Période
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    if not date_debut:
        date_debut = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not date_fin:
        date_fin = date.today().strftime('%Y-%m-%d')

    # Emprunts par période
    emprunts = Emprunt.objects.filter(
        date_emprunt__gte=date_debut,
        date_emprunt__lte=date_fin
    )
    # Sécurité : filtrer par l'école de l'élève (appartenance métier réelle,
    # cohérent avec retourner_livre ; cree_par peut être vide sur les imports)
    if ecole:
        emprunts = emprunts.filter(eleve__classe__ecole=ecole)

    stats = calculer_stats_emprunts(emprunts)

    # Livres les plus empruntés
    livres_populaires = Livre.objects.filter(
        emprunts__date_emprunt__gte=date_debut,
        emprunts__date_emprunt__lte=date_fin
    )
    if ecole:
        livres_populaires = livres_populaires.filter(cree_par__profil__ecole=ecole)
    livres_populaires = livres_populaires.annotate(
        nb_emprunts=Count('emprunts')
    ).order_by('-nb_emprunts')[:10]

    # Élèves les plus actifs
    eleves_actifs = Eleve.objects.filter(
        emprunts_livres__date_emprunt__gte=date_debut,
        emprunts_livres__date_emprunt__lte=date_fin
    )
    if ecole:
        eleves_actifs = eleves_actifs.filter(classe__ecole=ecole)
    eleves_actifs = eleves_actifs.annotate(
        nb_emprunts=Count('emprunts_livres')
    ).order_by('-nb_emprunts')[:10]

    context = {
        'titre_page': 'Statistiques Bibliothèque',
        'date_debut': date_debut,
        'date_fin': date_fin,
        'stats': stats,
        'livres_populaires': livres_populaires,
        'eleves_actifs': eleves_actifs,
    }

    return render(request, 'depenses/bibliotheque/statistiques.html', context)
