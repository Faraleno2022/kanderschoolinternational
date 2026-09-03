from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ResponsiveNavigationTemplateTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = (
            Path(settings.BASE_DIR) / 'templates' / 'base.html'
        ).read_text(encoding='utf-8')

    def test_bootstrap_local_est_charge_sans_dependre_du_mode_hors_ligne(self):
        self.assertEqual(
            self.template.count("vendor/bootstrap/bootstrap.bundle.min.js"),
            1,
        )
        self.assertEqual(
            self.template.count("vendor/bootstrap/bootstrap.min.css"),
            1,
        )
        self.assertNotIn(
            'cdn.jsdelivr.net/npm/bootstrap',
            self.template,
        )

    def test_hamburger_est_accessible_et_lie_au_menu(self):
        self.assertIn('navbar-expand-xxl', self.template)
        self.assertIn('data-bs-target="#navbarNav"', self.template)
        self.assertIn('aria-controls="navbarNav"', self.template)
        self.assertIn('aria-expanded="false"', self.template)
        self.assertIn('id="navbarNav"', self.template)

    def test_menu_tablette_est_defilable_et_dispose_d_un_secours_javascript(self):
        self.assertIn('@media (max-width: 1399.98px)', self.template)
        self.assertIn('max-height: calc(100dvh - 70px)', self.template)
        self.assertIn('overflow-y: auto', self.template)
        self.assertIn("menu.classList.toggle('show')", self.template)
        self.assertIn('Collapse.getOrCreateInstance', self.template)
