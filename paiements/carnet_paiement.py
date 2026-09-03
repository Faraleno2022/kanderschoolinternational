"""Carnet annuel professionnel des encaissements d'un élève."""

from decimal import Decimal
from functools import partial
from io import BytesIO
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ecole_moderne.security_decorators import require_school_object
from ecole_moderne.theme import get_school_palette
from rapports.utils import _draw_header_and_watermark, _get_logo_path
from utilisateurs.utils import filter_by_user_school

from .models import EcheancierPaiement, Paiement


MOIS_FR = (
    '', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
    'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
)


def _decimal(value):
    return Decimal(str(value or 0))


def _format_montant(value):
    return f"{int(_decimal(value)):,}".replace(',', ' ')


def _construire_donnees_carnet(paiement):
    """Construit l'historique et le reste progressif du contexte du reçu."""
    ecole = paiement.ecole_historique
    classe = paiement.classe_historique
    annee_scolaire = paiement.annee_scolaire or getattr(classe, 'annee_scolaire', '')
    ecole_id = paiement.ecole_encaissement_id or getattr(ecole, 'pk', None)

    paiements = list(
        Paiement.objects.filter(
            eleve_id=paiement.eleve_id,
            statut='VALIDE',
            annee_scolaire=annee_scolaire,
            ecole_encaissement_id=ecole_id,
        )
        .select_related('type_paiement', 'mode_paiement', 'valide_par')
        .prefetch_related('remises')
        .order_by('date_paiement', 'date_creation', 'id')
    )

    echeancier = (
        EcheancierPaiement.objects.filter(
            eleve_id=paiement.eleve_id,
            annee_scolaire=annee_scolaire,
            ecole_reference_id=ecole_id,
        )
        .select_related('classe_reference')
        .first()
    )

    total_encaisse = sum((_decimal(item.montant) for item in paiements), Decimal('0'))
    total_remises = sum(
        (
            sum((_decimal(remise.montant_remise) for remise in item.remises.all()), Decimal('0'))
            for item in paiements
        ),
        Decimal('0'),
    )
    total_du = _decimal(echeancier.total_du if echeancier else 0)
    if not echeancier:
        # Un ancien paiement sans échéancier reste imprimable sans produire un
        # solde négatif ou arbitraire.
        total_du = total_encaisse + total_remises

    couverture = Decimal('0')
    lignes = []
    for item in paiements:
        remise_item = sum(
            (_decimal(remise.montant_remise) for remise in item.remises.all()),
            Decimal('0'),
        )
        couverture += _decimal(item.montant) + remise_item
        lignes.append({
            'mois': MOIS_FR[item.date_paiement.month],
            'date': item.date_paiement,
            'montant': _decimal(item.montant),
            'remise': remise_item,
            'reste': max(Decimal('0'), total_du - couverture),
            'numero_recu': item.numero_recu,
            'valide_par': item.valide_par,
        })

    return {
        'ecole': ecole,
        'classe': classe or getattr(echeancier, 'classe_reference', None),
        'annee_scolaire': annee_scolaire,
        'echeancier': echeancier,
        'paiements': paiements,
        'lignes': lignes,
        'total_du': total_du,
        'total_encaisse': total_encaisse,
        'total_remises': total_remises,
        'reste_final': max(Decimal('0'), total_du - total_encaisse - total_remises),
    }


def _decorer_page(canvas, doc, *, ecole):
    palette = get_school_palette(ecole)
    _draw_header_and_watermark(
        canvas,
        doc,
        ecole=ecole,
        titre_override='CARNET DE PAIEMENT',
    )
    canvas.saveState()
    try:
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor(palette['secondary']))
        canvas.drawRightString(
            A4[0] - 1.2 * cm,
            0.7 * cm,
            f"Page {doc.page} • Édité le {timezone.localtime():%d/%m/%Y à %H:%M}",
        )
    finally:
        canvas.restoreState()


@login_required
@require_school_object(Paiement, pk_kwarg='paiement_id', field_path='ecole_encaissement')
def generer_carnet_paiement_pdf(request, paiement_id):
    paiement_qs = Paiement.objects.select_related(
        'eleve', 'eleve__classe', 'eleve__classe__ecole',
        'ecole_encaissement', 'classe_encaissement',
    )
    paiement_qs = filter_by_user_school(
        paiement_qs, request.user, 'ecole_encaissement'
    )
    paiement = get_object_or_404(paiement_qs, pk=paiement_id)
    if paiement.statut != 'VALIDE':
        messages.warning(
            request,
            "Le carnet de paiement est disponible uniquement après validation du paiement.",
        )
        return redirect('paiements:detail_paiement', paiement_id=paiement.pk)

    return _generer_carnet_paiement_pdf(paiement)


def _generer_carnet_paiement_pdf(paiement):
    """Génère le carnet d'un paiement validé déjà autorisé par l'appelant."""
    donnees = _construire_donnees_carnet(paiement)
    ecole = donnees['ecole']
    palette = get_school_palette(ecole)
    eleve = paiement.eleve
    classe = donnees['classe']

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=2.7 * cm,
        bottomMargin=1.35 * cm,
        title=f"Carnet de paiement - {eleve.nom_complet}",
        author=getattr(ecole, 'nom', '') or 'MySchoolGN',
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CarnetTitle', parent=styles['Title'], fontName='Helvetica-Bold',
        fontSize=18, leading=22, textColor=colors.HexColor(palette['primary']),
        alignment=TA_CENTER, spaceAfter=8,
    )
    label_style = ParagraphStyle(
        'CarnetLabel', parent=styles['Normal'], fontName='Helvetica-Bold',
        fontSize=9, leading=12, textColor=colors.HexColor(palette['secondary']),
    )
    value_style = ParagraphStyle(
        'CarnetValue', parent=styles['Normal'], fontName='Helvetica',
        fontSize=9, leading=12, textColor=colors.HexColor(palette['text']),
    )
    center_style = ParagraphStyle(
        'CarnetCenter', parent=value_style, alignment=TA_CENTER, leading=11,
    )
    amount_style = ParagraphStyle(
        'CarnetAmount', parent=value_style, alignment=TA_RIGHT, leading=11,
    )

    story = [
        Paragraph('CARNET DE PAIEMENT SCOLAIRE', title_style),
        Paragraph(
            "Historique officiel des versements validés et du solde restant.",
            ParagraphStyle(
                'CarnetSubtitle', parent=value_style, alignment=TA_CENTER,
                textColor=colors.HexColor('#475569'), spaceAfter=10,
            ),
        ),
    ]

    logo_path = _get_logo_path(ecole)
    identite = Table(
        [[
            Image(logo_path, width=2.1 * cm, height=1.6 * cm) if logo_path else '',
            [
                Paragraph(f"<b>Élève :</b> {eleve.nom_complet}", value_style),
                Paragraph(f"<b>Matricule :</b> {eleve.matricule}", value_style),
                Paragraph(
                    f"<b>Classe :</b> {getattr(classe, 'nom', 'Non renseignée')}",
                    value_style,
                ),
            ],
            [
                Paragraph(
                    f"<b>Année scolaire :</b> {donnees['annee_scolaire']}",
                    value_style,
                ),
                Paragraph(f"<b>Établissement :</b> {getattr(ecole, 'nom', '')}", value_style),
                Paragraph(f"<b>Nombre de versements :</b> {len(donnees['lignes'])}", value_style),
            ],
        ]],
        colWidths=[2.5 * cm, 7.4 * cm, 7.2 * cm],
    )
    identite.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(palette['light'])),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor(palette['primary'])),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, colors.HexColor(palette['primary_soft'])),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([identite, Spacer(1, 0.35 * cm)])

    resume_header_style = ParagraphStyle(
        'CarnetResumeHeader', parent=label_style, textColor=colors.white,
        alignment=TA_CENTER,
    )
    resume = Table(
        [[
            Paragraph('TOTAL DÛ', resume_header_style),
            Paragraph('ENCAISSÉ', resume_header_style),
            Paragraph('REMISES', resume_header_style),
            Paragraph('RESTE À PAYER', resume_header_style),
        ], [
            Paragraph(f"{_format_montant(donnees['total_du'])} GNF", amount_style),
            Paragraph(f"{_format_montant(donnees['total_encaisse'])} GNF", amount_style),
            Paragraph(f"{_format_montant(donnees['total_remises'])} GNF", amount_style),
            Paragraph(f"{_format_montant(donnees['reste_final'])} GNF", amount_style),
        ]],
        colWidths=[4.25 * cm] * 4,
    )
    resume.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['primary'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor(palette['primary'])),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([resume, Spacer(1, 0.45 * cm)])

    table_data = [[
        Paragraph('MOIS', label_style),
        Paragraph('DATE', label_style),
        Paragraph('MONTANT', label_style),
        Paragraph('RESTE À PAYER', label_style),
        Paragraph('SIGNATURE COMPTABLE', label_style),
    ]]
    for ligne in donnees['lignes']:
        table_data.append([
            Paragraph(ligne['mois'], center_style),
            Paragraph(
                f"{ligne['date']:%d/%m/%Y}<br/><font size='7'>Reçu {ligne['numero_recu']}</font>",
                center_style,
            ),
            Paragraph(f"{_format_montant(ligne['montant'])} GNF", amount_style),
            Paragraph(f"{_format_montant(ligne['reste'])} GNF", amount_style),
            Paragraph("<br/><font size='7' color='#64748b'>Visa / cachet</font>", center_style),
        ])

    historique = Table(
        table_data,
        colWidths=[2.6 * cm, 3.1 * cm, 3.5 * cm, 3.7 * cm, 4.2 * cm],
        repeatRows=1,
        hAlign='CENTER',
    )
    historique.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['primary_soft'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(palette['primary'])),
        ('BOX', (0, 0), (-1, -1), 0.9, colors.HexColor('#64748b')),
        ('INNERGRID', (0, 0), (-1, -1), 0.45, colors.HexColor('#94a3b8')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
    ]))
    story.extend([
        historique,
        Spacer(1, 0.35 * cm),
        Paragraph(
            "Le reste à payer est recalculé après chaque versement validé. "
            "Les remises accordées réduisent le solde mais ne sont pas présentées comme un encaissement.",
            ParagraphStyle(
                'CarnetNote', parent=value_style, fontSize=8, leading=11,
                textColor=colors.HexColor('#475569'), alignment=TA_LEFT,
            ),
        ),
    ])

    page_decorator = partial(_decorer_page, ecole=ecole)
    doc.build(story, onFirstPage=page_decorator, onLaterPages=page_decorator)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    matricule = re.sub(r'[^A-Za-z0-9_-]+', '_', eleve.matricule or str(eleve.pk))
    annee = re.sub(r'[^0-9-]+', '', donnees['annee_scolaire'] or '')
    response['Content-Disposition'] = (
        f'attachment; filename="Carnet_paiement_{matricule}_{annee}.pdf"'
    )
    return response
