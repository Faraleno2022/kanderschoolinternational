from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from .models import (
    Depense, CategorieDepense, Fournisseur, 
    PieceJustificative, BudgetAnnuel, HistoriqueDepense
)
from .forms import (
    DepenseForm, CategorieDepenseForm, FournisseurForm,
    PieceJustificativeForm, BudgetAnnuelForm
)
from utilisateurs.utils import user_is_admin, user_is_superadmin, user_school
from utilisateurs.permissions import can_add_expenses, can_modify_expenses, can_delete_expenses, can_validate_expenses
from ecole_moderne.security_decorators import require_school_object

@login_required
def tableau_bord(request):
    """Tableau de bord principal du module dépenses"""
    # Base filtrée par école - seul le superuser voit toutes les écoles
    base_qs = Depense.objects.all()
    if not user_is_superadmin(request.user):
        ecole = user_school(request.user)
        if ecole is None:
            base_qs = Depense.objects.none()
        else:
            base_qs = base_qs.filter(cree_par__profil__ecole=ecole)
    # Statistiques générales
    total_depenses = base_qs.count()
    depenses_validees = base_qs.filter(statut='VALIDEE').count()
    depenses_payees = base_qs.filter(statut='PAYEE').count()
    depenses_en_attente = base_qs.filter(statut='EN_ATTENTE').count()
    # Dépenses invalidées (rejetées ou annulées)
    depenses_rejetees = base_qs.filter(statut='REJETEE').count()
    depenses_annulees = base_qs.filter(statut='ANNULEE').count()
    depenses_brouillon = base_qs.filter(statut='BROUILLON').count()
    # Impayés : engagées (validées ou en attente) mais pas encore payées
    depenses_impayees = base_qs.filter(statut__in=['VALIDEE', 'EN_ATTENTE']).count()
    
    # Montants
    montant_total = base_qs.aggregate(
        total=Sum('montant_ttc')
    )['total'] or Decimal('0')
    
    montant_paye = base_qs.filter(statut='PAYEE').aggregate(
        total=Sum('montant_ttc')
    )['total'] or Decimal('0')
    
    montant_en_attente = base_qs.filter(statut='EN_ATTENTE').aggregate(
        total=Sum('montant_ttc')
    )['total'] or Decimal('0')

    # Montant réellement impayé : validées + en attente (hors rejetées/annulées)
    montant_impaye = base_qs.filter(statut__in=['VALIDEE', 'EN_ATTENTE']).aggregate(
        total=Sum('montant_ttc')
    )['total'] or Decimal('0')

    # Montant invalidé (rejeté ou annulé) - exclu des engagements
    montant_rejete = base_qs.filter(statut__in=['REJETEE', 'ANNULEE']).aggregate(
        total=Sum('montant_ttc')
    )['total'] or Decimal('0')
    
    # Dépenses récentes
    depenses_recentes = base_qs.select_related(
        'categorie', 'fournisseur', 'cree_par'
    ).order_by('-date_creation')[:10]
    
    # Dépenses en retard
    depenses_en_retard = base_qs.filter(
        date_echeance__lt=timezone.now().date(),
        statut__in=['VALIDEE', 'EN_ATTENTE']
    ).count()
    
    # Statistiques par catégorie
    # Statistiques par catégorie (portée approximée si non-superadmin)
    stats_categories = CategorieDepense.objects.filter(actif=True)
    # NOTE: Les annotations globales peuvent inclure des dépenses d'autres écoles.
    # Pour éviter toute fuite de données, on ne joint pas de totaux précis ici pour les non-superadmins.
    if user_is_superadmin(request.user):
        stats_categories = stats_categories.annotate(
            nb_depenses=Count('depenses'),
            montant_total=Sum('depenses__montant_ttc')
        )
    
    context = {
        'total_depenses': total_depenses,
        'depenses_validees': depenses_validees,
        'depenses_payees': depenses_payees,
        'depenses_en_attente': depenses_en_attente,
        'depenses_rejetees': depenses_rejetees,
        'depenses_annulees': depenses_annulees,
        'depenses_brouillon': depenses_brouillon,
        'depenses_impayees': depenses_impayees,
        'montant_total': montant_total,
        'montant_paye': montant_paye,
        'montant_en_attente': montant_en_attente,
        'montant_impaye': montant_impaye,
        'montant_rejete': montant_rejete,
        'depenses_recentes': depenses_recentes,
        'depenses_en_retard': depenses_en_retard,
        'stats_categories': stats_categories,
    }
    
    return render(request, 'depenses/tableau_bord.html', context)

@login_required
def liste_depenses(request):
    """Liste des dépenses avec filtres et pagination"""
    depenses = Depense.objects.select_related(
        'categorie', 'fournisseur', 'cree_par', 'valide_par'
    ).order_by('-date_creation')
    # IMPORTANT: Seul le superuser peut voir toutes les écoles
    if not user_is_superadmin(request.user):
        ecole = user_school(request.user)
        if ecole is None:
            depenses = Depense.objects.none()
        else:
            depenses = depenses.filter(cree_par__profil__ecole=ecole)
    
    # Filtres
    statut_filtre = request.GET.get('statut')
    if statut_filtre:
        depenses = depenses.filter(statut=statut_filtre)
    
    categorie_filtre = request.GET.get('categorie')
    if categorie_filtre:
        depenses = depenses.filter(categorie_id=categorie_filtre)
    
    fournisseur_filtre = request.GET.get('fournisseur')
    if fournisseur_filtre:
        depenses = depenses.filter(fournisseur_id=fournisseur_filtre)
    
    recherche = request.GET.get('recherche')
    if recherche:
        depenses = depenses.filter(
            Q(libelle__icontains=recherche) |
            Q(numero_facture__icontains=recherche) |
            Q(description__icontains=recherche)
        )
    
    # Pagination
    paginator = Paginator(depenses, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Totaux pour les filtres appliqués
    totaux = {
        'nombre_total': depenses.count(),
        'montant_total': depenses.aggregate(Sum('montant_ttc'))['montant_ttc__sum'] or Decimal('0'),
        'nombre_en_attente': depenses.filter(statut='EN_ATTENTE').count(),
        'montant_en_attente': depenses.filter(statut='EN_ATTENTE').aggregate(Sum('montant_ttc'))['montant_ttc__sum'] or Decimal('0'),
    }
    
    # Données pour les filtres
    categories = CategorieDepense.objects.filter(actif=True)
    fournisseurs = Fournisseur.objects.filter(actif=True)
    
    context = {
        'page_obj': page_obj,
        'totaux': totaux,
        'categories': categories,
        'fournisseurs': fournisseurs,
        'statut_filtre': statut_filtre,
        'categorie_filtre': categorie_filtre,
        'fournisseur_filtre': fournisseur_filtre,
        'recherche': recherche,
    }
    
    return render(request, 'depenses/liste_depenses.html', context)

@login_required
@require_school_object(model=Depense, pk_kwarg='depense_id', field_path='cree_par__profil__ecole')
def detail_depense(request, depense_id):
    """Détail d'une dépense"""
    qs = Depense.objects.select_related(
        'categorie', 'fournisseur', 'cree_par', 'valide_par'
    ).prefetch_related('pieces_justificatives', 'historique')
    if not user_is_admin(request.user):
        qs = qs.filter(cree_par__profil__ecole=user_school(request.user))
    depense = get_object_or_404(qs, id=depense_id)
    
    context = {
        'depense': depense,
    }
    
    return render(request, 'depenses/detail_depense.html', context)

@login_required
@can_add_expenses
def ajouter_depense(request):
    """Ajouter une nouvelle dépense"""
    from django.db import transaction

    if request.method == 'POST':
        form = DepenseForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                depense = form.save(commit=False)
                depense.cree_par = request.user
                depense.save()

                # Créer l'historique
                HistoriqueDepense.objects.create(
                    depense=depense,
                    action='CREATION',
                    description=f'Dépense créée: {depense.libelle}',
                    nouveau_statut=depense.statut,
                    utilisateur=request.user
                )

            messages.success(request, 'Dépense ajoutée avec succès.')
            return redirect('depenses:detail_depense', depense_id=depense.id)
    else:
        form = DepenseForm()
    
    context = {
        'form': form,
        'title': 'Ajouter une dépense',
    }
    
    return render(request, 'depenses/form_depense.html', context)

@login_required
@can_modify_expenses
@require_school_object(model=Depense, pk_kwarg='depense_id', field_path='cree_par__profil__ecole')
def modifier_depense(request, depense_id):
    """Modifier une dépense existante"""
    qs = Depense.objects.all()
    if not user_is_admin(request.user):
        qs = qs.filter(cree_par__profil__ecole=user_school(request.user))
    depense = get_object_or_404(qs, id=depense_id)
    
    # Vérifier que la dépense peut être modifiée
    if depense.statut in ['PAYEE', 'ANNULEE']:
        messages.error(request, 'Cette dépense ne peut plus être modifiée.')
        return redirect('depenses:detail_depense', depense_id=depense.id)
    
    if request.method == 'POST':
        from django.db import transaction
        form = DepenseForm(request.POST, instance=depense)
        if form.is_valid():
            with transaction.atomic():
                ancien_statut = depense.statut
                depense = form.save()

                # Créer l'historique
                HistoriqueDepense.objects.create(
                    depense=depense,
                    action='MODIFICATION',
                    description=f'Dépense modifiée: {depense.libelle}',
                    ancien_statut=ancien_statut,
                    nouveau_statut=depense.statut,
                    utilisateur=request.user
                )

            messages.success(request, 'Dépense modifiée avec succès.')
            return redirect('depenses:detail_depense', depense_id=depense.id)
    else:
        form = DepenseForm(instance=depense)
    
    context = {
        'form': form,
        'depense': depense,
        'title': 'Modifier la dépense',
    }
    
    return render(request, 'depenses/form_depense.html', context)

@login_required
@can_validate_expenses
@require_school_object(model=Depense, pk_kwarg='depense_id', field_path='cree_par__profil__ecole')
def valider_depense(request, depense_id):
    """Valider une dépense"""
    from django.db import transaction

    if request.method == 'POST':
        qs = Depense.objects.all()
        if not user_is_admin(request.user):
            qs = qs.filter(cree_par__profil__ecole=user_school(request.user))
        depense = get_object_or_404(qs, id=depense_id)

        if depense.statut != 'EN_ATTENTE':
            messages.error(request, 'Seules les dépenses en attente peuvent être validées.')
        else:
            with transaction.atomic():
                # Verrouiller la ligne pour éviter les validations concurrentes
                depense_locked = Depense.objects.select_for_update().get(pk=depense.pk)
                if depense_locked.statut != 'EN_ATTENTE':
                    messages.warning(request, 'Cette dépense a déjà été traitée.')
                else:
                    ancien_statut = depense_locked.statut
                    depense_locked.statut = 'VALIDEE'
                    depense_locked.valide_par = request.user
                    depense_locked.date_validation = timezone.now()
                    depense_locked.save()

                    HistoriqueDepense.objects.create(
                        depense=depense_locked,
                        action='VALIDATION',
                        description=f'Dépense validée: {depense_locked.libelle}',
                        ancien_statut=ancien_statut,
                        nouveau_statut=depense_locked.statut,
                        utilisateur=request.user
                    )
                    messages.success(request, 'Dépense validée avec succès.')

    return redirect('depenses:detail_depense', depense_id=depense_id)

@login_required
@require_school_object(model=Depense, pk_kwarg='depense_id', field_path='cree_par__profil__ecole')
def marquer_payee(request, depense_id):
    """Marquer une dépense comme payée"""
    from django.db import transaction

    if request.method == 'POST':
        qs = Depense.objects.all()
        if not user_is_admin(request.user):
            qs = qs.filter(cree_par__profil__ecole=user_school(request.user))
        depense = get_object_or_404(qs, id=depense_id)

        if depense.statut != 'VALIDEE':
            messages.error(request, 'Seules les dépenses validées peuvent être marquées comme payées.')
        else:
            with transaction.atomic():
                # Verrouiller la ligne pour éviter les doubles paiements
                depense_locked = Depense.objects.select_for_update().get(pk=depense.pk)
                if depense_locked.statut != 'VALIDEE':
                    messages.warning(request, 'Cette dépense a déjà été traitée.')
                else:
                    ancien_statut = depense_locked.statut
                    depense_locked.statut = 'PAYEE'
                    depense_locked.date_paiement = timezone.now().date()
                    depense_locked.save()

                    HistoriqueDepense.objects.create(
                        depense=depense_locked,
                        action='PAIEMENT',
                        description=f'Dépense payée: {depense_locked.libelle}',
                        ancien_statut=ancien_statut,
                        nouveau_statut=depense_locked.statut,
                        utilisateur=request.user
                    )
                    messages.success(request, 'Dépense marquée comme payée.')

    return redirect('depenses:detail_depense', depense_id=depense_id)

@login_required
@can_modify_expenses
def gestion_categories(request):
    """Gestion des catégories de dépenses"""
    # Filtrer par école pour non-admin
    categories = CategorieDepense.objects.all()
    if not user_is_admin(request.user):
        # Pour les non-admin, on peut afficher toutes les catégories car elles sont globales
        # mais on peut limiter les actions selon les permissions
        pass
    
    if request.method == 'POST':
        form = CategorieDepenseForm(request.POST)
        if form.is_valid():
            categorie = form.save()
            messages.success(request, f'Catégorie "{categorie.nom}" créée avec succès.')
            return redirect('depenses:gestion_categories')
    else:
        form = CategorieDepenseForm()
    
    # Pagination
    paginator = Paginator(categories.order_by('nom'), 10)
    page_number = request.GET.get('page')
    categories_page = paginator.get_page(page_number)
    
    context = {
        'categories': categories_page,
        'form': form,
        'title': 'Gestion des catégories de dépenses',
    }
    
    return render(request, 'depenses/gestion_categories.html', context)

@login_required
@can_modify_expenses
def modifier_categorie(request, categorie_id):
    """Modifier une catégorie de dépense"""
    categorie = get_object_or_404(CategorieDepense, id=categorie_id)
    
    if request.method == 'POST':
        form = CategorieDepenseForm(request.POST, instance=categorie)
        if form.is_valid():
            categorie = form.save()
            messages.success(request, f'Catégorie "{categorie.nom}" modifiée avec succès.')
            return redirect('depenses:gestion_categories')
    else:
        form = CategorieDepenseForm(instance=categorie)
    
    context = {
        'form': form,
        'categorie': categorie,
        'title': 'Modifier la catégorie',
    }
    
    return render(request, 'depenses/form_categorie.html', context)

@login_required
@can_delete_expenses
def supprimer_categorie(request, categorie_id):
    """Supprimer une catégorie de dépense"""
    categorie = get_object_or_404(CategorieDepense, id=categorie_id)
    
    if request.method == 'POST':
        # Vérifier s'il y a des dépenses liées à cette catégorie
        if categorie.depense_set.exists():
            messages.error(request, 'Impossible de supprimer cette catégorie car elle est utilisée par des dépenses.')
        else:
            nom_categorie = categorie.nom
            categorie.delete()
            messages.success(request, f'Catégorie "{nom_categorie}" supprimée avec succès.')
        return redirect('depenses:gestion_categories')
    
    context = {
        'categorie': categorie,
        'title': 'Supprimer la catégorie',
    }
    
    return render(request, 'depenses/confirm_delete_categorie.html', context)

@login_required
@can_delete_expenses
@require_school_object(model=Depense, pk_kwarg='depense_id', field_path='cree_par__profil__ecole')
def supprimer_depense(request, depense_id):
    """Supprimer définitivement une dépense"""
    qs = Depense.objects.all()
    if not user_is_admin(request.user):
        qs = qs.filter(cree_par__profil__ecole=user_school(request.user))
    depense = get_object_or_404(qs, id=depense_id)
    
    if request.method == 'POST':
        # Interdire la suppression des dépenses validées ou payées
        if depense.statut in ['PAYEE', 'VALIDEE']:
            messages.error(request, 'Impossible de supprimer une dépense validée ou payée.')
            return redirect('depenses:detail_depense', depense_id=depense.id)

        numero_facture = depense.numero_facture
        libelle = depense.libelle
        depense.delete()
        messages.success(request, f'Dépense "{numero_facture} - {libelle}" supprimée définitivement.')
        return redirect('depenses:liste_depenses')
    
    context = {
        'depense': depense,
        'title': 'Supprimer la dépense',
    }
    
    return render(request, 'depenses/confirm_delete_depense.html', context)
