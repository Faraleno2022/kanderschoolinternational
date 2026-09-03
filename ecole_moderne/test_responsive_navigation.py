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
            self.template.count('vendor/bootstrap/bootstrap.bundle.min.js'),
            1,
        )
        self.assertEqual(
            self.template.count('vendor/bootstrap/bootstrap.min.css'),
            1,
        )
        self.assertNotIn('cdn.jsdelivr.net/npm/bootstrap', self.template)

    def test_detection_couvre_ios_android_et_les_tablettes_tactiles(self):
        self.assertIn('Android|iPhone|iPad|iPod', self.template)
        self.assertIn("navigator.platform === 'MacIntel'", self.template)
        self.assertIn("'(hover: none) and (pointer: coarse)'", self.template)
        self.assertIn("classList.add('touch-navigation')", self.template)
        self.assertNotIn("'desktop-navigation'", self.template)

    def test_ordinateur_retrouve_la_navbar_bootstrap_d_origine(self):
        self.assertIn('navbar navbar-expand-lg navbar-dark', self.template)
        self.assertNotIn('.desktop-navigation .app-navbar', self.template)
        self.assertIn('padding: 0.5rem 0.55rem', self.template)
        self.assertIn('font-size: 0.84rem', self.template)
        self.assertIn('@media (max-width: 991.98px)', self.template)

    def test_hamburger_tactile_est_accessible_et_lie_au_menu(self):
        self.assertIn('data-bs-target="#navbarNav"', self.template)
        self.assertIn('aria-controls="navbarNav"', self.template)
        self.assertIn('aria-expanded="false"', self.template)
        self.assertIn('id="navbarNav"', self.template)
        self.assertIn(
            '.touch-navigation .app-navbar .navbar-toggler',
            self.template,
        )

    def test_menu_tactile_est_defilable_et_dispose_d_un_secours_javascript(self):
        self.assertIn('max-height: calc(100dvh - 70px)', self.template)
        self.assertIn('overflow-y: auto', self.template)
        self.assertIn("menu.classList.toggle('show')", self.template)
        self.assertIn('Collapse.getOrCreateInstance', self.template)
