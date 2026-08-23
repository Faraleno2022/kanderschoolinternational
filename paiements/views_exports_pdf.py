from collections import OrderedDict
from decimal import Decimal
from functools import partial
from xml.sax.saxutils import escape

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone

from eleves.utils_annee import get_annee_active
from rapports.utils import _draw_header_and_watermark, _get_logo_path
from utilisateurs.utils import filter_by_user_school, user_school

from .models import Paiement


def _paiements_liste_export(request):
    """Reprend les filtres utiles de /paiements/liste/ sans pagination."""
    queryset = (
        Paiement.objects
        .select_related(
            'eleve', 'eleve__classe', 'eleve__classe__ecole',
            'classe_encaissement', 'ecole_encaissement',
            'type_paiement', 'mode_paiement',
        )
        .order_by('ecole_encaissement__nom', '-date_paiement', '-pk')
    )
    queryset = filter_by_user_school(
        queryset, request.user, 'ecole_encaissement',
    )

    recherche = (request.GET.get('q') or '').strip()
    statut = (request.GET.get('statut') or '').strip()
    annee = (
        request.GET.get('annee')
        or request.GET.get('annee_scolaire')
        or ''
    ).strip()
    ecole = user_school(request.user)
    if not annee and ecole:
        annee = get_annee_active(request, ecole) or ''

    if annee:
        queryset = queryset.filter(annee_scolaire=annee)
    if statut:
        queryset = queryset.filter(statut=statut)
    if recherche:
        queryset = queryset.filter(
            Q(numero_recu__icontains=recherche)
            | Q(reference_externe__icontains=recherche)
            | Q(observations__icontains=recherche)
            | Q(eleve__nom__icontains=recherche)
            | Q(eleve__prenom__icontains=recherche)
            | Q(eleve__matricule__icontains=recherche)
            | Q(classe_encaissement__nom__icontains=recherche)
            | Q(ecole_encaissement__nom__icontains=recherche)
            | Q(type_paiement__nom__icontains=recherche)
            | Q(mode_paiement__nom__icontains=recherche)
        )
    return list(queryset), recherche, statut, annee


@login_required
def export_liste_paiements_pdf(request):
    """Exporte la liste filtrée avec le logo de chaque établissement."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    paiements, recherche, statut, annee = _paiements_liste_export(request)
    groupes = OrderedDict()
    for paiement in paiements:
        ecole = paiement.ecole_historique
        groupes.setdefault(ecole.pk, {'ecole': ecole, 'paiements': []})[
            'paiements'
        ].append(paiement)

    ecoles = [groupe['ecole'] for groupe in groupes.values()]
    ecole_entete = ecoles[0] if len(ecoles) == 1 else user_school(request.user)

    response = HttpResponse(content_type='application/pdf')
    suffix = timezone.localdate().isoformat()
    response['Content-Disposition'] = (
        f'attachment; filename="liste_paiements_{suffix}.pdf"'
    )
    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        leftMargin=0.8*cm,
        rightMargin=0.8*cm,
        topMargin=1.75*cm,
        bottomMargin=0.8*cm,
        title='Liste des paiements',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        'ExportCell', parent=styles['Normal'], fontSize=6.6, leading=8,
        textColor=colors.HexColor('#24333D'),
    ))
    styles.add(ParagraphStyle(
        'ExportHeader', parent=styles['ExportCell'], fontName='Helvetica-Bold',
        textColor=colors.white,
    ))
    styles.add(ParagraphStyle(
        'SchoolName', parent=styles['Heading2'], fontName='Helvetica-Bold',
        fontSize=12, leading=14, textColor=colors.HexColor('#174A6E'),
    ))

    def cellule(value, style='ExportCell'):
        return Paragraph(escape(str(value if value is not None else '-')), styles[style])

    elements = [
        Paragraph('LISTE DES PAIEMENTS', styles['Title']),
        Paragraph(
            escape(' | '.join(filter(None, [
                f"Année scolaire : {annee}" if annee else '',
                f"Recherche : {recherche}" if recherche else '',
                f"Statut : {statut}" if statut else '',
                f"Édité le {timezone.localtime():%d/%m/%Y à %H:%M}",
            ]))),
            styles['Normal'],
        ),
        Spacer(1, 0.35*cm),
    ]

    if not groupes:
        elements.append(Paragraph(
            'Aucun paiement ne correspond aux filtres sélectionnés.',
            styles['Heading2'],
        ))

    entetes = [
        'Date', 'N° reçu', 'Élève', 'Matricule', 'Classe', 'Type',
        'Mode', 'Montant', 'Statut', 'Référence',
    ]
    largeurs = [
        1.7*cm, 2.4*cm, 3.4*cm, 2.1*cm, 2.5*cm,
        2.9*cm, 2.5*cm, 2.3*cm, 2.1*cm, 3.0*cm,
    ]

    for groupe_index, groupe in enumerate(groupes.values()):
        if groupe_index:
            elements.append(PageBreak())
        ecole = groupe['ecole']
        logo_path = _get_logo_path(ecole)
        nom_ecole = cellule(ecole.nom, 'SchoolName')
        if logo_path:
            marque = Table(
                [[Image(logo_path, width=2.1*cm, height=1.25*cm), nom_ecole]],
                colWidths=[2.5*cm, 22.5*cm],
                style=TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]),
            )
            elements.append(marque)
        else:
            elements.append(nom_ecole)

        lignes = [[cellule(item, 'ExportHeader') for item in entetes]]
        total = Decimal('0')
        for paiement in groupe['paiements']:
            montant = Decimal(paiement.montant or 0)
            total += montant
            lignes.append([
                cellule(paiement.date_paiement.strftime('%d/%m/%Y')),
                cellule(paiement.numero_recu or '-'),
                cellule(paiement.eleve.nom_complet),
                cellule(paiement.eleve.matricule),
                cellule(getattr(paiement.classe_historique, 'nom', 'Non identifiée')),
                cellule(paiement.type_paiement.nom),
                cellule(paiement.mode_paiement.nom),
                cellule(f"{montant:,.0f}".replace(',', ' ')),
                cellule(paiement.get_statut_display()),
                cellule(paiement.reference_externe or '-'),
            ])
        lignes.append([
            cellule('TOTAL ÉTABLISSEMENT'), '', '', '', '', '', '',
            cellule(f"{total:,.0f}".replace(',', ' ')),
            cellule(f"{len(groupe['paiements'])} paiement(s)"), '',
        ])
        tableau = Table(lignes, colWidths=largeurs, repeatRows=1)
        tableau.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#174A6E')),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#AEBBC4')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [
                colors.white, colors.HexColor('#F3F7FA'),
            ]),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#DCEAF3')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('ALIGN', (7, 1), (7, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.extend([tableau, Spacer(1, 0.25*cm)])

    dessiner_entete = partial(
        _draw_header_and_watermark,
        ecole=ecole_entete,
        titre_override='Liste des paiements',
    )
    doc.build(
        elements,
        onFirstPage=dessiner_entete,
        onLaterPages=dessiner_entete,
    )
    return response
