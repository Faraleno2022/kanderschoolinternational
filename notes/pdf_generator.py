"""
Générateur de bulletins PDF avec ReportLab
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from django.http import HttpResponse
import os
from .calculs_moyennes import detecter_niveau_scolaire
from ecole_moderne.pdf_utils import draw_logo_watermark
from ecole_moderne.theme import get_school_palette


def generer_bulletin_pdf(eleve_data, classe, periode, periode_libelle):
    """
    Génère un bulletin PDF pour un élève
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*cm, bottomMargin=1*cm)
    elements = []
    ecole = getattr(classe, 'ecole', None)
    palette = get_school_palette(ecole)
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor(palette['primary']),
        spaceAfter=12,
        alignment=1  # Center
    )
    
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor(palette['text']),
        spaceAfter=6
    )
    
    # En-tête du bulletin
    elements.append(Paragraph("BULLETIN DE NOTES", title_style))
    elements.append(Spacer(1, 0.5*cm))
    
    # Informations élève
    info_data = [
        ['Nom et Prénom:', f"{eleve_data['eleve'].nom} {eleve_data['eleve'].prenom}", 
         'Matricule:', eleve_data['eleve'].matricule],
        ['Classe:', classe.nom, 
         'Année scolaire:', classe.annee_scolaire],
        ['Période:', periode_libelle, 
         'Rang:', f"{eleve_data['rang']}/{eleve_data.get('total_eleves', '?')}"],
    ]
    
    info_table = Table(info_data, colWidths=[3*cm, 6*cm, 3*cm, 6*cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor(palette['light'])),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor(palette['light'])),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # Détecter le niveau scolaire pour la notation
    niveau_scolaire = detecter_niveau_scolaire(classe.nom)
    est_primaire = (niveau_scolaire == 'PRIMAIRE')
    base_notation = 10 if est_primaire else 20
    
    # Tableau des notes
    notes_data = [['Matière', 'Coef.', 'Moyenne', 'Points', 'Appréciation']]
    
    # Fonction pour obtenir l'appréciation selon le niveau
    def get_appreciation(note, est_primaire):
        if est_primaire:
            # Seuils pour primaire (sur 10)
            if note >= 9:
                return 'Excellent'
            elif note >= 8:
                return 'Très bien'
            elif note >= 7:
                return 'Bien'
            elif note >= 6:
                return 'Assez bien'
            elif note >= 5:
                return 'Passable'
            elif note >= 4:
                return 'Insuffisant'
            elif note >= 3:
                return 'Faible'
            else:
                return 'Très faible'
        else:
            # Seuils pour secondaire (sur 20)
            if note >= 18:
                return 'Excellent'
            elif note >= 16:
                return 'Très bien'
            elif note >= 14:
                return 'Bien'
            elif note >= 12:
                return 'Assez bien'
            elif note >= 10:
                return 'Passable'
            elif note >= 8:
                return 'Insuffisant'
            elif note >= 6:
                return 'Faible'
            else:
                return 'Très faible'
    
    for note_matiere in eleve_data['notes_matieres']:
        moyenne = note_matiere['moyenne']
        coef = note_matiere['coefficient']
        points = round(moyenne * coef, 2)
        
        # Appréciation adaptée au niveau
        appreciation = get_appreciation(moyenne, est_primaire)
        
        notes_data.append([
            note_matiere['matiere'].nom,
            str(coef),
            f"{moyenne}/{base_notation}",
            str(points),
            appreciation
        ])
    
    # Ligne de total
    moyenne_generale = eleve_data['moyenne_generale']
    appreciation_generale = get_appreciation(moyenne_generale, est_primaire)
    
    notes_data.append([
        'MOYENNE GÉNÉRALE',
        str(eleve_data['total_coefficients']),
        f"{moyenne_generale}/{base_notation}",
        str(eleve_data['total_points']),
        appreciation_generale
    ])
    
    notes_table = Table(notes_data, colWidths=[7*cm, 2*cm, 3*cm, 3*cm, 3*cm])
    notes_table.setStyle(TableStyle([
        # En-tête
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['primary'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Corps du tableau
        ('BACKGROUND', (0, 1), (-1, -2), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -2), colors.black),
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 10),
        ('ALIGN', (1, 1), (-1, -2), 'CENTER'),
        
        # Ligne de total
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor(palette['light'])),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.black),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('ALIGN', (1, -1), (-1, -1), 'CENTER'),
        
        # Grille
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(notes_table)
    elements.append(Spacer(1, 1*cm))
    
    # Observations
    elements.append(Paragraph("Observations du professeur:", header_style))
    elements.append(Spacer(1, 2*cm))
    
    elements.append(Paragraph("Signature du directeur:", header_style))
    elements.append(Spacer(1, 2*cm))
    
    # Construire le PDF
    on_page = lambda canvas, document: draw_logo_watermark(
        canvas, document.pagesize[0], document.pagesize[1], ecole=ecole
    )
    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
    buffer.seek(0)
    return buffer


def generer_bulletins_classe_pdf(eleves_avec_notes, classe, periode, periode_libelle):
    """
    Génère un PDF avec tous les bulletins d'une classe
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*cm, bottomMargin=1*cm)
    elements = []
    ecole = getattr(classe, 'ecole', None)
    
    # Ajouter le total d'élèves à chaque élève_data
    total_eleves = len(eleves_avec_notes)
    for eleve_data in eleves_avec_notes:
        eleve_data['total_eleves'] = total_eleves
    
    for i, eleve_data in enumerate(eleves_avec_notes):
        # Générer le bulletin pour cet élève
        eleve_elements = generer_elements_bulletin(eleve_data, classe, periode, periode_libelle)
        elements.extend(eleve_elements)
        
        # Ajouter un saut de page sauf pour le dernier bulletin
        if i < len(eleves_avec_notes) - 1:
            elements.append(PageBreak())
    
    # Construire le PDF
    on_page = lambda canvas, document: draw_logo_watermark(
        canvas, document.pagesize[0], document.pagesize[1], ecole=ecole
    )
    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
    buffer.seek(0)
    return buffer


def generer_elements_bulletin(eleve_data, classe, periode, periode_libelle):
    """
    Génère les éléments d'un bulletin (sans créer de document)
    """
    elements = []
    palette = get_school_palette(getattr(classe, 'ecole', None))
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor(palette['primary']),
        spaceAfter=12,
        alignment=1  # Center
    )
    
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor(palette['text']),
        spaceAfter=6
    )
    
    # En-tête du bulletin
    elements.append(Paragraph("BULLETIN DE NOTES", title_style))
    elements.append(Spacer(1, 0.5*cm))
    
    # Informations élève
    info_data = [
        ['Nom et Prénom:', f"{eleve_data['eleve'].nom} {eleve_data['eleve'].prenom}", 
         'Matricule:', eleve_data['eleve'].matricule],
        ['Classe:', classe.nom, 
         'Année scolaire:', classe.annee_scolaire],
        ['Période:', periode_libelle, 
         'Rang:', f"{eleve_data['rang']}/{eleve_data.get('total_eleves', '?')}"],
    ]
    
    info_table = Table(info_data, colWidths=[3*cm, 6*cm, 3*cm, 6*cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor(palette['light'])),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor(palette['light'])),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # Détecter le niveau scolaire pour la notation
    niveau_scolaire = detecter_niveau_scolaire(classe.nom)
    est_primaire = (niveau_scolaire == 'PRIMAIRE')
    base_notation = 10 if est_primaire else 20
    
    # Tableau des notes
    notes_data = [['Matière', 'Coef.', 'Moyenne', 'Points', 'Appréciation']]
    
    # Fonction pour obtenir l'appréciation selon le niveau
    def get_appreciation(note, est_primaire):
        if est_primaire:
            # Seuils pour primaire (sur 10)
            if note >= 9:
                return 'Excellent'
            elif note >= 8:
                return 'Très bien'
            elif note >= 7:
                return 'Bien'
            elif note >= 6:
                return 'Assez bien'
            elif note >= 5:
                return 'Passable'
            elif note >= 4:
                return 'Insuffisant'
            elif note >= 3:
                return 'Faible'
            else:
                return 'Très faible'
        else:
            # Seuils pour secondaire (sur 20)
            if note >= 18:
                return 'Excellent'
            elif note >= 16:
                return 'Très bien'
            elif note >= 14:
                return 'Bien'
            elif note >= 12:
                return 'Assez bien'
            elif note >= 10:
                return 'Passable'
            elif note >= 8:
                return 'Insuffisant'
            elif note >= 6:
                return 'Faible'
            else:
                return 'Très faible'
    
    for note_matiere in eleve_data['notes_matieres']:
        moyenne = note_matiere['moyenne']
        coef = note_matiere['coefficient']
        points = round(moyenne * coef, 2)
        
        # Appréciation adaptée au niveau
        appreciation = get_appreciation(moyenne, est_primaire)
        
        notes_data.append([
            note_matiere['matiere'].nom,
            str(coef),
            f"{moyenne}/{base_notation}",
            str(points),
            appreciation
        ])
    
    # Ligne de total
    moyenne_generale = eleve_data['moyenne_generale']
    appreciation_generale = get_appreciation(moyenne_generale, est_primaire)
    
    notes_data.append([
        'MOYENNE GÉNÉRALE',
        str(eleve_data['total_coefficients']),
        f"{moyenne_generale}/{base_notation}",
        str(eleve_data['total_points']),
        appreciation_generale
    ])
    
    notes_table = Table(notes_data, colWidths=[7*cm, 2*cm, 3*cm, 3*cm, 3*cm])
    notes_table.setStyle(TableStyle([
        # En-tête
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['primary'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Corps du tableau
        ('BACKGROUND', (0, 1), (-1, -2), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -2), colors.black),
        ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -2), 10),
        ('ALIGN', (1, 1), (-1, -2), 'CENTER'),
        
        # Ligne de total
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor(palette['light'])),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.black),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('ALIGN', (1, -1), (-1, -1), 'CENTER'),
        
        # Grille
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(notes_table)
    elements.append(Spacer(1, 1*cm))
    
    # Observations
    elements.append(Paragraph("Observations du professeur:", header_style))
    elements.append(Spacer(1, 2*cm))
    
    elements.append(Paragraph("Signature du directeur:", header_style))
    elements.append(Spacer(1, 2*cm))
    
    return elements
