"""Réduction des photos d'activités culturelles avant mise en ligne.

Le site servait les originaux d'appareil photo — une quinzaine de Mo — dans
des vignettes de 356x220 px.
"""

import shutil
import tempfile
from io import BytesIO, StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from notes.image_optimizer import optimiser_image
from notes.models import ActiviteCulturelle


MEDIA_TEMPORAIRE = tempfile.mkdtemp(prefix='test_media_activites_')


def _photo(largeur, hauteur, *, nom='DSC_0512.jpg', format='JPEG', couleur=None):
    """Fabrique une photo pleine de bruit, donc peu compressible."""
    from PIL import Image
    import random

    image = Image.new('RGB', (largeur, hauteur))
    random.seed(1)
    # Un dégradé bruité pèse lourd, comme une vraie photo — un aplat uni se
    # compresserait à quelques kilo-octets et ne prouverait rien.
    image.putdata([
        (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        for _ in range(largeur * hauteur)
    ])
    tampon = BytesIO()
    image.save(tampon, format=format, quality=95)
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAIRE)
class OptimiserImageTest(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TEMPORAIRE, ignore_errors=True)
        super().tearDownClass()

    def test_une_grande_photo_est_reduite(self):
        contenu, nom = optimiser_image(_photo(3000, 2000))

        self.assertIsNotNone(contenu)
        self.assertTrue(nom.endswith('.jpg'))

        from PIL import Image
        reduite = Image.open(BytesIO(contenu.read()))
        self.assertLessEqual(max(reduite.size), 1600)
        # Le rapport 3:2 doit être conservé.
        self.assertAlmostEqual(reduite.size[0] / reduite.size[1], 1.5, places=2)

    def test_le_poids_chute(self):
        origine = _photo(3000, 2000)
        taille_avant = origine.size

        contenu, _ = optimiser_image(origine)

        self.assertLess(len(contenu.read()), taille_avant / 4)

    def test_une_image_deja_legere_est_laissee_telle_quelle(self):
        """Recompresser une petite image ne ferait que dégrader sa qualité."""
        contenu, nom = optimiser_image(_photo(600, 400))

        self.assertIsNone(contenu)
        self.assertIsNone(nom)

    def test_l_operation_est_idempotente(self):
        """Réappliquée à sa propre sortie, l'optimisation ne doit rien faire.

        Sinon chaque passage de la commande dégraderait un peu plus la photo.
        """
        contenu, nom = optimiser_image(_photo(3000, 2000))
        deja_optimisee = SimpleUploadedFile(nom, contenu.read())

        rebelote, _ = optimiser_image(deja_optimisee)

        self.assertIsNone(rebelote)

    def test_l_orientation_exif_est_appliquee_avant_d_etre_perdue(self):
        """Sans cela, une photo prise en portrait ressortirait couchée."""
        from PIL import Image

        tampon = BytesIO()
        image = Image.new('RGB', (2400, 1600), (120, 90, 60))
        exif = image.getexif()
        exif[274] = 6  # rotation 90° imposée par l'appareil
        image.save(tampon, format='JPEG', exif=exif, quality=95)
        fichier = SimpleUploadedFile('portrait.jpg', tampon.getvalue())

        contenu, _ = optimiser_image(fichier)

        redressee = Image.open(BytesIO(contenu.read()))
        self.assertLess(redressee.size[0], redressee.size[1])

    def test_un_png_transparent_devient_un_jpeg_lisible(self):
        from PIL import Image

        tampon = BytesIO()
        Image.new('RGBA', (2000, 2000), (0, 0, 0, 0)).save(tampon, format='PNG')
        fichier = SimpleUploadedFile('logo.png', tampon.getvalue())

        contenu, nom = optimiser_image(fichier)

        self.assertEqual(nom, 'logo.jpg')
        self.assertEqual(Image.open(BytesIO(contenu.read())).mode, 'RGB')

    def test_un_fichier_illisible_ne_fait_pas_echouer_l_enregistrement(self):
        fichier = SimpleUploadedFile('casse.jpg', b'ceci nest pas une image')

        contenu, nom = optimiser_image(fichier)

        self.assertIsNone(contenu)
        self.assertIsNone(nom)


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAIRE)
class ActiviteCulturelleSaveTest(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TEMPORAIRE, ignore_errors=True)
        super().tearDownClass()

    def test_l_image_est_reduite_a_l_enregistrement(self):
        origine = _photo(3000, 2000)
        taille_avant = origine.size

        activite = ActiviteCulturelle.objects.create(
            titre="Fête de fin d'année", description="Spectacle des élèves",
            image=origine,
        )

        self.assertLess(activite.image.size, taille_avant / 4)
        from PIL import Image
        self.assertLessEqual(max(Image.open(activite.image.path).size), 1600)

    def test_un_reenregistrement_ne_recompresse_pas(self):
        """Sans garde, chaque sauvegarde dégraderait un peu plus la photo."""
        activite = ActiviteCulturelle.objects.create(
            titre="Sortie au zoo", description="Visite guidée",
            image=_photo(3000, 2000),
        )
        taille_apres_upload = activite.image.size
        nom_apres_upload = activite.image.name

        activite.titre = "Sortie au zoo (corrigé)"
        activite.save()

        activite.refresh_from_db()
        self.assertEqual(activite.image.name, nom_apres_upload)
        self.assertEqual(activite.image.size, taille_apres_upload)


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAIRE)
class CommandeOptimisationTest(TestCase):
    """La commande reprend les photos déjà en ligne, que l'upload ne touche pas."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TEMPORAIRE, ignore_errors=True)
        super().tearDownClass()

    def _activite_avec_original(self, titre):
        """Crée une activité en court-circuitant l'optimisation à l'upload,
        pour reproduire l'état des photos déjà enregistrées."""
        activite = ActiviteCulturelle.objects.create(
            titre=titre, description="Photo d'appareil non réduite",
            image=_photo(600, 400),
        )
        activite.image.save('original.jpg', _photo(3000, 2000), save=True)
        return activite

    def test_simulation_ne_modifie_rien(self):
        activite = self._activite_avec_original("Kermesse")
        taille_avant = activite.image.size

        sortie = StringIO()
        call_command('optimiser_images_activites', '--dry-run', stdout=sortie)

        activite.refresh_from_db()
        self.assertEqual(activite.image.size, taille_avant)
        self.assertIn('SIMULATION', sortie.getvalue())

    def test_les_images_existantes_sont_reduites(self):
        activite = self._activite_avec_original("Carnaval")
        taille_avant = activite.image.size

        call_command('optimiser_images_activites', stdout=StringIO())

        activite.refresh_from_db()
        self.assertLess(activite.image.size, taille_avant / 4)
        from PIL import Image
        self.assertLessEqual(max(Image.open(activite.image.path).size), 1600)

    def test_relancer_la_commande_ne_degrade_pas(self):
        """Une deuxième passe doit reconnaître une image déjà légère."""
        activite = self._activite_avec_original("Spectacle")
        call_command('optimiser_images_activites', stdout=StringIO())
        activite.refresh_from_db()
        taille_apres_premiere_passe = activite.image.size

        call_command('optimiser_images_activites', stdout=StringIO())

        activite.refresh_from_db()
        self.assertEqual(activite.image.size, taille_apres_premiere_passe)
