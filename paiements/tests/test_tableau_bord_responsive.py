from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class TableauBordPaiementsResponsiveTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = (
            Path(settings.BASE_DIR)
            / 'templates'
            / 'paiements'
            / 'tableau_bord.html'
        ).read_text(encoding='utf-8')

    def test_actions_et_blocs_financiers_peuvent_revenir_a_la_ligne(self):
        self.assertIn('payments-page-actions d-flex flex-wrap gap-2', self.template)
        self.assertIn('audit-card-header', self.template)
        self.assertIn('payment-entry-row', self.template)
        self.assertIn('overdue-entry-row', self.template)
        self.assertIn('payment-mode-row', self.template)

    def test_grilles_passent_sur_une_colonne_sur_telephone(self):
        self.assertIn('@media (max-width: 575.98px)', self.template)
        self.assertIn(
            '.category-period-grid,\n        .audit-period-grid { grid-template-columns: minmax(0, 1fr); }',
            self.template,
        )
        self.assertIn('overflow-wrap: anywhere', self.template)
