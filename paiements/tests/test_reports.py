from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class PaiementsReportsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass1234")
        self.client.force_login(self.user)

    def test_export_periode_excel_ok(self):
        url = reverse("paiements:export_paiements_periode_excel")
        resp = self.client.get(url, {"du": "2025-01-01", "au": "2025-12-31"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", resp["Content-Type"]) 
        # Content-Disposition should include a filename
        self.assertIn("attachment; filename=\"paiements_periode.xlsx\"", resp.get("Content-Disposition", ""))

    def test_rapport_retards_ok(self):
        url = reverse("paiements:rapport_retards")
        resp = self.client.get(url)
        # Either HTML page or fallback string, but HTTP 200
        self.assertEqual(resp.status_code, 200)

    def test_rapport_encaissements_ok(self):
        url = reverse("paiements:rapport_encaissements")
        resp = self.client.get(url, {"du": "2025-01-01", "au": "2025-12-31"})
        self.assertEqual(resp.status_code, 200)
