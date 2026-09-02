from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from ecole_moderne.theme import DEFAULT_PALETTE, get_school_palette
from utilisateurs.context_processors import user_context

from .forms_charte import COLOR_FIELDS
from .models import Ecole


class CharteGraphiqueTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(nom="École Palette")
        self.autre_ecole = Ecole.objects.create(nom="Autre École")
        self.admin = User.objects.create_user("admin-palette", password="test-pass")
        self.admin.profil.role = "ADMIN"
        self.admin.profil.ecole = self.ecole
        self.admin.profil.save(update_fields=["role", "ecole"])
        self.client.force_login(self.admin)
        self.url = reverse("eleves:charte_graphique")

    def _payload(self, **overrides):
        payload = {
            "ecole_id": str(self.ecole.pk),
            "action": "save",
            "afficher_filigrane": "on",
            "opacite_filigrane": "0.12",
        }
        for key, field_name in {
            "primary": "couleur_principale",
            "secondary": "couleur_secondaire",
            "accent": "couleur_accent",
            "light": "couleur_fond_clair",
            "text": "couleur_texte",
            "success": "couleur_succes",
            "warning": "couleur_avertissement",
            "danger": "couleur_danger",
            "eleves": "couleur_carte_eleves",
            "paiements": "couleur_carte_paiements",
            "notes": "couleur_carte_notes",
            "salaires": "couleur_carte_salaires",
            "bus": "couleur_carte_bus",
            "cantine": "couleur_carte_cantine",
            "depenses": "couleur_carte_depenses",
        }.items():
            payload[field_name] = DEFAULT_PALETTE[key]
        payload.update(overrides)
        return payload

    def test_admin_ecole_peut_afficher_et_enregistrer_sa_charte(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aperçu en direct")

        response = self.client.post(
            self.url,
            self._payload(couleur_principale="#6D28D9", couleur_carte_notes="#0F766E"),
        )
        self.assertRedirects(response, f"{self.url}?ecole={self.ecole.pk}")
        self.ecole.refresh_from_db()
        self.assertEqual(self.ecole.couleur_principale, "#6D28D9")
        self.assertEqual(self.ecole.couleur_carte_notes, "#0F766E")
        self.assertEqual(self.ecole.opacite_filigrane, 0.12)

    def test_admin_ecole_ne_peut_pas_modifier_une_autre_ecole(self):
        response = self.client.post(
            self.url,
            self._payload(ecole_id=str(self.autre_ecole.pk)),
        )
        self.assertEqual(response.status_code, 404)

    def test_validation_refuse_une_couleur_invalide(self):
        response = self.client.post(
            self.url,
            self._payload(couleur_principale="rouge"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "couleur_principale",
            "Saisissez une couleur hexadécimale valide, par exemple #3563AE.",
        )

    def test_reinitialisation_retablit_toute_la_palette(self):
        self.ecole.couleur_principale = "#111111"
        self.ecole.couleur_carte_paiements = "#222222"
        self.ecole.afficher_filigrane = False
        self.ecole.save()
        response = self.client.post(
            self.url,
            {"ecole_id": self.ecole.pk, "action": "reset"},
        )
        self.assertEqual(response.status_code, 302)
        self.ecole.refresh_from_db()
        self.assertEqual(self.ecole.couleur_principale, DEFAULT_PALETTE["primary"])
        self.assertEqual(self.ecole.couleur_carte_paiements, DEFAULT_PALETTE["paiements"])
        self.assertTrue(self.ecole.afficher_filigrane)

    def test_contexte_global_expose_la_palette_de_lecole(self):
        self.ecole.couleur_principale = "#123456"
        self.ecole.save(update_fields=["couleur_principale"])
        request = RequestFactory().get("/")
        request.user = self.admin
        palette = user_context(request)["charte_graphique"]
        self.assertEqual(palette["primary"], "#123456")
        self.assertIn("primary_soft", palette)

    def test_palette_est_complete_sans_ecole(self):
        palette = get_school_palette()
        self.assertEqual(len(COLOR_FIELDS), 15)
        self.assertEqual(palette["primary"], DEFAULT_PALETTE["primary"])
        self.assertEqual(set(palette["rgb"]), {
            "primary", "secondary", "accent", "success", "warning", "danger",
        })
