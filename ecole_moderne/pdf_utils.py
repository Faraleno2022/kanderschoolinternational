from django.contrib.staticfiles import finders

try:
    # ReportLab imports are optional to avoid import errors where not installed
    from reportlab.lib.pagesizes import A4
except Exception:  # pragma: no cover
    A4 = (595.27, 841.89)


def draw_logo_watermark(c, width=None, height=None, *, opacity=None, rotate=30, scale=1.5, ecole=None):
    """
    Dessine un filigrane (logo) discret et centré sur la page courante du canvas ReportLab.

    - c: canvas ReportLab
    - width/height: dimensions de la page. Si None, utilise A4.
    - opacity: opacité du filigrane (0.04 = 4%)
    - rotate: rotation en degrés (par défaut 30)
    - scale: facteur d'échelle par rapport à la largeur de page (1.5 = 150%)
    - ecole: objet École optionnel. Si fourni et ecole.logo existe, utilise le logo de cette école
    """
    if width is None or height is None:
        width, height = A4

    if ecole is not None and not getattr(ecole, 'afficher_filigrane', True):
        return
    if ecole is not None:
        from ecole_moderne.theme import get_school_palette
        opacity = get_school_palette(ecole)['watermark_opacity']
    elif opacity is None:
        opacity = 0.04

    # 1) Préférence pour le logo spécifique à l'école s'il est fourni et disponible
    logo_path = None
    try:
        import os
        if ecole is not None and hasattr(ecole, 'logo'):
            school_logo_path = getattr(getattr(ecole, 'logo', None), 'path', None)
            if school_logo_path and os.path.exists(school_logo_path):
                logo_path = school_logo_path
    except Exception:
        logo_path = None

    # 2) Fallback vers le logo global statique
    if not logo_path:
        logo_path = finders.find('logos/logo.png')
    if not logo_path:
        return  # Pas de logo, on ne dessine rien (évite les erreurs)

    c.saveState()
    try:
        # Opacité discrète
        try:
            c.setFillAlpha(opacity)
        except Exception:
            # Certaines versions de reportlab ne supportent pas l'alpha
            pass

        # Taille du watermark: carré basé sur la largeur de page
        wm_width = width * scale
        wm_height = wm_width
        wm_x = (width - wm_width) / 2
        wm_y = (height - wm_height) / 2

        # Légère rotation
        c.translate(width / 2.0, height / 2.0)
        c.rotate(rotate)
        c.translate(-width / 2.0, -height / 2.0)

        # Dessin
        c.drawImage(
            logo_path,
            wm_x,
            wm_y,
            width=wm_width,
            height=wm_height,
            preserveAspectRatio=True,
            mask='auto'
        )
    finally:
        c.restoreState()
