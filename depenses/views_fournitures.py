from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import DecimalField, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from utilisateurs.permissions import can_add_expenses, can_delete_expenses, can_modify_expenses
from utilisateurs.utils import filter_by_user_school, user_is_superadmin, user_school

from .forms_fournitures import ProduitFournitureForm, VenteFournitureForm
from .models_fournitures import ProduitFourniture, VenteFourniture


MONEY_FIELD = DecimalField(max_digits=20, decimal_places=0)


def _produits_queryset(request):
    return filter_by_user_school(
        ProduitFourniture.objects.select_related('ecole', 'cree_par'),
        request.user,
        'ecole',
    )


def _ventes_queryset(request):
    return filter_by_user_school(
        VenteFourniture.objects.select_related(
            'produit', 'produit__ecole', 'cree_par', 'annulee_par'
        ),
        request.user,
        'produit__ecole',
    )


def _annoter_ventes(produits):
    ventes_confirmees = Q(ventes__statut=VenteFourniture.STATUT_CONFIRMEE)
    return produits.annotate(
        quantite_vendue_calc=Coalesce(
            Sum('ventes__quantite', filter=ventes_confirmees),
            Value(0),
            output_field=IntegerField(),
        ),
        chiffre_affaires_calc=Coalesce(
            Sum('ventes__montant_vente', filter=ventes_confirmees),
            Value(Decimal('0'), output_field=MONEY_FIELD),
            output_field=MONEY_FIELD,
        ),
        solde_calc=Coalesce(
            Sum('ventes__solde', filter=ventes_confirmees),
            Value(Decimal('0'), output_field=MONEY_FIELD),
            output_field=MONEY_FIELD,
        ),
    )


@login_required
def dashboard_fournitures(request):
    q = (request.GET.get('q') or '').strip()
    statut = (request.GET.get('statut') or 'actifs').strip().lower()

    scope = _annoter_ventes(_produits_queryset(request))
    produits_actifs = list(scope.filter(actif=True))
    ventes_confirmees = _ventes_queryset(request).filter(
        statut=VenteFourniture.STATUT_CONFIRMEE
    )
    ventes_stats = ventes_confirmees.aggregate(
        quantite=Coalesce(Sum('quantite'), Value(0), output_field=IntegerField()),
        chiffre_affaires=Coalesce(
            Sum('montant_vente'), Value(Decimal('0'), output_field=MONEY_FIELD),
            output_field=MONEY_FIELD,
        ),
        cout_vente=Coalesce(
            Sum('montant_achat'), Value(Decimal('0'), output_field=MONEY_FIELD),
            output_field=MONEY_FIELD,
        ),
        solde=Coalesce(
            Sum('solde'), Value(Decimal('0'), output_field=MONEY_FIELD),
            output_field=MONEY_FIELD,
        ),
    )

    quantite_stock = sum(int(p.quantite_stock or 0) for p in produits_actifs)
    quantite_vendue = int(ventes_stats['quantite'] or 0)
    quantite_restante = sum(p.quantite_restante for p in produits_actifs)
    valeur_stock_restante = sum(
        (p.valeur_stock_restante for p in produits_actifs),
        Decimal('0'),
    )
    alertes = sum(1 for p in produits_actifs if p.en_alerte)

    produits = scope
    if statut == 'actifs':
        produits = produits.filter(actif=True)
    elif statut == 'inactifs':
        produits = produits.filter(actif=False)
    if q:
        produits = produits.filter(
            Q(nom__icontains=q) | Q(description__icontains=q) | Q(ecole__nom__icontains=q)
        )

    page_obj = Paginator(produits.order_by('nom'), 25).get_page(request.GET.get('page'))
    ventes_recentes = _ventes_queryset(request).order_by('-date_vente', '-date_creation')[:12]

    context = {
        'titre_page': 'Gestion et vente des fournitures scolaires',
        'page_obj': page_obj,
        'ventes_recentes': ventes_recentes,
        'q': q,
        'statut': statut,
        'show_ecole': user_is_superadmin(request.user),
        'stats': {
            'produits': len(produits_actifs),
            'quantite_stock': quantite_stock,
            'quantite_vendue': quantite_vendue,
            'quantite_restante': quantite_restante,
            'chiffre_affaires': ventes_stats['chiffre_affaires'] or Decimal('0'),
            'cout_vente': ventes_stats['cout_vente'] or Decimal('0'),
            'solde': ventes_stats['solde'] or Decimal('0'),
            'valeur_stock_restante': valeur_stock_restante,
            'alertes': alertes,
        },
    }
    return render(request, 'depenses/fournitures/dashboard.html', context)


@can_add_expenses
def ajouter_produit_fourniture(request):
    ecole = None if user_is_superadmin(request.user) else user_school(request.user)
    if not user_is_superadmin(request.user) and ecole is None:
        messages.error(request, 'Aucun établissement associé à votre compte.')
        return redirect('depenses:dashboard_fournitures')

    data = request.POST.copy() if request.method == 'POST' else None
    if data is not None and ecole is not None:
        data['ecole'] = str(ecole.pk)
    form = ProduitFournitureForm(data, ecole=ecole)
    if request.method == 'POST' and form.is_valid():
        produit = form.save(commit=False)
        if ecole is not None:
            produit.ecole = ecole
        produit.cree_par = request.user
        produit.full_clean()
        produit.save()
        messages.success(request, f'Le produit « {produit.nom} » a été ajouté au stock.')
        return redirect('depenses:dashboard_fournitures')

    return render(request, 'depenses/fournitures/form_produit.html', {
        'titre_page': 'Ajouter une fourniture scolaire',
        'form': form,
        'produit': None,
    })


@can_modify_expenses
def modifier_produit_fourniture(request, produit_id):
    produit = get_object_or_404(_produits_queryset(request), pk=produit_id)
    ecole = None if user_is_superadmin(request.user) else produit.ecole
    data = request.POST.copy() if request.method == 'POST' else None
    if data is not None and ecole is not None:
        data['ecole'] = str(ecole.pk)
    form = ProduitFournitureForm(data, instance=produit, ecole=ecole)
    if request.method == 'POST' and form.is_valid():
        produit = form.save(commit=False)
        if ecole is not None:
            produit.ecole = ecole
        produit.full_clean()
        produit.save()
        messages.success(request, f'Le produit « {produit.nom} » a été mis à jour.')
        return redirect('depenses:dashboard_fournitures')

    return render(request, 'depenses/fournitures/form_produit.html', {
        'titre_page': 'Modifier une fourniture scolaire',
        'form': form,
        'produit': produit,
    })


@can_add_expenses
@transaction.atomic
def vendre_fourniture(request, produit_id):
    produit = get_object_or_404(
        filter_by_user_school(
            ProduitFourniture.objects.select_for_update().select_related('ecole'),
            request.user,
            'ecole',
        ),
        pk=produit_id,
    )
    if not produit.actif:
        messages.error(request, 'Ce produit est inactif et ne peut pas être vendu.')
        return redirect('depenses:dashboard_fournitures')

    form = VenteFournitureForm(request.POST or None, initial={'date_vente': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        quantite_vendue = produit.ventes.filter(
            statut=VenteFourniture.STATUT_CONFIRMEE
        ).aggregate(total=Sum('quantite'))['total'] or 0
        disponible = max(0, int(produit.quantite_stock or 0) - int(quantite_vendue))
        quantite = int(form.cleaned_data['quantite'])
        if quantite > disponible:
            form.add_error(
                'quantite',
                f'Stock insuffisant : {disponible} unité(s) disponible(s).',
            )
        else:
            vente = form.save(commit=False)
            vente.produit = produit
            vente.prix_achat_unitaire = produit.prix_achat_unitaire
            vente.prix_vente_unitaire = produit.prix_vente_unitaire
            vente.cree_par = request.user
            vente.full_clean()
            vente.save()
            messages.success(
                request,
                f'Vente enregistrée : {quantite} × {produit.nom} pour '
                f'{vente.montant_vente:,.0f} GNF.',
            )
            return redirect('depenses:dashboard_fournitures')

    return render(request, 'depenses/fournitures/form_vente.html', {
        'titre_page': f'Vendre : {produit.nom}',
        'form': form,
        'produit': produit,
    })


@can_delete_expenses
@require_POST
def annuler_vente_fourniture(request, vente_id):
    with transaction.atomic():
        vente = get_object_or_404(
            filter_by_user_school(
                VenteFourniture.objects.select_for_update().select_related('produit'),
                request.user,
                'produit__ecole',
            ),
            pk=vente_id,
        )
        if vente.statut == VenteFourniture.STATUT_ANNULEE:
            messages.info(request, 'Cette vente est déjà annulée.')
        else:
            vente.statut = VenteFourniture.STATUT_ANNULEE
            vente.annulee_par = request.user
            vente.date_annulation = timezone.now()
            vente.save()
            messages.success(request, 'La vente a été annulée et le stock disponible recalculé.')
    return redirect('depenses:dashboard_fournitures')
