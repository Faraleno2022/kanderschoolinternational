from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.db.models import Prefetch
from django.utils import timezone
from datetime import date, datetime
from decimal import Decimal
import unicodedata

from eleves.models import Classe, GrilleTarifaire
from eleves.utils_annee import get_annee_active
from paiements.models import Paiement
from utilisateurs.utils import user_is_admin, user_school
from rapports.utils import _draw_header_and_watermark

# ReportLab
# ReportLab: fera l'objet d'un import différé dans la vue PDF


def _annee_vers_dates(annee_scolaire: str):
    try:
        deb, fin = annee_scolaire.split('-')
        an_deb = int(deb)
        an_fin = int(fin)
        return an_deb, an_fin
    except Exception:
        # Fallback année en cours selon rentrée (Septembre)
        today = timezone.now().date()
        y = today.year
        if today.month >= 9:
            return y, y + 1
        return y - 1, y


def _normaliser_type_paiement(value):
    """Normalise un libellé pour reconnaître inscription/réinscription."""
    value = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(
        caractere for caractere in value
        if not unicodedata.combining(caractere)
    ).lower().replace('-', ' ').strip()


def _paiements_valides_de_periode(eleve, annee_scolaire):
    paiements = list(getattr(eleve, '_paiements_valides_export', ()))
    if not annee_scolaire:
        return paiements

    an_deb, an_fin = _annee_vers_dates(annee_scolaire)
    debut = date(an_deb, 9, 1)
    fin = date(an_fin, 8, 31)
    return [
        paiement for paiement in paiements
        if debut <= paiement.date_paiement <= fin
    ]


def _est_reinscription(echeancier, paiements, grille):
    """Détermine la nature du poste d'admission sans le compter deux fois."""
    types = [
        _normaliser_type_paiement(p.type_paiement.nom)
        for p in paiements
        if getattr(p, 'type_paiement_id', None)
    ]
    a_reinscription = any('reinscription' in nom for nom in types)
    a_inscription = any(
        'inscription' in nom and 'reinscription' not in nom
        for nom in types
    )
    if a_reinscription != a_inscription:
        return a_reinscription

    if grille is not None:
        montant_reinscription = Decimal(grille.frais_reinscription or 0)
        montant_admission = Decimal(echeancier.frais_inscription_du or 0)
        if montant_reinscription > 0 and montant_admission == montant_reinscription:
            return True
    return False


def _ventiler_sans_echeancier(paiements, grille):
    """Reconstitue la répartition en reproduisant l'ordre du moteur d'allocation."""
    total_paye = sum((Decimal(p.montant or 0) for p in paiements), Decimal('0'))
    types = [
        _normaliser_type_paiement(p.type_paiement.nom)
        for p in paiements
        if getattr(p, 'type_paiement_id', None)
    ]
    est_reinscription = any('reinscription' in nom for nom in types)

    if grille is None:
        # Sans grille ni échéancier, seul le total encaissé est certain.
        return {
            'inscription': Decimal('0'), 'reinscription': Decimal('0'),
            't1': Decimal('0'), 't2': Decimal('0'), 't3': Decimal('0'),
            'total_du': Decimal('0'), 'total_paye': total_paye,
            'reste': Decimal('0'),
        }

    admission_due = Decimal((
        grille.frais_reinscription if est_reinscription
        else grille.frais_inscription
    ) or 0)
    dus = [
        admission_due,
        Decimal(grille.tranche_1 or 0),
        Decimal(grille.tranche_2 or 0),
        Decimal(grille.tranche_3 or 0),
    ]
    restant = total_paye
    payes = []
    for montant_du in dus:
        affecte = min(max(restant, Decimal('0')), max(montant_du, Decimal('0')))
        payes.append(affecte)
        restant -= affecte

    return {
        'inscription': Decimal('0') if est_reinscription else payes[0],
        'reinscription': payes[0] if est_reinscription else Decimal('0'),
        't1': payes[1], 't2': payes[2], 't3': payes[3],
        'total_du': sum(dus, Decimal('0')),
        'total_paye': total_paye,
        'reste': max(sum(dus, Decimal('0')) - total_paye, Decimal('0')),
    }


def _lignes_classe(classe, annee_scolaire):
    """Retourne les mêmes lignes comptables pour les exports PDF et Excel."""
    grille = GrilleTarifaire.objects.filter(
        ecole=classe.ecole,
        niveau=classe.niveau,
        annee_scolaire=annee_scolaire or classe.annee_scolaire,
    ).first()
    paiements_valides = Paiement.objects.filter(statut='VALIDE').select_related(
        'type_paiement'
    ).order_by('date_paiement', 'id')
    eleves = classe.eleves.select_related('echeancier').prefetch_related(
        Prefetch(
            'paiements', queryset=paiements_valides,
            to_attr='_paiements_valides_export',
        )
    ).order_by('nom', 'prenom')
    if hasattr(eleves.model, 'est_dans_corbeille'):
        eleves = eleves.filter(est_dans_corbeille=False)

    for eleve in eleves:
        paiements = _paiements_valides_de_periode(
            eleve, annee_scolaire or classe.annee_scolaire,
        )
        echeancier = getattr(eleve, 'echeancier', None)
        if echeancier is not None and (
            not annee_scolaire or echeancier.annee_scolaire == annee_scolaire
        ):
            admission_paye = Decimal(echeancier.frais_inscription_paye or 0)
            reinscription = _est_reinscription(
                echeancier, paiements, grille,
            )
            inscription_payee = (
                Decimal('0') if reinscription else admission_paye
            )
            reinscription_payee = (
                admission_paye if reinscription else Decimal('0')
            )
            t1 = Decimal(echeancier.tranche_1_payee or 0)
            t2 = Decimal(echeancier.tranche_2_payee or 0)
            t3 = Decimal(echeancier.tranche_3_payee or 0)
            total_du = Decimal(echeancier.total_du or 0)
            total_paye = admission_paye + t1 + t2 + t3
            valeurs = {
                'inscription': inscription_payee,
                'reinscription': reinscription_payee,
                't1': t1, 't2': t2, 't3': t3,
                'total_du': total_du,
                'total_paye': total_paye,
                'reste': max(total_du - total_paye, Decimal('0')),
            }
        else:
            valeurs = _ventiler_sans_echeancier(paiements, grille)

        valeurs['eleve'] = (
            getattr(eleve, 'nom_complet', None)
            or f"{getattr(eleve, 'prenom', '')} {getattr(eleve, 'nom', '')}".strip()
        )
        yield valeurs


@login_required
def export_tranches_par_classe_pdf(request):
    """Export PDF des tranches par classe avec logo entête et filigrane.

    Filtres GET:
    - ecole: id de l'école
    - classe: id de la classe
    - annee_scolaire: ex '2024-2025'

    Respecte la séparation par école pour les non-admins.
    """
    # Contrôle d'accès: Admin ou Comptable uniquement
    is_admin = user_is_admin(request.user)
    is_comptable = False
    try:
        if hasattr(request.user, 'profil'):
            is_comptable = (getattr(request.user.profil, 'role', None) == 'COMPTABLE')
    except Exception:
        is_comptable = False
    if not (is_admin or is_comptable):
        return HttpResponseForbidden("Accès refusé: vous n'avez pas l'autorisation d'exporter ce rapport.")

    # Lecture et validation des paramètres
    raw_ecole = (request.GET.get('ecole') or '').strip()
    raw_classe = (request.GET.get('classe') or request.GET.get('classe_id') or '').strip()
    annee_scolaire = (request.GET.get('annee_scolaire') or '').strip()

    def parse_int(value):
        try:
            return int(value)
        except Exception:
            return None

    ecole_id = parse_int(raw_ecole) if raw_ecole else None
    classe_id = parse_int(raw_classe) if raw_classe else None

    # Scope classes (filtrées par année active)
    classes = Classe.objects.select_related('ecole').all()
    ecole_user = user_school(request.user)
    annee_active = get_annee_active(request, ecole_user) if ecole_user else None
    restreindre = not user_is_admin(request.user) and ecole_user is not None
    if restreindre:
        classes = classes.filter(ecole=ecole_user)
    elif ecole_id:
        classes = classes.filter(ecole_id=ecole_id)
    if classe_id:
        classes = classes.filter(id=classe_id)
    if annee_active and not annee_scolaire:
        classes = classes.filter(annee_scolaire=annee_active)
    elif annee_scolaire:
        classes = classes.filter(annee_scolaire=annee_scolaire)

    # Anti-abus: limiter le nombre de classes exportées en une requête
    classes = classes.order_by('ecole__nom', 'niveau', 'nom')[:200]

    # Préparer réponse PDF
    response = HttpResponse(content_type='application/pdf')
    suffix = datetime.now().strftime('%Y%m%d')
    response['Content-Disposition'] = f'attachment; filename="tranches_par_classe_{suffix}.pdf"'

    # Import différé de ReportLab pour éviter les erreurs si non installé
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
    except Exception:
        return HttpResponse("ReportLab n'est pas installé. Veuillez exécuter: pip install reportlab", status=500)

    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=20, leftMargin=20, topMargin=60, bottomMargin=30
    )
    elements = []
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=8, leading=9)

    titre = 'Tranches par classe'
    if annee_scolaire:
        titre += f" – Année {annee_scolaire}"
    elements.append(Paragraph(titre, styles['Title']))
    elements.append(Spacer(1, 0.5*cm))

    header = [
        'Élève', 'Inscription payée', 'Réinscription payée',
        'Tranche 1 payée', 'Tranche 2 payée', 'Tranche 3 payée',
        'Total dû', 'Total payé', 'Reste'
    ]

    def P(x):
        return Paragraph(str(x or ''), cell)

    # Parcours des classes
    for classe in classes:
        # Titre de la classe
        titre_classe = f"Classe: {classe.nom} – {getattr(classe.ecole, 'nom', '')}"
        elements.append(Paragraph(titre_classe, styles['Heading2']))
        elements.append(Spacer(1, 0.2*cm))

        data = [header]

        for ligne in _lignes_classe(classe, annee_scolaire):
            data.append([
                P(ligne['eleve']),
                f"{ligne['inscription']:,}".replace(',', ' '),
                f"{ligne['reinscription']:,}".replace(',', ' '),
                f"{ligne['t1']:,}".replace(',', ' '),
                f"{ligne['t2']:,}".replace(',', ' '),
                f"{ligne['t3']:,}".replace(',', ' '),
                f"{ligne['total_du']:,}".replace(',', ' '),
                f"{ligne['total_paye']:,}".replace(',', ' '),
                f"{ligne['reste']:,}".replace(',', ' '),
            ])

        # Construire la table pour la classe
        col_widths = [4.5*cm] + [2.75*cm] * 8
        table = Table(data, repeatRows=1, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.black),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 8),
            ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
            ('ALIGN', (0,0), (0,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 2),
            ('RIGHTPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.6*cm))

    # Construire le document avec en-tête + filigrane logo
    doc.build(elements, onFirstPage=_draw_header_and_watermark, onLaterPages=_draw_header_and_watermark)
    return response

@login_required
def export_tranches_par_classe_excel(request):
    """Export Excel identique au PDF des tranches par classe.

    Filtres GET facultatifs: ecole, classe/classe_id, annee_scolaire.
    Respecte la séparation par école pour non-admin.
    """
    # Contrôle d'accès
    is_admin = user_is_admin(request.user)
    is_comptable = False
    try:
        if hasattr(request.user, 'profil'):
            is_comptable = (getattr(request.user.profil, 'role', None) == 'COMPTABLE')
    except Exception:
        is_comptable = False
    if not (is_admin or is_comptable):
        return HttpResponseForbidden("Accès refusé: vous n'avez pas l'autorisation d'exporter ce rapport.")

    # Import openpyxl
    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
    except Exception:
        return HttpResponse("OpenPyXL n'est pas installé. Veuillez exécuter: pip install openpyxl", status=500)

    raw_ecole = (request.GET.get('ecole') or '').strip()
    raw_classe = (request.GET.get('classe') or request.GET.get('classe_id') or '').strip()
    annee_scolaire = (request.GET.get('annee_scolaire') or '').strip()

    def parse_int(value):
        try:
            return int(value)
        except Exception:
            return None

    ecole_id = parse_int(raw_ecole) if raw_ecole else None
    classe_id = parse_int(raw_classe) if raw_classe else None

    classes = Classe.objects.select_related('ecole').all()
    ecole_user = user_school(request.user)
    annee_active_xl = get_annee_active(request, ecole_user) if ecole_user else None
    restreindre = not user_is_admin(request.user) and ecole_user is not None
    if restreindre:
        classes = classes.filter(ecole=ecole_user)
    elif ecole_id:
        classes = classes.filter(ecole_id=ecole_id)
    if classe_id:
        classes = classes.filter(id=classe_id)
    if annee_active_xl and not annee_scolaire:
        classes = classes.filter(annee_scolaire=annee_active_xl)
    elif annee_scolaire:
        classes = classes.filter(annee_scolaire=annee_scolaire)
    classes = classes.order_by('ecole__nom', 'niveau', 'nom')[:200]

    wb = Workbook()
    ws_index = wb.active
    ws_index.title = 'Index'
    ws_index.append(['Tranches par classe', f"Année: {annee_scolaire}" if annee_scolaire else ''])
    ws_index.append(['Écoles / Classes listées:'])

    headers = [
        'Élève', 'Inscription payée', 'Réinscription payée',
        'Tranche 1 payée', 'Tranche 2 payée', 'Tranche 3 payée',
        'Total dû', 'Total payé', 'Reste',
    ]

    for idx, classe in enumerate(classes, start=1):
        sheet_name = f"{classe.nom[:25]}"  # Limite Excel <=31
        ws = wb.create_sheet(title=sheet_name)
        ws.append([f"Classe: {classe.nom} – {getattr(classe.ecole, 'nom', '')}"])
        ws.append(headers)

        for ligne in _lignes_classe(classe, annee_scolaire):
            ws.append([
                ligne['eleve'],
                int(ligne['inscription']), int(ligne['reinscription']),
                int(ligne['t1']), int(ligne['t2']), int(ligne['t3']),
                int(ligne['total_du']), int(ligne['total_paye']),
                int(ligne['reste']),
            ])

        # Ajuster largeur colonnes simple
        for col in range(1, 10):
            ws.column_dimensions[get_column_letter(col)].width = 22 if col == 1 else 16

        # Index line
        ws_index.append([getattr(classe.ecole, 'nom', ''), classe.nom, sheet_name])

    # Supprimer la feuille par défaut si vide
    if ws_index.max_row == 2:
        ws_index.append(['Aucune classe'])

    from io import BytesIO
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    resp = HttpResponse(stream.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    suffix = datetime.now().strftime('%Y%m%d')
    filename = f'tranches_par_classe_{suffix}.xlsx'
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
