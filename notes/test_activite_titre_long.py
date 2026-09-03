from pathlib import Path

from django.conf import settings
from django.forms import Textarea
from django.test import SimpleTestCase

from notes.forms import ActiviteJournaliereForm
from notes.models import ActiviteJournaliere


class ActiviteTitreLongTests(SimpleTestCase):
    def test_titre_accepte_jusqu_a_500_caracteres(self):
        model_field = ActiviteJournaliere._meta.get_field('titre')
        form_field = ActiviteJournaliereForm.base_fields['titre']

        self.assertEqual(model_field.max_length, 500)
        self.assertEqual(form_field.max_length, 500)
        self.assertIsInstance(form_field.widget, Textarea)
        self.assertEqual(form_field.widget.attrs['rows'], 2)
        self.assertEqual(int(form_field.widget.attrs['maxlength']), 500)

    def test_formulaire_affiche_une_zone_large_et_un_compteur(self):
        template = (
            Path(settings.BASE_DIR)
            / 'templates'
            / 'notes'
            / 'activites'
            / 'form.html'
        ).read_text(encoding='utf-8')

        self.assertIn('max-width: 1100px', template)
        self.assertIn('activity-title-input', template)
        self.assertIn('title-character-counter', template)
        self.assertIn('Titre de l\'activité', template)
        self.assertIn('500 caractères maximum', template)
