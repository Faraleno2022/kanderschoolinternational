"""
Générateur de cartes scolaires modernes avec design amélioré
"""
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as ReportlabImage
try:
    from PIL import Image, ImageDraw, ImageOps
except Exception:
    Image = ImageDraw = ImageOps = None
import io
import os
from django.utils import timezone
from datetime import timedelta


def _safe_text(value, default=""):
    """Return a printable one-line string."""
    if value is None:
        return default
    return " ".join(str(value).strip().split()) or default


def _fit_font_size(text, font_name, max_size, min_size, max_width):
    """Pick the largest font size that fits in max_width."""
    text = _safe_text(text)
    size = max_size
    while size > min_size and pdfmetrics.stringWidth(text, font_name, size) > max_width:
        size -= 0.5
    return max(size, min_size)


def _draw_fit_text(c, text, x, y, max_width, font_name, max_size, min_size, color):
    """Draw text fitted to a fixed width, truncating only as a last resort."""
    original_text = _safe_text(text)
    text = original_text
    size = _fit_font_size(text, font_name, max_size, min_size, max_width)
    while text and pdfmetrics.stringWidth(text, font_name, size) > max_width:
        text = text[:-1].rstrip()
    if len(text) < len(original_text):
        suffix = "..."
        while text and pdfmetrics.stringWidth(text.rstrip(". ") + suffix, font_name, size) > max_width:
            text = text[:-1].rstrip()
        text = (text.rstrip(". ") + suffix) if text else suffix
    c.setFillColor(colors.HexColor(color))
    c.setFont(font_name, size)
    c.drawString(x, y, text)
    return size


def _draw_value_row(c, label, value, x, y, label_width, value_width, main_font, bold_font):
    label = _safe_text(label)
    value = _safe_text(value, "-")
    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont(bold_font, 5.6)
    c.drawString(x, y, label.upper())
    _draw_fit_text(c, value, x + label_width, y, value_width, main_font, 6.6, 4.7, "#111827")


def _draw_cover_image(c, image_path, x, y, width, height, radius=0):
    """Draw an image cropped to fill the requested box."""
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow is unavailable")
    img = Image.open(image_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    target_size = (max(1, int(width * 3)), max(1, int(height * 3)))
    img = ImageOps.fit(img, target_size, method=Image.Resampling.LANCZOS)
    temp_buffer = io.BytesIO()
    img.save(temp_buffer, format="JPEG", quality=94)
    temp_buffer.seek(0)
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(temp_buffer), x, y, width=width, height=height, mask="auto")


def generer_carte_scolaire_moderne(eleve, response, custom_canvas=None, 
                                  offset_x=0, offset_y=0, 
                                  custom_width=None, custom_height=None):
    """
    Génère une carte scolaire moderne avec le design spécifié:
    - Haut: Logo + nom de l'établissement
    - Gauche: Photo (35-40% de la hauteur)
    - Droite: Informations alignées
    
    Args:
        eleve: L'objet élève
        response: HttpResponse pour le PDF
        custom_canvas: Canvas existant (optionnel, pour intégration PVC)
        offset_x, offset_y: Décalage pour positionnement (pour PVC)
        custom_width, custom_height: Dimensions personnalisées (pour PVC)
    """
    # Configuration des dimensions (format carte de crédit standard)
    if custom_width and custom_height:
        width, height = custom_width, custom_height
    else:
        width, height = 86*mm, 54*mm
    
    if custom_canvas:
        c = custom_canvas
        # Ajuster toutes les positions avec les offsets
        def draw_x(x):
            return x + offset_x
        def draw_y(y):
            return y + offset_y
    else:
        c = canvas.Canvas(response, pagesize=(width, height))
        # Pas d'offset si canvas normal
        def draw_x(x):
            return x
        def draw_y(y):
            return y
    
    # Enregistrement des polices
    try:
        pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:/Windows/Fonts/arialbd.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-Italic', 'C:/Windows/Fonts/ariali.ttf'))
        main_font = 'Arial'
        bold_font = 'Arial-Bold'
        italic_font = 'Arial-Italic'
    except:
        main_font = 'Helvetica'
        bold_font = 'Helvetica-Bold'
        italic_font = 'Helvetica-Oblique'
    
    # Utiliser le moteur robuste partage avec les cartes en lot.
    _dessiner_carte_simple(c, eleve, offset_x, offset_y, width, height, main_font, bold_font)
    if not custom_canvas:
        # Recto (page 1) puis verso (page 2), même verso que le ticket de retrait
        from .views import _dessiner_ticket_retrait_verso
        c.showPage()
        _dessiner_ticket_retrait_verso(c, eleve, 0, 0, width, height, main_font, bold_font)
        c.showPage()
        c.save()
    return response

    # Couleurs du thème
    primary_blue = '#1e40af'
    secondary_blue = '#3b82f6'
    accent_green = '#10b981'
    text_dark = '#1f2937'
    text_gray = '#6b7280'
    light_gray = '#f3f4f6'
    border_color = '#e5e7eb'
    
    # 1. FOND BLANC ET BORDURE
    c.setFillColor(colors.white)
    c.rect(0, 0, width, height, stroke=0, fill=1)
    
    # FILIGRANE DU LOGO (arrière-plan)
    c.saveState()
    c.setFillAlpha(0.08)  # Très transparent pour effet filigrane
    
    # Dessiner le logo en filigrane au centre
    filigrane_size = 35*mm
    filigrane_x = (width - filigrane_size) / 2
    filigrane_y = (height - filigrane_size) / 2
    
    try:
        if eleve.classe.ecole.logo and hasattr(eleve.classe.ecole.logo, 'path'):
            if os.path.exists(eleve.classe.ecole.logo.path):
                c.drawImage(eleve.classe.ecole.logo.path, 
                          filigrane_x, filigrane_y,
                          width=filigrane_size, height=filigrane_size,
                          preserveAspectRatio=True, mask='auto')
        else:
            # Filigrane texte si pas de logo
            c.setFillColor(colors.HexColor(primary_blue))
            c.setFont(bold_font, 48)
            c.rotate(30)
            ecole_initiales = ''.join([mot[0] for mot in eleve.classe.ecole.nom.split()[:3]])
            c.drawCentredString(width/2 + 10, height/2 - 10, ecole_initiales.upper())
    except:
        pass
    
    c.restoreState()
    
    # Bordure externe avec coins arrondis (optimisée pour PVC)
    c.setStrokeColor(colors.HexColor(primary_blue))
    c.setLineWidth(2)  # Plus épais pour PVC
    c.roundRect(1, 1, width-2, height-2, 6, stroke=1, fill=0)
    
    # 2. EN-TÊTE (Logo + Nom de l'école)
    header_height = 16*mm  # Augmenté de 14mm à 16mm pour plus d'espace
    
    # Fond dégradé pour l'en-tête
    c.setFillColor(colors.HexColor(primary_blue))
    c.roundRect(2, height - header_height - 1, width-4, header_height, 5, stroke=0, fill=1)
    
    # Logo de l'école
    logo_size = 12*mm  # Augmenté de 10mm à 12mm
    logo_x = 4*mm
    logo_y = height - 14*mm  # Ajusté pour le nouvel en-tête
    
    # Cercle blanc pour le logo
    c.setFillColor(colors.white)
    c.circle(logo_x + logo_size/2, logo_y + logo_size/2, logo_size/2, stroke=0, fill=1)
    
    # Insérer le logo ou les initiales
    try:
        if eleve.classe.ecole.logo and hasattr(eleve.classe.ecole.logo, 'path'):
            if os.path.exists(eleve.classe.ecole.logo.path):
                # Charger et traiter le logo
                c.drawImage(eleve.classe.ecole.logo.path, logo_x + 0.5, logo_y + 0.5, 
                          width=logo_size-1, height=logo_size-1, preserveAspectRatio=True, mask='auto')
    except:
        # Si pas de logo, afficher les initiales
        c.setFillColor(colors.HexColor(primary_blue))
        c.setFont(bold_font, 14)
        initiales = eleve.classe.ecole.nom[:2].upper()
        c.drawCentredString(logo_x + logo_size/2, logo_y + logo_size/2 - 2, initiales)
    
    # Nom de l'école
    c.setFillColor(colors.white)
    school_name = eleve.classe.ecole.nom.upper()
    
    # Ajuster la taille de police selon la longueur du nom (TAILLES AUGMENTÉES)
    if len(school_name) > 35:
        c.setFont(bold_font, 10)  # Police réduite mais lisible pour les noms longs
    elif len(school_name) > 25:
        c.setFont(bold_font, 12)  # Police moyenne augmentée
    else:
        c.setFont(bold_font, 14)  # Police normale augmentée
    
    # Afficher le nom complet sans troncature
    c.drawString(logo_x + logo_size + 3*mm, logo_y + logo_size - 3*mm, school_name)
    
    # Sous-titre
    c.setFont(italic_font, 7)
    c.drawString(logo_x + logo_size + 3*mm, logo_y + logo_size - 6*mm, "CARTE D'ÉTUDIANT")
    
    # 3. SECTION PHOTO (Gauche - 35% de la largeur)
    photo_section_width = width * 0.35
    photo_x = 4*mm
    photo_y = 8*mm
    photo_width = 24*mm
    photo_height = 30*mm
    
    # Cadre photo avec ombre
    c.setFillColor(colors.HexColor(light_gray))
    c.roundRect(photo_x + 0.5, photo_y - 0.5, photo_width, photo_height, 3, stroke=0, fill=1)
    
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor(border_color))
    c.setLineWidth(1)
    c.roundRect(photo_x, photo_y, photo_width, photo_height, 3, stroke=1, fill=1)
    
    # Insérer la photo de l'élève
    photo_inserted = False
    if eleve.photo:
        try:
            if hasattr(eleve.photo, 'path') and eleve.photo.name and os.path.exists(eleve.photo.path):
                img = Image.open(eleve.photo.path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Redimensionner en gardant le ratio
                img.thumbnail((int(photo_width*2.83-10), int(photo_height*2.83-10)), Image.Resampling.LANCZOS)
                
                # Sauvegarder temporairement
                temp_buffer = io.BytesIO()
                img.save(temp_buffer, format='JPEG', quality=95)
                temp_buffer.seek(0)
                
                # Centrer la photo dans le cadre
                img_width = (photo_width - 2*mm)
                img_height = (photo_height - 2*mm)
                img_x = photo_x + 1*mm
                img_y = photo_y + 1*mm
                
                # Utiliser ImageReader pour BytesIO
                from reportlab.lib.utils import ImageReader
                img_reader = ImageReader(temp_buffer)
                c.drawImage(img_reader, img_x, img_y, 
                          width=img_width, height=img_height, 
                          preserveAspectRatio=True)
                photo_inserted = True
        except Exception as e:
            print(f"Erreur lors du chargement de la photo: {e}")
    
    # Si pas de photo, afficher un placeholder
    if not photo_inserted:
        c.setFillColor(colors.HexColor(light_gray))
        c.rect(photo_x + 1, photo_y + 1, photo_width - 2, photo_height - 2, stroke=0, fill=1)
        
        # Icône utilisateur
        c.setFillColor(colors.HexColor(text_gray))
        c.setFont(bold_font, 24)
        c.drawCentredString(photo_x + photo_width/2, photo_y + photo_height/2 + 3, 
                          f"{eleve.prenom[0]}{eleve.nom[0]}".upper())
        
        c.setFont(main_font, 8)
        c.drawCentredString(photo_x + photo_width/2, photo_y + photo_height/2 - 5, "PHOTO")
    
    # 4. SECTION INFORMATIONS (Droite - 65% de la largeur)
    info_x = photo_x + photo_width + 4*mm
    info_y_start = height - header_height - 4*mm  # Ajusté pour le nouvel en-tête
    line_height = 5*mm
    
    # Nom complet (taille réduite)
    c.setFillColor(colors.HexColor(text_dark))
    c.setFont(bold_font, 9)
    nom_complet = f"{eleve.prenom} {eleve.nom}".upper()
    if len(nom_complet) > 25:
        nom_complet = nom_complet[:22] + "..."
    c.drawString(info_x, info_y_start, nom_complet)
    
    # Ligne de séparation subtile
    c.setStrokeColor(colors.HexColor(border_color))
    c.setLineWidth(0.5)
    c.line(info_x, info_y_start - 2*mm, width - 4*mm, info_y_start - 2*mm)
    
    # Informations détaillées
    info_y = info_y_start - 5*mm
    
    # Matricule
    c.setFont(bold_font, 7)
    c.setFillColor(colors.HexColor(text_gray))
    c.drawString(info_x, info_y, "Matricule:")
    c.setFont(main_font, 7)
    c.setFillColor(colors.HexColor(text_dark))
    c.drawString(info_x + 16*mm, info_y, eleve.matricule)
    
    # Classe
    info_y -= 3.5*mm
    c.setFont(bold_font, 7)
    c.setFillColor(colors.HexColor(text_gray))
    c.drawString(info_x, info_y, "Classe:")
    c.setFont(main_font, 7)
    c.setFillColor(colors.HexColor(text_dark))
    c.drawString(info_x + 16*mm, info_y, eleve.classe.nom)
    
    # Niveau
    info_y -= 3.5*mm
    c.setFont(bold_font, 7)
    c.setFillColor(colors.HexColor(text_gray))
    c.drawString(info_x, info_y, "Niveau:")
    c.setFont(main_font, 7)
    c.setFillColor(colors.HexColor(text_dark))
    c.drawString(info_x + 16*mm, info_y, eleve.classe.niveau)
    
    # Date de naissance et âge
    info_y -= 3.5*mm
    c.setFont(bold_font, 7)
    c.setFillColor(colors.HexColor(text_gray))
    c.drawString(info_x, info_y, "Né(e) le:")
    c.setFont(main_font, 7)
    c.setFillColor(colors.HexColor(text_dark))
    # Calculer l'âge
    from datetime import date
    today = date.today()
    age = today.year - eleve.date_naissance.year - ((today.month, today.day) < (eleve.date_naissance.month, eleve.date_naissance.day))
    date_info = f"{eleve.date_naissance.strftime('%d/%m/%Y')} ({age} ans)"
    c.drawString(info_x + 16*mm, info_y, date_info)
    
    # Lieu de naissance
    info_y -= 3.5*mm
    c.setFont(bold_font, 7)
    c.setFillColor(colors.HexColor(text_gray))
    c.drawString(info_x, info_y, "À:")
    c.setFont(main_font, 7)
    c.setFillColor(colors.HexColor(text_dark))
    lieu_naissance = eleve.lieu_naissance[:25] if len(eleve.lieu_naissance) > 25 else eleve.lieu_naissance
    c.drawString(info_x + 16*mm, info_y, lieu_naissance)
    
    # Année scolaire avec badge de validité
    info_y -= 4*mm
    c.setFillColor(colors.HexColor('#fef3c7'))
    c.roundRect(info_x - 1, info_y - 1, 45*mm, 5*mm, 2, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor('#fbbf24'))
    c.setLineWidth(0.5)
    c.roundRect(info_x - 1, info_y - 1, 45*mm, 5*mm, 2, stroke=1, fill=0)
    
    c.setFont(bold_font, 7)
    c.setFillColor(colors.HexColor('#92400e'))
    annee_scolaire = eleve.classe.annee_scolaire
    date_fin = timezone.now().date() + timedelta(days=365)
    c.drawString(info_x + 1, info_y + 1, f"Valide jusqu'au {date_fin.strftime('%d/%m/%Y')}")
    
    # 5. CONTACT D'URGENCE (en bas)
    contact_y = 4*mm
    
    # Ligne de séparation
    c.setStrokeColor(colors.HexColor(border_color))
    c.setLineWidth(0.3)
    c.setDash(1, 2)
    c.line(info_x, contact_y + 6*mm, width - 4*mm, contact_y + 6*mm)
    c.setDash()
    
    # Titre contact d'urgence
    c.setFont(bold_font, 6)
    c.setFillColor(colors.HexColor('#ef4444'))
    c.drawString(info_x, contact_y + 3.5*mm, "CONTACT D'URGENCE:")
    
    # Informations du contact
    if eleve.responsable_principal:
        c.setFont(main_font, 6)
        c.setFillColor(colors.HexColor(text_dark))
        
        # Nom complet du responsable (prénom et nom)
        resp_prenom = eleve.responsable_principal.prenom if hasattr(eleve.responsable_principal, 'prenom') else ""
        resp_nom = eleve.responsable_principal.nom if hasattr(eleve.responsable_principal, 'nom') else ""
        resp_complet = f"{resp_prenom} {resp_nom}".strip()
        if not resp_complet:
            resp_complet = eleve.responsable_principal.nom_complet[:30]
        else:
            resp_complet = resp_complet[:30]
        c.drawString(info_x, contact_y + 1*mm, resp_complet)
        
        # Téléphone et adresse sur la même ligne
        contact_info = ""
        if eleve.responsable_principal.telephone:
            contact_info = f"📞 {eleve.responsable_principal.telephone}"
        
        if eleve.responsable_principal.adresse:
            adresse_courte = eleve.responsable_principal.adresse[:25]
            if contact_info:
                contact_info += f" | {adresse_courte}"
            else:
                contact_info = adresse_courte
        
        c.setFont(main_font, 5.5)
        c.setFillColor(colors.HexColor(text_gray))
        c.drawString(info_x, contact_y - 1*mm, contact_info[:50])
    
    # 6. BANDE DÉCORATIVE EN BAS
    c.setFillColor(colors.HexColor(accent_green))
    c.rect(2, 1, width-4, 2, stroke=0, fill=1)
    
    # 7. MOTIF DE SÉCURITÉ (micro-texte pour PVC)
    c.saveState()
    c.setFont(main_font, 3)
    c.setFillColor(colors.HexColor('#e5e7eb'))
    security_text = f"{eleve.classe.ecole.nom} " * 10
    c.drawString(2, 0.5, security_text[:150])
    c.restoreState()
    
    # 8. Numéro de série et marquage PVC
    c.setFont(main_font, 5)
    c.setFillColor(colors.HexColor('#9ca3af'))
    c.drawRightString(width - 3*mm, 2*mm, f"#{eleve.id:06d}")
    c.drawString(3*mm, 2*mm, "PVC CARD")
    
    # 9. MARQUES DE DÉCOUPE pour impression PVC (coins)
    if False:  # Activer si nécessaire pour l'imprimeur
        c.setStrokeColor(colors.HexColor('#cbd5e1'))
        c.setLineWidth(0.25)
        mark_length = 3*mm
        # Coin supérieur gauche
        c.line(0, height-mark_length, 0, height)
        c.line(0, height, mark_length, height)
        # Coin supérieur droit
        c.line(width-mark_length, height, width, height)
        c.line(width, height, width, height-mark_length)
        # Coin inférieur gauche
        c.line(0, mark_length, 0, 0)
        c.line(0, 0, mark_length, 0)
        # Coin inférieur droit
        c.line(width-mark_length, 0, width, 0)
        c.line(width, 0, width, mark_length)
    
    c.showPage()
    c.save()
    return response


def generer_carte_pvc_haute_qualite(eleve, response, with_crop_marks=True):
    """
    Génère une carte scolaire optimisée pour l'impression PVC professionnelle
    Format CR80 standard: 85.6mm x 53.98mm (format carte bancaire)
    Résolution: 300 DPI minimum recommandé
    """
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import io
    import os
    
    # Dimensions standard carte PVC CR80
    width, height = 85.6*mm, 53.98*mm
    
    # Ajouter une marge de fond perdu (bleed) pour l'impression
    if with_crop_marks:
        bleed = 3*mm
        total_width = width + (2 * bleed)
        total_height = height + (2 * bleed)
        c = canvas.Canvas(response, pagesize=(total_width, total_height))
    else:
        c = canvas.Canvas(response, pagesize=(width, height))
        bleed = 0
    
    # Configuration haute résolution
    c.setPageCompression(0)  # Pas de compression pour qualité maximale
    
    # Enregistrement des polices
    try:
        pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:/Windows/Fonts/arialbd.ttf'))
        main_font = 'Arial'
        bold_font = 'Arial-Bold'
    except:
        main_font = 'Helvetica'
        bold_font = 'Helvetica-Bold'
    
    # Couleurs optimisées pour impression PVC (CMYK friendly)
    primary_blue = '#004494'  # Bleu plus foncé pour meilleur contraste
    text_black = '#000000'    # Noir pur pour texte
    
    # Zone de carte principale (avec bleed)
    card_x = bleed
    card_y = bleed
    
    # Fond blanc avec filigrane
    c.setFillColor(colors.white)
    c.rect(card_x, card_y, width, height, stroke=0, fill=1)
    
    # FILIGRANE HAUTE QUALITÉ
    c.saveState()
    c.setFillAlpha(0.06)  # Encore plus subtil pour PVC
    
    filigrane_size = 40*mm
    filigrane_x = card_x + (width - filigrane_size) / 2
    filigrane_y = card_y + (height - filigrane_size) / 2
    
    try:
        if eleve.classe.ecole.logo and hasattr(eleve.classe.ecole.logo, 'path'):
            if os.path.exists(eleve.classe.ecole.logo.path):
                # Rotation du filigrane pour effet professionnel
                c.translate(card_x + width/2, card_y + height/2)
                c.rotate(15)
                c.drawImage(eleve.classe.ecole.logo.path,
                          -filigrane_size/2, -filigrane_size/2,
                          width=filigrane_size, height=filigrane_size,
                          preserveAspectRatio=True, mask='auto')
    except:
        pass
    
    c.restoreState()
    
    # MARQUES DE DÉCOUPE (si activées)
    if with_crop_marks:
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.25)
        mark_length = 5*mm
        mark_offset = 1*mm
        
        # Coins avec marques de repérage
        corners = [
            (bleed, bleed),  # Bas gauche
            (bleed + width, bleed),  # Bas droit
            (bleed, bleed + height),  # Haut gauche
            (bleed + width, bleed + height)  # Haut droit
        ]
        
        for x, y in corners:
            # Marques horizontales
            c.line(x - bleed + mark_offset, y, x - mark_offset, y)
            c.line(x + mark_offset, y, x + bleed - mark_offset, y)
            # Marques verticales
            c.line(x, y - bleed + mark_offset, x, y - mark_offset)
            c.line(x, y + mark_offset, x, y + bleed - mark_offset)
    
    # Dessiner directement le contenu optimisé pour PVC
    # (Copie simplifiée du design principal avec optimisations PVC)
    
    # En-tête
    header_height = 12*mm
    c.setFillColor(colors.HexColor(primary_blue))
    c.roundRect(card_x + 1, card_y + height - header_height - 1, 
               width - 2, header_height, 4, stroke=0, fill=1)
    
    # Texte de l'école
    c.setFillColor(colors.white)
    school_name = eleve.classe.ecole.nom.upper()
    
    # Ajuster la taille de police selon la longueur du nom (PVC - TAILLES AUGMENTÉES)
    if len(school_name) > 35:
        c.setFont(bold_font, 9)  # Police réduite mais plus grande
    elif len(school_name) > 25:
        c.setFont(bold_font, 11)  # Police moyenne augmentée
    else:
        c.setFont(bold_font, 13)  # Police normale augmentée
    
    c.drawString(card_x + 5*mm, card_y + height - 8*mm, school_name)
    
    # Informations principales
    c.setFillColor(colors.HexColor(text_black))
    c.setFont(bold_font, 9)
    nom = f"{eleve.prenom} {eleve.nom}".upper()[:25]
    c.drawString(card_x + 30*mm, card_y + 32*mm, nom)
    
    c.setFont(main_font, 8)
    c.drawString(card_x + 30*mm, card_y + 27*mm, f"Mat: {eleve.matricule}")
    c.drawString(card_x + 30*mm, card_y + 23*mm, f"Classe: {eleve.classe.nom}")
    c.drawString(card_x + 30*mm, card_y + 19*mm, f"Niveau: {eleve.classe.niveau}")
    
    # Indicateur PVC
    c.setFont(main_font, 4)
    c.setFillColor(colors.HexColor('#9ca3af'))
    c.drawString(card_x + 2, card_y + 1, "PVC CARD - HIGH QUALITY")
    
    c.showPage()
    c.save()
    return response


def generer_cartes_classe_moderne(classe, eleves, response):
    """
    Génère plusieurs cartes par page pour une classe entière
    Format: 8 cartes par page A4
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    
    # Créer le canvas PDF
    c = canvas.Canvas(response, pagesize=A4)
    
    # Dimensions et positions pour l'impression en masse (4x2 = 8 cartes)
    page_width, page_height = A4
    
    # Dimensions fixes format PVC standard (CR80)
    card_width = 85.6*mm   # Largeur standard carte PVC
    card_height = 53.98*mm  # Hauteur standard carte PVC
    
    # Calcul des marges et espacements pour centrer les 8 cartes
    total_cards_width = 2 * card_width  # 2 colonnes
    total_cards_height = 4 * card_height  # 4 lignes
    
    # Espacement entre les cartes
    h_spacing = 5*mm  # Espacement horizontal
    v_spacing = 5*mm  # Espacement vertical
    
    # Marges automatiques pour centrer sur la page
    margin_x = (page_width - total_cards_width - h_spacing) / 2
    margin_y = (page_height - total_cards_height - 3*v_spacing) / 2
    
    # Positions des 8 cartes (4 lignes, 2 colonnes)
    positions = []
    for row in range(4):  # 4 lignes
        for col in range(2):  # 2 colonnes
            x = margin_x + col * (card_width + h_spacing)
            y = page_height - margin_y - (row + 1) * card_height - row * v_spacing
            positions.append((x, y))
    
    # Enregistrement des polices
    try:
        pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:/Windows/Fonts/arialbd.ttf'))
        main_font = 'Arial'
        bold_font = 'Arial-Bold'
    except:
        main_font = 'Helvetica'
        bold_font = 'Helvetica-Bold'
    
    # Recto verso : une feuille de versos après chaque feuille de rectos
    from .views import _dessiner_planches_recto_verso, _dessiner_ticket_retrait_verso
    _dessiner_planches_recto_verso(
        c, eleves, positions,
        lambda eleve, x, y: _dessiner_carte_simple(c, eleve, x, y, card_width, card_height, main_font, bold_font),
        lambda eleve, x, y: _dessiner_ticket_retrait_verso(c, eleve, x, y, card_width, card_height, main_font, bold_font),
    )
    c.save()
    return response


def _dessiner_carte_simple(c, eleve, x, y, width, height, main_font, bold_font):
    """Draw one print-ready CR80 student card for batch PDFs."""
    primary = "#1746a2"
    accent = "#0f766e"
    dark = "#0f172a"
    muted = "#64748b"
    line = "#dbe3ef"
    paper = "#ffffff"
    soft = "#f5f8fc"

    margin = 2.2 * mm
    header_h = 10.5 * mm
    footer_h = 6.2 * mm
    radius = 4.5

    school = eleve.classe.ecole
    school_name = _safe_text(getattr(school, "nom", "")).upper()
    student_name = _safe_text(f"{getattr(eleve, 'prenom', '')} {getattr(eleve, 'nom', '')}").upper()
    matricule = _safe_text(getattr(eleve, "matricule", ""))
    classe_nom = _safe_text(getattr(eleve.classe, "nom", ""))
    annee = _safe_text(getattr(eleve.classe, "annee_scolaire", ""))

    c.saveState()

    c.setFillColor(colors.HexColor(paper))
    c.setStrokeColor(colors.HexColor(line))
    c.setLineWidth(0.7)
    c.roundRect(x, y, width, height, radius, stroke=1, fill=1)

    c.setFillColor(colors.HexColor(primary))
    c.roundRect(x + 0.8, y + height - header_h - 0.8, width - 1.6, header_h, radius, stroke=0, fill=1)
    c.rect(x + 0.8, y + height - header_h - 0.8, width - 1.6, header_h / 2, stroke=0, fill=1)

    logo_size = 7.2 * mm
    logo_x = x + margin
    logo_y = y + height - header_h + 1.1 * mm
    c.setFillColor(colors.white)
    c.circle(logo_x + logo_size / 2, logo_y + logo_size / 2, logo_size / 2, stroke=0, fill=1)
    try:
        if school.logo and hasattr(school.logo, "path") and os.path.exists(school.logo.path):
            c.drawImage(
                school.logo.path,
                logo_x + 0.6,
                logo_y + 0.6,
                width=logo_size - 1.2,
                height=logo_size - 1.2,
                preserveAspectRatio=True,
                mask="auto",
            )
        else:
            raise ValueError("No logo")
    except Exception:
        c.setFillColor(colors.HexColor(primary))
        c.setFont(bold_font, 7)
        c.drawCentredString(logo_x + logo_size / 2, logo_y + logo_size / 2 - 2, school_name[:2] or "EC")

    title_x = logo_x + logo_size + 2 * mm
    title_w = width - (title_x - x) - margin
    _draw_fit_text(c, school_name, title_x, y + height - 5.1 * mm, title_w, bold_font, 7.6, 4.8, "#ffffff")
    _draw_fit_text(c, "CARTE SCOLAIRE", title_x, y + height - 8.2 * mm, title_w, main_font, 5.2, 4.2, "#dbeafe")

    try:
        c.saveState()
        c.setFillAlpha(0.06)
        if school.logo and hasattr(school.logo, "path") and os.path.exists(school.logo.path):
            mark = 30 * mm
            c.drawImage(
                school.logo.path,
                x + width - mark - 4 * mm,
                y + footer_h + 5 * mm,
                width=mark,
                height=mark,
                preserveAspectRatio=True,
                mask="auto",
            )
        else:
            c.setFillColor(colors.HexColor(primary))
            c.setFont(bold_font, 28)
            c.drawCentredString(x + width * 0.70, y + height * 0.46, school_name[:3])
        c.restoreState()
    except Exception:
        try:
            c.restoreState()
        except Exception:
            pass

    photo_w = 22.5 * mm
    photo_h = 27.5 * mm
    photo_x = x + margin
    photo_y = y + footer_h + 3.2 * mm
    c.setFillColor(colors.HexColor(soft))
    c.setStrokeColor(colors.HexColor(line))
    c.setLineWidth(0.7)
    c.roundRect(photo_x, photo_y, photo_w, photo_h, 3.2, stroke=1, fill=1)

    photo_drawn = False
    try:
        if eleve.photo and hasattr(eleve.photo, "path") and eleve.photo.name and os.path.exists(eleve.photo.path):
            _draw_cover_image(c, eleve.photo.path, photo_x + 1, photo_y + 1, photo_w - 2, photo_h - 2)
            photo_drawn = True
    except Exception:
        photo_drawn = False

    if not photo_drawn:
        initials = (_safe_text(getattr(eleve, "prenom", "E"))[:1] + _safe_text(getattr(eleve, "nom", "L"))[:1]).upper()
        c.setFillColor(colors.HexColor("#e8eef8"))
        c.roundRect(photo_x + 1, photo_y + 1, photo_w - 2, photo_h - 2, 2.5, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(primary))
        c.setFont(bold_font, 17)
        c.drawCentredString(photo_x + photo_w / 2, photo_y + photo_h / 2 - 4, initials or "EL")

    info_x = photo_x + photo_w + 3 * mm
    info_w = x + width - margin - info_x
    name_y = y + height - header_h - 4.4 * mm
    _draw_fit_text(c, student_name, info_x, name_y, info_w, bold_font, 8.7, 5.8, dark)

    c.setStrokeColor(colors.HexColor(accent))
    c.setLineWidth(1.0)
    c.line(info_x, name_y - 1.7 * mm, info_x + info_w, name_y - 1.7 * mm)

    row_y = name_y - 5.3 * mm
    label_w = 14 * mm
    value_w = info_w - label_w
    _draw_value_row(c, "Mat.", matricule, info_x, row_y, label_w, value_w, main_font, bold_font)
    row_y -= 4.2 * mm
    _draw_value_row(c, "Classe", classe_nom, info_x, row_y, label_w, value_w, main_font, bold_font)

    try:
        niveau = eleve.classe.get_niveau_display()
    except Exception:
        niveau = getattr(eleve.classe, "niveau", "")
    row_y -= 4.2 * mm
    _draw_value_row(c, "Niveau", niveau, info_x, row_y, label_w, value_w, main_font, bold_font)

    if getattr(eleve, "date_naissance", None):
        row_y -= 4.2 * mm
        _draw_value_row(c, "Ne(e)", eleve.date_naissance.strftime("%d/%m/%Y"), info_x, row_y, label_w, value_w, main_font, bold_font)

    if getattr(eleve, "lieu_naissance", None):
        row_y -= 4.2 * mm
        _draw_value_row(c, "Lieu", eleve.lieu_naissance, info_x, row_y, label_w, value_w, main_font, bold_font)

    resp = getattr(eleve, "responsable_principal", None)
    if resp:
        contact = _safe_text(getattr(resp, "telephone", "")) or _safe_text(getattr(resp, "nom_complet", ""))
        if contact:
            row_y -= 4.2 * mm
            _draw_value_row(c, "Contact", contact, info_x, row_y, label_w, value_w, main_font, bold_font)

    c.setFillColor(colors.HexColor("#eef4fb"))
    c.rect(x + 0.8, y + 0.8, width - 1.6, footer_h, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor(line))
    c.setLineWidth(0.5)
    c.line(x + 0.8, y + footer_h + 0.8, x + width - 0.8, y + footer_h + 0.8)

    _draw_fit_text(c, f"ANNEE SCOLAIRE {annee}", x + margin, y + 2.4 * mm, width * 0.55, bold_font, 5.8, 4.2, primary)
    c.setFillColor(colors.HexColor(muted))
    c.setFont(main_font, 4.6)
    c.drawRightString(x + width - margin, y + 2.4 * mm, f"ID #{getattr(eleve, 'id', 0):06d}")

    c.setStrokeColor(colors.HexColor(primary))
    c.setLineWidth(0.9)
    c.roundRect(x, y, width, height, radius, stroke=1, fill=0)
    c.restoreState()
    return

    """
    Dessine une carte simplifiée pour l'impression en masse
    """
    # Couleurs
    primary_blue = '#1e40af'
    text_dark = '#1f2937'
    text_gray = '#6b7280'
    border_color = '#e5e7eb'
    
    # FILIGRANE DU LOGO (arrière-plan) - Ajouté en premier pour être derrière
    c.saveState()
    c.setFillAlpha(0.15)  # Opacité augmentée pour meilleure visibilité du filigrane
    
    # Dessiner le logo en filigrane au centre de la carte
    filigrane_size = 25*mm  # Taille augmentée pour meilleure visibilité
    filigrane_x = x + (width - filigrane_size) / 2
    filigrane_y = y + (height - filigrane_size) / 2
    
    try:
        if eleve.classe.ecole.logo and hasattr(eleve.classe.ecole.logo, 'path'):
            if os.path.exists(eleve.classe.ecole.logo.path):
                # Rotation du filigrane pour effet professionnel
                c.translate(x + width/2, y + height/2)
                c.rotate(15)  # Rotation de 15 degrés
                c.drawImage(eleve.classe.ecole.logo.path,
                          -filigrane_size/2, -filigrane_size/2,
                          width=filigrane_size, height=filigrane_size,
                          preserveAspectRatio=True, mask='auto')
                c.rotate(-15)  # Annuler la rotation
                c.translate(-(x + width/2), -(y + height/2))
        else:
            # Filigrane texte si pas de logo
            c.setFillColor(colors.HexColor(primary_blue))
            c.setFont(bold_font, 24)
            c.translate(x + width/2, y + height/2)
            c.rotate(15)
            initiales = eleve.classe.ecole.nom[:3].upper()
            c.drawCentredString(0, 0, initiales)
            c.rotate(-15)
            c.translate(-(x + width/2), -(y + height/2))
    except:
        pass
    
    c.restoreState()  # Restaurer l'état normal (opacité normale)
    
    # Bordure de la carte
    c.setStrokeColor(colors.HexColor(primary_blue))
    c.setLineWidth(1)
    c.roundRect(x, y, width, height, 4, stroke=1, fill=0)
    
    # En-tête
    header_height = 7*mm  # Adapté pour format PVC
    c.setFillColor(colors.HexColor(primary_blue))
    c.roundRect(x+1, y+height-header_height-1, width-2, header_height, 3, stroke=0, fill=1)
    
    # Logo dans l'en-tête (à gauche)
    logo_size = 4.5*mm  # Adapté pour format PVC
    logo_x = x + 1.5*mm
    logo_y = y + height - 6*mm  # Ajusté
    
    # Cercle blanc pour le logo
    c.setFillColor(colors.white)
    c.circle(logo_x + logo_size/2, logo_y + logo_size/2, logo_size/2, stroke=0, fill=1)
    
    # Insérer le logo ou les initiales
    try:
        if eleve.classe.ecole.logo and hasattr(eleve.classe.ecole.logo, 'path'):
            if os.path.exists(eleve.classe.ecole.logo.path):
                c.drawImage(eleve.classe.ecole.logo.path, 
                          logo_x + 0.5, logo_y + 0.5,
                          width=logo_size-1, height=logo_size-1,
                          preserveAspectRatio=True, mask='auto')
            else:
                # Initiales si pas de logo
                c.setFillColor(colors.HexColor(primary_blue))
                c.setFont(bold_font, 6)  # Réduit de 10 à 6
                initiales = eleve.classe.ecole.nom[:2].upper()
                c.drawCentredString(logo_x + logo_size/2, logo_y + logo_size/2 - 1, initiales)
        else:
            # Initiales si pas de logo
            c.setFillColor(colors.HexColor(primary_blue))
            c.setFont(bold_font, 6)  # Réduit à 6
            initiales = eleve.classe.ecole.nom[:2].upper()
            c.drawCentredString(logo_x + logo_size/2, logo_y + logo_size/2 - 1, initiales)
    except:
        # En cas d'erreur, afficher les initiales
        c.setFillColor(colors.HexColor(primary_blue))
        c.setFont(bold_font, 6)  # Réduit à 6
        initiales = eleve.classe.ecole.nom[:2].upper()
        c.drawCentredString(logo_x + logo_size/2, logo_y + logo_size/2 - 1, initiales)
    
    # Nom de l'école (décalé à droite du logo)
    c.setFillColor(colors.white)
    school_name = eleve.classe.ecole.nom.upper()
    
    # Ajuster la taille de police selon la longueur du nom (cartes en masse - TAILLES AUGMENTÉES)
    available_width = width - (logo_x + logo_size + 3*mm)  # Espace disponible
    
    if len(school_name) > 30:
        c.setFont(bold_font, 6)  # Police plus grande pour les noms très longs
    elif len(school_name) > 22:
        c.setFont(bold_font, 7)  # Police moyenne augmentée
    else:
        c.setFont(bold_font, 8)  # Police normale augmentée
    
    # Si le nom est vraiment trop long, on peut le diviser sur deux lignes
    if len(school_name) > 40:
        # Trouver un point de coupure approprié
        mid_point = len(school_name) // 2
        space_index = school_name.rfind(' ', 0, mid_point + 10)
        if space_index == -1:
            space_index = mid_point
        
        line1 = school_name[:space_index].strip()
        line2 = school_name[space_index:].strip()
        
        c.drawString(logo_x + logo_size + 1*mm, y+height-4.5*mm, line1)
        c.drawString(logo_x + logo_size + 1*mm, y+height-6.5*mm, line2)
    else:
        c.drawString(logo_x + logo_size + 1*mm, y+height-5*mm, school_name)
    
    # Photo (simplifiée)
    photo_size = 22*mm  # Encore plus grande pour meilleure visibilité
    photo_x = x + 2*mm
    photo_y = y + 18*mm  # Remontée encore plus haut sur la carte
    
    c.setFillColor(colors.HexColor('#f3f4f6'))
    c.rect(photo_x, photo_y, photo_size, photo_size, stroke=1, fill=1)
    
    # Petit logo dans le coin supérieur gauche du cadre photo
    corner_logo_size = 3*mm  # Réduit de 5mm à 3mm
    corner_logo_x = photo_x + 0.5*mm
    corner_logo_y = photo_y + photo_size - corner_logo_size - 0.5*mm
    
    # Dessiner le petit logo avec transparence
    c.saveState()
    c.setFillAlpha(0.7)  # Semi-transparent
    
    # Fond blanc circulaire pour le logo
    c.setFillColor(colors.white)
    c.circle(corner_logo_x + corner_logo_size/2, corner_logo_y + corner_logo_size/2, 
             corner_logo_size/2, stroke=0, fill=1)
    
    # Logo ou initiales
    try:
        if eleve.classe.ecole.logo and hasattr(eleve.classe.ecole.logo, 'path'):
            if os.path.exists(eleve.classe.ecole.logo.path):
                c.drawImage(eleve.classe.ecole.logo.path,
                          corner_logo_x, corner_logo_y,
                          width=corner_logo_size, height=corner_logo_size,
                          preserveAspectRatio=True, mask='auto')
            else:
                # Initiales en bleu si pas de logo
                c.setFillColor(colors.HexColor(primary_blue))
                c.setFont(bold_font, 5)  # Réduit de 7 à 5
                initiales = eleve.classe.ecole.nom[0].upper()
                c.drawCentredString(corner_logo_x + corner_logo_size/2, 
                                  corner_logo_y + corner_logo_size/2 - 0.5, initiales)
        else:
            # Initiales en bleu si pas de logo
            c.setFillColor(colors.HexColor(primary_blue))
            c.setFont(bold_font, 5)  # Réduit de 7 à 5
            initiales = eleve.classe.ecole.nom[0].upper()
            c.drawCentredString(corner_logo_x + corner_logo_size/2, 
                              corner_logo_y + corner_logo_size/2 - 0.5, initiales)
    except:
        pass
    
    c.restoreState()  # Restaurer l'opacité normale
    
    # Gestion de la photo ou placeholder
    photo_drawn = False
    if eleve.photo:
        try:
            if hasattr(eleve.photo, 'path') and eleve.photo.name and os.path.exists(eleve.photo.path):
                from PIL import Image
                img = Image.open(eleve.photo.path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.thumbnail((int(photo_size*2.83), int(photo_size*2.83)), Image.Resampling.LANCZOS)
                temp_buffer = io.BytesIO()
                img.save(temp_buffer, format='JPEG', quality=90)
                temp_buffer.seek(0)
                # Utiliser ImageReader pour BytesIO
                from reportlab.lib.utils import ImageReader
                img_reader = ImageReader(temp_buffer)
                c.drawImage(img_reader, photo_x, photo_y, 
                          width=photo_size, height=photo_size, preserveAspectRatio=True)
                photo_drawn = True
        except:
            photo_drawn = False
    
    # Si pas de photo, afficher les initiales
    if not photo_drawn:
        c.setFillColor(colors.HexColor(text_gray))
        c.setFont(bold_font, 16)  # Encore plus grand pour photo agrandie
        c.drawCentredString(photo_x + photo_size/2, photo_y + photo_size/2 - 3, 
                          f"{eleve.prenom[0]}{eleve.nom[0]}".upper())
    
    # Informations de l'élève (ajustées pour photo plus grande)
    info_x = photo_x + photo_size + 3*mm  # Décalage adapté
    info_y = y + height - header_height - 6*mm  # Position descendue
    
    # Nom
    c.setFillColor(colors.HexColor(text_dark))
    c.setFont(bold_font, 10)  # Police réduite
    c.drawString(info_x, info_y, f"{eleve.prenom} {eleve.nom}".upper()[:20])
    
    # Matricule
    info_y -= 4.5*mm  # Espacement ajusté
    c.setFont(main_font, 11)  # Police maximale
    c.setFillColor(colors.HexColor(text_gray))
    c.drawString(info_x, info_y, f"Mat: {eleve.matricule}")
    
    # Classe et niveau
    info_y -= 4*mm  # Espacement ajusté
    c.setFont(main_font, 10)  # Police maximale
    c.drawString(info_x, info_y, f"Cl: {eleve.classe.nom[:16]}")
    
    # Date de naissance et âge
    info_y -= 4*mm  # Espacement ajusté
    c.setFont(main_font, 9)  # Police maximale
    if eleve.date_naissance:
        from datetime import date
        age = date.today().year - eleve.date_naissance.year
        if date.today() < date(date.today().year, eleve.date_naissance.month, eleve.date_naissance.day):
            age -= 1
        c.drawString(info_x, info_y, f"{eleve.date_naissance.strftime('%d/%m/%Y')} ({age}a)")
    
    # Lieu de naissance
    if eleve.lieu_naissance:
        info_y -= 3.5*mm  # Espacement ajusté
        c.setFont(main_font, 9)  # Police maximale
        c.drawString(info_x, info_y, f"{eleve.lieu_naissance[:18]}")
    
    # Responsable
    info_y -= 4*mm  # Espacement ajusté
    c.setFont(bold_font, 9)  # Police maximale
    c.setFillColor(colors.HexColor(text_dark))
    c.drawString(info_x, info_y, "Contact:")
    
    c.setFont(main_font, 9)  # Police maximale
    c.setFillColor(colors.HexColor(text_gray))
    
    if eleve.responsable_principal:
        info_y -= 3.5*mm  # Espacement ajusté
        resp = eleve.responsable_principal
        if resp.prenom and resp.nom:
            c.drawString(info_x, info_y, f"{resp.prenom} {resp.nom}".upper()[:18])
        
        if resp.telephone:
            info_y -= 3*mm  # Espacement ajusté
            c.drawString(info_x, info_y, f"{resp.telephone}")
        
        # Adresse (version condensée)
        if resp.adresse:
            info_y -= 3*mm  # Espacement ajusté
            adresse = resp.adresse[:20]  # Adapté PVC
            c.drawString(info_x, info_y, adresse)
    
    # Année scolaire en bas
    c.setFont(main_font, 6)  # Police maximale
    c.setFillColor(colors.HexColor(text_gray))
    c.drawString(x + 2*mm, y + 2*mm, f"AS {eleve.classe.annee_scolaire}")
