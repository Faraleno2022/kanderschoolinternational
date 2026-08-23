"""Réduction des photos destinées au site public.

Les activités culturelles sont illustrées par des photos d'appareil : la
page d'accueil les affichait dans des vignettes de 356x220 px tout en
servant les originaux, soit une quinzaine de mégaoctets chacun. Le
redimensionnement se fait une fois, à l'enregistrement, plutôt qu'à chaque
visite.
"""

import logging
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

# Une vignette occupe au plus ~700 px de large sur un grand écran ; 1600 px
# laisse de la marge pour les écrans à haute densité et pour un éventuel
# agrandissement, sans conserver les 6000 px d'un reflex.
LARGEUR_MAX = 1600
QUALITE_JPEG = 82
# Une image déjà aux bonnes dimensions n'est reprise que si elle reste
# anormalement lourde. Le seuil est haut à dessein : notre propre sortie
# (1600 px, qualité 82) ne l'atteint jamais, donc repasser la commande sur
# une image déjà traitée ne la recompresse pas — sans quoi chaque exécution
# dégraderait un peu plus la photo.
SEUIL_RECOMPRESSION = 1536 * 1024


def optimiser_image(fichier, *, largeur_max=LARGEUR_MAX, qualite=QUALITE_JPEG,
                    seuil_octets=SEUIL_RECOMPRESSION):
    """Retourne (ContentFile, nom) réduits, ou (None, None) s'il n'y a rien à gagner.

    L'opération est idempotente : réappliquée à sa propre sortie, elle ne
    fait rien.

    L'orientation EXIF est appliquée avant que les métadonnées ne soient
    perdues : sans cela, une photo prise en portrait ressortirait couchée.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - Pillow est requis par ImageField
        logger.warning("Pillow indisponible : image servie telle quelle.")
        return None, None

    try:
        taille = getattr(fichier, 'size', 0) or 0
    except Exception:
        taille = 0

    try:
        fichier.open('rb') if hasattr(fichier, 'open') else None
        fichier.seek(0)
        image = Image.open(fichier)
        image.load()
    except Exception:
        logger.exception("Image illisible, laissée telle quelle.")
        return None, None

    largeur, hauteur = image.size
    trop_grande = max(largeur, hauteur) > largeur_max
    trop_lourde = taille > seuil_octets
    if not trop_grande and not trop_lourde:
        return None, None

    try:
        image = ImageOps.exif_transpose(image)
        # La transparence n'a pas de sens sur ces photos et empêcherait
        # l'encodage JPEG : on aplatit sur du blanc le cas échéant.
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGBA')
            fond = Image.new('RGB', image.size, (255, 255, 255))
            fond.paste(image, mask=image.split()[-1])
            image = fond
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        image.thumbnail((largeur_max, largeur_max), Image.Resampling.LANCZOS)

        tampon = BytesIO()
        image.save(tampon, format='JPEG', quality=qualite, optimize=True, progressive=True)
    except Exception:
        logger.exception("Optimisation impossible, image laissée telle quelle.")
        return None, None

    nom_origine = Path(getattr(fichier, 'name', 'image') or 'image').name
    nom = f"{Path(nom_origine).stem}.jpg"
    return ContentFile(tampon.getvalue()), nom
