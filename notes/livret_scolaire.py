"""
Livret Scolaire - Generation PDF du parcours complet d'un eleve.
Format officiel guineen : paysage A4, deux niveaux par page GAUCHE/DROITE.

College/Lycee : Matieres | Coef | 1er Sem (Moy Cours | Moy Composition | Moy Semestrielle) | 2eme Sem (idem)
Primaire : Matieres | 1er Trim | 2eme Trim | 3eme Trim | Moy Annuelle | Observations
"""

import io
import re
import logging
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.db.models import Q

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader

from eleves.models import Eleve, Classe, Ecole, HistoriqueEleve
from .models import (
    ClasseNote, MatiereNote, Classement,
    NoteMensuelle, CompositionNote,
    AppreciationMaternelle,
)
from .calculs_moyennes import (
    calculer_classement_classe,
    calculer_moyenne_generale_annuelle,
    calculer_moyenne_periode_guineenne,
    detecter_niveau_scolaire,
)
from utilisateurs.utils import filter_by_user_school, user_school
from ecole_moderne.theme import get_school_palette

logger = logging.getLogger(__name__)

# ==============================================================================
#  CONSTANTES
# ==============================================================================

CYCLE_LABELS = {
    'MATERNELLE': 'Cycle Maternelle',
    'PRIMAIRE':   'Cycle Primaire',
    'COLLEGE':    'Cycle College',
    'LYCEE':      'Cycle Lycee / Terminale',
}


def _s(val):
    """Convertit en string safe."""
    if val is None:
        return ''
    return str(val)


def _fmt(v):
    """Formate une note."""
    if v is None:
        return ''
    try:
        return f'{float(v):.2f}'
    except (ValueError, TypeError):
        return ''


def _get_logo_reader(ecole):
    try:
        if ecole.logo and hasattr(ecole.logo, 'path'):
            return ImageReader(ecole.logo.path)
    except Exception:
        pass
    return None


def _get_image_reader(ecole):
    """Retourne un ImageReader pour la photo de l'ecole."""
    try:
        if ecole.image and hasattr(ecole.image, 'path'):
            return ImageReader(ecole.image.path)
    except Exception:
        pass
    return None


def _appreciation_generale(moy_ann, sur):
    """Retourne l'appreciation generale en fonction de la moyenne annuelle."""
    if moy_ann is None:
        return ''
    seuil = 5.0 if sur == 10 else 10.0
    if sur == 10:
        if moy_ann >= 9:
            return 'Excellent travail. Continuez ainsi !'
        elif moy_ann >= 8:
            return 'Tr\u00e8s bon travail. F\u00e9licitations !'
        elif moy_ann >= 7:
            return 'Bon travail. Encouragements.'
        elif moy_ann >= 6:
            return 'Assez bien. Peut mieux faire.'
        elif moy_ann >= seuil:
            return 'Travail passable. Des efforts sont n\u00e9cessaires.'
        else:
            return 'Travail insuffisant. Redoubler d\'efforts.'
    else:
        if moy_ann >= 18:
            return 'Excellent travail. Continuez ainsi !'
        elif moy_ann >= 16:
            return 'Tr\u00e8s bon travail. F\u00e9licitations !'
        elif moy_ann >= 14:
            return 'Bon travail. Encouragements.'
        elif moy_ann >= 12:
            return 'Assez bien. Peut mieux faire.'
        elif moy_ann >= seuil:
            return 'Travail passable. Des efforts sont n\u00e9cessaires.'
        else:
            return 'Travail insuffisant. Redoubler d\'efforts.'


def _calculer_moyenne_from_matieres(matieres_data, is_semestre, sur):
    """Calcule la moyenne annuelle a partir des donnees matieres si Classement absent."""
    total = 0.0
    count = 0
    for m in matieres_data:
        vals = []
        if is_semestre:
            for k in ['sem1_moyenne', 'sem2_moyenne']:
                v = m.get(k)
                if v is not None:
                    vals.append(float(v))
        else:
            for k in ['t1_moy', 't2_moy', 't3_moy']:
                v = m.get(k)
                if v is not None:
                    vals.append(float(v))
        if vals:
            coef = float(m.get('coef') or 1)
            avg = sum(vals) / len(vals)
            total += avg * coef
            count += coef
    if count > 0:
        return round(total / count, 2)
    return None


def _draw_watermark(c, x, y, w, h, logo, ecole=None):
    """Dessine le logo de l'ecole en filigrane au centre d'une demi-page."""
    if not logo or (ecole is not None and not getattr(ecole, 'afficher_filigrane', True)):
        return
    palette = get_school_palette(ecole)
    try:
        c.saveState()
        wm_size = min(w, h) * 0.45
        wm_x = x + (w - wm_size) / 2
        wm_y = y + (h - wm_size) / 2
        c.setFillAlpha(palette['watermark_opacity'])
        c.drawImage(logo, wm_x, wm_y, wm_size, wm_size,
                    preserveAspectRatio=True, mask='auto')
        c.restoreState()
    except Exception:
        pass


# ==============================================================================
#  DESSIN D'UNE DEMI-PAGE (une colonne gauche ou droite)
# ==============================================================================

def _draw_half_college(c, x, y, w, h, ecole, entry, eleve, page_number):
    """
    Dessine UNE demi-page format College/Lycee (semestre).
    x, y = coin bas-gauche de la zone ; w, h = dimensions.
    Le contenu remplit toute la demi-page : tableau etire + pied ancre en bas.
    """
    # Filigrane logo
    logo_wm = _get_logo_reader(ecole)
    _draw_watermark(c, x, y, w, h, logo_wm, ecole)
    classe_nom = entry['classe_nom']
    annee = entry['annee_scolaire']
    matieres = entry['matieres_data']
    sur = entry['sur']
    moy_ann = entry['moyenne_annuelle']
    rang = entry['rang']
    passe_en = entry['passe_en']

    # Cadre principal
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 4
    lx = x + pad
    rx = x + w - pad
    top = y + h
    cy = top

    # ------------------------------------------------------------------
    # EN-TETE (haut)
    # ------------------------------------------------------------------
    venant_de = entry.get('venant_de', '')
    date_entree = entry.get('date_entree', '')

    cy -= 12
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    if ecole.desee:
        c.drawString(lx, cy, f"DSEE : {_s(ecole.desee)}")
    c.drawRightString(rx, cy, f"Matricule : {_s(eleve.matricule) if eleve.matricule else ''}")

    cy -= 9
    c.drawString(lx, cy, f"Venant de : {_s(venant_de) if venant_de else '........................'}")
    c.drawString(lx + w * 0.50, cy, f"Date d'entr\u00e9e : {date_entree if date_entree else '...............'}")

    cy -= 9
    censeur = _s(ecole.censeur) if ecole.censeur else ''
    if censeur:
        c.drawString(lx, cy, f"Censeur : {censeur}")
    directeur_hdr = _s(ecole.directeur) if ecole.directeur else ''
    if directeur_hdr:
        c.drawString(lx + w * 0.50, cy, f"Directeur : {directeur_hdr}")

    # Ligne separatrice
    cy -= 4
    c.setLineWidth(0.5)
    c.line(x, cy, x + w, cy)

    # Bande classe
    band_h = 14
    cy -= band_h
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['light']))
    c.rect(x, cy, w, band_h, fill=1, stroke=1)
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.black)
    c.drawString(lx + 5, cy + 3, f"Classe : {_s(classe_nom)}")
    c.drawRightString(rx - 5, cy + 3, f"Ann\u00e9e scolaire : {annee}")

    table_top = cy - 2  # Y ou le tableau commence

    # ------------------------------------------------------------------
    # PIED (ancre en BAS du cadre)
    # ------------------------------------------------------------------
    footer_h = 75  # hauteur totale reservee au pied
    page_num_h = 12
    footer_top = y + page_num_h + footer_h

    # Numero de page (tout en bas)
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(x + w / 2, y + 5, f"-{page_number}-")

    # Ligne separatrice appreciations
    sep_y = footer_top
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.black)
    c.line(x, sep_y, x + w, sep_y)

    # Appreciations (gauche) | Aux parents (droite)
    left_w = w * 0.50
    c.setLineWidth(0.3)
    c.line(x + left_w, sep_y, x + left_w, y + page_num_h)

    ay = sep_y - 10
    c.setFont('Helvetica-Bold', 8)
    c.drawString(lx, ay, "Appr\u00e9ciations G\u00e9n\u00e9rales")
    ay -= 10
    c.setFont('Helvetica', 7)
    app_txt = _appreciation_generale(moy_ann, sur)
    c.drawString(lx, ay, app_txt if app_txt else '')
    ay -= 9
    moy_footer = f"Moy: {moy_ann:.2f}/{sur}" if moy_ann else ''
    rang_footer = f" - Rang: {_s(rang)}" if rang else ''
    c.drawString(lx, ay, f"{moy_footer}{rang_footer}")

    rstart_x = x + left_w + pad
    py = sep_y - 10
    c.setFont('Helvetica', 8)
    c.drawString(rstart_x, py, f"\u00c9l\u00e8ve : {_s(eleve.prenom)} {_s(eleve.nom)}")
    py -= 11
    c.setFont('Helvetica', 7)
    dn = eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else ''
    lieu = _s(getattr(eleve, 'lieu_naissance', '') or '')
    c.drawString(rstart_x, py, f"N\u00e9(e) le {dn}  \u00e0 {lieu}")
    py -= 11
    directeur = _s(ecole.directeur) if ecole.directeur else ''
    c.setFont('Helvetica-Bold', 7)
    c.drawString(rstart_x, py, f"Le Directeur : {directeur}")
    py -= 10
    c.setFont('Helvetica', 7)
    c.drawString(rstart_x, py, "Signature :")

    # ------------------------------------------------------------------
    # TABLEAU DES NOTES (hauteur fixe par ligne, colle a l'en-tete)
    # ------------------------------------------------------------------
    header1 = ['Matieres', 'Coef', '1er Sem.', '', '', '2eme Sem.', '', '']
    header2 = ['', '', 'Moy.\nCours', 'Moy.\nCompo', 'Moy.\nSem.',
               'Moy.\nCours', 'Moy.\nCompo', 'Moy.\nSem.']

    col_ratios = [0.22, 0.05, 0.105, 0.105, 0.105, 0.105, 0.105, 0.105]
    col_widths = [w * r for r in col_ratios]
    diff_w = w - sum(col_widths)
    col_widths[0] += diff_w

    data = [header1, header2]
    for m in matieres:
        data.append([
            _s(m['nom']),
            str(m.get('coef', '')),
            _fmt(m.get('sem1_moy')),
            _fmt(m.get('sem1_compo')),
            _fmt(m.get('sem1_moyenne')),
            _fmt(m.get('sem2_moy')),
            _fmt(m.get('sem2_compo')),
            _fmt(m.get('sem2_moyenne')),
        ])

    # Tronquer les noms de matieres trop longs pour eviter le debordement
    for row in data[2:]:
        if row[0] and len(str(row[0])) > 28:
            row[0] = str(row[0])[:26] + '..'

    nb_rows = len(data)
    header1_rh = 16
    header2_rh = 26  # plus haut pour le texte sur 2 lignes
    data_rh = 20

    # Ajuster dynamiquement la hauteur des lignes si le tableau deborde dans le pied
    available_h = table_top - footer_top - 35  # 35pt pour moyenne/stats sous le tableau
    needed_h = header1_rh + header2_rh + data_rh * (nb_rows - 2)
    if needed_h > available_h and nb_rows > 2:
        data_rh = max(11, int((available_h - header1_rh - header2_rh) / (nb_rows - 2)))

    # Adapter la taille de police si les lignes sont petites
    data_fs = 9 if data_rh >= 16 else 8 if data_rh >= 13 else 7

    row_heights = [header1_rh, header2_rh] + [data_rh] * (nb_rows - 2)

    table = Table(data, colWidths=col_widths, rowHeights=row_heights)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTNAME', (0, 2), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, 1), 8),
        ('FONTSIZE', (0, 2), (-1, -1), data_fs),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor(get_school_palette(ecole)['light'])),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 1), (-1, 1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 3),
        ('SPAN', (0, 0), (0, 1)),
        ('SPAN', (1, 0), (1, 1)),
        ('SPAN', (2, 0), (4, 0)),
        ('SPAN', (5, 0), (7, 0)),
    ]))

    table_total_h = sum(row_heights)
    table_y = table_top - table_total_h
    table.wrapOn(c, w, table_total_h + 20)
    table.drawOn(c, x, table_y)

    # ------------------------------------------------------------------
    # MOYENNE ANNUELLE (collee juste sous le tableau, avec garde anti-chevauchement)
    # ------------------------------------------------------------------
    fy = table_y - 10
    if fy > footer_top + 5:
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(colors.black)
        if moy_ann is not None:
            c.drawString(lx, fy, f"Moyenne Annuelle : {moy_ann:.2f}/{sur}")
        else:
            c.drawString(lx, fy, "Moyenne Annuelle : -")

        fy -= 10
        if fy > footer_top + 5:
            c.setFont('Helvetica', 7)
            passe_txt = _s(passe_en) if passe_en else ''
            if passe_txt:
                c.drawString(lx, fy, f"Passe en : {passe_txt}")
            rang_txt2 = _s(rang) if rang else ''
            if rang_txt2:
                c.drawString(lx + w * 0.40, fy, f"Classement : {rang_txt2}")
            eff_entry = entry.get('effectif_classe', 0)
            if eff_entry:
                c.drawRightString(rx, fy, f"Effectif : {eff_entry}")

            # Stats de la classe
            fy -= 10
            if fy > footer_top + 5:
                moy_cl = entry.get('moy_classe')
                note_min_cl = entry.get('note_min_classe')
                note_max_cl = entry.get('note_max_classe')
                c.setFont('Helvetica', 6.5)
                stats_parts = []
                if moy_cl is not None:
                    stats_parts.append(f"Moy. classe: {moy_cl:.2f}/{sur}")
                if note_min_cl is not None:
                    stats_parts.append(f"Min: {note_min_cl:.2f}")
                if note_max_cl is not None:
                    stats_parts.append(f"Max: {note_max_cl:.2f}")
                if stats_parts:
                    c.drawString(lx, fy, "  |  ".join(stats_parts))


def _draw_half_primaire(c, x, y, w, h, ecole, entry, eleve, page_number):
    """
    Dessine UNE demi-page format Primaire (trimestre).
    Le contenu remplit toute la demi-page.
    """
    # Filigrane logo
    logo_wm = _get_logo_reader(ecole)
    _draw_watermark(c, x, y, w, h, logo_wm, ecole)
    classe_nom = entry['classe_nom']
    annee = entry['annee_scolaire']
    matieres = entry['matieres_data']
    sur = entry['sur']
    moy_ann = entry['moyenne_annuelle']
    rang = entry['rang']
    passe_en = entry['passe_en']

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 4
    lx = x + pad
    rx = x + w - pad
    top = y + h
    cy = top

    # EN-TETE
    venant_de = entry.get('venant_de', '')
    date_entree = entry.get('date_entree', '')

    cy -= 12
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    if ecole.desee:
        c.drawString(lx, cy, f"DSEE : {_s(ecole.desee)}")
    c.drawRightString(rx, cy, f"Matricule : {_s(eleve.matricule) if eleve.matricule else ''}")

    cy -= 9
    c.drawString(lx, cy, f"Date d'entr\u00e9e : {date_entree if date_entree else '...............'}")
    c.drawString(lx + w * 0.45, cy, f"Venant de : {_s(venant_de) if venant_de else '...............'}")

    # BANDE CLASSE
    cy -= 4
    c.setLineWidth(0.5)
    c.line(x, cy, x + w, cy)

    band_h = 14
    cy -= band_h
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['light']))
    c.rect(x, cy, w, band_h, fill=1, stroke=1)
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.black)
    c.drawString(lx + 5, cy + 3, f"Classe : {_s(classe_nom)}")
    c.drawRightString(rx - 5, cy + 3, f"Ann\u00e9e scolaire : {annee}")

    # Directeur
    cy -= 12
    c.setFont('Helvetica', 8)
    directeur = _s(ecole.directeur) if ecole.directeur else ''
    c.drawString(lx, cy, f"Directeur : {directeur}")
    cy -= 3

    table_top = cy

    # ------------------------------------------------------------------
    # PIED (ancre en BAS)
    # ------------------------------------------------------------------
    footer_h = 75
    page_num_h = 12
    footer_top = y + page_num_h + footer_h

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(x + w / 2, y + 5, f"-{page_number}-")

    sep_y = footer_top
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.black)
    c.line(x, sep_y, x + w, sep_y)

    # Appreciations (gauche) | Aux parents (droite)
    left_w = w * 0.50
    c.setLineWidth(0.3)
    c.line(x + left_w, sep_y, x + left_w, y + page_num_h)

    ay = sep_y - 10
    c.setFont('Helvetica-Bold', 8)
    c.drawString(lx, ay, "Appr\u00e9ciations G\u00e9n\u00e9rales")
    ay -= 10
    c.setFont('Helvetica', 7)
    app_txt_p = _appreciation_generale(moy_ann, sur)
    c.drawString(lx, ay, app_txt_p if app_txt_p else '')
    ay -= 9
    moy_footer_p = f"Moy: {moy_ann:.2f}/{sur}" if moy_ann else ''
    rang_footer_p = f" - Rang: {_s(rang)}" if rang else ''
    c.drawString(lx, ay, f"{moy_footer_p}{rang_footer_p}")

    rstart_x = x + left_w + pad
    py = sep_y - 10
    c.setFont('Helvetica', 8)
    c.drawString(rstart_x, py, f"\u00c9l\u00e8ve : {_s(eleve.prenom)} {_s(eleve.nom)}")
    py -= 11
    c.setFont('Helvetica', 7)
    dn = eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else ''
    lieu = _s(getattr(eleve, 'lieu_naissance', '') or '')
    c.drawString(rstart_x, py, f"N\u00e9(e) le {dn}  \u00e0 {lieu}")
    py -= 11
    directeur_pied = _s(ecole.directeur) if ecole.directeur else ''
    c.setFont('Helvetica-Bold', 7)
    c.drawString(rstart_x, py, f"Le Directeur : {directeur_pied}")
    py -= 10
    c.setFont('Helvetica', 7)
    c.drawString(rstart_x, py, "Signature :")

    # ------------------------------------------------------------------
    # TABLEAU (hauteur fixe par ligne, colle a l'en-tete)
    # ------------------------------------------------------------------
    header = ['Matieres', '1er\nTrimestre', '2eme\nTrimestre', '3eme\nTrimestre',
              'Moyenne\nAnnuelle', 'Observations']
    col_ratios = [0.26, 0.13, 0.13, 0.13, 0.14, 0.21]
    col_widths = [w * r for r in col_ratios]
    diff_w = w - sum(col_widths)
    col_widths[-1] += diff_w

    data = [header]
    for m in matieres:
        t1 = m.get('t1_moy')
        t2 = m.get('t2_moy')
        t3 = m.get('t3_moy')
        vals = [v for v in [t1, t2, t3] if v is not None]
        m_ann = round(sum(float(v) for v in vals) / len(vals), 2) if vals else None

        seuil = 5.0 if sur == 10 else 10.0
        obs = ''
        if m_ann is not None:
            if sur == 10:
                obs = 'TB' if m_ann >= 8 else 'B' if m_ann >= 7 else 'AB' if m_ann >= 6 else 'P' if m_ann >= seuil else 'I'
            else:
                obs = 'TB' if m_ann >= 16 else 'B' if m_ann >= 14 else 'AB' if m_ann >= 12 else 'P' if m_ann >= seuil else 'I'
        # Tronquer les noms de matieres trop longs
        nom_m = _s(m['nom'])
        if len(nom_m) > 30:
            nom_m = nom_m[:28] + '..'
        data.append([nom_m, _fmt(t1), _fmt(t2), _fmt(t3), _fmt(m_ann), obs])

    nb_rows = len(data)
    header_rh = 20
    data_rh = 20

    # Ajuster dynamiquement la hauteur des lignes si le tableau deborde dans le pied
    available_h = table_top - footer_top - 35  # 35pt pour moyenne/stats sous le tableau
    needed_h = header_rh + data_rh * (nb_rows - 1)
    if needed_h > available_h and nb_rows > 1:
        data_rh = max(11, int((available_h - header_rh) / (nb_rows - 1)))

    data_fs = 9 if data_rh >= 16 else 8 if data_rh >= 13 else 7
    row_heights = [header_rh] + [data_rh] * (nb_rows - 1)

    table = Table(data, colWidths=col_widths, rowHeights=row_heights)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, -1), data_fs),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(get_school_palette(ecole)['light'])),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    table_total_h = sum(row_heights)
    table_y = table_top - table_total_h
    table.wrapOn(c, w, table_total_h + 20)
    table.drawOn(c, x, table_y)

    # ------------------------------------------------------------------
    # MOYENNE ANNUELLE (collee sous le tableau, avec garde anti-chevauchement)
    # ------------------------------------------------------------------
    fy = table_y - 10
    if fy > footer_top + 5:
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(colors.black)
        if moy_ann is not None:
            c.drawString(lx, fy, f"Moyenne Annuelle : {moy_ann:.2f}/{sur}")
        else:
            c.drawString(lx, fy, "Moyenne Annuelle : -")

        fy -= 10
        if fy > footer_top + 5:
            c.setFont('Helvetica', 7)
            passe_txt = _s(passe_en) if passe_en else ''
            if passe_txt:
                c.drawString(lx, fy, f"Passe en : {passe_txt}")
            rang_txt2 = _s(rang) if rang else ''
            if rang_txt2:
                c.drawString(lx + w * 0.40, fy, f"Classement : {rang_txt2}")
            eff_entry = entry.get('effectif_classe', 0)
            if eff_entry:
                c.drawRightString(rx, fy, f"Effectif : {eff_entry}")

            # Stats de la classe
            fy -= 10
            if fy > footer_top + 5:
                moy_cl = entry.get('moy_classe')
                note_min_cl = entry.get('note_min_classe')
                note_max_cl = entry.get('note_max_classe')
                c.setFont('Helvetica', 6.5)
                stats_parts = []
                if moy_cl is not None:
                    stats_parts.append(f"Moy. classe: {moy_cl:.2f}/{sur}")
                if note_min_cl is not None:
                    stats_parts.append(f"Min: {note_min_cl:.2f}")
                if note_max_cl is not None:
                    stats_parts.append(f"Max: {note_max_cl:.2f}")
                if stats_parts:
                    c.drawString(lx, fy, "  |  ".join(stats_parts))


def _draw_half_maternelle(c, x, y, w, h, ecole, entry, eleve, page_number):
    """Demi-page Maternelle avec contenu remplissant la page."""
    # Filigrane logo
    logo_wm = _get_logo_reader(ecole)
    _draw_watermark(c, x, y, w, h, logo_wm, ecole)
    classe_nom = entry['classe_nom']
    annee = entry['annee_scolaire']

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 4
    lx = x + pad
    rx = x + w - pad
    top = y + h
    cy = top

    # En-tete
    venant_de = entry.get('venant_de', '')
    date_entree = entry.get('date_entree', '')

    cy -= 12
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    if ecole.desee:
        c.drawString(lx, cy, f"DSEE : {_s(ecole.desee)}")
    c.drawRightString(rx, cy, f"Matricule : {_s(eleve.matricule) if eleve.matricule else ''}")

    cy -= 9
    c.drawString(lx, cy, f"Date d'entr\u00e9e : {date_entree if date_entree else '...............'}")
    c.drawString(lx + w * 0.45, cy, f"Venant de : {_s(venant_de) if venant_de else '...............'}")

    cy -= 4
    c.setLineWidth(0.5)
    c.line(x, cy, x + w, cy)

    band_h = 14
    cy -= band_h
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['light']))
    c.rect(x, cy, w, band_h, fill=1, stroke=1)
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.black)
    c.drawString(lx + 5, cy + 3, f"Classe : {_s(classe_nom)}")
    c.drawRightString(rx - 5, cy + 3, f"Ann\u00e9e scolaire : {annee}")

    cy -= 14
    c.setFont('Helvetica', 8)
    c.drawString(lx, cy, f"\u00c9l\u00e8ve : {_s(eleve.prenom)} {_s(eleve.nom)}")
    dn = eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else ''
    lieu = _s(getattr(eleve, 'lieu_naissance', '') or '')
    c.drawString(lx + w * 0.45, cy, f"N\u00e9(e) le {dn}  \u00e0 {lieu}")

    # Zone centrale
    cy -= 14
    c.setFont('Helvetica-Oblique', 7)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawString(lx, cy, "\u00c9valuation qualitative : A+ Excellent | A Tr\u00e8s bien | B+ Bien | B Assez bien | B- Moyen | C Passable | D Difficult\u00e9s")

    # Tableau avec vraies matieres et appreciations de la base de donnees
    cy -= 12
    matieres = entry.get('matieres_data', [])
    header = ['Domaines / Mati\u00e8res', '1er Trim.', '2\u00e8me Trim.', '3\u00e8me Trim.', 'Appr\u00e9ciation']
    col_ratios_m = [0.32, 0.14, 0.14, 0.14, 0.26]
    col_widths_m = [w * r for r in col_ratios_m]
    diff_m = w - sum(col_widths_m)
    col_widths_m[-1] += diff_m

    data_m = [header]
    if matieres:
        for m in matieres:
            t1 = m.get('t1_app', '')
            t2 = m.get('t2_app', '')
            t3 = m.get('t3_app', '')
            # Appreciation globale : la plus recente non-vide
            app_globale = t3 or t2 or t1 or ''
            data_m.append([_s(m['nom']), t1, t2, t3, app_globale])
    else:
        # Fallback si aucune matiere configuree : domaines generiques vides
        for d in [
            "Langage / Communication", "Graphisme / \u00c9criture",
            "Math\u00e9matiques / Logique", "D\u00e9couverte du monde",
            "Arts plastiques / Dessin", "\u00c9ducation physique",
            "Socialisation / Autonomie", "Comportement g\u00e9n\u00e9ral",
        ]:
            data_m.append([d, '', '', '', ''])

    # Pied ancre en bas
    footer_h = 75
    page_num_h = 12
    footer_top = y + page_num_h + footer_h

    # Tronquer les noms de matieres trop longs
    for row in data_m[1:]:
        if row[0] and len(str(row[0])) > 30:
            row[0] = str(row[0])[:28] + '..'

    nb_rows_m = len(data_m)
    header_rh_m = 20
    data_rh_m = 20

    # Ajuster dynamiquement la hauteur des lignes si le tableau deborde dans le pied
    available_h_m = cy - footer_top - 5
    needed_h_m = header_rh_m + data_rh_m * (nb_rows_m - 1)
    if needed_h_m > available_h_m and nb_rows_m > 1:
        data_rh_m = max(11, int((available_h_m - header_rh_m) / (nb_rows_m - 1)))

    data_fs_m = 9 if data_rh_m >= 16 else 8 if data_rh_m >= 13 else 7
    row_heights_m = [header_rh_m] + [data_rh_m] * (nb_rows_m - 1)

    table_m = Table(data_m, colWidths=col_widths_m, rowHeights=row_heights_m)
    table_m.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, -1), data_fs_m),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(get_school_palette(ecole)['light'])),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    table_total_h_m = sum(row_heights_m)
    table_y_m = cy - table_total_h_m
    table_m.wrapOn(c, w, table_total_h_m + 20)
    table_m.drawOn(c, x, table_y_m)

    # Pied
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(x + w / 2, y + 5, f"-{page_number}-")

    sep_y = footer_top
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.black)
    c.line(x, sep_y, x + w, sep_y)

    left_w = w * 0.50
    c.setLineWidth(0.3)
    c.line(x + left_w, sep_y, x + left_w, y + page_num_h)

    ay = sep_y - 10
    c.setFont('Helvetica-Bold', 8)
    c.drawString(lx, ay, "Appr\u00e9ciations G\u00e9n\u00e9rales")
    ay -= 10
    c.setFont('Helvetica', 7)
    # Maternelle: pas de moyenne numerique, appreciation basee sur les appreciations collectees
    matieres_mat = entry.get('matieres_data', [])
    nb_apps = 0
    nb_bons = 0
    for m_mat in matieres_mat:
        for tk in ['t1_app', 't2_app', 't3_app']:
            val = m_mat.get(tk, '')
            if val and val != 'Abs.':
                nb_apps += 1
                if val in ('A+', 'A', 'B+', 'B'):
                    nb_bons += 1
    if nb_apps > 0:
        ratio = nb_bons / nb_apps
        if ratio >= 0.8:
            app_mat = 'Excellent travail. Continuez ainsi !'
        elif ratio >= 0.6:
            app_mat = 'Bon travail. Encouragements.'
        elif ratio >= 0.4:
            app_mat = 'Assez bien. Peut mieux faire.'
        else:
            app_mat = 'Des efforts sont n\u00e9cessaires.'
        c.drawString(lx, ay, app_mat)
    ay -= 9
    c.drawString(lx, ay, '')

    rstart_x = x + left_w + pad
    py = sep_y - 10
    c.setFont('Helvetica', 8)
    c.drawString(rstart_x, py, f"\u00c9l\u00e8ve : {_s(eleve.prenom)} {_s(eleve.nom)}")
    py -= 11
    c.setFont('Helvetica', 7)
    dn = eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else ''
    lieu = _s(getattr(eleve, 'lieu_naissance', '') or '')
    c.drawString(rstart_x, py, f"N\u00e9(e) le {dn}  \u00e0 {lieu}")
    py -= 11
    directeur = _s(ecole.directeur) if ecole.directeur else ''
    c.setFont('Helvetica-Bold', 7)
    c.drawString(rstart_x, py, f"Le Directeur : {directeur}")
    py -= 10
    c.setFont('Helvetica', 7)
    c.drawString(rstart_x, py, "Signature :")


def _draw_half_page(c, x, y, w, h, ecole, entry, eleve, page_number):
    """Dispatch vers le bon format selon le niveau."""
    niveau = entry['niveau']
    if niveau == 'MATERNELLE':
        _draw_half_maternelle(c, x, y, w, h, ecole, entry, eleve, page_number)
    elif niveau in ('COLLEGE', 'LYCEE'):
        _draw_half_college(c, x, y, w, h, ecole, entry, eleve, page_number)
    else:
        _draw_half_primaire(c, x, y, w, h, ecole, entry, eleve, page_number)


# ==============================================================================
#  PAGES SPECIALES DU DEPLIANT
# ==============================================================================

def _draw_guinea_flag(c, cx, y_top, flag_w=60, flag_h=40):
    """Dessine le drapeau de la Guinee (3 bandes verticales : rouge, jaune, vert)."""
    stripe_w = flag_w / 3
    fx = cx - flag_w / 2

    # Rouge
    c.setFillColor(colors.HexColor('#CE1126'))
    c.rect(fx, y_top - flag_h, stripe_w, flag_h, fill=1, stroke=0)
    # Jaune
    c.setFillColor(colors.HexColor('#FCD116'))
    c.rect(fx + stripe_w, y_top - flag_h, stripe_w, flag_h, fill=1, stroke=0)
    # Vert
    c.setFillColor(colors.HexColor('#009460'))
    c.rect(fx + 2 * stripe_w, y_top - flag_h, stripe_w, flag_h, fill=1, stroke=0)

    # Bordure fine
    c.setStrokeColor(colors.HexColor('#333333'))
    c.setLineWidth(0.5)
    c.rect(fx, y_top - flag_h, flag_w, flag_h, fill=0, stroke=1)


def _draw_mont_nimba(c, cx, y_top, size=50):
    """Dessine le Mont Nimba (sommet de Guinee) en vectoriel."""
    mw = size * 1.2
    mh = size * 0.85
    base_y = y_top - mh

    # Ciel degrade bleu clair (fond)
    c.setFillColor(colors.HexColor('#D6EAF8'))
    c.rect(cx - mw / 2, base_y, mw, mh, fill=1, stroke=0)

    # Montagne principale (pic central)
    p = c.beginPath()
    p.moveTo(cx - mw / 2, base_y)           # base gauche
    p.lineTo(cx - mw * 0.12, y_top)         # sommet principal
    p.lineTo(cx + mw / 2, base_y)           # base droite
    p.close()
    c.setFillColor(colors.HexColor('#2E7D32'))
    c.drawPath(p, fill=1, stroke=0)

    # Montagne secondaire (gauche, plus petite)
    p2 = c.beginPath()
    p2.moveTo(cx - mw / 2, base_y)
    p2.lineTo(cx - mw * 0.28, y_top - mh * 0.30)
    p2.lineTo(cx - mw * 0.05, base_y)
    p2.close()
    c.setFillColor(colors.HexColor('#388E3C'))
    c.drawPath(p2, fill=1, stroke=0)

    # Montagne secondaire (droite)
    p3 = c.beginPath()
    p3.moveTo(cx + mw * 0.05, base_y)
    p3.lineTo(cx + mw * 0.30, y_top - mh * 0.35)
    p3.lineTo(cx + mw / 2, base_y)
    p3.close()
    c.setFillColor(colors.HexColor('#43A047'))
    c.drawPath(p3, fill=1, stroke=0)

    # Neige / nuage au sommet
    c.setFillColor(colors.HexColor('#E8F5E9'))
    peak_x = cx - mw * 0.12
    peak_y = y_top
    p4 = c.beginPath()
    p4.moveTo(peak_x - mw * 0.08, peak_y - mh * 0.12)
    p4.lineTo(peak_x, peak_y)
    p4.lineTo(peak_x + mw * 0.08, peak_y - mh * 0.12)
    p4.close()
    c.drawPath(p4, fill=1, stroke=0)

    # Soleil
    sun_x = cx + mw * 0.30
    sun_y = y_top - mh * 0.12
    c.setFillColor(colors.HexColor('#FCD116'))
    c.circle(sun_x, sun_y, size * 0.09, fill=1, stroke=0)

    # Bordure
    c.setStrokeColor(colors.HexColor('#333333'))
    c.setLineWidth(0.5)
    c.rect(cx - mw / 2, base_y, mw, mh, fill=0, stroke=1)

    # Texte
    c.setFont('Helvetica-Bold', 4)
    c.setFillColor(colors.HexColor('#333333'))
    c.drawCentredString(cx, base_y - 8, "MONT NIMBA")


def _draw_cover_half(c, x, y, w, h, ecole, eleve, parcours, logo, page_number):
    """Dessine la couverture (page 1) sur une demi-page GAUCHE."""
    c.setStrokeColor(colors.HexColor('#555555'))
    c.setLineWidth(1.5)
    c.rect(x, y, w, h)

    # Fond gris
    c.setFillColor(colors.HexColor('#E8E8E8'))
    c.rect(x + 1, y + 1, w - 2, h - 2, fill=1, stroke=0)

    pad = 10
    cx = x + w / 2
    top = y + h

    # --- IMAGES ALIGNEES : Drapeau (gauche) | Logo (centre) | Photo eleve (droite) ---
    img_row_y = top - 12          # haut de la rangee d'images
    img_h = 42                    # hauteur des images
    img_spacing = w * 0.28        # espacement depuis le centre

    # Drapeau de la Guinee (GAUCHE)
    _draw_guinea_flag(c, cx - img_spacing, img_row_y, flag_w=55, flag_h=img_h)

    # Logo de l'ecole (CENTRE)
    logo_size = img_h + 4
    if logo:
        try:
            c.drawImage(logo, cx - logo_size / 2, img_row_y - logo_size,
                        logo_size, logo_size,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    else:
        # Placeholder si pas de logo
        c.setStrokeColor(colors.HexColor('#999999'))
        c.setDash(2, 2)
        c.rect(cx - logo_size / 2, img_row_y - logo_size, logo_size, logo_size, stroke=1, fill=0)
        c.setDash()
        c.setFont('Helvetica', 5)
        c.setFillColor(colors.HexColor('#999999'))
        c.drawCentredString(cx, img_row_y - logo_size / 2, 'Logo')

    # Photo de l'eleve (DROITE)
    photo_w = img_h * 0.8
    photo_h = img_h
    photo_x = cx + img_spacing - photo_w / 2
    photo_y = img_row_y - photo_h
    photo_drawn = False
    try:
        if eleve.photo and hasattr(eleve.photo, 'path'):
            photo_reader = ImageReader(eleve.photo.path)
            c.drawImage(photo_reader, photo_x, photo_y, photo_w, photo_h,
                        preserveAspectRatio=True, mask='auto')
            photo_drawn = True
    except Exception:
        pass
    if not photo_drawn:
        # Placeholder si pas de photo
        c.setFillColor(colors.HexColor('#F0F0F0'))
        c.setStrokeColor(colors.HexColor('#888888'))
        c.setLineWidth(0.5)
        c.rect(photo_x, photo_y, photo_w, photo_h, fill=1, stroke=1)
        c.setFont('Helvetica', 5)
        c.setFillColor(colors.HexColor('#999999'))
        c.drawCentredString(photo_x + photo_w / 2, photo_y + photo_h / 2, 'Photo')
    # Bordure de la photo
    c.setStrokeColor(colors.HexColor('#555555'))
    c.setLineWidth(0.6)
    c.rect(photo_x, photo_y, photo_w, photo_h, fill=0, stroke=1)

    # Titre sous les images
    title_y = img_row_y - img_h - 18
    c.setFillColor(colors.HexColor('#222222'))
    c.setFont('Helvetica-Bold', 18)
    c.drawCentredString(cx, title_y, "LIVRET SCOLAIRE")

    # Ligne decorative tricolore sous le titre
    line_y = title_y - 6
    c.setStrokeColor(colors.HexColor('#CE1126'))
    c.setLineWidth(1.5)
    c.line(cx - 80, line_y, cx + 80, line_y)
    c.setStrokeColor(colors.HexColor('#FCD116'))
    c.line(cx - 60, line_y - 3, cx + 60, line_y - 3)
    c.setStrokeColor(colors.HexColor('#009460'))
    c.setLineWidth(1.5)
    c.line(cx - 80, line_y - 6, cx + 80, line_y - 6)

    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor('#222222'))
    ty = line_y - 18
    c.drawCentredString(cx, ty, "REPUBLIQUE DE GUINEE")
    ty -= 11
    c.setFont('Helvetica', 8)
    c.drawCentredString(cx, ty, "Ministere de l'Enseignement Pre-Universitaire")
    ty -= 9
    c.drawCentredString(cx, ty, "et de l'Alphabetisation")
    ty -= 10
    c.setFont('Helvetica-Oblique', 8)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, ty, "Travail - Justice - Solidarite")
    ty -= 16

    # Ligne separatrice
    c.setStrokeColor(colors.HexColor('#999999'))
    c.setLineWidth(0.5)
    c.line(x + pad, ty + 5, x + w - pad, ty + 5)

    # Ecole
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor('#222222'))
    c.drawCentredString(cx, ty - 6, _s(ecole.nom))
    ty -= 20

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#333333'))
    for label, val in [
        ("DSEE", ecole.desee), ("Adresse", ecole.adresse),
        ("Tel", ecole.telephone),
    ]:
        if val:
            c.drawCentredString(cx, ty, f"{label}: {_s(val)}")
            ty -= 10
    ty -= 8

    # Cadre eleve (fond blanc avec bordure)
    box_w = w - 2 * pad
    box_h = 105  # augmente pour eviter que le texte touche les bords
    box_x = x + pad
    box_y = ty - box_h
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor('#888888'))
    c.setLineWidth(1)
    c.rect(box_x, box_y, box_w, box_h, fill=1, stroke=1)

    # Bande de titre du cadre eleve
    c.setFillColor(colors.HexColor('#555555'))
    c.rect(box_x, box_y + box_h - 16, box_w, 16, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.white)
    c.drawCentredString(cx, box_y + box_h - 13, "IDENTIFICATION DE L'ELEVE")

    c.setFillColor(colors.HexColor('#222222'))
    # Adapter la taille du nom si trop long
    nom_complet = f"{_s(eleve.nom)} {_s(eleve.prenom)}"
    from reportlab.pdfbase.pdfmetrics import stringWidth
    nom_fs = 13
    while nom_fs > 9 and stringWidth(nom_complet, 'Helvetica-Bold', nom_fs) > box_w - 20:
        nom_fs -= 1
    c.setFont('Helvetica-Bold', nom_fs)
    c.drawCentredString(cx, box_y + box_h - 34, nom_complet)
    c.setFont('Helvetica', 9)
    c.drawCentredString(cx, box_y + box_h - 50, f"Matricule: {eleve.matricule}")
    dn = eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else '-'
    lieu = _s(getattr(eleve, 'lieu_naissance', '') or '')
    c.drawCentredString(cx, box_y + box_h - 64, f"Ne(e) le {dn}  a {lieu}")
    sexe_txt = 'Masculin' if getattr(eleve, 'sexe', '') == 'M' else 'Feminin'
    c.drawCentredString(cx, box_y + box_h - 78, f"Sexe: {sexe_txt}")
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, box_y + box_h - 92,
                        f"Parcours : {len(parcours)} annee(s)")

    # Image de l'ecole (grande, sous le cadre eleve)
    ecole_img = _get_image_reader(ecole)
    if ecole_img:
        img_top = box_y - 8
        img_bottom = y + 20  # juste au-dessus du numero de page
        img_avail_h = img_top - img_bottom
        img_avail_w = w - 2 * pad
        if img_avail_h > 30:
            try:
                c.drawImage(ecole_img, x + pad, img_bottom,
                            img_avail_w, img_avail_h,
                            preserveAspectRatio=True, mask='auto')
                # Bordure
                c.setStrokeColor(colors.HexColor('#888888'))
                c.setLineWidth(0.5)
                c.rect(x + pad, img_bottom, img_avail_w, img_avail_h, fill=0, stroke=1)
            except Exception:
                pass

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, y + 5, f"-{page_number}-")


def _draw_fiche_sante_half(c, x, y, w, h, ecole, eleve, page_number):
    """Dessine la fiche de sante (derniere page du depliant) sur une demi-page DROITE."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 6
    lx = x + pad
    rx = x + w - pad
    cx = x + w / 2
    top = y + h

    # Titre
    cy = top - 15
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, cy, "FICHE DE SANTE DE L'ELEVE")

    cy -= 5
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx, cy, rx, cy)

    # Infos generales
    cy -= 16
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.black)
    c.drawString(lx, cy, f"Nom et Prenom : {_s(eleve.nom)} {_s(eleve.prenom)}")

    cy -= 14
    dn = eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else ''
    c.drawString(lx, cy, f"Date de naissance : {dn}")
    c.drawString(lx + w * 0.5, cy, f"Sexe : {'M' if getattr(eleve, 'sexe', '') == 'M' else 'F'}")

    # Tableau de sante
    cy -= 18
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "Etat de sante general")

    cy -= 5
    fields = [
        ("Groupe sanguin", "............"),
        ("Allergies connues", "............................................"),
        ("Maladies chroniques", "............................................"),
        ("Traitements en cours", "............................................"),
        ("Vaccinations a jour", "Oui ......    Non ......"),
        ("Handicap / Deficience", "............................................"),
        ("Porte des lunettes", "Oui ......    Non ......"),
        ("Observations medicales", "............................................"),
    ]
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    for label, val in fields:
        cy -= 14
        c.setFont('Helvetica-Bold', 8)
        c.drawString(lx, cy, f"{label} :")
        c.setFont('Helvetica', 8)
        c.drawString(lx + w * 0.35, cy, val)

    # Personne a contacter en cas d'urgence
    cy -= 22
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "Personne a contacter en cas d'urgence")

    urgence_fields = [
        ("Nom et Prenom", "............................................"),
        ("Lien de parente", "............................................"),
        ("Telephone", "............................................"),
        ("Adresse", "............................................"),
    ]
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    for label, val in urgence_fields:
        cy -= 14
        c.setFont('Helvetica-Bold', 8)
        c.drawString(lx, cy, f"{label} :")
        c.setFont('Helvetica', 8)
        c.drawString(lx + w * 0.30, cy, val)

    # Tableau suivi annuel
    cy -= 22
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "Suivi medical annuel")

    cy -= 5
    suivi_header = ['Annee', 'Taille', 'Poids', 'Observations', 'Visa Medical']
    suivi_data = [suivi_header]
    for _ in range(4):
        suivi_data.append(['', '', '', '', ''])

    col_w_s = [w * 0.15, w * 0.12, w * 0.12, w * 0.35, w * 0.20]
    diff_s = w - 2 * pad - sum(col_w_s)
    col_w_s[-1] += diff_s
    rh_s = 16
    table_s = Table(suivi_data, colWidths=col_w_s, rowHeights=[rh_s] * len(suivi_data))
    table_s.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(get_school_palette(ecole)['light'])),
    ]))
    th_s = rh_s * len(suivi_data)
    table_s.wrapOn(c, w - 2 * pad, th_s + 10)
    table_s.drawOn(c, lx, cy - th_s)

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, y + 5, f"-{page_number}-")


def _draw_renseignements_parents_half(c, x, y, w, h, ecole, eleve, page_number):
    """Dessine les renseignements des parents (page 2 du depliant)."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 6
    lx = x + pad
    rx = x + w - pad
    cx = x + w / 2
    top = y + h

    # Titre
    cy = top - 15
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, cy, "RENSEIGNEMENTS SUR LES PARENTS")

    cy -= 5
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx, cy, rx, cy)

    # Infos eleve recap
    cy -= 16
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.black)
    c.drawString(lx, cy, f"Eleve : {_s(eleve.nom)} {_s(eleve.prenom)}")
    c.drawString(lx + w * 0.5, cy, f"Matricule : {eleve.matricule}")

    # ------- PERE / Responsable principal -------
    cy -= 22
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "PERE / RESPONSABLE PRINCIPAL")
    cy -= 3
    c.setLineWidth(0.3)
    c.line(lx, cy, rx, cy)

    resp1 = getattr(eleve, 'responsable_principal', None)

    pere_fields = [
        ("Nom et Prenom", f"{_s(resp1.nom)} {_s(resp1.prenom)}" if resp1 else "............................................"),
        ("Lien de parente", _s(resp1.get_relation_display()) if resp1 else "............................................"),
        ("Profession", _s(resp1.profession) if resp1 and resp1.profession else "............................................"),
        ("Telephone", _s(resp1.telephone) if resp1 else "............................................"),
        ("Adresse", _s(resp1.adresse) if resp1 else "............................................"),
        ("Email", _s(resp1.email) if resp1 and resp1.email else "............................................"),
    ]

    # Largeur max disponible pour les valeurs (eviter debordement droit)
    max_val_chars_28 = 45  # pour offset w*0.28
    max_val_chars_35 = 38  # pour offset w*0.35

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    for label, val in pere_fields:
        cy -= 14
        if cy < y + 15:
            break
        c.setFont('Helvetica-Bold', 8)
        c.drawString(lx, cy, f"{label} :")
        c.setFont('Helvetica', 8)
        val_trunc = val[:max_val_chars_28] if len(val) > max_val_chars_28 else val
        c.drawString(lx + w * 0.28, cy, val_trunc)

    # ------- MERE / Responsable secondaire -------
    cy -= 22
    if cy > y + 15:
        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
        c.drawString(lx, cy, "MERE / RESPONSABLE SECONDAIRE")
        cy -= 3
        c.setLineWidth(0.3)
        c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
        c.line(lx, cy, rx, cy)

    resp2 = getattr(eleve, 'responsable_secondaire', None)

    mere_fields = [
        ("Nom et Prenom", f"{_s(resp2.nom)} {_s(resp2.prenom)}" if resp2 else "............................................"),
        ("Lien de parente", _s(resp2.get_relation_display()) if resp2 else "............................................"),
        ("Profession", _s(resp2.profession) if resp2 and resp2.profession else "............................................"),
        ("Telephone", _s(resp2.telephone) if resp2 else "............................................"),
        ("Adresse", _s(resp2.adresse) if resp2 else "............................................"),
    ]

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    for label, val in mere_fields:
        cy -= 14
        if cy < y + 15:
            break
        c.setFont('Helvetica-Bold', 8)
        c.drawString(lx, cy, f"{label} :")
        c.setFont('Helvetica', 8)
        val_trunc = val[:max_val_chars_28] if len(val) > max_val_chars_28 else val
        c.drawString(lx + w * 0.28, cy, val_trunc)

    # ------- SITUATION FAMILIALE -------
    cy -= 22
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "ADRESSE ET SITUATION FAMILIALE")
    cy -= 3
    c.setLineWidth(0.3)
    c.line(lx, cy, rx, cy)

    # Auto-remplir depuis les donnees disponibles
    dots = "............................................"
    # Adresse: prendre celle du responsable principal ou secondaire
    adresse_eleve = ''
    if resp1 and resp1.adresse:
        adresse_eleve = _s(resp1.adresse)
    elif resp2 and resp2.adresse:
        adresse_eleve = _s(resp2.adresse)

    # Vit avec: deduire des responsables existants
    vit_avec = ''
    if resp1 and resp2:
        rel1 = resp1.relation if resp1 else ''
        rel2 = resp2.relation if resp2 else ''
        parts = []
        if rel1 == 'PERE' or rel2 == 'PERE':
            parts.append('P\u00e8re')
        if rel1 == 'MERE' or rel2 == 'MERE':
            parts.append('M\u00e8re')
        if rel1 in ('TUTEUR', 'TUTRICE') or rel2 in ('TUTEUR', 'TUTRICE'):
            parts.append('Tuteur')
        if rel1 in ('GRAND_PERE', 'GRAND_MERE', 'ONCLE', 'TANTE'):
            parts.append(_s(resp1.get_relation_display()))
        if not parts and resp1:
            parts.append(_s(resp1.get_relation_display()))
        vit_avec = ', '.join(parts)
    elif resp1:
        vit_avec = _s(resp1.get_relation_display())

    sit_fields = [
        ("Adresse de l'eleve", adresse_eleve if adresse_eleve else dots),
        ("Quartier / Secteur", dots),
        ("Ville", dots),
        ("Nombre de freres/soeurs", dots),
        ("Rang dans la fratrie", dots),
        ("Vit avec", vit_avec if vit_avec else "P\u00e8re ......  M\u00e8re ......  Tuteur ......"),
        ("Observations", dots),
    ]

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    for label, val in sit_fields:
        cy -= 14
        if cy < y + 15:
            break
        c.setFont('Helvetica-Bold', 8)
        c.drawString(lx, cy, f"{label} :")
        c.setFont('Helvetica', 8)
        val_trunc = val[:max_val_chars_35] if len(val) > max_val_chars_35 else val
        c.drawString(lx + w * 0.35, cy, val_trunc)

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, y + 5, f"-{page_number}-")


# ==============================================================================
#  COLLECTE DES DONNEES DU PARCOURS
# ==============================================================================

def _collecter_parcours_eleve(eleve, ecole):
    """Collecte tout le parcours d'un eleve.

    Decouvre TOUTES les annees scolaires ou l'eleve a des donnees
    (notes mensuelles, compositions, appreciations, classements, historique)
    et genere une entree par annee dans l'ordre chronologique.
    """
    parcours = []
    annees_classes = {}

    # Source 1: Historique des changements de classe
    try:
        historiques = HistoriqueEleve.objects.filter(
            eleve=eleve, action='CHANGEMENT_CLASSE'
        ).order_by('date_action')

        for h in historiques:
            desc = h.description or ''
            match_annee = re.search(r'(\d{4}-\d{4})', desc)
            if match_annee:
                annee = match_annee.group(1)
                match_classe = re.search(r':\s*(.+?)\s*(?:->|\u2192)', desc)
                if match_classe and annee not in annees_classes:
                    parts = annee.split('-')
                    try:
                        prev_annee = f"{int(parts[0])-1}-{int(parts[1])-1}"
                    except Exception:
                        prev_annee = annee
                    annees_classes[prev_annee] = match_classe.group(1).strip()
    except Exception as e:
        logger.warning(f"Erreur lecture historique eleve {eleve.pk}: {e}")

    # Source 2: Classe actuelle
    if eleve.classe:
        annees_classes[eleve.classe.annee_scolaire] = eleve.classe.nom

    # Source 3: Classements (moyenne/rang deja calcules)
    try:
        for cl in Classement.objects.filter(eleve=eleve).order_by('annee_scolaire'):
            if cl.annee_scolaire not in annees_classes:
                annees_classes[cl.annee_scolaire] = cl.classe.nom if cl.classe else '?'
    except Exception as e:
        logger.warning(f"Erreur lecture classements eleve {eleve.pk}: {e}")

    # Source 4: Notes mensuelles (source la plus fiable - notes reelles)
    try:
        for nm in NoteMensuelle.objects.filter(eleve=eleve).values(
            'annee_scolaire', 'matiere__classe__nom'
        ).distinct().order_by('annee_scolaire'):
            annee = nm['annee_scolaire']
            if annee and annee not in annees_classes:
                annees_classes[annee] = nm['matiere__classe__nom'] or '?'
    except Exception as e:
        logger.warning(f"Erreur lecture notes mensuelles eleve {eleve.pk}: {e}")

    # Source 5: Compositions
    try:
        for cn in CompositionNote.objects.filter(eleve=eleve).values(
            'annee_scolaire', 'matiere__classe__nom'
        ).distinct().order_by('annee_scolaire'):
            annee = cn['annee_scolaire']
            if annee and annee not in annees_classes:
                annees_classes[annee] = cn['matiere__classe__nom'] or '?'
    except Exception as e:
        logger.warning(f"Erreur lecture compositions eleve {eleve.pk}: {e}")

    # Source 6: Appreciations maternelle
    try:
        for am in AppreciationMaternelle.objects.filter(eleve=eleve).values(
            'annee_scolaire', 'matiere__classe__nom'
        ).distinct().order_by('annee_scolaire'):
            annee = am['annee_scolaire']
            if annee and annee not in annees_classes:
                annees_classes[annee] = am['matiere__classe__nom'] or '?'
    except Exception as e:
        logger.warning(f"Erreur lecture appreciations maternelle eleve {eleve.pk}: {e}")

    for annee_scolaire in sorted(annees_classes.keys()):
        classe_nom = annees_classes[annee_scolaire]
        niveau = detecter_niveau_scolaire(classe_nom)
        sur = 10 if niveau == 'PRIMAIRE' else 20
        is_semestre = niveau in ('COLLEGE', 'LYCEE')

        # Strategie 1: trouver ClasseNote via les notes reelles de l'eleve
        classe_note = None
        actual_note = NoteMensuelle.objects.filter(
            eleve=eleve, annee_scolaire=annee_scolaire
        ).select_related('matiere__classe').first()
        if actual_note and actual_note.matiere and actual_note.matiere.classe:
            classe_note = actual_note.matiere.classe
        else:
            actual_compo = CompositionNote.objects.filter(
                eleve=eleve, annee_scolaire=annee_scolaire
            ).select_related('matiere__classe').first()
            if actual_compo and actual_compo.matiere and actual_compo.matiere.classe:
                classe_note = actual_compo.matiere.classe

        # Strategie 2: recherche par nom de classe
        if not classe_note:
            search_nom = classe_nom.split('(')[0].strip()[:15]
            classe_note = ClasseNote.objects.filter(
                ecole=ecole, annee_scolaire=annee_scolaire,
                nom__icontains=search_nom
            ).first()

        # Strategie 3: n'importe quelle ClasseNote de cette annee
        if not classe_note:
            classe_note = ClasseNote.objects.filter(
                ecole=ecole, annee_scolaire=annee_scolaire,
            ).first()

        matieres_data = []
        moyenne_annuelle = None
        rang_info = ''
        classement_annuel_courant = None
        result_annuel = None
        passe_en = ''

        if classe_note:
            matieres = MatiereNote.objects.filter(
                classe=classe_note, actif=True
            ).order_by('nom')

            for mat in matieres:
                m_data = {'nom': mat.nom, 'coef': float(mat.coefficient) if mat.coefficient is not None else 1.0}

                # MATERNELLE : appreciations qualitatives (pas de notes numeriques)
                if niveau == 'MATERNELLE':
                    for trim_num, trim_key in [(1, 't1_app'), (2, 't2_app'), (3, 't3_app')]:
                        try:
                            app = AppreciationMaternelle.objects.get(
                                eleve=eleve, matiere=mat,
                                trimestre=f'TRIMESTRE_{trim_num}',
                                annee_scolaire=annee_scolaire
                            )
                            if not app.absent:
                                m_data[trim_key] = app.get_appreciation_display()
                            else:
                                m_data[trim_key] = 'Abs.'
                        except AppreciationMaternelle.DoesNotExist:
                            m_data[trim_key] = ''
                    matieres_data.append(m_data)
                    continue

                if is_semestre:
                    # Memes mois que calculs_moyennes.calculer_moyenne_matiere
                    for sem_num, mois_list, prefix in [
                        (1, ['OCTOBRE', 'NOVEMBRE', 'DECEMBRE', 'JANVIER'], 'sem1'),
                        (2, ['MARS', 'AVRIL', 'MAI'], 'sem2'),
                    ]:
                        notes = NoteMensuelle.objects.filter(
                            eleve=eleve, matiere=mat, annee_scolaire=annee_scolaire,
                            mois__in=mois_list
                        )
                        compo = CompositionNote.objects.filter(
                            eleve=eleve, matiere=mat, annee_scolaire=annee_scolaire,
                            periode=f'SEMESTRE_{sem_num}'
                        ).first()

                        moy = None
                        if notes.exists():
                            vals = [float(n.note) for n in notes if n.note is not None and not n.absent]
                            moy = round(sum(vals) / len(vals), 2) if vals else None

                        compo_val = float(compo.note) if compo and compo.note is not None and not compo.absent else None
                        sem_calc = calculer_moyenne_periode_guineenne(
                            moy,
                            compo_val,
                            'PRIMAIRE' if niveau == 'PRIMAIRE' else 'SECONDAIRE'
                        )
                        sem_moy = round(sem_calc, 2) if sem_calc is not None else None

                        m_data[f'{prefix}_moy'] = moy
                        m_data[f'{prefix}_compo'] = compo_val
                        m_data[f'{prefix}_moyenne'] = sem_moy
                else:
                    for i, (t_label, mois_list) in enumerate([
                        ('t1', ['OCTOBRE', 'NOVEMBRE']),
                        ('t2', ['JANVIER', 'FEVRIER']),
                        ('t3', ['AVRIL', 'MAI']),
                    ], 1):
                        notes_t = NoteMensuelle.objects.filter(
                            eleve=eleve, matiere=mat, annee_scolaire=annee_scolaire,
                            mois__in=mois_list
                        )
                        compo_t = CompositionNote.objects.filter(
                            eleve=eleve, matiere=mat, annee_scolaire=annee_scolaire,
                            periode=f'TRIMESTRE_{i}'
                        ).first()

                        moy_t = None
                        if notes_t.exists():
                            vals = [float(n.note) for n in notes_t if n.note is not None and not n.absent]
                            moy_t = round(sum(vals) / len(vals), 2) if vals else None

                        compo_t_val = float(compo_t.note) if compo_t and compo_t.note is not None and not compo_t.absent else None
                        final_calc = calculer_moyenne_periode_guineenne(
                            moy_t,
                            compo_t_val,
                            'PRIMAIRE' if niveau == 'PRIMAIRE' else 'SECONDAIRE'
                        )
                        final_t = round(final_calc, 2) if final_calc is not None else None

                        m_data[f'{t_label}_moy'] = final_t
                        m_data[f'{t_label}_compo'] = compo_t_val

                matieres_data.append(m_data)

            # Source courante: meme moteur de calcul que les bulletins.
            # Classement est un ancien instantane et ne doit servir que de secours.
            stats_classe = classe_note
            if niveau != 'MATERNELLE':
                system_type_annuel = 'annuel_semestriel' if is_semestre else 'annuel_trimestriel'
                result_annuel = calculer_moyenne_generale_annuelle(eleve, matieres, system_type_annuel)
                if result_annuel.get('moyenne_generale') is not None:
                    moyenne_annuelle = float(result_annuel['moyenne_generale'])
                    try:
                        classe_eleve = Classe.objects.filter(
                            nom=classe_note.nom,
                            ecole=classe_note.ecole,
                            annee_scolaire=annee_scolaire,
                        ).first()
                        eleves_classe = Eleve.objects.filter(classe=classe_eleve, statut='ACTIF') if classe_eleve else Eleve.objects.none()
                        periode_annuelle = 'ANNUEL_SEM' if is_semestre else 'ANNUEL_TRIM'
                        classement_calc = calculer_classement_classe(
                            eleves_classe, matieres, periode_annuelle, system_type_annuel, use_cache=False
                        )
                        classement_annuel_courant = classement_calc
                        rang_num = classement_calc.get('rang_map', {}).get(eleve.id)
                        total = classement_calc.get('total_eleves', 0)
                        if rang_num:
                            rang_info = f"{rang_num}eme/{total}" if total else f"{rang_num}eme"
                    except Exception as e:
                        logger.warning(f"Erreur classement annuel courant: {e}")

            # Trouver la classe reelle utilisee dans Classement pour cet eleve
            # (peut differer de classe_note trouvee par nom__icontains)
            eleve_cls = Classement.objects.filter(
                eleve=eleve, annee_scolaire=annee_scolaire,
            ).first()
            if eleve_cls and moyenne_annuelle is None:
                stats_classe = eleve_cls.classe

            # Moyenne annuelle via Classement
            # Chercher d'abord avec stats_classe, puis sans filtre classe
            cl_ann = Classement.objects.filter(
                eleve=eleve, classe=stats_classe, annee_scolaire=annee_scolaire,
                periode__icontains='ANNUEL'
            ).first()
            if not cl_ann:
                # Fallback: sans filtre classe
                cl_ann = Classement.objects.filter(
                    eleve=eleve, annee_scolaire=annee_scolaire,
                    periode__icontains='ANNUEL'
                ).first()
                if cl_ann:
                    stats_classe = cl_ann.classe

            if moyenne_annuelle is None and cl_ann and cl_ann.moyenne_generale is not None:
                moyenne_annuelle = float(cl_ann.moyenne_generale)
                rang_info = cl_ann.rang_formate or f"{cl_ann.rang}eme/{cl_ann.effectif}"
            elif moyenne_annuelle is None:
                # Fallback: moyenne des periodes depuis Classement
                cls_p = Classement.objects.filter(
                    eleve=eleve, annee_scolaire=annee_scolaire,
                ).exclude(periode__icontains='ANNUEL')
                if cls_p.exists():
                    # Mettre a jour stats_classe si necessaire
                    if not eleve_cls:
                        first_cls = cls_p.first()
                        if first_cls:
                            stats_classe = first_cls.classe
                    moyennes = [float(cp.moyenne_generale) for cp in cls_p if cp.moyenne_generale is not None]
                    if moyennes:
                        moyenne_annuelle = round(sum(moyennes) / len(moyennes), 2)
                    # Prendre le rang du dernier classement disponible
                    last_cl = cls_p.order_by('-periode').first()
                    if last_cl and not rang_info:
                        rang_info = last_cl.rang_formate or (f"{last_cl.rang}eme/{last_cl.effectif}" if last_cl.rang else '')

            # Fallback ultime: calculer depuis les matieres collectees
            if moyenne_annuelle is None and matieres_data and niveau != 'MATERNELLE':
                moyenne_annuelle = _calculer_moyenne_from_matieres(matieres_data, is_semestre, sur)

            # Statistiques de la classe (moyenne, min, max)
            moy_classe = None
            note_min_classe = None
            note_max_classe = None
            effectif_classe = 0
            if classement_annuel_courant:
                moyennes_courantes = [
                    float(moy)
                    for moy in classement_annuel_courant.get('moyennes_par_eleve', {}).values()
                    if moy is not None
                ]
                if moyennes_courantes:
                    moy_classe = round(sum(moyennes_courantes) / len(moyennes_courantes), 2)
                    note_min_classe = round(min(moyennes_courantes), 2)
                    note_max_classe = round(max(moyennes_courantes), 2)
                    effectif_classe = len(moyennes_courantes)
            try:
                from django.db.models import Avg, Min, Max, Count

                def _get_class_stats(cls_filter):
                    """Tente d'obtenir les stats depuis un queryset Classement."""
                    # Essayer ANNUEL d'abord
                    qs = cls_filter.filter(periode__icontains='ANNUEL')
                    if not qs.exists():
                        # Fallback: dernier trimestre/semestre
                        qs = cls_filter.exclude(periode__icontains='ANNUEL')
                        if qs.exists():
                            last_per = qs.order_by('-periode').first().periode
                            qs = qs.filter(periode=last_per)
                    if qs.exists():
                        return qs.aggregate(
                            avg=Avg('moyenne_generale'),
                            mn=Min('moyenne_generale'),
                            mx=Max('moyenne_generale'),
                            cnt=Count('eleve', distinct=True),
                        )
                    return None

                # Strategie 1: via stats_classe (ClasseNote du Classement eleve)
                stats = _get_class_stats(
                    Classement.objects.filter(classe=stats_classe, annee_scolaire=annee_scolaire)
                )

                # Strategie 2: si rien, essayer avec classe_note (ClasseNote trouvee par nom)
                if stats is None and classe_note and classe_note != stats_classe:
                    stats = _get_class_stats(
                        Classement.objects.filter(classe=classe_note, annee_scolaire=annee_scolaire)
                    )

                # Strategie 3: si rien, essayer tous les Classement de cette annee pour l'ecole
                if stats is None:
                    all_classes_ecole = ClasseNote.objects.filter(
                        ecole=ecole, annee_scolaire=annee_scolaire,
                        nom__icontains=classe_nom.split('(')[0].strip()[:10]
                    )
                    if all_classes_ecole.exists():
                        stats = _get_class_stats(
                            Classement.objects.filter(
                                classe__in=all_classes_ecole,
                                annee_scolaire=annee_scolaire
                            )
                        )

                if stats and moy_classe is None:
                    moy_classe = round(float(stats['avg']), 2) if stats['avg'] else None
                    note_min_classe = round(float(stats['mn']), 2) if stats['mn'] else None
                    note_max_classe = round(float(stats['mx']), 2) if stats['mx'] else None
                    effectif_classe = stats['cnt'] or 0

                # Fallback effectif depuis ClasseNote
                if effectif_classe == 0 and classe_note and classe_note.effectif:
                    effectif_classe = classe_note.effectif
            except Exception as e:
                logger.warning(f"Erreur stats classe: {e}")

            # Moyennes par periode pour graphique d'evolution
            moyennes_periodes = []
            if result_annuel:
                for per, moy in result_annuel.get('moyennes_periodes', {}).items():
                    if moy is not None:
                        moyennes_periodes.append({
                            'periode': per,
                            'moyenne': float(moy),
                        })
            try:
                if not moyennes_periodes:
                    cls_periods = Classement.objects.filter(
                        eleve=eleve, classe=stats_classe, annee_scolaire=annee_scolaire,
                    ).exclude(periode__icontains='ANNUEL').order_by('periode')
                    for cp in cls_periods:
                        if cp.moyenne_generale is not None:
                            moyennes_periodes.append({
                                'periode': cp.periode,
                                'moyenne': float(cp.moyenne_generale),
                            })
            except Exception:
                pass

        try:
            from eleves.views_nouvelle_annee import PROGRESSION_CLASSES, PROGRESSION_LABELS, _normaliser
            base_norm = _normaliser(classe_nom.split('(')[0].strip())
            next_base = PROGRESSION_CLASSES.get(base_norm)
            if next_base:
                passe_en = PROGRESSION_LABELS.get(next_base, next_base)
        except Exception:
            pass

        parcours.append({
            'annee_scolaire': annee_scolaire,
            'classe_nom': classe_nom,
            'niveau': niveau,
            'cycle': niveau,
            'sur': sur,
            'is_semestre': is_semestre,
            'matieres_data': matieres_data,
            'moyenne_annuelle': moyenne_annuelle,
            'rang': rang_info,
            'passe_en': passe_en,
            'moy_classe': moy_classe,
            'note_min_classe': note_min_classe,
            'note_max_classe': note_max_classe,
            'effectif_classe': effectif_classe,
            'moyennes_periodes': moyennes_periodes,
        })

    # Enrichir chaque entree avec les infos de provenance
    for i, p in enumerate(parcours):
        if i > 0:
            p['venant_de'] = parcours[i - 1]['classe_nom']
        else:
            p['venant_de'] = ''
        # Date d'entree : date d'inscription de l'eleve
        if eleve.date_inscription:
            p['date_entree'] = eleve.date_inscription.strftime('%d/%m/%Y')
        else:
            p['date_entree'] = ''

    return parcours


# ==============================================================================
#  GENERATION PDF COMPLETE
# ==============================================================================

def _draw_synthese_half(c, x, y_base, w, h, ecole, eleve, parcours, page_number):
    """Dessine la synthese du parcours par cycle sur une demi-page."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y_base, w, h)

    pad = 6
    lx = x + pad
    rx = x + w - pad
    cx = x + w / 2
    top = y_base + h
    usable_w = w - 2 * pad

    # Titre
    cy = top - 15
    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, cy, "SYNTHESE DU PARCOURS SCOLAIRE")

    cy -= 12
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, cy,
                        f"Eleve : {_s(eleve.nom)} {_s(eleve.prenom)}"
                        f"  -  Matricule : {eleve.matricule}")

    # Synthese par cycle
    cycles_data = {}
    for p in parcours:
        cycle = p['cycle']
        if cycle not in cycles_data:
            cycles_data[cycle] = []
        cycles_data[cycle].append(p)

    cy -= 14
    for cycle_key, cycle_entries in cycles_data.items():
        if cy < y_base + 80:
            break
        cycle_label = CYCLE_LABELS.get(cycle_key, cycle_key)
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
        c.drawString(lx, cy, cycle_label)
        cy -= 10

        synth_data = [['Annee', 'Classe', 'Moy. Ann.', 'Classement', 'Obs.']]
        for p in cycle_entries:
            moy_txt = f"{p['moyenne_annuelle']:.2f}/{p['sur']}" if p['moyenne_annuelle'] else '-'
            seuil = 5.0 if p['sur'] == 10 else 10.0
            if p['moyenne_annuelle'] and p['moyenne_annuelle'] >= seuil:
                obs = 'Admis(e)'
            elif p['moyenne_annuelle']:
                obs = 'Non admis(e)'
            else:
                obs = '-'
            synth_data.append([
                p['annee_scolaire'], _s(p['classe_nom']),
                moy_txt, p['rang'] or '-', obs
            ])

        moyennes_cycle = [p['moyenne_annuelle'] for p in cycle_entries if p['moyenne_annuelle']]
        if moyennes_cycle:
            moy_cycle = round(sum(moyennes_cycle) / len(moyennes_cycle), 2)
            sur_cycle = cycle_entries[0]['sur']
            synth_data.append(['', 'MOY. CYCLE', f'{moy_cycle:.2f}/{sur_cycle}', '', ''])

        col_w = [usable_w * 0.16, usable_w * 0.24, usable_w * 0.20,
                 usable_w * 0.20, usable_w * 0.20]
        rh = 13
        table = Table(synth_data, colWidths=col_w, rowHeights=[rh] * len(synth_data))
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 6.5),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#555555')),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(get_school_palette(ecole)['primary'])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8eef5')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ]))
        th = rh * len(synth_data)
        table.wrapOn(c, usable_w, th + 5)
        table.drawOn(c, lx, cy - th)
        cy -= th + 8

    # Graphique evolution (barres simplifiees)
    moyennes_all = [(p['annee_scolaire'], p['moyenne_annuelle'], p['sur'])
                    for p in parcours if p['moyenne_annuelle'] is not None]
    if moyennes_all and cy > y_base + 100:
        cy -= 8
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
        c.drawString(lx, cy, "EVOLUTION DES MOYENNES")
        cy -= 3
        c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
        c.setLineWidth(0.4)
        c.line(lx, cy, rx, cy)

        graph_h = 50
        graph_y = cy - graph_h - 5
        nb = len(moyennes_all)
        bar_gap = 6
        bar_w_each = (usable_w - (nb + 1) * bar_gap) / nb if nb > 0 else 0

        for i, (annee, moy, s) in enumerate(moyennes_all):
            moy_20 = moy * (20.0 / s) if s else moy
            frac = min(moy_20 / 20.0, 1.0)
            bx = lx + bar_gap + i * (bar_w_each + bar_gap)
            bh = graph_h * frac
            s_threshold = 5.0 if s == 10 else 10.0
            color = '#2e7d32' if moy >= s_threshold * 1.3 else '#43a047' if moy >= s_threshold else '#e53935'
            c.setFillColor(colors.HexColor(color))
            c.rect(bx, graph_y, bar_w_each, bh, fill=1, stroke=0)
            c.setFont('Helvetica-Bold', 5.5)
            c.setFillColor(colors.HexColor('#222222'))
            c.drawCentredString(bx + bar_w_each / 2, graph_y + bh + 2, f"{moy:.1f}")
            c.setFont('Helvetica', 5)
            c.setFillColor(colors.HexColor('#555555'))
            # Annee courte: "24-25"
            short_annee = annee[-5:] if len(annee) >= 5 else annee
            c.drawCentredString(bx + bar_w_each / 2, graph_y - 8, short_annee)

        cy = graph_y - 14

    # Signatures
    sig_y = y_base + 25
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(colors.black)
    c.drawString(lx, sig_y, "Le Directeur / Proviseur :")
    c.drawString(cx, sig_y, "Le Censeur :")
    sig_y -= 9
    c.setFont('Helvetica', 7)
    c.drawString(lx, sig_y, f"{_s(ecole.directeur) if ecole.directeur else ''}")
    if ecole.censeur:
        c.drawString(cx, sig_y, f"{_s(ecole.censeur)}")

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, y_base + 3, f"-{page_number}-")


def _draw_orientation_half(c, x, y_base, w, h, ecole, eleve, parcours, page_number):
    """Dessine la page d'orientation universitaire/professionnelle."""
    # Filigrane
    logo_wm = _get_logo_reader(ecole)
    _draw_watermark(c, x, y_base, w, h, logo_wm, ecole)

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y_base, w, h)

    pad = 8
    lx = x + pad
    rx = x + w - pad
    cx = x + w / 2
    top = y_base + h
    usable_w = w - 2 * pad

    # Bordure tricolore en haut
    stripe_h = 3
    third = usable_w / 3
    c.setFillColor(colors.HexColor('#CE1126'))
    c.rect(lx, top - stripe_h, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#FCD116'))
    c.rect(lx + third, top - stripe_h, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#009460'))
    c.rect(lx + 2 * third, top - stripe_h, third, stripe_h, fill=1, stroke=0)

    cy = top - stripe_h - 16

    # Titre
    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, cy, "ANALYSE ET ORIENTATION")
    cy -= 4
    c.setLineWidth(0.6)
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx + 40, cy, rx - 40, cy)

    cy -= 12
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, cy,
                        f"{_s(eleve.prenom)} {_s(eleve.nom)}  -  "
                        f"Matricule : {_s(eleve.matricule)}")

    # Contenu de l'orientation
    cy -= 14
    orientation = _calculer_orientation(parcours)
    # Largeur max en caracteres pour eviter debordement a droite
    max_line_chars = int((rx - lx - 20) / 3.5)  # ~3.5pt par char a font 7

    for line in orientation:
        if cy < y_base + 50:
            break
        # Tronquer les lignes trop longues
        if len(line.strip()) > max_line_chars:
            indent = len(line) - len(line.lstrip())
            line = line[:indent] + line.strip()[:max_line_chars - 2] + '..'

        # Mise en forme selon le contenu
        if line.startswith('BILAN') or line.startswith('POINTS FORTS') \
                or line.startswith('POINTS A') or line.startswith('ORIENTATION'):
            cy -= 3
            c.setFont('Helvetica-Bold', 8)
            c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
            c.drawString(lx, cy, line)
            cy -= 2
            c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
            c.setLineWidth(0.3)
            c.line(lx, cy, lx + 180, cy)
        elif line.startswith('  >>'):
            cy -= 2
            c.setFont('Helvetica-Bold', 8)
            c.setFillColor(colors.HexColor('#2e7d32'))
            c.drawString(lx + 4, cy, line.strip())
        elif line.startswith('  +'):
            c.setFont('Helvetica', 7)
            c.setFillColor(colors.HexColor('#2e7d32'))
            c.drawString(lx + 8, cy, line.strip())
        elif line.startswith('  -') and not line.startswith('  - '):
            c.setFont('Helvetica', 7)
            c.setFillColor(colors.HexColor('#c62828'))
            c.drawString(lx + 8, cy, line.strip())
        elif line.startswith('     Filieres') or line.startswith('     Options'):
            c.setFont('Helvetica-Bold', 7)
            c.setFillColor(colors.HexColor('#333333'))
            c.drawString(lx + 12, cy, line.strip())
        elif line.startswith('       - '):
            c.setFont('Helvetica', 7)
            c.setFillColor(colors.black)
            c.drawString(lx + 18, cy, line.strip())
        elif line.startswith('  Niveau'):
            c.setFont('Helvetica-Bold', 7.5)
            c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
            c.drawString(lx + 8, cy, line.strip())
        elif line.startswith('  Note') or line.startswith('  Attention') or line.startswith('  L\''):
            c.setFont('Helvetica-Oblique', 7)
            c.setFillColor(colors.HexColor('#555555'))
            c.drawString(lx + 8, cy, line.strip())
        elif line == '':
            cy -= 2
            continue
        else:
            c.setFont('Helvetica', 7)
            c.setFillColor(colors.black)
            c.drawString(lx + 8, cy, line.strip())

        cy -= 8

    # Signatures
    sig_y = y_base + 35
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(colors.black)
    directeur = _s(ecole.directeur) if ecole.directeur else ''
    c.drawString(lx, sig_y, "Le Directeur :")
    c.drawString(cx, sig_y, "Signature parent :")
    sig_y -= 9
    c.setFont('Helvetica', 7)
    c.drawString(lx, sig_y, directeur)
    sig_y -= 9
    c.drawString(lx, sig_y, "Signature et cachet :")

    # Bordure tricolore en bas
    c.setFillColor(colors.HexColor('#CE1126'))
    c.rect(lx, y_base + 15, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#FCD116'))
    c.rect(lx + third, y_base + 15, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#009460'))
    c.rect(lx + 2 * third, y_base + 15, third, stripe_h, fill=1, stroke=0)

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, y_base + 3, f"-{page_number}-")


def _draw_lettre_remerciement_half(c, x, y, w, h, ecole, eleve, parcours, page_number):
    """Dessine la lettre de remerciement aux parents avec recommandations sur une demi-page."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 10
    lx = x + pad
    rx = x + w - pad
    cx = x + w / 2
    top = y + h
    usable_w = w - 2 * pad

    # --- Bordure decorative tricolore en haut ---
    stripe_h = 3
    third = usable_w / 3
    c.setFillColor(colors.HexColor('#CE1126'))
    c.rect(lx, top - stripe_h, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#FCD116'))
    c.rect(lx + third, top - stripe_h, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#009460'))
    c.rect(lx + 2 * third, top - stripe_h, third, stripe_h, fill=1, stroke=0)

    cy = top - stripe_h - 18

    # --- Titre ---
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, cy, "LETTRE DE REMERCIEMENT AUX PARENTS")
    cy -= 4
    c.setLineWidth(0.8)
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx + 30, cy, rx - 30, cy)

    # --- Entete ecole ---
    cy -= 14
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, cy, f"{_s(ecole.nom)}  -  {_s(ecole.adresse)}")
    if ecole.telephone:
        cy -= 10
        c.drawCentredString(cx, cy, f"Tel: {ecole.telephone}")

    # --- Salutation ---
    cy -= 18
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)

    resp = getattr(eleve, 'responsable_principal', None)
    if resp:
        nom_parent = f"{_s(resp.prenom)} {_s(resp.nom)}"
        relation = resp.get_relation_display() if hasattr(resp, 'get_relation_display') else ''
        c.drawString(lx, cy, f"Cher(e) {relation} {nom_parent},")
    else:
        c.drawString(lx, cy, "Chers Parents / Tuteurs,")

    # --- Corps de la lettre ---
    cy -= 16
    c.setFont('Helvetica', 7.5)
    line_h = 10

    # Determiner annee et classe
    derniere = parcours[-1] if parcours else {}
    annee = derniere.get('annee_scolaire', '')
    classe_nom = derniere.get('classe_nom', '')
    moy = derniere.get('moyenne_annuelle')
    sur = derniere.get('sur', 20)
    directeur = _s(ecole.directeur) if ecole.directeur else "La Direction"

    paragraphes = [
        f"Au terme de l'ann\u00e9e scolaire {annee}, nous tenons \u00e0 vous exprimer nos sinc\u00e8res",
        f"remerciements pour la confiance que vous avez plac\u00e9e en notre \u00e9tablissement,",
        f"{_s(ecole.nom)}, pour l'\u00e9ducation et la formation de votre enfant",
        f"{_s(eleve.prenom)} {_s(eleve.nom)}.",
        "",
        f"Votre implication dans le suivi scolaire de votre enfant, en classe de {_s(classe_nom)},",
        f"a \u00e9t\u00e9 un facteur d\u00e9terminant dans son parcours cette ann\u00e9e. Nous sommes convaincus",
        f"que la r\u00e9ussite scolaire est le fruit d'une collaboration \u00e9troite entre l'\u00e9cole",
        f"et la famille.",
    ]

    if moy is not None:
        seuil = 5.0 if sur == 10 else 10.0
        if moy >= seuil * 1.5:
            paragraphes.append("")
            paragraphes.append(f"Avec une moyenne de {moy:.2f}/{sur}, votre enfant a r\u00e9alis\u00e9 une excellente")
            paragraphes.append(f"performance. Nous vous f\u00e9licitons et encourageons \u00e0 maintenir cet \u00e9lan.")
        elif moy >= seuil:
            paragraphes.append("")
            paragraphes.append(f"Avec une moyenne de {moy:.2f}/{sur}, votre enfant a fourni des efforts")
            paragraphes.append(f"appr\u00e9ciables. Nous l'encourageons \u00e0 pers\u00e9v\u00e9rer pour de meilleurs r\u00e9sultats.")
        else:
            paragraphes.append("")
            paragraphes.append(f"Avec une moyenne de {moy:.2f}/{sur}, des efforts suppl\u00e9mentaires sont")
            paragraphes.append(f"n\u00e9cessaires. Nous comptons sur votre soutien pour aider votre enfant \u00e0 progresser.")

    for line in paragraphes:
        c.drawString(lx, cy, line)
        cy -= line_h

    # --- Section Recommandations ---
    cy -= 6
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "RECOMMANDATIONS POUR LE PROGR\u00c8S SCOLAIRE :")
    cy -= 3
    c.setLineWidth(0.4)
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx, cy, lx + 200, cy)

    cy -= 12
    c.setFont('Helvetica', 7.5)
    c.setFillColor(colors.black)

    recommandations = [
        ("1.", "Suivi r\u00e9gulier des devoirs et le\u00e7ons \u00e0 la maison. V\u00e9rifiez chaque jour"),
        ("",   "   les cahiers et encouragez l'enfant \u00e0 r\u00e9viser ses cours."),
        ("2.", "Communication avec les enseignants. N'h\u00e9sitez pas \u00e0 prendre rendez-vous"),
        ("",   "   pour discuter des progr\u00e8s et difficult\u00e9s de votre enfant."),
        ("3.", "Encouragement de la lecture. Offrez des livres et cr\u00e9ez un environnement"),
        ("",   "   propice \u00e0 la lecture quotidienne, m\u00eame pendant les vacances."),
        ("4.", "Ponctualit\u00e9 et assiduit\u00e9. Assurez-vous que votre enfant arrive \u00e0 l'heure"),
        ("",   "   et ne manque aucune journ\u00e9e de cours sans raison valable."),
        ("5.", "Soutien \u00e9motionnel et motivation. F\u00e9licitez les efforts, pas seulement"),
        ("",   "   les notes. Chaque progr\u00e8s, m\u00eame petit, m\u00e9rite d'\u00eatre c\u00e9l\u00e9br\u00e9."),
        ("6.", "Limitation du temps d'\u00e9cran. Privil\u00e9giez les activit\u00e9s \u00e9ducatives et"),
        ("",   "   sportives en dehors des heures de cours."),
        ("7.", "Participation aux r\u00e9unions de parents d'\u00e9l\u00e8ves. Votre pr\u00e9sence t\u00e9moigne"),
        ("",   "   de votre engagement dans la vie scolaire de votre enfant."),
    ]

    for num, texte in recommandations:
        if num:
            c.setFont('Helvetica-Bold', 7.5)
            c.drawString(lx, cy, num)
        c.setFont('Helvetica', 7.5)
        c.drawString(lx + 14, cy, texte)
        cy -= line_h

    # --- Conclusion ---
    cy -= 8
    c.setFont('Helvetica', 7.5)
    c.setFillColor(colors.black)
    conclusions = [
        f"Ensemble, continuons \u00e0 oeuvrer pour l'\u00e9panouissement et la r\u00e9ussite de nos enfants.",
        f"Nous vous renouvelons notre gratitude et restons \u00e0 votre enti\u00e8re disposition.",
        "",
        f"Avec nos salutations les plus respectueuses,",
    ]
    for line in conclusions:
        c.drawString(lx, cy, line)
        cy -= line_h

    # --- Signature ---
    cy -= 8
    c.setFont('Helvetica-Bold', 8)
    c.drawRightString(rx, cy, f"{directeur}")
    cy -= 10
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawRightString(rx, cy, f"Directeur de {_s(ecole.nom)}")

    # --- Bordure decorative tricolore en bas ---
    c.setFillColor(colors.HexColor('#CE1126'))
    c.rect(lx, y + 15, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#FCD116'))
    c.rect(lx + third, y + 15, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#009460'))
    c.rect(lx + 2 * third, y + 15, third, stripe_h, fill=1, stroke=0)

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, y + 5, f"-{page_number}-")


# ==============================================================================
#  FICHE D'ORIENTATION FIN DE COLLEGE (choix de serie au lycee)
# ==============================================================================

# Matieres cles pour chaque serie du lycee guineen
_SERIES_LYCEE = {
    'MATH': {
        'label': 'Sciences Math\u00e9matiques',
        'code': 'Math',
        'couleur': '#1565c0',
        'matieres_cles': [
            'math', 'algebre', 'geometrie', 'arithmetique', 'statistique',
            'physique', 'chimie', 'sciences physiques',
        ],
        'matieres_secondaires': [
            'biologie', 'svt', 'informatique', 'technologie',
        ],
        'debouches': [
            "Ing\u00e9nierie (civil, m\u00e9canique, \u00e9lectrique)",
            "Informatique / Intelligence artificielle",
            "M\u00e9decine / Pharmacie (voie scientifique)",
            "Architecture / Urbanisme",
            "Recherche en sciences exactes",
            "Ecoles militaires / Polytechnique",
        ],
    },
    'SE': {
        'label': 'Sciences Exp\u00e9rimentales',
        'code': 'SE',
        'couleur': '#2e7d32',
        'matieres_cles': [
            'biologie', 'svt', 'sciences naturelles', 'sciences de la vie',
            'chimie', 'physique', 'sciences physiques',
        ],
        'matieres_secondaires': [
            'math', 'algebre', 'ecologie', 'botanique', 'zoologie',
        ],
        'debouches': [
            "M\u00e9decine / Chirurgie / Dentaire",
            "Pharmacie / Biochimie",
            "Sage-femme / Infirmerie",
            "Agronomie / V\u00e9t\u00e9rinaire",
            "Biologie / Environnement",
            "Laboratoire / Recherche biom\u00e9dicale",
        ],
    },
    'SS': {
        'label': 'Sciences Sociales',
        'code': 'SS',
        'couleur': '#c62828',
        'matieres_cles': [
            'histoire', 'geographie', 'education civique', 'instruction civique',
            'philosophie', 'francais', 'redaction', 'dictee',
            'litterature', 'expression',
        ],
        'matieres_secondaires': [
            'anglais', 'arabe', 'espagnol', 'economie', 'sociologie', 'droit',
        ],
        'debouches': [
            "Droit / Sciences juridiques",
            "Sciences politiques / Diplomatie",
            "Economie / Gestion / Finance",
            "Journalisme / Communication",
            "Enseignement (ENS / Professorat)",
            "Administration publique / Douane",
        ],
    },
}


def _normaliser_nom_matiere(nom):
    """Normalise le nom d'une matiere pour la comparaison."""
    return nom.lower().replace('\u00e9', 'e').replace('\u00e8', 'e') \
        .replace('\u00ea', 'e').replace('\u00e0', 'a').replace('\u00e7', 'c') \
        .replace('\u00ee', 'i').replace('\u00f4', 'o').replace('\u00fb', 'u') \
        .replace('\u00e2', 'a').replace('\u00f9', 'u')


def _calculer_score_serie(matieres_globales, serie_config, poids_recent=1.5):
    """Calcule le score d'adequation d'un eleve pour une serie.

    matieres_globales: dict { nom_matiere_normalise: [(moy, sur, annee_index)] }
    serie_config: config d'une serie depuis _SERIES_LYCEE
    poids_recent: multiplicateur pour les annees recentes
    """
    score_total = 0.0
    nb_matieres = 0
    details = []  # (nom_original, moyenne_ponderee_sur20)

    for nom_orig, notes_list in matieres_globales.items():
        nom_norm = _normaliser_nom_matiere(nom_orig)
        is_cle = any(mot in nom_norm for mot in serie_config['matieres_cles'])
        is_secondaire = any(mot in nom_norm for mot in serie_config['matieres_secondaires'])

        if not is_cle and not is_secondaire:
            continue

        # Ponderer les notes (annees recentes comptent plus)
        total_pond = 0.0
        total_poids = 0.0
        for moy, sur, annee_idx in notes_list:
            moy_20 = moy * (20.0 / sur) if sur else moy
            # Plus l'annee est recente (index eleve), plus le poids est fort
            poids = 1.0 + (annee_idx * 0.3)
            total_pond += moy_20 * poids
            total_poids += poids

        if total_poids > 0:
            avg_pond = total_pond / total_poids
            coef = 3.0 if is_cle else 1.0
            score_total += avg_pond * coef
            nb_matieres += coef
            details.append((nom_orig, round(avg_pond, 2)))

    score_final = round(score_total / nb_matieres, 2) if nb_matieres > 0 else 0.0
    details.sort(key=lambda x: x[1], reverse=True)
    return score_final, details


def _draw_fiche_orientation_lycee_half(c, x, y, w, h, ecole, eleve, parcours, page_number):
    """Fiche d'orientation fin de college - choix de serie pour le lycee.

    Analyse toutes les notes de la maternelle a la 10eme pour determiner
    si l'eleve doit s'orienter vers Math, Sciences Experimentales ou
    Sciences Sociales.
    """
    logo_wm = _get_logo_reader(ecole)
    _draw_watermark(c, x, y, w, h, logo_wm, ecole)

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 8
    lx = x + pad
    rx = x + w - pad
    cx = x + w / 2
    top = y + h
    usable_w = w - 2 * pad

    # Bordure tricolore en haut
    stripe_h = 4
    third = usable_w / 3
    c.setFillColor(colors.HexColor('#CE1126'))
    c.rect(lx, top - stripe_h, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#FCD116'))
    c.rect(lx + third, top - stripe_h, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#009460'))
    c.rect(lx + 2 * third, top - stripe_h, third, stripe_h, fill=1, stroke=0)

    cy = top - stripe_h - 14

    # === TITRE ===
    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, cy, "FICHE D'ORIENTATION - FIN DE CYCLE COLLEGE")
    cy -= 4
    c.setLineWidth(0.6)
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx + 20, cy, rx - 20, cy)

    cy -= 11
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, cy,
                        f"R\u00e9publique de Guin\u00e9e - Minist\u00e8re de l'Education Nationale")
    cy -= 9
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, cy, f"{_s(ecole.nom)}")

    # === IDENTIFICATION ===
    cy -= 14
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "IDENTIFICATION DE L'ELEVE")
    cy -= 3
    c.setLineWidth(0.3)
    c.line(lx, cy, rx, cy)

    cy -= 11
    c.setFont('Helvetica', 7.5)
    c.setFillColor(colors.black)
    c.drawString(lx, cy, f"Nom et Pr\u00e9nom : {_s(eleve.prenom)} {_s(eleve.nom)}")
    c.drawString(lx + usable_w * 0.55, cy, f"Matricule : {_s(eleve.matricule)}")
    cy -= 10
    dn = eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else ''
    lieu = _s(getattr(eleve, 'lieu_naissance', '') or '')
    c.drawString(lx, cy, f"N\u00e9(e) le : {dn}")
    c.drawString(lx + usable_w * 0.35, cy, f"\u00e0 : {lieu}")
    # Derniere classe college
    derniere_college = None
    for p in reversed(parcours):
        if p['niveau'] in ('COLLEGE', 'LYCEE'):
            derniere_college = p
            break
    if derniere_college:
        cy -= 10
        c.drawString(lx, cy, f"Derni\u00e8re classe : {_s(derniere_college['classe_nom'])}")
        c.drawString(lx + usable_w * 0.55, cy,
                     f"Ann\u00e9e : {derniere_college['annee_scolaire']}")

    # === COLLECTE DES MATIERES SUR TOUT LE PARCOURS ===
    matieres_globales = {}  # nom -> [(moy, sur, annee_index)]
    for annee_idx, p in enumerate(parcours):
        p_sur = p.get('sur', 20)
        for m in p.get('matieres_data', []):
            nom = _s(m.get('nom', ''))
            if not nom:
                continue
            vals = []
            for key in ['sem1_moyenne', 'sem2_moyenne', 't1_moy', 't2_moy', 't3_moy']:
                v = m.get(key)
                if v is not None:
                    try:
                        vals.append(float(v))
                    except (ValueError, TypeError):
                        pass
            if vals:
                avg = sum(vals) / len(vals)
                matieres_globales.setdefault(nom, []).append((avg, p_sur, annee_idx))

    # === CALCUL DES SCORES PAR SERIE ===
    resultats = {}
    for serie_code, config in _SERIES_LYCEE.items():
        score, details = _calculer_score_serie(matieres_globales, config)
        resultats[serie_code] = {'score': score, 'details': details, 'config': config}

    # Trier par score decroissant
    series_triees = sorted(resultats.items(), key=lambda x: x[1]['score'], reverse=True)
    serie_recommandee = series_triees[0][0] if series_triees and series_triees[0][1]['score'] > 0 else None

    # === TABLEAU COMPARATIF DES 3 SERIES ===
    cy -= 16
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "ANALYSE COMPARATIVE DES TROIS SERIES")
    cy -= 3
    c.setLineWidth(0.3)
    c.line(lx, cy, rx, cy)
    cy -= 5

    # Barres horizontales comparatives
    bar_max_w = usable_w * 0.45
    bar_h_each = 16
    label_w = usable_w * 0.30
    score_w = usable_w * 0.15

    max_score = max((r['score'] for r in resultats.values()), default=1) or 1

    for serie_code, data in series_triees:
        config = data['config']
        score = data['score']
        frac = min(score / 20.0, 1.0)  # sur 20

        # Label
        c.setFont('Helvetica-Bold', 7.5)
        color = config['couleur']
        is_best = (serie_code == serie_recommandee)
        if is_best:
            # Fond surbrillance pour la serie recommandee
            c.setFillColor(colors.HexColor('#f0f7ff'))
            c.rect(lx - 2, cy - bar_h_each + 2, usable_w + 4, bar_h_each + 2, fill=1, stroke=0)

        c.setFillColor(colors.HexColor(color))
        # Reduire la police si le label est trop long pour label_w
        lbl_text = config['label']
        lbl_fs = 7.5
        from reportlab.pdfbase.pdfmetrics import stringWidth as _sw
        if _sw(lbl_text, 'Helvetica-Bold', lbl_fs) > label_w - 5:
            lbl_fs = 6.5
        c.setFont('Helvetica-Bold', lbl_fs)
        c.drawString(lx, cy - 3, lbl_text)
        if is_best:
            c.setFont('Helvetica-Bold', 5.5)
            c.setFillColor(colors.HexColor('#2e7d32'))
            c.drawString(lx, cy - 3 - lbl_fs, "RECOMMANDE")

        # Barre
        bar_x = lx + label_w + 5
        bar_y = cy - bar_h_each + 5
        # Fond gris
        c.setFillColor(colors.HexColor('#e0e0e0'))
        c.rect(bar_x, bar_y, bar_max_w, bar_h_each - 6, fill=1, stroke=0)
        # Barre coloree
        c.setFillColor(colors.HexColor(color))
        c.rect(bar_x, bar_y, bar_max_w * frac, bar_h_each - 6, fill=1, stroke=0)

        # Score
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(colors.black)
        c.drawString(bar_x + bar_max_w + 5, cy - 5, f"{score:.1f}/20")

        cy -= bar_h_each + 2

    # === DETAIL DES MATIERES PAR SERIE ===
    cy -= 8
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "DETAIL PAR SERIE (moyennes ponderees sur tout le parcours)")
    cy -= 3
    c.setLineWidth(0.3)
    c.line(lx, cy, rx, cy)
    cy -= 5

    # Afficher les details des 3 series cote a cote
    col_w_each = usable_w / 3
    for idx, (serie_code, data) in enumerate(series_triees):
        config = data['config']
        details = data['details']
        col_x = lx + idx * col_w_each

        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(colors.HexColor(config['couleur']))
        c.drawString(col_x + 2, cy, f"{config['code']}")

        detail_y = cy - 10
        c.setFont('Helvetica', 6.5)
        c.setFillColor(colors.black)
        for nom, avg in details[:6]:
            if detail_y < y + 160:
                break
            # Tronquer le nom si trop long
            nom_court = nom[:18] + '..' if len(nom) > 20 else nom
            c.drawString(col_x + 2, detail_y, f"{nom_court}: {avg:.1f}")
            detail_y -= 8

    cy = cy - 10 - min(6, max(len(d['details']) for d in resultats.values())) * 8 - 5

    # === RECOMMANDATION OFFICIELLE ===
    cy -= 6
    if cy < y + 130:
        cy = y + 130

    # Cadre recommandation
    rec_h = 55
    c.setFillColor(colors.HexColor('#f5f9ff'))
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.setLineWidth(1)
    c.rect(lx, cy - rec_h, usable_w, rec_h, fill=1, stroke=1)

    rec_y = cy - 10
    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, rec_y, "SERIE RECOMMANDEE")
    rec_y -= 13

    if serie_recommandee:
        config_rec = _SERIES_LYCEE[serie_recommandee]
        c.setFont('Helvetica-Bold', 11)
        c.setFillColor(colors.HexColor(config_rec['couleur']))
        c.drawCentredString(cx, rec_y, f"{config_rec['label']} ({config_rec['code']})")
        rec_y -= 11
        score_rec = resultats[serie_recommandee]['score']
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.HexColor('#555555'))
        c.drawCentredString(cx, rec_y,
                            f"Score d'ad\u00e9quation : {score_rec:.1f}/20")
        rec_y -= 10
        # Deuxieme choix
        if len(series_triees) > 1:
            alt = series_triees[1]
            c.drawCentredString(cx, rec_y,
                                f"Alternative : {alt[1]['config']['label']} "
                                f"({alt[1]['score']:.1f}/20)")
    else:
        c.setFont('Helvetica', 8)
        c.setFillColor(colors.HexColor('#666666'))
        c.drawCentredString(cx, rec_y, "Donn\u00e9es insuffisantes pour une recommandation.")

    cy -= rec_h + 8

    # === DEBOUCHES DE LA SERIE RECOMMANDEE ===
    if serie_recommandee and cy > y + 80:
        c.setFont('Helvetica-Bold', 7.5)
        c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
        c.drawString(lx, cy, f"DEBOUCHES - {_SERIES_LYCEE[serie_recommandee]['label'].upper()}")
        cy -= 3
        c.setLineWidth(0.3)
        c.line(lx, cy, lx + 200, cy)
        cy -= 10

        c.setFont('Helvetica', 7)
        c.setFillColor(colors.black)
        for deb in _SERIES_LYCEE[serie_recommandee]['debouches']:
            if cy < y + 55:
                break
            c.drawString(lx + 6, cy, f"\u2022 {deb}")
            cy -= 9

    # === SIGNATURES ===
    sig_y = y + 38
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(colors.black)
    col1 = lx
    col2 = lx + usable_w * 0.33
    col3 = lx + usable_w * 0.66

    c.drawString(col1, sig_y, "Le Directeur :")
    c.drawString(col2, sig_y, "Le Censeur :")
    c.drawString(col3, sig_y, "Le Parent :")
    sig_y -= 9
    c.setFont('Helvetica', 7)
    directeur = _s(ecole.directeur) if ecole.directeur else ''
    censeur = _s(ecole.censeur) if ecole.censeur else ''
    c.drawString(col1, sig_y, directeur)
    c.drawString(col2, sig_y, censeur)

    # Bordure tricolore en bas
    c.setFillColor(colors.HexColor('#CE1126'))
    c.rect(lx, y + 15, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#FCD116'))
    c.rect(lx + third, y + 15, third, stripe_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#009460'))
    c.rect(lx + 2 * third, y + 15, third, stripe_h, fill=1, stroke=0)

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(cx, y + 5, f"-{page_number}-")


def _eleve_a_termine_college(parcours):
    """Verifie si l'eleve a au moins une annee de college dans son parcours."""
    for p in parcours:
        if p.get('niveau') in ('COLLEGE', 'LYCEE'):
            return True
    return False


def _draw_blank_half(c, x, y, w, h, page_number):
    """Dessine une demi-page vide (remplissage pour multiple de 4)."""
    c.setStrokeColor(colors.HexColor('#cccccc'))
    c.setDash(3, 3)
    c.rect(x, y, w, h)
    c.setDash()
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#999999'))
    c.drawCentredString(x + w / 2, y + 5, f"-{page_number}-")


def _draw_analyse_annuelle_half(c, x, y, w, h, ecole, eleve, entry, page_number):
    """Dessine la page d'analyse du niveau de l'eleve pour une annee."""
    logo_wm = _get_logo_reader(ecole)
    _draw_watermark(c, x, y, w, h, logo_wm, ecole)

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)

    pad = 6
    lx = x + pad
    rx = x + w - pad
    cx = x + w / 2
    top = y + h
    usable_w = w - 2 * pad

    sur = entry.get('sur', 20)
    seuil = 5.0 if sur == 10 else 10.0
    moy_ann = entry.get('moyenne_annuelle')
    moy_classe = entry.get('moy_classe')
    note_min = entry.get('note_min_classe')
    note_max = entry.get('note_max_classe')
    effectif = entry.get('effectif_classe', 0)
    rang = entry.get('rang', '')
    matieres = entry.get('matieres_data', [])
    is_sem = entry.get('is_semestre', False)
    moyennes_periodes = entry.get('moyennes_periodes', [])

    # === TITRE ===
    cy = top - 14
    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawCentredString(cx, cy, "ANALYSE DU NIVEAU DE L'ELEVE")
    cy -= 10
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, cy,
                        f"{_s(eleve.nom)} {_s(eleve.prenom)}  -  "
                        f"Classe: {_s(entry['classe_nom'])}  -  {entry['annee_scolaire']}")

    # === SECTION 1 : STATISTIQUES GENERALES ===
    cy -= 14
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "STATISTIQUES GENERALES")
    cy -= 3
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx, cy, rx, cy)

    cy -= 12
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    col1 = lx
    col2 = lx + usable_w * 0.5

    moy_txt = f"{moy_ann:.2f}/{sur}" if moy_ann else '-'
    c.drawString(col1, cy, f"Moyenne de l'eleve : {moy_txt}")
    c.drawString(col2, cy, f"Classement : {_s(rang)}")
    cy -= 11
    moy_c_txt = f"{moy_classe:.2f}/{sur}" if moy_classe else '-'
    c.drawString(col1, cy, f"Moyenne de la classe : {moy_c_txt}")
    c.drawString(col2, cy, f"Effectif : {effectif}")
    cy -= 11
    min_txt = f"{note_min:.2f}/{sur}" if note_min else '-'
    max_txt = f"{note_max:.2f}/{sur}" if note_max else '-'
    c.drawString(col1, cy, f"Note la plus faible : {min_txt}")
    c.drawString(col2, cy, f"Note la plus forte : {max_txt}")

    # Barre visuelle position eleve vs classe
    cy -= 16
    if moy_ann and note_min is not None and note_max is not None and note_max > note_min:
        bar_x = lx
        bar_w = usable_w
        bar_h = 10
        # Fond barre
        c.setFillColor(colors.HexColor('#e0e0e0'))
        c.rect(bar_x, cy, bar_w, bar_h, fill=1, stroke=0)
        # Zone verte (au-dessus du seuil)
        seuil_pos = ((seuil - note_min) / (note_max - note_min)) * bar_w
        c.setFillColor(colors.HexColor('#c8e6c9'))
        c.rect(bar_x + seuil_pos, cy, bar_w - seuil_pos, bar_h, fill=1, stroke=0)
        # Position moyenne classe
        if moy_classe:
            mc_pos = ((moy_classe - note_min) / (note_max - note_min)) * bar_w
            c.setStrokeColor(colors.HexColor('#1565c0'))
            c.setLineWidth(1.5)
            c.line(bar_x + mc_pos, cy, bar_x + mc_pos, cy + bar_h)
        # Position eleve
        el_pos = ((moy_ann - note_min) / (note_max - note_min)) * bar_w
        el_pos = max(0, min(el_pos, bar_w))
        c.setFillColor(colors.HexColor('#d32f2f') if moy_ann < seuil else colors.HexColor('#2e7d32'))
        c.circle(bar_x + el_pos, cy + bar_h / 2, 4, fill=1, stroke=0)
        # Bordure barre
        c.setStrokeColor(colors.HexColor('#999999'))
        c.setLineWidth(0.5)
        c.rect(bar_x, cy, bar_w, bar_h, fill=0, stroke=1)
        # Legende
        cy -= 10
        c.setFont('Helvetica', 6)
        c.setFillColor(colors.HexColor('#2e7d32'))
        c.drawString(lx, cy, "o Eleve")
        c.setFillColor(colors.HexColor('#1565c0'))
        c.drawString(lx + 40, cy, "| Moy. classe")
        c.setFillColor(colors.HexColor('#666666'))
        c.drawString(lx + 100, cy, f"Min: {min_txt}")
        c.drawString(lx + 155, cy, f"Max: {max_txt}")
    else:
        cy -= 10

    # === SECTION 2 : MATIERES FORTES ET FAIBLES ===
    cy -= 12
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "ANALYSE PAR MATIERE")
    cy -= 3
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx, cy, rx, cy)

    # Calculer la moyenne par matiere
    mat_avgs = []
    for m in matieres:
        nom = m.get('nom', '')
        vals = []
        if is_sem:
            for k in ['sem1_moyenne', 'sem2_moyenne']:
                v = m.get(k)
                if v is not None:
                    vals.append(float(v))
        else:
            for k in ['t1_moy', 't2_moy', 't3_moy']:
                v = m.get(k)
                if v is not None:
                    vals.append(float(v))
        if vals:
            avg = round(sum(vals) / len(vals), 2)
            mat_avgs.append((nom, avg))

    mat_avgs.sort(key=lambda t: t[1], reverse=True)

    # Tableau matieres fortes / faibles
    cy -= 5
    if mat_avgs:
        fortes = [(n, v) for n, v in mat_avgs if v >= seuil]
        faibles = [(n, v) for n, v in mat_avgs if v < seuil]

        # Afficher TOUTES les matieres (triees par moyenne decroissante)
        display_items = mat_avgs

        tbl_data = [['Matiere', 'Moyenne', 'Niveau']]
        for nom, avg in display_items:
            if avg is None:
                tbl_data.append([nom, '', ''])
                continue
            if avg >= seuil * 1.6:
                niv = 'Excellent'
            elif avg >= seuil * 1.3:
                niv = 'Bon'
            elif avg >= seuil:
                niv = 'Passable'
            else:
                niv = 'Insuffisant'
            tbl_data.append([nom, f"{avg:.2f}/{sur}", niv])

        col_w_m = [usable_w * 0.45, usable_w * 0.25, usable_w * 0.30]
        # Adapter la hauteur de ligne si beaucoup de matieres
        rh_m = 11 if len(tbl_data) > 12 else 12
        fs_m = 6 if len(tbl_data) > 12 else 7
        # Tronquer les noms de matieres trop longs dans le tableau
        for row in tbl_data[1:]:
            if row[0] and len(str(row[0])) > 35:
                row[0] = str(row[0])[:33] + '..'
        tbl = Table(tbl_data, colWidths=col_w_m, rowHeights=[rh_m] * len(tbl_data))
        style_cmds = [
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), fs_m),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#999999')),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(get_school_palette(ecole)['primary'])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]
        # Colorier les lignes selon le niveau
        for i, (nom, avg) in enumerate(display_items, 1):
            if avg is None:
                continue
            if avg < seuil:
                style_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#ffebee')))
            elif avg >= seuil * 1.3:
                style_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#e8f5e9')))
        tbl.setStyle(TableStyle(style_cmds))

        th_m = rh_m * len(tbl_data)
        tbl.wrapOn(c, usable_w, th_m + 5)
        tbl.drawOn(c, lx, cy - th_m)
        cy -= th_m + 8

        # Resume texte
        c.setFont('Helvetica-Bold', 6)
        c.setFillColor(colors.HexColor('#2e7d32'))
        c.drawString(lx, cy, f"Forts ({len(fortes)}) : ")
        c.setFont('Helvetica', 6)
        noms_fortes = ', '.join(n for n, _ in fortes[:3])
        if len(fortes) > 3:
            noms_fortes += ' ...'
        c.drawString(lx + 45, cy, noms_fortes if noms_fortes else 'Aucune')
        cy -= 9
        c.setFont('Helvetica-Bold', 6)
        c.setFillColor(colors.HexColor('#c62828'))
        c.drawString(lx, cy, f"Faibles ({len(faibles)}) : ")
        c.setFont('Helvetica', 6)
        noms_faibles = ', '.join(n for n, _ in faibles[:3])
        if len(faibles) > 3:
            noms_faibles += ' ...'
        c.drawString(lx + 45, cy, noms_faibles if noms_faibles else 'Aucune')

    # === SECTION 3 : EVOLUTION PAR PERIODE (graphique barres) ===
    cy -= 16
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "EVOLUTION PAR PERIODE")
    cy -= 3
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx, cy, rx, cy)

    cy -= 5
    if moyennes_periodes and len(moyennes_periodes) >= 1:
        graph_h = 55
        graph_w = usable_w
        graph_y = cy - graph_h
        nb = len(moyennes_periodes)
        bar_gap = 8
        bar_w_each = (graph_w - (nb + 1) * bar_gap) / nb if nb > 0 else 0

        # Axe et fond
        c.setStrokeColor(colors.HexColor('#cccccc'))
        c.setLineWidth(0.3)
        for frac in [0.25, 0.5, 0.75, 1.0]:
            ly = graph_y + graph_h * frac
            c.line(lx, ly, rx, ly)
            c.setFont('Helvetica', 5)
            c.setFillColor(colors.HexColor('#999999'))
            c.drawRightString(lx - 2, ly - 2, f"{sur * frac:.0f}")

        # Ligne de seuil
        seuil_frac = seuil / sur
        seuil_y = graph_y + graph_h * seuil_frac
        c.setStrokeColor(colors.HexColor('#ff5722'))
        c.setLineWidth(0.6)
        c.setDash(3, 2)
        c.line(lx, seuil_y, rx, seuil_y)
        c.setDash()
        c.setFont('Helvetica', 5)
        c.setFillColor(colors.HexColor('#ff5722'))
        c.drawRightString(lx - 2, seuil_y - 2, f"{seuil:.0f}")

        # Barres
        prev_val = None
        for i, mp in enumerate(moyennes_periodes):
            bx = lx + bar_gap + i * (bar_w_each + bar_gap)
            val = mp['moyenne']
            frac = min(val / sur, 1.0)
            bh = graph_h * frac

            # Couleur selon le seuil
            if val >= seuil * 1.3:
                bar_color = '#2e7d32'
            elif val >= seuil:
                bar_color = '#43a047'
            else:
                bar_color = '#e53935'
            c.setFillColor(colors.HexColor(bar_color))
            c.rect(bx, graph_y, bar_w_each, bh, fill=1, stroke=0)

            # Valeur au-dessus de la barre
            c.setFont('Helvetica-Bold', 6)
            c.setFillColor(colors.HexColor('#222222'))
            c.drawCentredString(bx + bar_w_each / 2, graph_y + bh + 2, f"{val:.1f}")

            # Fleche tendance
            if prev_val is not None:
                arrow_x = bx + bar_w_each / 2
                arrow_y = graph_y - 6
                if val > prev_val:
                    c.setFillColor(colors.HexColor('#2e7d32'))
                    c.drawCentredString(arrow_x, arrow_y, "^")
                elif val < prev_val:
                    c.setFillColor(colors.HexColor('#c62828'))
                    c.drawCentredString(arrow_x, arrow_y, "v")
                else:
                    c.setFillColor(colors.HexColor('#666666'))
                    c.drawCentredString(arrow_x, arrow_y, "=")
            prev_val = val

            # Label periode
            label = mp['periode'].replace('SEMESTRE_', 'S').replace('TRIMESTRE_', 'T')
            c.setFont('Helvetica', 5.5)
            c.setFillColor(colors.HexColor('#333333'))
            c.drawCentredString(bx + bar_w_each / 2, graph_y - 12, label)

        cy = graph_y - 18
    else:
        c.setFont('Helvetica-Oblique', 7)
        c.setFillColor(colors.HexColor('#999999'))
        c.drawString(lx, cy - 10, "Donnees insuffisantes pour le graphique d'evolution.")
        cy -= 20

    # === SECTION 4 : DECISION ET ACCOMPAGNEMENT ===
    cy -= 6
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.drawString(lx, cy, "DECISION ET ACCOMPAGNEMENT")
    cy -= 3
    c.setStrokeColor(colors.HexColor(get_school_palette(ecole)['primary']))
    c.line(lx, cy, rx, cy)

    cy -= 11
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.black)

    if moy_ann:
        if moy_ann >= seuil * 1.6:
            decision = "Excellent resultat. Admis(e) avec les felicitations."
            conseil = "Continuer sur cette lancee. L'eleve peut envisager les filieres d'excellence."
        elif moy_ann >= seuil * 1.3:
            decision = "Bon resultat. Admis(e) avec encouragement."
            conseil = "Poursuivre les efforts. Renforcer les matieres les plus faibles."
        elif moy_ann >= seuil:
            decision = "Resultat passable. Admis(e) en classe superieure."
            conseil = "Accompagnement necessaire dans les matieres insuffisantes."
        else:
            decision = "Resultat insuffisant. Risque de redoublement."
            conseil = "Soutien scolaire indispensable. Reprendre les bases."
    else:
        decision = "Donnees insuffisantes pour evaluer."
        conseil = ""

    c.setFont('Helvetica-Bold', 7)
    c.drawString(lx, cy, "Decision :")
    c.setFont('Helvetica', 7)
    c.drawString(lx + 50, cy, decision)

    if conseil:
        cy -= 10
        c.setFont('Helvetica-Bold', 7)
        c.drawString(lx, cy, "Conseil :")
        c.setFont('Helvetica', 7)
        c.drawString(lx + 50, cy, conseil)

    # Matieres a travailler en priorite
    faibles_prio = [(n, v) for n, v in mat_avgs if v < seuil] if mat_avgs else []
    if faibles_prio:
        cy -= 12
        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(colors.HexColor('#c62828'))
        c.drawString(lx, cy, "Matieres a travailler en priorite :")
        cy -= 9
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.black)
        for nom, avg in faibles_prio[:6]:
            ecart = seuil - avg
            c.drawString(lx + 8, cy, f"- {nom} ({avg:.2f}/{sur}, ecart: -{ecart:.2f})")
            cy -= 8

    # Signatures
    sig_y = y + 25
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(colors.black)
    c.drawString(lx, sig_y, "Le Directeur / Proviseur :")
    c.drawString(cx, sig_y, "Signature parent :")

    # Numero de page
    c.setFont('Helvetica', 8)
    c.setFillColor(colors.black)
    c.drawCentredString(cx, y + 5, f"-{page_number}-")


def _generer_livret_pdf(eleve, ecole, parcours):
    """Genere le PDF du livret scolaire en pages sequentielles.

    Format paysage A4, deux demi-pages par feuille (gauche/droite).
    Les pages se suivent dans l'ordre de lecture, sans saut ni page vide.

    Ordre de lecture :
      Page 1 : Couverture
      Page 2 : Renseignements parents
      Pages 3..N-2 : Niveaux scolaires du parcours (maternelle -> terminale)
      Page N-1 : Analyse et rapport final
      Page N : Fiche de sante
    """
    buffer = io.BytesIO()
    width, height = landscape(A4)  # 842 x 595
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    c.setTitle(f"Livret Scolaire - {_s(eleve.nom)} {_s(eleve.prenom)}")

    margin = 10
    gap = 6
    half_w = (width - 2 * margin - gap) / 2
    usable_h = height - 2 * margin
    left_x = margin
    right_x = margin + half_w + gap
    logo = _get_logo_reader(ecole)

    # =====================================================================
    # Construire la liste des demi-pages dans l'ORDRE DE LECTURE
    # =====================================================================
    logical_pages = []

    # Page 1 : Couverture
    logical_pages.append(
        lambda c, x, y, w, h, pn: _draw_cover_half(
            c, x, y, w, h, ecole, eleve, parcours, logo, pn))

    # Page 2 : Renseignements parents
    logical_pages.append(
        lambda c, x, y, w, h, pn: _draw_renseignements_parents_half(
            c, x, y, w, h, ecole, eleve, pn))

    # Pages 3+ : Niveaux scolaires du parcours (maternelle -> terminale)
    for entry in parcours:
        logical_pages.append(
            lambda c, x, y, w, h, pn, e=entry: _draw_half_page(
                c, x, y, w, h, ecole, e, eleve, pn))

    # Fiche d'orientation fin de college (si l'eleve a fait le college)
    if _eleve_a_termine_college(parcours):
        logical_pages.append(
            lambda c, x, y, w, h, pn: _draw_fiche_orientation_lycee_half(
                c, x, y, w, h, ecole, eleve, parcours, pn))

    # Synthese du parcours par cycle
    logical_pages.append(
        lambda c, x, y, w, h, pn: _draw_synthese_half(
            c, x, y, w, h, ecole, eleve, parcours, pn))

    # Analyse et orientation universitaire/professionnelle
    logical_pages.append(
        lambda c, x, y, w, h, pn: _draw_orientation_half(
            c, x, y, w, h, ecole, eleve, parcours, pn))

    # Fiche de sante
    logical_pages.append(
        lambda c, x, y, w, h, pn: _draw_fiche_sante_half(
            c, x, y, w, h, ecole, eleve, pn))

    # Derniere page : Lettre de remerciement aux parents
    logical_pages.append(
        lambda c, x, y, w, h, pn: _draw_lettre_remerciement_half(
            c, x, y, w, h, ecole, eleve, parcours, pn))

    # =====================================================================
    # Generer le PDF — pages sequentielles, 2 demi-pages par feuille
    # =====================================================================
    N = len(logical_pages)
    for i in range(0, N, 2):
        # Demi-page gauche
        logical_pages[i](c, left_x, margin, half_w, usable_h, i + 1)

        # Demi-page droite (si elle existe)
        if i + 1 < N:
            logical_pages[i + 1](c, right_x, margin, half_w, usable_h, i + 2)

        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer


def _generer_livret_annuel_pdf(eleve, ecole, parcours, annee_scolaire):
    """Genere le livret scolaire pour une seule annee.

    Format paysage A4 : couverture (gauche) + tableau des notes (droite).
    """
    entry = None
    for p in parcours:
        if p['annee_scolaire'] == annee_scolaire:
            entry = p
            break
    if not entry:
        return None

    buffer = io.BytesIO()
    width, height = landscape(A4)
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    c.setTitle(f"Livret Annuel - {_s(eleve.nom)} {_s(eleve.prenom)} - {annee_scolaire}")

    margin = 10
    gap = 6
    half_w = (width - 2 * margin - gap) / 2
    usable_h = height - 2 * margin
    left_x = margin
    right_x = margin + half_w + gap
    logo = _get_logo_reader(ecole)

    # Page 1 : Couverture (gauche) + Notes de l'annee (droite)
    _draw_cover_half(c, left_x, margin, half_w, usable_h,
                     ecole, eleve, [entry], logo, 1)
    _draw_half_page(c, right_x, margin, half_w, usable_h,
                    ecole, entry, eleve, 2)
    c.showPage()

    # Page 2 : Analyse du niveau de l'eleve (gauche) + Orientation (droite)
    _draw_analyse_annuelle_half(c, left_x, margin, half_w, usable_h,
                                ecole, eleve, entry, 3)
    _draw_orientation_half(c, right_x, margin, half_w, usable_h,
                           ecole, eleve, parcours, 4)
    c.showPage()

    page_num = 5

    # Page optionnelle : Fiche d'orientation lycee (si college)
    if _eleve_a_termine_college(parcours):
        _draw_fiche_orientation_lycee_half(c, left_x, margin, half_w, usable_h,
                                           ecole, eleve, parcours, page_num)
        _draw_lettre_remerciement_half(c, right_x, margin, half_w, usable_h,
                                       ecole, eleve, [entry], page_num + 1)
        c.showPage()
    else:
        # Page 3 : Lettre de remerciement (gauche)
        _draw_lettre_remerciement_half(c, left_x, margin, half_w, usable_h,
                                       ecole, eleve, [entry], page_num)
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer


# Classement des matieres par domaine pour l'orientation
_DOMAINES_MATIERES = {
    'SCIENCES_EXACTES': [
        'math', 'physique', 'chimie', 'sciences physiques', 'algebre',
        'geometrie', 'arithmetique', 'statistique',
    ],
    'SCIENCES_VIE': [
        'biologie', 'svt', 'sciences de la vie', 'sciences naturelles',
        'botanique', 'zoologie', 'ecologie',
    ],
    'LETTRES_LANGUES': [
        'francais', 'anglais', 'arabe', 'espagnol', 'allemand',
        'redaction', 'dictee', 'grammaire', 'orthographe', 'vocabulaire',
        'conjugaison', 'lecture', 'expression', 'litterature', 'langage',
        'communication', 'ecriture', 'graphisme',
    ],
    'SCIENCES_SOCIALES': [
        'histoire', 'geographie', 'education civique', 'philosophie',
        'sociologie', 'economie', 'droit', 'instruction civique',
        'decouverte du monde',
    ],
    'ARTS_CULTURE': [
        'dessin', 'arts', 'musique', 'art plastique', 'arts plastiques',
        'culture', 'theatre',
    ],
    'SPORT': [
        'sport', 'education physique', 'eps', 'gymnastique',
    ],
    'TECHNIQUE': [
        'informatique', 'technologie', 'technique', 'comptabilite',
        'gestion', 'economie familiale',
    ],
}


def _classifier_matiere(nom_matiere):
    """Retourne le domaine d'une matiere."""
    nom_lower = nom_matiere.lower().replace('\u00e9', 'e').replace('\u00e8', 'e') \
        .replace('\u00ea', 'e').replace('\u00e0', 'a').replace('\u00e7', 'c') \
        .replace('\u00ee', 'i').replace('\u00f4', 'o')
    for domaine, mots_cles in _DOMAINES_MATIERES.items():
        for mot in mots_cles:
            if mot in nom_lower:
                return domaine
    return 'AUTRE'


def _calculer_orientation(parcours):
    """Analyse complete de l'evolution de l'eleve et proposition d'orientation.

    Analyse:
    - Evolution des moyennes annuelles (tendance)
    - Moyennes par domaine sur tout le parcours
    - Points forts et faibles persistants
    - Proposition de filieres universitaires ou professionnelles
    """
    if not parcours:
        return ["Aucune donnee disponible pour proposer une orientation."]

    derniere = parcours[-1]
    sur = derniere['sur']
    seuil = 5.0 if sur == 10 else 10.0

    # ---------------------------------------------------------------
    # 1. EVOLUTION DES MOYENNES ANNUELLES
    # ---------------------------------------------------------------
    moyennes_all = []
    for p in parcours:
        if p['moyenne_annuelle'] is not None:
            moyennes_all.append((p['annee_scolaire'], p['classe_nom'], p['moyenne_annuelle'], p['sur']))

    if not moyennes_all:
        return ["Aucune moyenne disponible pour proposer une orientation."]

    # Normaliser toutes les moyennes sur 20 pour comparer
    moyennes_norm = []
    for annee, classe, moy, s in moyennes_all:
        moy_sur20 = moy * (20.0 / s) if s else moy
        moyennes_norm.append((annee, classe, moy_sur20, moy, s))

    moy_globale_20 = round(sum(m[2] for m in moyennes_norm) / len(moyennes_norm), 2)
    derniere_moy_20 = moyennes_norm[-1][2]

    # Tendance (regression lineaire simple)
    n = len(moyennes_norm)
    tendance = "stable"
    if n >= 2:
        premiere_moy = moyennes_norm[0][2]
        ecart = derniere_moy_20 - premiere_moy
        if ecart > 1.5:
            tendance = "progression"
        elif ecart < -1.5:
            tendance = "regression"

    lines = []
    lines.append("BILAN DU PARCOURS SCOLAIRE")
    lines.append(f"  {len(moyennes_all)} annee(s) evaluee(s)")
    moy_aff = moyennes_all[-1][2]
    sur_aff = moyennes_all[-1][3]
    lines.append(f"  Moyenne generale du parcours : {moy_globale_20:.2f}/20")
    lines.append(f"  Derniere moyenne : {moy_aff:.2f}/{sur_aff}")
    if tendance == "progression":
        lines.append(f"  Tendance : En progression (+{derniere_moy_20 - moyennes_norm[0][2]:.1f} pts)")
    elif tendance == "regression":
        lines.append(f"  Tendance : En baisse ({derniere_moy_20 - moyennes_norm[0][2]:.1f} pts)")
    else:
        lines.append("  Tendance : Stable")
    lines.append("")

    # ---------------------------------------------------------------
    # 2. ANALYSE PAR DOMAINE (toutes annees confondues)
    # ---------------------------------------------------------------
    domaines_notes = {}  # domaine -> liste de (moyenne_normalisee_sur20)
    matieres_global = {}  # nom_matiere -> liste de notes

    for p in parcours:
        p_sur = p.get('sur', 20)
        for m in p.get('matieres_data', []):
            nom = _s(m.get('nom', ''))
            vals = []
            for key in ['sem1_moyenne', 'sem2_moyenne', 't1_moy', 't2_moy', 't3_moy']:
                v = m.get(key)
                if v is not None:
                    try:
                        vals.append(float(v))
                    except (ValueError, TypeError):
                        pass
            if vals:
                avg = sum(vals) / len(vals)
                avg_20 = avg * (20.0 / p_sur) if p_sur else avg
                domaine = _classifier_matiere(nom)
                domaines_notes.setdefault(domaine, []).append(avg_20)
                matieres_global.setdefault(nom, []).append((avg, p_sur))

    # Moyenne par domaine
    domaines_avg = {}
    for dom, notes_list in domaines_notes.items():
        if notes_list:
            domaines_avg[dom] = round(sum(notes_list) / len(notes_list), 2)

    # Top matieres globales
    matieres_avg = {}
    for nom, notes_list in matieres_global.items():
        all_20 = [v * (20.0 / s) if s else v for v, s in notes_list]
        if all_20:
            matieres_avg[nom] = round(sum(all_20) / len(all_20), 2)

    matieres_sorted = sorted(matieres_avg.items(), key=lambda x: x[1], reverse=True)
    fortes = [(n, v) for n, v in matieres_sorted if v >= 12]
    faibles = [(n, v) for n, v in matieres_sorted if v < 10]

    lines.append("POINTS FORTS (sur tout le parcours)")
    if fortes:
        for nom, avg in fortes[:5]:
            lines.append(f"  + {nom} : {avg:.1f}/20")
    else:
        lines.append("  Aucune matiere au-dessus de 12/20")
    lines.append("")

    if faibles:
        lines.append("POINTS A AMELIORER")
        for nom, avg in faibles[:4]:
            lines.append(f"  - {nom} : {avg:.1f}/20")
        lines.append("")

    # ---------------------------------------------------------------
    # 3. PROFIL DOMINANT ET ORIENTATION
    # ---------------------------------------------------------------
    DOMAINE_LABELS = {
        'SCIENCES_EXACTES': 'Sciences exactes',
        'SCIENCES_VIE': 'Sciences de la vie',
        'LETTRES_LANGUES': 'Lettres et langues',
        'SCIENCES_SOCIALES': 'Sciences sociales',
        'ARTS_CULTURE': 'Arts et culture',
        'SPORT': 'Sport',
        'TECHNIQUE': 'Technique',
    }

    # Trier les domaines par moyenne decroissante (hors AUTRE)
    domaines_sorted = sorted(
        [(d, a) for d, a in domaines_avg.items() if d != 'AUTRE'],
        key=lambda x: x[1], reverse=True
    )

    # Profil dominant = domaine(s) avec meilleure moyenne
    profil_dom = domaines_sorted[0][0] if domaines_sorted else None
    profil_score = domaines_sorted[0][1] if domaines_sorted else 0

    lines.append("ORIENTATION PROPOSEE")

    # Filieres selon le profil et le niveau
    if moy_globale_20 >= 16:
        excellence = True
        lines.append("  Niveau : EXCELLENT - Acces aux filieres d'excellence")
    elif moy_globale_20 >= 12:
        excellence = False
        lines.append("  Niveau : BON - Acces aux filieres universitaires")
    elif moy_globale_20 >= 10:
        excellence = False
        lines.append("  Niveau : PASSABLE - Filieres generales ou professionnelles")
    else:
        excellence = False
        lines.append("  Niveau : INSUFFISANT - Formation professionnelle recommandee")
    lines.append("")

    # Propositions basees sur le domaine dominant
    if profil_dom == 'SCIENCES_EXACTES' and profil_score >= 12:
        lines.append("  >> PROFIL SCIENTIFIQUE")
        if excellence:
            lines.append("     Filieres universitaires :")
            lines.append("       - Medecine / Pharmacie / Dentaire")
            lines.append("       - Ecoles d'ingenieurs (Polytechnique, Mines)")
            lines.append("       - Licence Mathematiques / Physique")
            lines.append("       - Informatique / Intelligence artificielle")
        else:
            lines.append("     Filieres recommandees :")
            lines.append("       - BTS / DUT Genie civil, Electrotechnique")
            lines.append("       - Licence Sciences et Technologies")
            lines.append("       - Formation en Informatique / Reseaux")
            lines.append("       - Comptabilite et Gestion")

    elif profil_dom == 'SCIENCES_VIE' and profil_score >= 12:
        lines.append("  >> PROFIL SCIENCES DE LA VIE")
        if excellence:
            lines.append("     Filieres universitaires :")
            lines.append("       - Medecine / Pharmacie / Sage-femme")
            lines.append("       - Biologie / Biochimie")
            lines.append("       - Agronomie / Sciences de l'environnement")
            lines.append("       - Veterinaire")
        else:
            lines.append("     Filieres recommandees :")
            lines.append("       - Infirmier / Laborantin")
            lines.append("       - Agriculture / Elevage")
            lines.append("       - Technicien de laboratoire")
            lines.append("       - Gestion des ressources naturelles")

    elif profil_dom == 'LETTRES_LANGUES' and profil_score >= 12:
        lines.append("  >> PROFIL LITTERAIRE ET LINGUISTIQUE")
        if excellence:
            lines.append("     Filieres universitaires :")
            lines.append("       - Droit / Sciences juridiques")
            lines.append("       - Lettres modernes / Linguistique")
            lines.append("       - Journalisme / Communication")
            lines.append("       - Relations internationales")
            lines.append("       - Enseignement (ENS / Professorat)")
        else:
            lines.append("     Filieres recommandees :")
            lines.append("       - Secretariat / Administration")
            lines.append("       - Communication et Marketing")
            lines.append("       - Tourisme et Hotellerie")
            lines.append("       - Traduction / Interpretation")

    elif profil_dom == 'SCIENCES_SOCIALES' and profil_score >= 12:
        lines.append("  >> PROFIL SCIENCES HUMAINES ET SOCIALES")
        if excellence:
            lines.append("     Filieres universitaires :")
            lines.append("       - Sciences politiques / Administration publique")
            lines.append("       - Economie / Finance")
            lines.append("       - Sociologie / Psychologie")
            lines.append("       - Histoire / Geographie")
        else:
            lines.append("     Filieres recommandees :")
            lines.append("       - Administration / Gestion")
            lines.append("       - Banque et Assurance")
            lines.append("       - Action sociale")
            lines.append("       - Douane / Police / Armee")

    elif profil_dom == 'TECHNIQUE' and profil_score >= 10:
        lines.append("  >> PROFIL TECHNIQUE ET PROFESSIONNEL")
        lines.append("     Filieres recommandees :")
        lines.append("       - BTS Informatique / Reseaux")
        lines.append("       - Gestion des entreprises")
        lines.append("       - Comptabilite / Finance")
        lines.append("       - Logistique / Transport")

    elif profil_dom == 'ARTS_CULTURE' and profil_score >= 12:
        lines.append("  >> PROFIL ARTISTIQUE ET CULTUREL")
        lines.append("     Filieres recommandees :")
        lines.append("       - Beaux-Arts / Design")
        lines.append("       - Architecture")
        lines.append("       - Communication visuelle")
        lines.append("       - Animation culturelle")

    elif profil_dom == 'SPORT' and profil_score >= 14:
        lines.append("  >> PROFIL SPORTIF")
        lines.append("     Filieres recommandees :")
        lines.append("       - STAPS / Sciences du sport")
        lines.append("       - Entraineur / Moniteur sportif")
        lines.append("       - Kinesitherapie / Reeducation")

    elif moy_globale_20 >= 10:
        # Profil general sans domaine dominant
        lines.append("  >> PROFIL GENERAL")
        lines.append("     Filieres recommandees :")
        if domaines_sorted:
            top2 = domaines_sorted[:2]
            for dom, avg in top2:
                label = DOMAINE_LABELS.get(dom, dom)
                lines.append(f"       - Domaine {label} ({avg:.1f}/20)")
        lines.append("       - Filiere generale avec specialisation progressive")
        lines.append("       - Formation professionnelle qualifiante")
    else:
        lines.append("  >> FORMATION PROFESSIONNELLE RECOMMANDEE")
        lines.append("     Options possibles :")
        lines.append("       - Centre de formation professionnelle (CFP)")
        lines.append("       - Apprentissage d'un metier (artisanat, BTP)")
        lines.append("       - Agriculture / Elevage / Peche")
        lines.append("       - Formation en entrepreneuriat")
        lines.append("     Conseil : renforcer les acquis de base avant toute")
        lines.append("     orientation en filiere longue.")

    # Conseil selon la tendance
    lines.append("")
    if tendance == "progression":
        lines.append("  Note : Parcours en progression constante.")
        lines.append("  L'eleve montre une capacite d'amelioration encourageante.")
    elif tendance == "regression":
        lines.append("  Attention : Parcours en baisse. Un soutien scolaire")
        lines.append("  renforce est recommande pour inverser la tendance.")

    return lines


# ==============================================================================
#  VUES DJANGO
# ==============================================================================

@login_required
def livret_scolaire_selection(request):
    """Page de selection."""
    try:
        ecole = user_school(request.user)
        if not ecole:
            messages.error(request, "Aucune ecole associee a votre compte.")
            return redirect('notes:tableau_bord')

        from eleves.utils_annee import get_annee_active
        annee_active = get_annee_active(request, ecole)

        classes = Classe.objects.filter(ecole=ecole)
        if annee_active:
            classes = classes.filter(annee_scolaire=annee_active)
        classes = classes.order_by('niveau', 'nom')

        classe_id = request.GET.get('classe_id')
        eleves = []
        classe_selected = None
        if classe_id:
            try:
                classe_selected = classes.get(pk=classe_id)
                eleves = Eleve.objects.filter(
                    classe=classe_selected, statut='ACTIF'
                ).order_by('nom', 'prenom')
            except Classe.DoesNotExist:
                pass

        context = {
            'ecole': ecole,
            'classes': classes,
            'classe_selected': classe_selected,
            'eleves': eleves,
            'annee_active': annee_active,
            'titre_page': 'Livrets Scolaires',
        }
        return render(request, 'notes/livret_scolaire_selection.html', context)
    except Exception as e:
        logger.error(f"Erreur livret_scolaire_selection: {e}", exc_info=True)
        messages.error(request, f"Erreur: {e}")
        return redirect('notes:tableau_bord')


@login_required
def livret_scolaire_pdf(request, eleve_id):
    """Genere le livret scolaire PDF d'un eleve."""
    ecole = user_school(request.user)
    if not ecole:
        messages.error(request, "Aucune ecole associee a votre compte.")
        return redirect('notes:tableau_bord')

    eleve = get_object_or_404(Eleve, pk=eleve_id)

    if not filter_by_user_school(
        Eleve.objects.filter(pk=eleve_id), request.user, 'classe__ecole'
    ).exists():
        messages.error(request, "Acces non autorise a cet eleve.")
        return redirect('notes:livret_scolaire')

    try:
        parcours = _collecter_parcours_eleve(eleve, ecole)
        if not parcours:
            messages.warning(request,
                             f"Aucune donnee de parcours trouvee pour {eleve.nom} {eleve.prenom}.")
            return redirect('notes:livret_scolaire')

        pdf_buffer = _generer_livret_pdf(eleve, ecole, parcours)
        filename = f"Livret_Scolaire_{_s(eleve.nom)}_{_s(eleve.prenom)}.pdf"
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.error(f"Erreur generation livret eleve {eleve_id}: {e}", exc_info=True)
        messages.error(request, f"Erreur lors de la generation du livret : {e}")
        return redirect('notes:livret_scolaire')


@login_required
def livret_scolaire_annuel_pdf(request, eleve_id):
    """Genere le livret scolaire annuel PDF d'un eleve (annee en cours)."""
    ecole = user_school(request.user)
    if not ecole:
        messages.error(request, "Aucune ecole associee a votre compte.")
        return redirect('notes:tableau_bord')

    eleve = get_object_or_404(Eleve, pk=eleve_id)

    if not filter_by_user_school(
        Eleve.objects.filter(pk=eleve_id), request.user, 'classe__ecole'
    ).exists():
        messages.error(request, "Acces non autorise a cet eleve.")
        return redirect('notes:livret_scolaire')

    from eleves.utils_annee import get_annee_active
    annee = request.GET.get('annee') or get_annee_active(request, ecole) or ''
    if not annee and eleve.classe:
        annee = eleve.classe.annee_scolaire

    try:
        parcours = _collecter_parcours_eleve(eleve, ecole)
        if not parcours:
            messages.warning(request,
                             f"Aucune donnee de parcours trouvee pour {eleve.nom} {eleve.prenom}.")
            return redirect('notes:livret_scolaire')

        pdf_buffer = _generer_livret_annuel_pdf(eleve, ecole, parcours, annee)
        if not pdf_buffer:
            messages.warning(request,
                             f"Aucune donnee trouvee pour l'annee {annee}.")
            return redirect('notes:livret_scolaire')

        filename = f"Livret_Annuel_{_s(eleve.nom)}_{_s(eleve.prenom)}_{annee}.pdf"
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.error(f"Erreur generation livret annuel eleve {eleve_id}: {e}", exc_info=True)
        messages.error(request, f"Erreur lors de la generation du livret annuel : {e}")
        return redirect('notes:livret_scolaire')


@login_required
def livret_scolaire_classe_pdf(request, classe_id):
    """Genere les livrets scolaires de tous les eleves d'une classe en un seul PDF."""
    ecole = user_school(request.user)
    if not ecole:
        messages.error(request, "Aucune ecole associee.")
        return redirect('notes:tableau_bord')

    classe = get_object_or_404(Classe, pk=classe_id, ecole=ecole)
    eleves_qs = Eleve.objects.filter(
        classe=classe, statut='ACTIF'
    ).order_by('nom', 'prenom')

    if not eleves_qs.exists():
        messages.warning(request, f"Aucun eleve actif dans la classe {classe.nom}.")
        return redirect('notes:livret_scolaire')

    buffer = io.BytesIO()
    width, height = landscape(A4)
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    c.setTitle(f"Livrets Scolaires - {_s(classe.nom)}")

    margin = 10
    gap = 6
    half_w = (width - 2 * margin - gap) / 2
    usable_h = height - 2 * margin
    left_x = margin
    right_x = margin + half_w + gap
    logo = _get_logo_reader(ecole)

    nb_generes = 0
    for eleve in eleves_qs:
        try:
            parcours = _collecter_parcours_eleve(eleve, ecole)
            if not parcours:
                continue

            # Construire les pages logiques pour cet eleve
            pages = []
            pages.append(
                lambda c, x, y, w, h, pn, el=eleve, pa=parcours: _draw_cover_half(
                    c, x, y, w, h, ecole, el, pa, logo, pn))
            pages.append(
                lambda c, x, y, w, h, pn, el=eleve: _draw_renseignements_parents_half(
                    c, x, y, w, h, ecole, el, pn))
            for entry in parcours:
                pages.append(
                    lambda c, x, y, w, h, pn, e=entry, el=eleve: _draw_half_page(
                        c, x, y, w, h, ecole, e, el, pn))
            if _eleve_a_termine_college(parcours):
                pages.append(
                    lambda c, x, y, w, h, pn, el=eleve, pa=parcours: _draw_fiche_orientation_lycee_half(
                        c, x, y, w, h, ecole, el, pa, pn))
            pages.append(
                lambda c, x, y, w, h, pn, el=eleve, pa=parcours: _draw_synthese_half(
                    c, x, y, w, h, ecole, el, pa, pn))
            pages.append(
                lambda c, x, y, w, h, pn, el=eleve, pa=parcours: _draw_orientation_half(
                    c, x, y, w, h, ecole, el, pa, pn))
            pages.append(
                lambda c, x, y, w, h, pn, el=eleve: _draw_fiche_sante_half(
                    c, x, y, w, h, ecole, el, pn))
            pages.append(
                lambda c, x, y, w, h, pn, el=eleve, pa=parcours: _draw_lettre_remerciement_half(
                    c, x, y, w, h, ecole, el, pa, pn))

            # Dessiner sequentiellement
            N = len(pages)
            for i in range(0, N, 2):
                pages[i](c, left_x, margin, half_w, usable_h, i + 1)
                if i + 1 < N:
                    pages[i + 1](c, right_x, margin, half_w, usable_h, i + 2)
                c.showPage()

            nb_generes += 1
        except Exception as e:
            logger.error(f"Erreur livret classe eleve {eleve.pk}: {e}", exc_info=True)
            continue

    if nb_generes == 0:
        messages.warning(request, "Aucune donnee disponible.")
        return redirect('notes:livret_scolaire')

    c.save()
    buffer.seek(0)
    filename = f"Livrets_{_s(classe.nom)}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
