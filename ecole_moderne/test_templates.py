"""Vérification de la syntaxe des modèles HTML livrés avec l'application."""
from pathlib import Path
from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase


class SyntaxeTemplatesTests(SimpleTestCase):
    def test_tous_les_templates_compilent(self):
        racine = Path(settings.BASE_DIR) / 'templates'
        moteur = engines['django'].engine
        for fichier in sorted(racine.rglob('*.html')):
            with self.subTest(template=str(fichier.relative_to(racine))):
                moteur.from_string(fichier.read_text(encoding='utf-8-sig'))
