from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Sum
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from datetime import datetime, date, timedelta
from decimal import Decimal

from .models_bibliotheque import (
    CategorieLivre, Livre, Emprunt, Reservation,
    HistoriqueLivre, ParametreBibliotheque
)
from eleves.models import Eleve


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
            livre.exemplaires_disponibles += 1
            livre.statut = 'DISPONIBLE'
            livre.etat = etat_retour
            livre.save()

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
    """Liste des réservations"""
    from utilisateurs.utils import user_school

    ecole = user_school(request.user)

    reservations = Reservation.objects.select_related(
        'livre', 'eleve', 'eleve__classe', 'cree_par'
    ).order_by('-date_reservation')
    # Sécurité : filtrer par l'école de l'élève
    if ecole:
        reservations = reservations.filter(eleve__classe__ecole=ecole)

    context = {
        'titre_page': 'Réservations',
        'reservations': reservations,
    }

    return render(request, 'depenses/bibliotheque/liste_reservations.html', context)


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
