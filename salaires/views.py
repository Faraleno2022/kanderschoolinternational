from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, Http404
from django.urls import reverse
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import csv
import os
from django.conf import settings

# ReportLab for PDF exports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

from .models import (
    Enseignant, AffectationClasse, AvanceSalaire, PeriodeSalaire,
    EtatSalaire, DetailHeuresClasse, TypeEnseignant, PresenceEnseignant,
    SourceHeuresSalaire,
)
from .forms import (
    AffectationClasseForm,
    AvanceSalaireForm,
    EnseignantForm,
    EtatSalaireAjustementForm,
    PresenceForm,
)
from .services import (
    arrondir_montant,
    calculer_etat_salaire,
    enseignants_eligibles,
    heures_reellement_travaillees,
    plafond_avance_disponible,
    synchroniser_avances_etat,
    total_avances_a_deduire,
)
from eleves.models import Ecole, Classe
from utilisateurs.utils import filter_by_user_school, user_is_admin, user_school
from utilisateurs.permissions import can_add_teachers
from ecole_moderne.security_decorators import delete_permission_required, require_school_object

# Importer les vues de présence
from .views_presences import (
    liste_presences, pointer_presence, modifier_presence,
    supprimer_presence, rapport_presences, export_presences_csv,
    export_presences_excel
)

def _ecole_utilisateur(request):
    """Compat: utiliser l'utilitaire centralisé"""
    return user_school(request.user)

@login_required
def tableau_bord(request):
    """Tableau de bord du module Salaires"""
    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None

    # Statistiques générales
    base_qs = Enseignant.objects.all()
    if restreindre:
        base_qs = base_qs.filter(ecole=ecole_user)
    stats = {
        'total_enseignants': base_qs.count(),
        'enseignants_actifs': base_qs.filter(statut='ACTIF').count(),
        'enseignants_taux_horaire': base_qs.filter(type_enseignant='SECONDAIRE').count(),
        'enseignants_salaire_fixe': base_qs.exclude(type_enseignant='SECONDAIRE').count(),
    }
    avances_qs = filter_by_user_school(
        AvanceSalaire.objects.all(), request.user, 'enseignant__ecole'
    )
    stats.update({
        'avances_en_attente': avances_qs.filter(
            statut=AvanceSalaire.Statut.EN_ATTENTE
        ).count(),
        'avances_a_deduire': avances_qs.filter(
            statut=AvanceSalaire.Statut.APPROUVEE
        ).aggregate(total=Sum('montant'))['total'] or 0,
    })
    
    # Période courante
    periode_courante = None
    try:
        now = timezone.now()
        qs_periodes = PeriodeSalaire.objects.filter(mois=now.month, annee=now.year)
        if restreindre:
            qs_periodes = qs_periodes.filter(ecole=ecole_user)
        periode_courante = qs_periodes.first()
    except:
        pass
    
    # États de salaire récents
    etats_recents = EtatSalaire.objects.select_related('enseignant', 'periode')
    if restreindre:
        etats_recents = etats_recents.filter(periode__ecole=ecole_user)
    etats_recents = etats_recents.order_by('-date_calcul')[:10]
    
    # Statistiques par école
    stats_ecoles = []
    ecoles_iter = Ecole.objects.all()
    if restreindre:
        ecoles_iter = ecoles_iter.filter(id=ecole_user.id)
    for ecole in ecoles_iter:
        enseignants_ecole = Enseignant.objects.filter(ecole=ecole, statut='ACTIF')
        stats_ecoles.append({
            'ecole': ecole,
            'total_enseignants': enseignants_ecole.count(),
            'taux_horaire': enseignants_ecole.filter(type_enseignant='SECONDAIRE').count(),
            'salaire_fixe': enseignants_ecole.exclude(type_enseignant='SECONDAIRE').count(),
        })
    
    # Alertes
    alertes = []
    
    # Vérifier les enseignants sans affectation active (période en cours)
    aujourd_hui = timezone.now().date()
    enseignants_base = Enseignant.objects.filter(statut='ACTIF')
    if restreindre:
        enseignants_base = enseignants_base.filter(ecole=ecole_user)
    enseignants_sans_affectation = (
        enseignants_base
        .annotate(
            nb_actives=Count(
                'affectations',
                filter=(
                    Q(affectations__actif=True,
                      affectations__date_debut__lte=aujourd_hui) &
                    (Q(affectations__date_fin__isnull=True) | Q(affectations__date_fin__gte=aujourd_hui))
                )
            )
        )
        .filter(nb_actives=0)
        .count()
    )
    
    if enseignants_sans_affectation > 0:
        alertes.append({
            'type': 'warning',
            'message': f'{enseignants_sans_affectation} enseignant(s) sans affectation de classe',
            'action': 'Gérer les affectations'
        })
    
    # Vérifier les périodes non clôturées
    periodes_ouvertes_qs = PeriodeSalaire.objects.filter(cloturee=False)
    if restreindre:
        periodes_ouvertes_qs = periodes_ouvertes_qs.filter(ecole=ecole_user)
    periodes_ouvertes = periodes_ouvertes_qs.count()
    if periodes_ouvertes > 2:
        alertes.append({
            'type': 'info',
            'message': f'{periodes_ouvertes} périodes de salaire ouvertes',
            'action': 'Clôturer les anciennes périodes'
        })
    
    context = {
        'stats': stats,
        'periode_courante': periode_courante,
        'etats_recents': etats_recents,
        'stats_ecoles': stats_ecoles,
        'alertes': alertes,
    }
    
    return render(request, 'salaires/tableau_bord.html', context)


def _avances_autorisees(user):
    return filter_by_user_school(
        AvanceSalaire.objects.select_related(
            'enseignant', 'enseignant__ecole', 'periode', 'cree_par', 'approuvee_par'
        ),
        user,
        'enseignant__ecole',
    )


@login_required
def liste_avances_salaire(request):
    avances = _avances_autorisees(request.user)
    search = (request.GET.get('search') or '').strip()
    statut = (request.GET.get('statut') or '').strip()
    periode_id = (request.GET.get('periode') or '').strip()
    if search:
        avances = avances.filter(
            Q(enseignant__nom__icontains=search)
            | Q(enseignant__prenoms__icontains=search)
            | Q(reference_paiement__icontains=search)
            | Q(motif__icontains=search)
        )
    if statut:
        avances = avances.filter(statut=statut)
    if periode_id:
        avances = avances.filter(periode_id=periode_id)

    totaux_qs = avances
    totaux = {
        'nombre': totaux_qs.count(),
        'en_attente': totaux_qs.filter(statut=AvanceSalaire.Statut.EN_ATTENTE).count(),
        'a_deduire': totaux_qs.filter(
            statut=AvanceSalaire.Statut.APPROUVEE
        ).aggregate(total=Sum('montant'))['total'] or 0,
        'deduit': totaux_qs.filter(
            statut=AvanceSalaire.Statut.DEDUITE
        ).aggregate(total=Sum('montant'))['total'] or 0,
    }
    paginator = Paginator(avances.order_by('-date_avance', '-id'), 25)
    periodes = filter_by_user_school(
        PeriodeSalaire.objects.select_related('ecole').order_by('-annee', '-mois'),
        request.user,
        'ecole',
    )
    return render(request, 'salaires/avances_liste.html', {
        'page_obj': paginator.get_page(request.GET.get('page')),
        'totaux': totaux,
        'periodes': periodes,
        'statuts': AvanceSalaire.Statut.choices,
        'search': search,
        'statut_selectionne': statut,
        'periode_selectionnee': periode_id,
    })


@login_required
def ajouter_avance_salaire(request):
    initial = {}
    if request.GET.get('enseignant'):
        initial['enseignant'] = request.GET['enseignant']
    if request.GET.get('periode'):
        initial['periode'] = request.GET['periode']
    form = AvanceSalaireForm(
        request.POST or None,
        initial=initial,
        user=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            avance = form.save(commit=False)
            avance.cree_par = request.user
            if form.cleaned_data['approuver_immediatement']:
                avance.statut = AvanceSalaire.Statut.APPROUVEE
                avance.approuvee_par = request.user
                avance.date_approbation = timezone.now()
            avance.full_clean()
            avance.save()
            synchroniser_avances_etat(avance.enseignant, avance.periode)
        messages.success(
            request,
            f"Avance de {avance.montant:,.0f} GNF enregistrée pour "
            f"{avance.enseignant.nom_complet}.",
        )
        return redirect('salaires:liste_avances_salaire')
    return render(request, 'salaires/avance_form.html', {
        'form': form,
        'titre': 'Nouvelle avance sur salaire',
    })


@login_required
@require_school_object(
    model=AvanceSalaire, pk_kwarg='avance_id', field_path='enseignant__ecole'
)
def modifier_avance_salaire(request, avance_id):
    avance = get_object_or_404(_avances_autorisees(request.user), pk=avance_id)
    etat = EtatSalaire.objects.filter(
        enseignant=avance.enseignant, periode=avance.periode
    ).first()
    if (
        avance.statut in {AvanceSalaire.Statut.DEDUITE, AvanceSalaire.Statut.ANNULEE}
        or avance.periode.cloturee
        or (etat and etat.valide)
    ):
        messages.error(request, "Cette avance est verrouillée et ne peut plus être modifiée.")
        return redirect('salaires:liste_avances_salaire')

    ancienne_cible = (avance.enseignant, avance.periode)
    form = AvanceSalaireForm(
        request.POST or None,
        instance=avance,
        user=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            avance = form.save(commit=False)
            if (
                avance.statut == AvanceSalaire.Statut.EN_ATTENTE
                and form.cleaned_data['approuver_immediatement']
            ):
                avance.statut = AvanceSalaire.Statut.APPROUVEE
                avance.approuvee_par = request.user
                avance.date_approbation = timezone.now()
            avance.full_clean()
            avance.save()
            synchroniser_avances_etat(*ancienne_cible)
            synchroniser_avances_etat(avance.enseignant, avance.periode)
        messages.success(request, "Avance sur salaire mise à jour.")
        return redirect('salaires:liste_avances_salaire')
    return render(request, 'salaires/avance_form.html', {
        'form': form,
        'avance': avance,
        'titre': "Modifier l'avance sur salaire",
    })


@login_required
@require_POST
@require_school_object(
    model=AvanceSalaire, pk_kwarg='avance_id', field_path='enseignant__ecole'
)
def approuver_avance_salaire(request, avance_id):
    with transaction.atomic():
        avance = get_object_or_404(
            AvanceSalaire.objects.select_for_update().select_related('enseignant', 'periode'),
            pk=avance_id,
        )
        etat = EtatSalaire.objects.filter(
            enseignant=avance.enseignant, periode=avance.periode
        ).first()
        if (
            avance.statut != AvanceSalaire.Statut.EN_ATTENTE
            or avance.periode.cloturee
            or (etat and etat.valide)
        ):
            messages.error(request, "Cette avance ne peut plus être approuvée.")
            return redirect('salaires:liste_avances_salaire')
        plafond = plafond_avance_disponible(
            avance.enseignant, avance.periode, exclure_avance=avance
        )
        if avance.montant > plafond:
            messages.error(
                request,
                f"L'avance dépasse le salaire disponible ({plafond:,.0f} GNF).",
            )
            return redirect('salaires:liste_avances_salaire')
        avance.statut = AvanceSalaire.Statut.APPROUVEE
        avance.approuvee_par = request.user
        avance.date_approbation = timezone.now()
        avance.save(update_fields={
            'statut', 'approuvee_par', 'date_approbation', 'date_modification'
        })
        synchroniser_avances_etat(avance.enseignant, avance.periode)
    messages.success(request, "Avance approuvée et intégrée au calcul du salaire.")
    return redirect('salaires:liste_avances_salaire')


@login_required
@require_POST
@require_school_object(
    model=AvanceSalaire, pk_kwarg='avance_id', field_path='enseignant__ecole'
)
def annuler_avance_salaire(request, avance_id):
    motif = (request.POST.get('motif_annulation') or '').strip()
    if not motif:
        messages.error(request, "Le motif d'annulation est obligatoire.")
        return redirect('salaires:liste_avances_salaire')
    with transaction.atomic():
        avance = get_object_or_404(
            AvanceSalaire.objects.select_for_update().select_related('enseignant', 'periode'),
            pk=avance_id,
        )
        etat = EtatSalaire.objects.filter(
            enseignant=avance.enseignant, periode=avance.periode
        ).first()
        if (
            avance.statut in {AvanceSalaire.Statut.DEDUITE, AvanceSalaire.Statut.ANNULEE}
            or avance.periode.cloturee
            or (etat and etat.valide)
        ):
            messages.error(request, "Cette avance ne peut plus être annulée.")
            return redirect('salaires:liste_avances_salaire')
        avance.statut = AvanceSalaire.Statut.ANNULEE
        avance.motif_annulation = motif
        avance.annulee_par = request.user
        avance.date_annulation = timezone.now()
        avance.save(update_fields={
            'statut', 'motif_annulation', 'annulee_par',
            'date_annulation', 'date_modification',
        })
        synchroniser_avances_etat(avance.enseignant, avance.periode)
    messages.success(request, "Avance annulée et salaire recalculé.")
    return redirect('salaires:liste_avances_salaire')


@login_required
def liste_enseignants(request):
    """Liste des enseignants avec filtres"""
    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None

    # Récupération des paramètres de filtrage
    search = request.GET.get('search', '')
    ecole_id = request.GET.get('ecole', '')
    type_enseignant = request.GET.get('type_enseignant', '')
    statut = request.GET.get('statut', '')
    
    # Construction de la requête
    enseignants = Enseignant.objects.select_related('ecole').prefetch_related('affectations__classe')
    if restreindre:
        enseignants = enseignants.filter(ecole=ecole_user)
    
    if search:
        enseignants = enseignants.filter(
            Q(nom__icontains=search) | 
            Q(prenoms__icontains=search) |
            Q(email__icontains=search)
        )
    
    if ecole_id:
        enseignants = enseignants.filter(ecole_id=ecole_id)
    
    if type_enseignant:
        enseignants = enseignants.filter(type_enseignant=type_enseignant)
    
    if statut:
        enseignants = enseignants.filter(statut=statut)
    
    # Pagination
    paginator = Paginator(enseignants, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Données pour les filtres
    ecoles = Ecole.objects.all()
    if restreindre:
        ecoles = ecoles.filter(id=ecole_user.id)
    types_enseignant = TypeEnseignant.choices
    
    # Vérifier s'il y a des enseignants
    if not enseignants.exists() and not any([search, ecole_id, type_enseignant, statut]):
        # Aucun enseignant et aucun filtre appliqué = base de données vide
        return render(request, 'salaires/empty_teachers_help.html')
    
    # Statistiques des résultats filtrés
    stats = {
        'total_enseignants': enseignants.count(),
        'enseignants_actifs': enseignants.filter(statut='ACTIF').count(),
        'taux_horaire': enseignants.filter(type_enseignant='SECONDAIRE').count(),
        'salaire_fixe': enseignants.exclude(type_enseignant='SECONDAIRE').count(),
    }
    
    context = {
        'page_obj': page_obj,
        'enseignants': page_obj,
        'ecoles': ecoles,
        'types_enseignant': types_enseignant,
        'stats': stats,
        'is_paginated': page_obj.has_other_pages(),
    }
    
    return render(request, 'salaires/liste_enseignants.html', context)


@login_required
def export_enseignants_csv(request):
    """Export CSV de la liste des enseignants en respectant les filtres"""
    search = request.GET.get('search', '')
    ecole_id = request.GET.get('ecole', '')
    type_enseignant = request.GET.get('type_enseignant', '')
    statut = request.GET.get('statut', '')

    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None
    enseignants = Enseignant.objects.select_related('ecole')
    if restreindre:
        enseignants = enseignants.filter(ecole=ecole_user)
    if search:
        enseignants = enseignants.filter(
            Q(nom__icontains=search) |
            Q(prenoms__icontains=search) |
            Q(email__icontains=search)
        )
    if ecole_id:
        enseignants = enseignants.filter(ecole_id=ecole_id)
    if type_enseignant:
        enseignants = enseignants.filter(type_enseignant=type_enseignant)
    if statut:
        enseignants = enseignants.filter(statut=statut)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="enseignants.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Ecole', 'Nom', 'Prénoms', 'Email', 'Téléphone', 'Type', 'Statut',
        'Salaire Fixe', 'Taux Horaire', 'Heures Mensuelles'
    ])

    for ens in enseignants.order_by('ecole__nom', 'nom'):
        writer.writerow([
            getattr(ens.ecole, 'nom', ''),
            ens.nom,
            ens.prenoms,
            ens.email or '',
            getattr(ens, 'telephone', ''),
            ens.type_enseignant,
            ens.statut,
            ens.salaire_fixe or '',
            ens.taux_horaire or '',
            ens.heures_mensuelles or ''
        ])

    return response


@login_required
def export_enseignants_pdf(request):
    """Export PDF de la liste des enseignants en respectant les mêmes filtres que la vue liste et CSV."""
    # Filtres
    search = request.GET.get('search', '')
    ecole_id = request.GET.get('ecole', '')
    type_enseignant = request.GET.get('type_enseignant', '')
    statut = request.GET.get('statut', '')

    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None
    enseignants = Enseignant.objects.select_related('ecole')
    if restreindre:
        enseignants = enseignants.filter(ecole=ecole_user)
    if search:
        enseignants = enseignants.filter(
            Q(nom__icontains=search) |
            Q(prenoms__icontains=search) |
            Q(email__icontains=search)
        )
    if ecole_id:
        enseignants = enseignants.filter(ecole_id=ecole_id)
    if type_enseignant:
        enseignants = enseignants.filter(type_enseignant=type_enseignant)
    if statut:
        enseignants = enseignants.filter(statut=statut)

    # Préparer la réponse HTTP
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="enseignants.pdf"'

    # Document (paysage pour meilleure lisibilité)
    doc = SimpleDocTemplate(response, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=60, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        name='Cell',
        parent=styles['Normal'],
        fontSize=7,
        leading=8,
    )

    title_text = "Liste des enseignants"
    elements.append(Paragraph(title_text, styles['Title']))
    elements.append(Spacer(1, 0.5*cm))

    # Table avec largeurs de colonnes et wrap des textes
    data = [[
        'École', 'Nom', 'Prénoms', 'Email', 'Téléphone', 'Type', 'Statut',
        'Salaire Fixe', 'Taux Horaire', 'Heures Mensuelles'
    ]]

    def P(txt):
        return Paragraph(str(txt or ''), cell_style)

    # Abréviation des noms d'écoles pour économiser l'espace
    def _abbr_ecole(nom):
        n = str(nom or '')
        low = n.lower()
        campus = ''
        if 'somayah' in low:
            campus = 'Somayah'
        elif 'sonfonia' in low:
            campus = 'Sonfonia'
        base_is_hk = (
            'hadja kanfing' in low or 'h.k' in low or 'h k' in low or 'hk' in low or 'diané' in low or 'diane' in low
        )
        if base_is_hk and campus:
            return f"H. K DIANÉ – {campus}"
        return n

    for ens in enseignants.order_by('ecole__nom', 'nom'):
        data.append([
            _abbr_ecole(getattr(ens.ecole, 'nom', '') or ''),
            P(ens.nom),
            P(ens.prenoms),
            P(ens.email or ''),
            P(getattr(ens, 'telephone', '')),
            P(ens.type_enseignant),
            P(ens.statut),
            f"{ens.salaire_fixe:,}".replace(',', ' ') if ens.salaire_fixe is not None else '',
            f"{ens.taux_horaire:,}".replace(',', ' ') if ens.taux_horaire is not None else '',
            f"{ens.heures_mensuelles:,}".replace(',', ' ') if ens.heures_mensuelles is not None else ''
        ])

    col_widths = [
        3.4*cm,  # École (élargi pour éviter le retour à la ligne)
        2.6*cm,  # Nom
        3.2*cm,  # Prénoms
        4.2*cm,  # Email
        2.6*cm,  # Téléphone
        2.6*cm,  # Type
        2.2*cm,  # Statut
        2.6*cm,  # Salaire Fixe
        2.6*cm,  # Taux Horaire
        2.3*cm,  # Heures Mensuelles
    ]

    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        # Le corps utilise ParagraphStyle(Cell) à 7pt; on maintient ici pour les cellules non-Paragraph
        ('FONTSIZE', (0,1), (-1,-1), 7),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
    ]))
    elements.append(table)

    # Logo + filigrane dynamiques par école
    def _draw_header_and_watermark(canvas, doc_):
        # Déterminer l'école courante (si l'utilisateur est restreint)
        try:
            ecole_user = _ecole_utilisateur(request)
        except Exception:
            ecole_user = None
        # Chercher logo d'école prioritaire
        school_logo_path = None
        try:
            if ecole_user and getattr(ecole_user, 'logo', None) and hasattr(ecole_user.logo, 'path') and os.path.exists(ecole_user.logo.path):
                school_logo_path = ecole_user.logo.path
        except Exception:
            school_logo_path = None
        if not school_logo_path:
            school_logo_path = os.path.join(getattr(settings, 'BASE_DIR', ''), 'static', 'logos', 'logo.png')

        # En-tête avec logo
        try:
            if school_logo_path and os.path.exists(school_logo_path):
                canvas.drawImage(school_logo_path, doc_.leftMargin, doc_.pagesize[1]-40, width=30, height=30, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
        canvas.setFont('Helvetica-Bold', 8)
        # Libellé d'école
        school_label = getattr(ecole_user, 'nom', None) or title_text
        canvas.drawString(doc_.leftMargin + 40, doc_.pagesize[1]-25, school_label)
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(doc_.pagesize[0]-doc_.rightMargin, doc_.pagesize[1]-25, title_text)

        # Filigrane avec logo (comme les autres documents), dynamique par école
        canvas.saveState()
        try:
            if school_logo_path and os.path.exists(school_logo_path):
                wm_width = doc_.pagesize[0] * 1.5
                wm_height = wm_width
                wm_x = (doc_.pagesize[0] - wm_width) / 2
                wm_y = (doc_.pagesize[1] - wm_height) / 2
                try:
                    canvas.setFillAlpha(0.15)
                except Exception:
                    pass
                canvas.translate(doc_.pagesize[0] / 2.0, doc_.pagesize[1] / 2.0)
                canvas.rotate(30)
                canvas.translate(-doc_.pagesize[0] / 2.0, -doc_.pagesize[1] / 2.0)
                canvas.drawImage(school_logo_path, wm_x, wm_y, width=wm_width, height=wm_height, preserveAspectRatio=True, mask='auto')
        finally:
            canvas.restoreState()

    doc.build(elements, onFirstPage=_draw_header_and_watermark, onLaterPages=_draw_header_and_watermark)
    return response


@login_required
@require_school_object(model=Enseignant, pk_kwarg='enseignant_id', field_path='ecole')
def detail_enseignant(request, enseignant_id):
    """Détail d'un enseignant"""
    ecole_user = _ecole_utilisateur(request)
    qs = Enseignant.objects.all()
    if not user_is_admin(request.user) and ecole_user is not None:
        qs = qs.filter(ecole=ecole_user)
    
    try:
        enseignant = get_object_or_404(qs, id=enseignant_id)
    except:
        # Si l'enseignant n'existe pas, rediriger vers la liste avec un message
        messages.error(
            request, 
            f"Aucun enseignant trouvé avec l'ID {enseignant_id}. "
            f"Voici la liste des enseignants disponibles."
        )
        return redirect('salaires:liste_enseignants')
    
    # Affectations actuelles
    affectations_actuelles = enseignant.affectations.filter(
        actif=True,
        date_debut__lte=timezone.now().date()
    ).filter(
        Q(date_fin__isnull=True) | Q(date_fin__gte=timezone.now().date())
    ).select_related('classe')
    
    # Historique des affectations
    historique_affectations = enseignant.affectations.exclude(
        id__in=affectations_actuelles.values_list('id', flat=True)
    ).select_related('classe').order_by('-date_debut')
    
    # États de salaire récents
    etats_salaire = enseignant.etats_salaire.select_related(
        'periode'
    ).order_by('-periode__annee', '-periode__mois')[:12]

    # Historique récent des avances sur salaire
    avances_salaire = enseignant.avances_salaire.select_related(
        'periode'
    ).order_by('-date_avance', '-id')[:10]
    
    # Statistiques
    stats = {
        'total_affectations': enseignant.affectations.count(),
        'affectations_actuelles': affectations_actuelles.count(),
        'etats_salaire': enseignant.etats_salaire.count(),
        'etats_valides': enseignant.etats_salaire.filter(valide=True).count(),
        'total_avances': enseignant.avances_salaire.exclude(
            statut=AvanceSalaire.Statut.ANNULEE
        ).aggregate(total=Sum('montant'))['total'] or 0,
    }
    
    # Calcul du salaire moyen si applicable
    if enseignant.etats_salaire.exists():
        stats['salaire_moyen'] = enseignant.etats_salaire.aggregate(
            moyenne=Avg('salaire_net')
        )['moyenne'] or 0
    else:
        stats['salaire_moyen'] = 0
    
    context = {
        'enseignant': enseignant,
        'affectations_actuelles': affectations_actuelles,
        'historique_affectations': historique_affectations,
        'etats_salaire': etats_salaire,
        'avances_salaire': avances_salaire,
        'stats': stats,
    }
    
    return render(request, 'salaires/detail_enseignant.html', context)


@login_required
@require_school_object(model=Enseignant, pk_kwarg='enseignant_id', field_path='ecole')
def ajouter_affectation(request, enseignant_id):
    """Créer une affectation de classe pour un enseignant"""
    ecole_user = _ecole_utilisateur(request)
    qs = Enseignant.objects.all()
    if not user_is_admin(request.user) and ecole_user is not None:
        qs = qs.filter(ecole=ecole_user)
    enseignant = get_object_or_404(qs, id=enseignant_id)

    if request.method == 'POST':
        form = AffectationClasseForm(request.POST, enseignant=enseignant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Affectation créée avec succès.')
            return redirect('salaires:detail_enseignant', enseignant_id=enseignant.id)
        else:
            messages.error(request, "Veuillez corriger les erreurs du formulaire.")
    else:
        form = AffectationClasseForm(enseignant=enseignant)

    context = {
        'enseignant': enseignant,
        'form': form,
    }
    return render(request, 'salaires/affectation_form.html', context)


@login_required
@require_school_object(model=AffectationClasse, pk_kwarg='affectation_id', field_path='enseignant__ecole')
def clore_affectation(request, affectation_id):
    """Clore (désactiver) une affectation en mettant une date de fin à aujourd'hui"""
    affectation = get_object_or_404(
        AffectationClasse.objects.select_related('enseignant__ecole'),
        id=affectation_id
    )
    ecole_user = _ecole_utilisateur(request)
    if not user_is_admin(request.user) and ecole_user is not None and affectation.enseignant.ecole_id != ecole_user.id:
        messages.error(request, "Accès refusé.")
        return redirect('salaires:detail_enseignant', enseignant_id=affectation.enseignant_id)

    if request.method == 'POST':
        affectation.actif = False
        affectation.date_fin = timezone.now().date()
        affectation.save()
        messages.success(request, 'Affectation clôturée avec succès.')
    else:
        messages.error(request, "Méthode non autorisée.")
    return redirect('salaires:detail_enseignant', enseignant_id=affectation.enseignant_id)


@login_required
@delete_permission_required()
@require_school_object(model=AffectationClasse, pk_kwarg='affectation_id', field_path='enseignant__ecole')
def supprimer_affectation(request, affectation_id):
    """Supprimer une affectation (si besoin)"""
    affectation = get_object_or_404(
        AffectationClasse.objects.select_related('enseignant__ecole'),
        id=affectation_id
    )
    ecole_user = _ecole_utilisateur(request)
    if not user_is_admin(request.user) and ecole_user is not None and affectation.enseignant.ecole_id != ecole_user.id:
        messages.error(request, "Accès refusé.")
        return redirect('salaires:detail_enseignant', enseignant_id=affectation.enseignant_id)

    if request.method == 'POST':
        enseignant_id = affectation.enseignant_id
        affectation.delete()
        messages.success(request, 'Affectation supprimée.')
        return redirect('salaires:detail_enseignant', enseignant_id=enseignant_id)
    else:
        messages.error(request, "Méthode non autorisée.")
        return redirect('salaires:detail_enseignant', enseignant_id=affectation.enseignant_id)


@login_required
def etats_salaire(request):
    """Liste des états de salaire avec filtres"""
    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None

    # Récupération des paramètres de filtrage
    periode_id = request.GET.get('periode', '')
    ecole_id = request.GET.get('ecole', '')
    enseignant_id = request.GET.get('enseignant', '')
    statut = request.GET.get('statut', '')
    search = request.GET.get('search', '')
    
    # Construction de la requête
    etats = EtatSalaire.objects.select_related('enseignant', 'periode', 'periode__ecole')
    if restreindre:
        etats = etats.filter(periode__ecole=ecole_user)
    
    if periode_id:
        etats = etats.filter(periode_id=periode_id)
    
    if ecole_id:
        etats = etats.filter(periode__ecole_id=ecole_id)
    
    if enseignant_id:
        etats = etats.filter(enseignant_id=enseignant_id)
    
    if statut == 'valide':
        etats = etats.filter(valide=True)
    elif statut == 'en_attente':
        etats = etats.filter(valide=False)
    elif statut == 'paye':
        etats = etats.filter(paye=True)
    elif statut == 'non_paye':
        etats = etats.filter(paye=False)
    
    if search:
        etats = etats.filter(
            Q(enseignant__nom__icontains=search) |
            Q(enseignant__prenoms__icontains=search)
        )
    
    # Tri par défaut
    etats = etats.order_by('-periode__annee', '-periode__mois', 'enseignant__nom')

    # Fallback intelligent: si aucun filtre n'est appliqué et que la requête est vide,
    # afficher les états des 3 dernières périodes disponibles (par école si restreint)
    filters_applied = any([periode_id, ecole_id, enseignant_id, statut, search])
    if not filters_applied and not etats.exists():
        periodes_recent = PeriodeSalaire.objects.order_by('-annee', '-mois')
        if restreindre:
            periodes_recent = periodes_recent.filter(ecole=ecole_user)
        recent_ids = list(periodes_recent.values_list('id', flat=True)[:3])
        if recent_ids:
            etats = (
                EtatSalaire.objects.select_related('enseignant', 'periode', 'periode__ecole')
                .filter(periode_id__in=recent_ids)
                .order_by('-periode__annee', '-periode__mois', 'enseignant__nom')
            )
    
    # Si toujours aucun résultat, vérifier s'il y a des périodes créées
    no_periods_exist = False
    periode_selected_exists = False
    if not etats.exists():
        periodes_count = PeriodeSalaire.objects.all()
        if restreindre:
            periodes_count = periodes_count.filter(ecole=ecole_user)
        no_periods_exist = periodes_count.count() == 0
        
        # Vérifier si une période spécifique est sélectionnée et existe
        if periode_id:
            try:
                periode_selected = PeriodeSalaire.objects.get(id=periode_id)
                if not restreindre or periode_selected.ecole == ecole_user:
                    periode_selected_exists = True
            except PeriodeSalaire.DoesNotExist:
                pass
    
    # Pagination
    paginator = Paginator(etats, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Données pour les filtres
    periodes = PeriodeSalaire.objects.order_by('-annee', '-mois')
    if restreindre:
        periodes = periodes.filter(ecole=ecole_user)
    ecoles = Ecole.objects.all()
    if restreindre:
        ecoles = ecoles.filter(id=ecole_user.id)
    
    # Statistiques des résultats filtrés
    totaux = {
        'total_etats': etats.count(),
        'montant_total': etats.aggregate(total=Sum('salaire_net'))['total'] or 0,
        'en_attente': etats.filter(valide=False).count(),
        'payes': etats.filter(paye=True).count(),
    }
    
    context = {
        'page_obj': page_obj,
        'etats': page_obj,
        'periodes': periodes,
        'ecoles': ecoles,
        'totaux': totaux,
        'is_paginated': page_obj.has_other_pages(),
        'no_periods_exist': no_periods_exist,
        'periode_selected_exists': periode_selected_exists,
        # Conserver les filtres sélectionnés
        'periode_selectionnee': periode_id,
        'ecole_selectionnee': ecole_id,
        'statut_selectionne': statut,
    }
    return render(request, 'salaires/etats_salaire.html', context)

@login_required
def export_etats_salaire_csv(request):
    """Export CSV des états de salaire en respectant exactement les filtres de la vue liste."""
    # Filtres identiques à etats_salaire()
    periode_id = request.GET.get('periode', '')
    ecole_id = request.GET.get('ecole', '')
    statut = request.GET.get('statut', '')
    search = request.GET.get('search', '')

    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None
    etats = EtatSalaire.objects.select_related('enseignant', 'periode', 'periode__ecole')
    if restreindre:
        etats = etats.filter(periode__ecole=ecole_user)

    if periode_id:
        etats = etats.filter(periode_id=periode_id)
    if ecole_id:
        etats = etats.filter(periode__ecole_id=ecole_id)
    if statut == 'valide':
        etats = etats.filter(valide=True)
    elif statut == 'en_attente':
        etats = etats.filter(valide=False)
    elif statut == 'paye':
        etats = etats.filter(paye=True)
    elif statut == 'non_paye':
        etats = etats.filter(paye=False)
    if search:
        etats = etats.filter(
            Q(enseignant__nom__icontains=search) |
            Q(enseignant__prenoms__icontains=search)
        )

    etats = etats.order_by('-periode__annee', '-periode__mois', 'enseignant__nom')

    # Générer le CSV
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="etats_salaire.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Ecole', 'Periode', 'Enseignant', 'Type', 'Valide', 'Payé',
        'Salaire Base', 'Primes', 'Retenues', 'Avances', 'Salaire Net',
        'Total Heures', 'Date Calcul'
    ])

    for e in etats:
        writer.writerow([
            getattr(e.periode.ecole, 'nom', ''),
            f"{e.periode.mois:02d}/{e.periode.annee}",
            getattr(e.enseignant, 'nom_complet', str(e.enseignant)),
            getattr(e.enseignant, 'type_enseignant', ''),
            'Oui' if e.valide else 'Non',
            'Oui' if e.paye else 'Non',
            e.salaire_base,
            e.primes,
            e.deductions,
            e.montant_avances,
            e.salaire_net,
            e.total_heures if e.total_heures is not None else '',
            e.date_calcul.strftime('%Y-%m-%d %H:%M') if e.date_calcul else ''
        ])

    return response

@login_required
def export_etats_salaire_pdf(request):
    """Export PDF des états de salaire avec les mêmes filtres, en-tête logo et filigrane."""
    # Filtres
    periode_id = request.GET.get('periode', '')
    ecole_id = request.GET.get('ecole', '')
    statut = request.GET.get('statut', '')
    search = request.GET.get('search', '')

    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None
    etats = EtatSalaire.objects.select_related('enseignant', 'periode', 'periode__ecole')
    if restreindre:
        etats = etats.filter(periode__ecole=ecole_user)
    if periode_id:
        etats = etats.filter(periode_id=periode_id)
    if ecole_id:
        etats = etats.filter(periode__ecole_id=ecole_id)
    if statut == 'valide':
        etats = etats.filter(valide=True)
    elif statut == 'en_attente':
        etats = etats.filter(valide=False)
    elif statut == 'paye':
        etats = etats.filter(paye=True)
    elif statut == 'non_paye':
        etats = etats.filter(paye=False)
    if search:
        etats = etats.filter(
            Q(enseignant__nom__icontains=search) |
            Q(enseignant__prenoms__icontains=search)
        )

    etats = etats.order_by('-periode__annee', '-periode__mois', 'enseignant__nom')

    # Préparer la réponse HTTP
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="etats_salaire.pdf"'

    # Document (paysage pour meilleure lisibilité)
    doc = SimpleDocTemplate(response, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=60, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()

    title_text = "États de salaire"
    elements.append(Paragraph(title_text, styles['Title']))
    elements.append(Spacer(1, 0.5*cm))

    # Table
    data = [[
        'École', 'Période', 'Enseignant', 'Type', 'Valide', 'Payé',
        'Salaire Base', 'Primes', 'Retenues', 'Avances', 'Salaire Net',
        'Total Heures', 'Date Calcul'
    ]]
    for e in etats:
        data.append([
            getattr(e.periode.ecole, 'nom', ''),
            f"{e.periode.mois:02d}/{e.periode.annee}",
            getattr(e.enseignant, 'nom_complet', str(e.enseignant)),
            getattr(e.enseignant, 'type_enseignant', ''),
            'Oui' if e.valide else 'Non',
            'Oui' if e.paye else 'Non',
            e.salaire_base,
            e.primes,
            e.deductions,
            e.montant_avances,
            e.salaire_net,
            e.total_heures if e.total_heures is not None else '',
            e.date_calcul.strftime('%Y-%m-%d %H:%M') if e.date_calcul else ''
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(table)

    # Logo + filigrane dynamiques par école
    def _draw_header_and_watermark(canvas, doc_):
        # Déterminer l'école courante (si l'utilisateur est restreint)
        try:
            ecole_user = _ecole_utilisateur(request)
        except Exception:
            ecole_user = None
        # Chercher logo d'école prioritaire
        school_logo_path = None
        try:
            if ecole_user and getattr(ecole_user, 'logo', None) and hasattr(ecole_user.logo, 'path') and os.path.exists(ecole_user.logo.path):
                school_logo_path = ecole_user.logo.path
        except Exception:
            school_logo_path = None
        if not school_logo_path:
            school_logo_path = os.path.join(getattr(settings, 'BASE_DIR', ''), 'static', 'logos', 'logo.png')

        # En-tête avec logo
        try:
            if school_logo_path and os.path.exists(school_logo_path):
                canvas.drawImage(school_logo_path, doc_.leftMargin, doc_.pagesize[1]-40, width=30, height=30, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
        canvas.setFont('Helvetica-Bold', 8)
        school_label = getattr(ecole_user, 'nom', None) or title_text
        canvas.drawString(doc_.leftMargin + 40, doc_.pagesize[1]-25, school_label)
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(doc_.pagesize[0]-doc_.rightMargin, doc_.pagesize[1]-25, title_text)

        # Filigrane avec logo (comme les autres documents), dynamique par école
        canvas.saveState()
        try:
            if school_logo_path and os.path.exists(school_logo_path):
                wm_width = doc_.pagesize[0] * 1.5
                wm_height = wm_width
                wm_x = (doc_.pagesize[0] - wm_width) / 2
                wm_y = (doc_.pagesize[1] - wm_height) / 2
                try:
                    canvas.setFillAlpha(0.15)
                except Exception:
                    pass
                canvas.translate(doc_.pagesize[0] / 2.0, doc_.pagesize[1] / 2.0)
                canvas.rotate(30)
                canvas.translate(-doc_.pagesize[0] / 2.0, -doc_.pagesize[1] / 2.0)
                canvas.drawImage(school_logo_path, wm_x, wm_y, width=wm_width, height=wm_height, preserveAspectRatio=True, mask='auto')
        finally:
            canvas.restoreState()

    doc.build(elements, onFirstPage=_draw_header_and_watermark, onLaterPages=_draw_header_and_watermark)
    return response


@login_required
@require_POST
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def calculer_salaires(request, periode_id):
    """Calculer tous les salaires d'une période en une transaction atomique."""
    try:
        with transaction.atomic():
            periode = get_object_or_404(
                PeriodeSalaire.objects.select_for_update(), id=periode_id
            )
            if periode.cloturee:
                messages.error(
                    request,
                    "Impossible de calculer les salaires d'une période clôturée.",
                )
                return redirect('salaires:etats_salaire')

            calculs_effectues = 0
            for enseignant in enseignants_eligibles(periode).select_for_update():
                _, modifie = calculer_etat_salaire(
                    enseignant, periode, request.user
                )
                calculs_effectues += int(modifie)

        messages.success(
            request,
            f"Calcul des salaires terminé. {calculs_effectues} état(s) calculé(s).",
        )
    except Exception as exc:
        messages.error(
            request,
            "Aucun salaire n'a été enregistré car le calcul a échoué : "
            f"{exc}",
        )
    
    return redirect('salaires:etats_salaire')


@login_required
@require_school_object(model=EtatSalaire, pk_kwarg='etat_id', field_path='periode__ecole')
def ajuster_etat_salaire(request, etat_id):
    """Modifier les primes, retenues et observations avant validation."""
    etat = get_object_or_404(
        EtatSalaire.objects.select_related('enseignant', 'periode'), id=etat_id
    )

    if etat.valide or etat.periode.cloturee:
        messages.error(
            request,
            "Un état validé ou appartenant à une période clôturée ne peut plus être ajusté.",
        )
        return redirect('salaires:etats_salaire')

    if request.method == 'POST':
        form = EtatSalaireAjustementForm(request.POST, instance=etat)
        if form.is_valid():
            with transaction.atomic():
                etat_verrouille = EtatSalaire.objects.select_for_update().get(pk=etat.pk)
                if etat_verrouille.valide or etat_verrouille.periode.cloturee:
                    messages.error(request, "Cet état ne peut plus être ajusté.")
                    return redirect('salaires:etats_salaire')

                etat_verrouille.primes = form.cleaned_data['primes']
                etat_verrouille.deductions = form.cleaned_data['deductions']
                etat_verrouille.observations = form.cleaned_data['observations']
                etat_verrouille.save()

            messages.success(
                request,
                f"Primes et retenues de {etat.enseignant.nom_complet} mises à jour.",
            )
            return redirect('salaires:etats_salaire')
    else:
        form = EtatSalaireAjustementForm(instance=etat)

    return render(
        request,
        'salaires/ajuster_etat_salaire.html',
        {'form': form, 'etat': etat},
    )


@login_required
@require_POST
@require_school_object(model=EtatSalaire, pk_kwarg='etat_id', field_path='periode__ecole')
def valider_etat_salaire(request, etat_id):
    """Valider un état de salaire"""
    with transaction.atomic():
        etat = get_object_or_404(
            EtatSalaire.objects.select_for_update().select_related(
                'enseignant', 'periode'
            ),
            id=etat_id,
        )

        if not etat.peut_etre_valide:
            messages.error(request, "Cet état de salaire ne peut pas être validé.")
            return redirect('salaires:etats_salaire')

        etat.montant_avances = total_avances_a_deduire(
            etat.enseignant, etat.periode
        )
        etat.valide = True
        etat.valide_par = request.user
        etat.date_validation = timezone.now()
        etat.save()

    messages.success(
        request,
        f"État de salaire de {etat.enseignant.nom_complet} validé avec succès.",
    )

    return redirect('salaires:etats_salaire')


@login_required
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def saisir_heures_mensuelles(request, periode_id):
    """Saisir en lot les heures mensuelles des enseignants au taux horaire."""
    periode = get_object_or_404(
        PeriodeSalaire.objects.select_related('ecole'),
        id=periode_id,
    )
    if periode.cloturee:
        messages.error(
            request,
            "Les heures d'une période clôturée ne peuvent plus être modifiées.",
        )
        return redirect('salaires:gestion_periodes')

    enseignants = list(
        enseignants_eligibles(periode)
        .filter(type_enseignant=TypeEnseignant.SECONDAIRE)
    )
    etats = {
        etat.enseignant_id: etat
        for etat in EtatSalaire.objects.filter(
            periode=periode,
            enseignant_id__in=[enseignant.id for enseignant in enseignants],
        )
    }

    if request.method == 'POST':
        saisies = []
        erreurs = []
        for enseignant in enseignants:
            if etats.get(enseignant.id) and etats[enseignant.id].valide:
                continue
            source = request.POST.get(
                f'source_{enseignant.id}',
                SourceHeuresSalaire.POINTAGE,
            )
            if source not in {
                SourceHeuresSalaire.POINTAGE,
                SourceHeuresSalaire.MENSUEL,
            }:
                erreurs.append(
                    f"Mode de calcul invalide pour {enseignant.nom_complet}."
                )
                continue

            heures = None
            if source == SourceHeuresSalaire.MENSUEL:
                valeur = (request.POST.get(f'heures_{enseignant.id}') or '').strip()
                try:
                    heures = Decimal(valeur)
                except (InvalidOperation, TypeError):
                    erreurs.append(
                        f"Renseignez des heures valides pour {enseignant.nom_complet}."
                    )
                    continue
                if heures < 0 or heures > Decimal('744'):
                    erreurs.append(
                        f"Les heures de {enseignant.nom_complet} doivent être comprises entre 0 et 744."
                    )
                    continue

            saisies.append((enseignant, source, heures))

        if not erreurs:
            calculs = 0
            ignores = 0
            with transaction.atomic():
                periode = PeriodeSalaire.objects.select_for_update().get(pk=periode.pk)
                if periode.cloturee:
                    messages.error(
                        request,
                        "Cette période vient d'être clôturée et ne peut plus être modifiée.",
                    )
                    return redirect('salaires:gestion_periodes')

                for enseignant, source, heures in saisies:
                    etat, modifie = calculer_etat_salaire(
                        enseignant,
                        periode,
                        request.user,
                        source_heures=source,
                        heures_mensuelles=heures,
                    )
                    calculs += int(modifie)
                    ignores += int(not modifie and etat.valide)

            messages.success(
                request,
                f"Heures enregistrées et {calculs} salaire(s) recalculé(s) immédiatement."
            )
            if ignores:
                messages.warning(
                    request,
                    f"{ignores} salaire(s) déjà validé(s) n'ont pas été modifiés."
                )
            return redirect(
                f"{reverse('salaires:etats_salaire')}?periode={periode.id}"
            )

        for erreur in erreurs[:10]:
            messages.error(request, erreur)

    lignes = []
    total_estime = Decimal('0')
    for enseignant in enseignants:
        etat = etats.get(enseignant.id)
        heures_pointage = heures_reellement_travaillees(enseignant, periode)
        source = (
            request.POST.get(f'source_{enseignant.id}')
            if request.method == 'POST'
            else getattr(etat, 'source_heures', SourceHeuresSalaire.POINTAGE)
        ) or SourceHeuresSalaire.POINTAGE
        if source == SourceHeuresSalaire.MENSUEL:
            heures_proposees = (
                request.POST.get(f'heures_{enseignant.id}')
                if request.method == 'POST'
                else (
                    etat.total_heures
                    if etat and etat.total_heures is not None
                    else enseignant.heures_mensuelles
                )
            )
            try:
                heures_calcul = Decimal(str(heures_proposees or 0))
            except InvalidOperation:
                heures_calcul = Decimal('0')
        else:
            heures_proposees = enseignant.heures_mensuelles or ''
            heures_calcul = heures_pointage

        salaire_estime = arrondir_montant(
            heures_calcul * (enseignant.taux_horaire or Decimal('0'))
        )
        total_estime += salaire_estime
        lignes.append({
            'enseignant': enseignant,
            'etat': etat,
            'source': source,
            'heures_pointage': heures_pointage,
            'heures_proposees': heures_proposees,
            'salaire_estime': salaire_estime,
        })

    return render(request, 'salaires/saisir_heures_mensuelles.html', {
        'periode': periode,
        'lignes': lignes,
        'source_pointage': SourceHeuresSalaire.POINTAGE,
        'source_mensuel': SourceHeuresSalaire.MENSUEL,
        'total_estime': total_estime,
    })


@login_required
@require_POST
@require_school_object(model=EtatSalaire, pk_kwarg='etat_id', field_path='periode__ecole')
def marquer_paye(request, etat_id):
    """Marquer un état de salaire comme payé"""

    with transaction.atomic():
        etat = get_object_or_404(
            EtatSalaire.objects.select_for_update().select_related(
                'enseignant', 'periode'
            ),
            id=etat_id,
        )

        if not etat.peut_etre_paye:
            messages.error(request, "Cet état de salaire ne peut pas être marqué comme payé.")
            return redirect('salaires:etats_salaire')

        etat.paye = True
        etat.date_paiement = timezone.now()
        etat.save()
        avances = AvanceSalaire.objects.select_for_update().filter(
            enseignant=etat.enseignant,
            periode=etat.periode,
            statut=AvanceSalaire.Statut.APPROUVEE,
        )
        for avance in avances:
            avance.statut = AvanceSalaire.Statut.DEDUITE
            avance.date_deduction = etat.date_paiement
            avance.save(update_fields=(
                'statut', 'date_deduction', 'date_modification',
            ))

    messages.success(
        request,
        f"État de salaire de {etat.enseignant.nom_complet} marqué comme payé.",
    )

    return redirect('salaires:etats_salaire')


@login_required
@require_school_object(model=EtatSalaire, pk_kwarg='etat_id', field_path='periode__ecole')
def fiche_paie_pdf(request, etat_id):
    """Génère une fiche de paie PDF pour un état de salaire"""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    from django.http import HttpResponse
    from datetime import datetime
    
    etat = get_object_or_404(EtatSalaire, id=etat_id)
    
    # Vérifier les permissions (double vérification en plus du décorateur)
    ecole_user = _ecole_utilisateur(request)
    if not user_is_admin(request.user) and ecole_user and etat.periode.ecole != ecole_user:
        raise Http404("État de salaire non trouvé")
    
    # Créer la réponse HTTP
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="fiche_paie_{etat.enseignant.nom}_{etat.periode.mois}_{etat.periode.annee}.pdf"'
    
    # Créer le PDF
    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    
    # Ajouter le logo en filigrane (spécifique à l'école de l'utilisateur)
    from ecole_moderne.pdf_utils import draw_logo_watermark
    draw_logo_watermark(p, width, height, opacity=0.06, rotate=30, scale=1.2, ecole=_ecole_utilisateur(request))
    
    # En-tête avec logo et coordonnées dynamiques de l'école de la période
    ecole_fp = getattr(getattr(etat, 'periode', None), 'ecole', None)
    try:
        header_logo_path = None
        # Priorité: logo de l'école si présent
        if ecole_fp is not None and hasattr(ecole_fp, 'logo'):
            school_logo_path = getattr(getattr(ecole_fp, 'logo', None), 'path', None)
            if school_logo_path and os.path.exists(school_logo_path):
                header_logo_path = school_logo_path
        # Fallback: logo statique
        if not header_logo_path:
            from django.contrib.staticfiles import finders
            header_logo_path = finders.find('logos/logo.png')
        if header_logo_path:
            p.drawImage(header_logo_path, 2*cm, height-4*cm, width=3*cm, height=2*cm, preserveAspectRatio=True, mask='auto')
    except Exception:
        pass

    # En-tête: Nom de l'école et coordonnées (à droite du logo)
    y_header = height - 2*cm
    try:
        if ecole_fp is not None:
            # Nom de l'école en gras
            p.setFont('Helvetica-Bold', 14)
            p.drawString(6*cm, y_header, f"{getattr(ecole_fp, 'nom', '')}")
            y_header -= 0.5*cm
            
            # Coordonnées en plus petit
            p.setFont('Helvetica', 9)
            adr = getattr(ecole_fp, 'adresse', '') or ''
            tel = getattr(ecole_fp, 'telephone', '') or ''
            email = getattr(ecole_fp, 'email', '') or ''
            dirc = getattr(ecole_fp, 'directeur', '') or ''
            
            if adr:
                p.drawString(6*cm, y_header, f"Adresse: {adr}")
                y_header -= 0.4*cm
            if tel:
                p.drawString(6*cm, y_header, f"Tél: {tel}")
                y_header -= 0.4*cm
            if email:
                p.drawString(6*cm, y_header, f"Email: {email}")
                y_header -= 0.4*cm
            if dirc:
                p.drawString(6*cm, y_header, f"Directeur: {dirc}")
    except Exception:
        pass
    
    # Ligne de séparation
    p.setStrokeColor(colors.grey)
    p.line(2*cm, height - 4.5*cm, width - 2*cm, height - 4.5*cm)
    
    # Titre FICHE DE PAIE centré
    p.setFont("Helvetica-Bold", 16)
    fiche_text = f"FICHE DE PAIE - {etat.periode.mois:02d}/{etat.periode.annee}"
    p.drawCentredString(width/2, height - 5.2*cm, fiche_text)
    
    # Informations période
    p.setFont("Helvetica", 10)
    p.drawString(2*cm, height - 5.8*cm, f"Date d'édition: {datetime.now().strftime('%d/%m/%Y')}")
    
    # Informations enseignant
    y_pos = height - 6.5*cm
    p.setFont("Helvetica-Bold", 12)
    p.drawString(2*cm, y_pos, "INFORMATIONS ENSEIGNANT")
    
    y_pos -= 0.8*cm
    p.setFont("Helvetica", 10)
    p.drawString(2*cm, y_pos, f"Nom: {etat.enseignant.nom} {etat.enseignant.prenoms}")
    y_pos -= 0.5*cm
    p.drawString(2*cm, y_pos, f"Téléphone: {etat.enseignant.telephone or 'Non renseigné'}")
    y_pos -= 0.5*cm
    p.drawString(2*cm, y_pos, f"Email: {etat.enseignant.email or 'Non renseigné'}")
    y_pos -= 0.5*cm
    p.drawString(2*cm, y_pos, f"Type: {'Salaire fixe' if etat.enseignant.est_salaire_fixe else 'Taux horaire'}")
    
    # Détails du salaire
    y_pos -= 1.5*cm
    p.setFont("Helvetica-Bold", 12)
    p.drawString(2*cm, y_pos, "DÉTAILS DU SALAIRE")
    
    # Tableau des montants
    data = [
        ['Élément', 'Montant (GNF)'],
        ['Salaire de base', f"{etat.salaire_base:,.0f}".replace(',', ' ')],
    ]
    
    if etat.total_heures is not None:
        data.append(['Heures travaillées', f"{etat.total_heures}h"])
        data.append(['Source des heures', etat.get_source_heures_display()])
        data.append(['Taux horaire', f"{etat.taux_horaire_applique or 0:,.0f}".replace(',', ' ')])
    
    if etat.primes:
        data.append(['Primes', f"{etat.primes:,.0f}".replace(',', ' ')])
    
    if etat.deductions:
        data.append(['Déductions', f"-{etat.deductions:,.0f}".replace(',', ' ')])
    if etat.montant_avances:
        data.append([
            'Avances sur salaire',
            f"-{etat.montant_avances:,.0f}".replace(',', ' '),
        ])
    
    data.append(['SALAIRE NET', f"{etat.salaire_net:,.0f}".replace(',', ' ')])
    
    # Créer le tableau
    y_pos -= 0.8*cm
    table = Table(data, colWidths=[8*cm, 4*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    table.wrapOn(p, width, height)
    table.drawOn(p, 2*cm, y_pos - len(data) * 0.6*cm)
    
    # Statut
    y_pos -= (len(data) + 2) * 0.6*cm
    p.setFont("Helvetica-Bold", 10)
    statut_text = "VALIDÉ" if etat.valide else "EN ATTENTE DE VALIDATION"
    if etat.paye:
        statut_text += " - PAYÉ"
    p.drawString(2*cm, y_pos, f"Statut: {statut_text}")
    
    if etat.valide and etat.date_validation:
        y_pos -= 0.5*cm
        p.setFont("Helvetica", 9)
        p.drawString(2*cm, y_pos, f"Validé le {etat.date_validation.strftime('%d/%m/%Y')} par {etat.valide_par}")
    
    if etat.paye and etat.date_paiement:
        y_pos -= 0.5*cm
        p.drawString(2*cm, y_pos, f"Payé le {etat.date_paiement.strftime('%d/%m/%Y')}")
    
    # Section signatures
    y_pos -= 3*cm
    p.setFont("Helvetica-Bold", 12)
    p.drawString(2*cm, y_pos, "SIGNATURES")
    
    # Ligne de séparation
    y_pos -= 0.5*cm
    p.line(2*cm, y_pos, width-2*cm, y_pos)
    
    # Signatures côte à côte
    y_pos -= 1*cm
    
    # Signature enseignant (gauche)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(2*cm, y_pos, "L'ENSEIGNANT")
    p.setFont("Helvetica", 9)
    p.drawString(2*cm, y_pos-0.4*cm, f"Nom: {etat.enseignant.nom} {etat.enseignant.prenoms}")
    
    # Cadre pour signature enseignant
    signature_width = 6*cm
    signature_height = 2*cm
    p.rect(2*cm, y_pos-3*cm, signature_width, signature_height)
    p.setFont("Helvetica", 8)
    p.drawString(2*cm + 0.2*cm, y_pos-3.2*cm, "Signature et date:")
    
    # Signature comptable (droite)
    comptable_x = width - 8*cm
    p.setFont("Helvetica-Bold", 10)
    p.drawString(comptable_x, y_pos, "LE COMPTABLE")
    p.setFont("Helvetica", 9)
    if etat.calcule_par:
        p.drawString(comptable_x, y_pos-0.4*cm, f"Nom: {etat.calcule_par.get_full_name() or etat.calcule_par.username}")
    else:
        p.drawString(comptable_x, y_pos-0.4*cm, "Nom: _________________")
    
    # Cadre pour signature comptable
    p.rect(comptable_x, y_pos-3*cm, signature_width, signature_height)
    p.setFont("Helvetica", 8)
    p.drawString(comptable_x + 0.2*cm, y_pos-3.2*cm, "Signature et date:")
    
    # Pied de page
    p.setFont("Helvetica", 8)
    p.drawString(2*cm, 2*cm, f"Document généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
    p.drawString(2*cm, 1.5*cm, "Ce document est confidentiel et ne doit pas être divulgué à des tiers.")
    
    p.showPage()
    p.save()
    
    return response


@login_required
def gestion_periodes(request):
    """Gestion des périodes de salaire"""
    
    # Récupération des paramètres de filtrage
    ecole_id = request.GET.get('ecole', '')
    annee = request.GET.get('annee', '')
    statut = request.GET.get('statut', '')  # 'cloture' | 'ouvert' | ''
    
    # Construction de la requête
    periodes = PeriodeSalaire.objects.select_related('ecole').prefetch_related('etats_salaire')

    # Restriction par école pour les non-admins
    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None
    if restreindre:
        periodes = periodes.filter(ecole=ecole_user)
    
    if ecole_id:
        periodes = periodes.filter(ecole_id=ecole_id)
    
    if annee:
        periodes = periodes.filter(annee=annee)
    
    # Filtre statut ouvert/clôturé
    if statut == 'cloture':
        periodes = periodes.filter(cloturee=True)
    elif statut == 'ouvert':
        periodes = periodes.filter(cloturee=False)
    
    periodes = periodes.order_by('-annee', '-mois')

    # Fallback: si aucun filtre n'est appliqué et aucune période trouvée,
    # charger les 6 dernières périodes disponibles (restreintes à l'école de l'utilisateur si nécessaire)
    filtres_appliques = any([ecole_id, annee, statut])
    if not filtres_appliques and not periodes.exists():
        fallback_base = PeriodeSalaire.objects.select_related('ecole')
        if restreindre:
            fallback_base = fallback_base.filter(ecole=ecole_user)
        fallback_ids = list(
            fallback_base.order_by('-annee', '-mois').values_list('id', flat=True)[:6]
        )
        periodes = (
            PeriodeSalaire.objects
            .select_related('ecole')
            .prefetch_related('etats_salaire')
            .filter(id__in=fallback_ids)
            .order_by('-annee', '-mois')
        )
    
    # Ajout des statistiques pour chaque période
    for periode in periodes:
        periode.etats_valides = periode.etats_salaire.filter(valide=True).count()
        periode.etats_payes = periode.etats_salaire.filter(paye=True).count()
    
    # Pagination
    paginator = Paginator(periodes, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Données pour les filtres
    ecoles = Ecole.objects.all()
    if restreindre and ecole_user:
        ecoles = ecoles.filter(id=ecole_user.id)
    annees_disponibles = PeriodeSalaire.objects.values_list('annee', flat=True).distinct().order_by('-annee')
    
    # Statistiques
    from django.db.models import Count
    # Utiliser une requête de base non-slicée pour les stats globales si besoin
    base_stats_qs = PeriodeSalaire.objects.all()
    if restreindre and ecole_user:
        base_stats_qs = base_stats_qs.filter(ecole=ecole_user)
    if ecole_id:
        base_stats_qs = base_stats_qs.filter(ecole_id=ecole_id)
    if annee:
        base_stats_qs = base_stats_qs.filter(annee=annee)
    if statut == 'cloture':
        base_stats_qs = base_stats_qs.filter(cloturee=True)
    elif statut == 'ouvert':
        base_stats_qs = base_stats_qs.filter(cloturee=False)

    total_etats = EtatSalaire.objects.filter(periode__in=base_stats_qs).count()
    
    stats = {
        'total_periodes': base_stats_qs.count(),
        'periodes_ouvertes': base_stats_qs.filter(cloturee=False).count(),
        'periodes_cloturees': base_stats_qs.filter(cloturee=True).count(),
        'etats_calcules': total_etats,
    }
    
    # Période courante (première ouverte la plus récente) pour styling
    try:
        periode_courante = (
            PeriodeSalaire.objects.filter(cloturee=False, **({'ecole': ecole_user} if restreindre else {}))
            .order_by('-annee', '-mois')
            .first()
        )
    except Exception:
        periode_courante = None

    context = {
        'page_obj': page_obj,
        'periodes': page_obj,
        'ecoles': ecoles,
        'annees_disponibles': annees_disponibles,
        'stats': stats,
        'periode_courante': periode_courante,
        'is_paginated': page_obj.has_other_pages(),
    }
    
    return render(request, 'salaires/gestion_periodes.html', context)


@login_required
def rapport_paiements(request):
    """Rapport des salaires payés: totaux par mois et par année, avec filtres."""
    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None

    annee = request.GET.get('annee', '')
    ecole_id = request.GET.get('ecole', '')

    qs = EtatSalaire.objects.filter(paye=True).select_related('periode', 'periode__ecole')
    if restreindre:
        qs = qs.filter(periode__ecole=ecole_user)
    if annee:
        qs = qs.filter(periode__annee=annee)
    if ecole_id:
        qs = qs.filter(periode__ecole_id=ecole_id)

    # Agrégation par année/mois de la période de salaire
    aggs = (
        qs.values('periode__annee', 'periode__mois')
          .annotate(total_paye=Sum('salaire_net'), nombre=Count('id'))
          .order_by('-periode__annee', '-periode__mois')
    )

    # Totaux globaux
    total_annuel = qs.aggregate(total=Sum('salaire_net'))['total'] or 0

    # Filtres disponibles
    annees_dispo_qs = PeriodeSalaire.objects.all()
    if restreindre:
        annees_dispo_qs = annees_dispo_qs.filter(ecole=ecole_user)
    annees_dispo = (annees_dispo_qs
                    .order_by('-annee')
                    .values_list('annee', flat=True)
                    .distinct())
    ecoles = Ecole.objects.all()
    if restreindre and ecole_user:
        ecoles = ecoles.filter(id=ecole_user.id)

    context = {
        'aggs': aggs,
        'total_annuel': total_annuel,
        'annees_dispo': annees_dispo,
        'ecoles': ecoles,
        'annee_selectionnee': annee,
        'ecole_selectionnee': ecole_id,
    }
    return render(request, 'salaires/rapport_paiements.html', context)


@login_required
def export_rapport_paiements_pdf(request):
    """Export PDF du rapport des salaires payés (paysage)."""
    ecole_user = _ecole_utilisateur(request)
    restreindre = not user_is_admin(request.user) and ecole_user is not None

    annee = request.GET.get('annee', '')
    ecole_id = request.GET.get('ecole', '')

    qs = EtatSalaire.objects.filter(paye=True).select_related('periode', 'periode__ecole')
    if restreindre:
        qs = qs.filter(periode__ecole=ecole_user)
    if annee:
        qs = qs.filter(periode__annee=annee)
    if ecole_id:
        qs = qs.filter(periode__ecole_id=ecole_id)

    aggs = (
        qs.values('periode__annee', 'periode__mois')
          .annotate(total_paye=Sum('salaire_net'), nombre=Count('id'))
          .order_by('periode__annee', 'periode__mois')
    )

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="rapport_paiements.pdf"'

    # Créer un template avec filigrane
    class WatermarkDocTemplate(SimpleDocTemplate):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
        
        def afterPage(self):
            c = self.canv
            try:
                from ecole_moderne.pdf_utils import draw_logo_watermark
                from utilisateurs.utils import user_school
                draw_logo_watermark(c, self.pagesize[0], self.pagesize[1], ecole=user_school(getattr(self, 'request_user', None) or getattr(doc, 'request_user', None) or None))
            except Exception:
                pass
    
    doc = WatermarkDocTemplate(response, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=60, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()
    
    # Ajouter le logo en en-tête
    try:
        from django.contrib.staticfiles import finders
        logo_path = finders.find('logos/logo.png')
        if logo_path:
            from reportlab.platypus import Image
            logo = Image(logo_path, width=60, height=60)
            elements.append(logo)
            elements.append(Spacer(1, 10))
    except Exception:
        pass

    titre = "Rapport des salaires payés"
    if annee:
        titre += f" - {annee}"
    elements.append(Paragraph(titre, styles['Title']))
    elements.append(Spacer(1, 0.5*cm))

    data = [['Année', 'Mois', 'Total payé (GNF)', 'Nombre d\'états payés']]
    for row in aggs:
        data.append([
            row['periode__annee'],
            f"{row['periode__mois']:02d}",
            f"{row['total_paye']:,}".replace(',', ' '),
            row['nombre'],
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(table)

    logo_path = os.path.join(getattr(settings, 'BASE_DIR', ''), 'static', 'logos', 'logo.png')

    def _draw_header_and_watermark(canvas, doc_):
        try:
            if os.path.exists(logo_path):
                canvas.drawImage(logo_path, doc_.leftMargin, doc_.pagesize[1]-40, width=30, height=30, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
        canvas.setFont('Helvetica-Bold', 8)
        canvas.drawString(doc_.leftMargin + 40, doc_.pagesize[1]-25, 'myschool')
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(doc_.pagesize[0]-doc_.rightMargin, doc_.pagesize[1]-25, titre)

        # Filigrane avec logo (comme les autres documents)
        canvas.saveState()
        try:
            if os.path.exists(logo_path):
                # Taille ~150% de la largeur de page
                wm_width = doc_.pagesize[0] * 1.5
                wm_height = wm_width
                wm_x = (doc_.pagesize[0] - wm_width) / 2
                wm_y = (doc_.pagesize[1] - wm_height) / 2
                
                # Opacité visible mais discrète
                try:
                    canvas.setFillAlpha(0.15)
                except Exception:
                    pass
                
                # Rotation pour l'effet filigrane
                canvas.translate(doc_.pagesize[0] / 2.0, doc_.pagesize[1] / 2.0)
                canvas.rotate(30)
                canvas.translate(-doc_.pagesize[0] / 2.0, -doc_.pagesize[1] / 2.0)
                
                canvas.drawImage(logo_path, wm_x, wm_y, width=wm_width, height=wm_height, preserveAspectRatio=True, mask='auto')
            else:
                # Fallback vers texte si logo non trouvé
                canvas.setFont('Helvetica-Bold', 42)
                canvas.setFillGray(0.85)
                canvas.translate(doc_.pagesize[0]/2, doc_.pagesize[1]/2)
                canvas.rotate(30)
                canvas.drawCentredString(0, 0, 'H.K. DIANÉ')
        finally:
            canvas.restoreState()

    doc.build(elements, onFirstPage=_draw_header_and_watermark, onLaterPages=_draw_header_and_watermark)
    return response


@login_required
def creer_periode(request):
    """Création d'une nouvelle période de salaire"""
    if request.method == 'POST':
        try:
            mois = int(request.POST.get('mois'))
            annee = int(request.POST.get('annee'))
            ecole_id = int(request.POST.get('ecole'))
            nombre_semaines = Decimal(request.POST.get('nombre_semaines', '4.33'))
            
            # Validation des données
            if not (1 <= mois <= 12):
                messages.error(request, "Le mois doit être entre 1 et 12.")
                return redirect('salaires:gestion_periodes')
            
            if annee < 2020 or annee > 2030:
                messages.error(request, "L'année doit être entre 2020 et 2030.")
                return redirect('salaires:gestion_periodes')

            if not nombre_semaines.is_finite() or not (
                Decimal('0') < nombre_semaines <= Decimal('6')
            ):
                messages.error(
                    request,
                    "Le nombre de semaines doit être supérieur à 0 et inférieur ou égal à 6.",
                )
                return redirect('salaires:gestion_periodes')
            
            # Récupérer l'école
            from eleves.models import Ecole
            ecole = get_object_or_404(Ecole, id=ecole_id)
            
            # Vérifier que l'utilisateur a le droit de créer une période pour cette école
            ecole_user = _ecole_utilisateur(request)
            if not user_is_admin(request.user) and ecole_user is not None and ecole.id != ecole_user.id:
                messages.error(request, "Vous n'avez pas le droit de créer une période pour cette école.")
                return redirect('salaires:gestion_periodes')
            
            # Vérifier si la période existe déjà
            periode_existante = PeriodeSalaire.objects.filter(
                mois=mois,
                annee=annee,
                ecole=ecole
            ).exists()
            
            if periode_existante:
                messages.error(
                    request, 
                    f"Une période pour {mois}/{annee} existe déjà pour {ecole.nom}."
                )
                return redirect('salaires:gestion_periodes')
            
            # Créer la nouvelle période
            nouvelle_periode = PeriodeSalaire.objects.create(
                mois=mois,
                annee=annee,
                ecole=ecole,
                nombre_semaines=nombre_semaines,
                cree_par=request.user
            )
            
            messages.success(
                request, 
                f"Période {nouvelle_periode} créée avec succès !"
            )
            
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, "Données invalides. Veuillez vérifier les champs.")
        except Exception as e:
            messages.error(request, f"Erreur lors de la création : {str(e)}")
    
    return redirect('salaires:gestion_periodes')


@login_required
def cloturer_periode(request, periode_id):
    """Clôture d'une période de salaire et crée automatiquement la période suivante"""
    if request.method == 'POST':
        try:
            periode = get_object_or_404(PeriodeSalaire, id=periode_id)
            
            # Vérifier que l'utilisateur a le droit de clôturer cette période
            ecole_user = _ecole_utilisateur(request)
            if not user_is_admin(request.user) and ecole_user is not None and periode.ecole_id != ecole_user.id:
                messages.error(request, "Vous n'avez pas le droit de clôturer cette période.")
                return redirect('salaires:gestion_periodes')
            
            # Vérifier que la période n'est pas déjà clôturée
            if periode.cloturee:
                messages.warning(request, f"La période {periode} est déjà clôturée.")
                return redirect('salaires:gestion_periodes')
            
            # Clôturer la période actuelle
            periode.cloturee = True
            periode.date_cloture = timezone.now()
            periode.cloturee_par = request.user
            periode.save()
            
            # Calculer le mois et l'année suivants
            mois_suivant = periode.mois + 1
            annee_suivante = periode.annee
            
            if mois_suivant > 12:
                mois_suivant = 1
                annee_suivante += 1
            
            # Vérifier si la période suivante existe déjà
            periode_suivante_existe = PeriodeSalaire.objects.filter(
                mois=mois_suivant,
                annee=annee_suivante,
                ecole=periode.ecole
            ).exists()
            
            if not periode_suivante_existe:
                # Créer automatiquement la période suivante
                nouvelle_periode = PeriodeSalaire.objects.create(
                    mois=mois_suivant,
                    annee=annee_suivante,
                    ecole=periode.ecole,
                    nombre_semaines=periode.nombre_semaines,  # Reprendre le même nombre de semaines
                    cree_par=request.user
                )
                
                messages.success(
                    request, 
                    f"Période {periode} clôturée avec succès ! "
                    f"Nouvelle période créée automatiquement : {nouvelle_periode}"
                )
            else:
                messages.success(
                    request, 
                    f"Période {periode} clôturée avec succès ! "
                    f"La période suivante existe déjà."
                )
                
        except Exception as e:
            messages.error(request, f"Erreur lors de la clôture : {str(e)}")
    
    return redirect('salaires:gestion_periodes')


@login_required
def changer_statut_enseignant(request, enseignant_id):
    """Changement de statut d'un enseignant"""
    ecole_user = _ecole_utilisateur(request)
    qs = Enseignant.objects.all()
    if not user_is_admin(request.user) and ecole_user is not None:
        qs = qs.filter(ecole=ecole_user)
    enseignant = get_object_or_404(qs, id=enseignant_id)
    
    if request.method == 'POST':
        nouveau_statut = request.POST.get('nouveau_statut')
        
        if nouveau_statut in ['ACTIF', 'CONGE', 'SUSPENDU', 'DEMISSIONNAIRE']:
            ancien_statut = enseignant.get_statut_display()
            enseignant.statut = nouveau_statut
            enseignant.save()
            
            nouveau_statut_display = enseignant.get_statut_display()
            messages.success(
                request, 
                f"Le statut de {enseignant.nom_complet} a été changé de '{ancien_statut}' à '{nouveau_statut_display}' avec succès !"
            )
        else:
            messages.error(request, "Statut invalide.")
    else:
        messages.info(request, "Méthode non autorisée pour cette action.")
    
    return redirect('salaires:liste_enseignants')


@login_required
@can_add_teachers
def ajouter_enseignant(request):
    """Ajouter un nouvel enseignant"""
    if request.method == 'POST':
        form = EnseignantForm(request.POST, user=request.user)
        if form.is_valid():
            enseignant = form.save(commit=False)
            enseignant.cree_par = request.user
            enseignant.save()
            
            messages.success(
                request, 
                f"L'enseignant {enseignant.nom_complet} a été ajouté avec succès !"
            )
            return redirect('salaires:detail_enseignant', enseignant_id=enseignant.id)
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")
    else:
        form = EnseignantForm(user=request.user)
    
    context = {
        'form': form,
        'title': 'Ajouter un Enseignant',
        'submit_text': 'Créer l\'Enseignant',
    }
    
    return render(request, 'salaires/ajouter_enseignant.html', context)


@login_required
def modifier_enseignant(request, enseignant_id):
    """Modifier un enseignant existant"""
    ecole_user = _ecole_utilisateur(request)
    qs = Enseignant.objects.all()
    if not user_is_admin(request.user) and ecole_user is not None:
        qs = qs.filter(ecole=ecole_user)
    enseignant = get_object_or_404(qs, id=enseignant_id)
    
    if request.method == 'POST':
        form = EnseignantForm(request.POST, instance=enseignant, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(
                request, 
                f"L'enseignant {enseignant.nom_complet} a été modifié avec succès !"
            )
            return redirect('salaires:detail_enseignant', enseignant_id=enseignant.id)
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")
    else:
        form = EnseignantForm(instance=enseignant, user=request.user)
    
    context = {
        'form': form,
        'enseignant': enseignant,
        'title': f'Modifier {enseignant.nom_complet}',
        'submit_text': 'Enregistrer les Modifications',
    }
    
    return render(request, 'salaires/ajouter_enseignant.html', context)


@login_required
def supprimer_enseignant(request, enseignant_id):
    """Vue pour supprimer un enseignant avec ses états de salaire (avec code de vérification)"""
    # Filtrer selon les permissions
    qs = Enseignant.objects.all()
    if not user_is_admin(request.user):
        qs = qs.filter(ecole=user_school(request.user))
    
    try:
        enseignant = qs.get(id=enseignant_id)
    except Enseignant.DoesNotExist:
        messages.error(request, f"L'enseignant avec l'ID {enseignant_id} n'existe pas ou a déjà été supprimé.")
        return redirect('salaires:liste_enseignants')
    
    nom_complet = enseignant.nom_complet
    
    # Vérifier la permission de suppression définitive
    peut_supprimer_definitivement = user_is_admin(request.user) or (
        hasattr(request.user, 'profil') and 
        request.user.profil.peut_supprimer_enseignants_definitivement
    )
    
    # Compter les éléments associés
    etats_salaire_count = enseignant.etats_salaire.count()
    affectations_count = enseignant.affectations.count()
    presences_count = enseignant.presences.count()
    
    if request.method == 'POST':
        # Vérifier le code de sécurité
        code_verification = request.POST.get('code_verification', '').strip()
        suppression_definitive = request.POST.get('suppression_definitive') == 'on'
        
        # Pour les admins, toujours activer la suppression définitive par défaut
        if user_is_admin(request.user):
            suppression_definitive = request.POST.get('suppression_definitive') != 'off'
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Admin {request.user.username} - Suppression définitive enseignant: {suppression_definitive}")
        
        from django.conf import settings as django_settings
        expected_code = django_settings.SECURITY_VERIFICATION_CODE
        if not expected_code or code_verification != expected_code:
            messages.error(request, "Code de vérification incorrect. Suppression annulée.")
            return render(request, 'salaires/confirmer_suppression_enseignant.html', {
                'enseignant': enseignant,
                'etats_salaire_count': etats_salaire_count,
                'affectations_count': affectations_count,
                'presences_count': presences_count,
                'peut_supprimer_definitivement': peut_supprimer_definitivement,
                'titre_page': f'Supprimer {nom_complet}'
            })
        
        # Vérifier la permission pour suppression définitive
        if suppression_definitive and not peut_supprimer_definitivement:
            messages.error(request, "Vous n'avez pas la permission de supprimer définitivement un enseignant.")
            return redirect('salaires:detail_enseignant', enseignant_id=enseignant.id)
        
        # Procéder à la suppression avec le code correct
        from django.db import transaction
        try:
            with transaction.atomic():
                if suppression_definitive and peut_supprimer_definitivement:
                    # Suppression définitive pour les utilisateurs autorisés
                    # Collecter les informations avant suppression
                    etats_supprimes = []
                    for etat in enseignant.etats_salaire.all():
                        etats_supprimes.append(f"{etat.periode.nom_periode} - {etat.salaire_net} GNF")
                    
                    affectations_supprimees = []
                    for affectation in enseignant.affectations.all():
                        affectations_supprimees.append(f"{affectation.classe.nom} - {affectation.matiere or 'Toutes matières'}")
                    
                    # Créer l'entrée dans la corbeille avant suppression
                    from administration.models import SystemLog
                    SystemLog.objects.create(
                        action='SUPPRESSION_DEFINITIVE_ENSEIGNANT',
                        description=f"Suppression définitive de l'enseignant {nom_complet} avec {etats_salaire_count} état(s) de salaire, {affectations_count} affectation(s) et {presences_count} présence(s)",
                        user=request.user,
                        ip_address=request.META.get('REMOTE_ADDR', ''),
                        details={
                            'enseignant_id': enseignant.id,
                            'nom_complet': nom_complet,
                            'ecole': enseignant.ecole.nom,
                            'type_enseignant': enseignant.type_enseignant,
                            'salaire_fixe': str(enseignant.salaire_fixe) if enseignant.salaire_fixe else None,
                            'taux_horaire': str(enseignant.taux_horaire) if enseignant.taux_horaire else None,
                            'etats_supprimes': etats_supprimes,
                            'affectations_supprimees': affectations_supprimees,
                            'verification_code_used': True,
                            'user_agent': request.META.get('HTTP_USER_AGENT', '')
                        }
                    )
                    
                    # Supprimer les états de salaire
                    enseignant.etats_salaire.all().delete()
                    
                    # Supprimer les affectations
                    enseignant.affectations.all().delete()
                    
                    # Supprimer les présences
                    enseignant.presences.all().delete()
                    
                    # Supprimer l'enseignant définitivement
                    enseignant.delete()
                    
                    total_elements = etats_salaire_count + affectations_count + presences_count
                    messages.success(request, f"L'enseignant {nom_complet} et tous ses éléments associés ({total_elements} au total) ont été supprimés définitivement et sauvegardés dans la corbeille.")
                else:
                    # Soft delete - changer le statut au lieu de supprimer
                    enseignant.statut = 'DEMISSIONNAIRE'
                    enseignant.save()
                    
                    # Log de l'activité
                    from utilisateurs.models import JournalActivite
                    JournalActivite.objects.create(
                        user=request.user,
                        action='DESACTIVATION',
                        type_objet='ENSEIGNANT',
                        objet_id=enseignant.id,
                        description=f"Désactivation de l'enseignant {nom_complet} (statut → Démissionnaire)",
                        adresse_ip=request.META.get('REMOTE_ADDR', ''),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')
                    )
                    
                    messages.success(request, f"L'enseignant {nom_complet} a été marqué comme démissionnaire (soft delete).")
                    
        except Exception as e:
            messages.error(request, f"Erreur lors de la suppression: {e}")
            return redirect('salaires:detail_enseignant', enseignant_id=enseignant.id)
        
        return redirect('salaires:liste_enseignants')
    
    # Afficher le formulaire de confirmation
    return render(request, 'salaires/confirmer_suppression_enseignant.html', {
        'enseignant': enseignant,
        'etats_salaire_count': etats_salaire_count,
        'affectations_count': affectations_count,
        'presences_count': presences_count,
        'peut_supprimer_definitivement': peut_supprimer_definitivement,
        'titre_page': f'Supprimer {nom_complet}'
    })
