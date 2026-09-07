from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from . import test_export_presences as export_support
from .models import EtatSalaire, PeriodeSalaire, PresenceEnseignant, TypeEnseignant
from .tests import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class PointageAccesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        export_support.ExportPresencesExcelTests.setUpTestData.__func__(cls)

    def page_pointage(self, user):
        self.client.force_login(user)
        response = self.client.get(
            reverse("salaires:pointer_presence"), {"date": "2026-09-07"}
        )
        self.assertEqual(response.status_code, 200)
        return response

    def pointer(self, user, *enseignants):
        self.client.force_login(user)
        data = {"date": "2026-09-07", "enseignants": [ens.pk for ens in enseignants]}
        for ens in enseignants:
            data.update({
                f"statut_{ens.pk}": "PRESENT",
                f"heures_travaillees_{ens.pk}": "4",
            })
        return self.client.post(reverse("salaires:pointer_presence"), data)

    def test_superadmin_sans_ecole_voit_les_noms_et_cumuls(self):
        response = self.page_pointage(self.admin)
        for ens in (self.enseignant, self.autre_enseignant):
            self.assertContains(response, ens.nom)
        self.assertEqual(response.context["stats_jour"]["total_enseignants"], 2)
        self.assertEqual(response.context["stats_jour"]["total_heures"], Decimal("6"))
        self.assertEqual(response.context["total_heures_mois"], Decimal("21.5"))
        self.assertIn(self.enseignant.pk, response.context["presences_existantes"])
        self.assertEqual(
            response.context["heures_mois_par_enseignant"][self.autre_enseignant.pk]["heures"],
            Decimal("8"),
        )

    def test_superadmin_sans_profil_voit_les_enseignants(self):
        self.admin.profil.delete()
        response = self.page_pointage(self.admin)
        self.assertEqual(response.context["enseignants"].count(), 2)

    def test_compte_ecole_reste_limite_a_ses_enseignants(self):
        for user in (self.user, self.admin):
            with self.subTest(user=user.username):
                user.profil.ecole = self.ecole
                user.profil.save()
                response = self.page_pointage(user)
                self.assertEqual(list(response.context["enseignants"]), [self.enseignant])
                self.assertNotContains(response, self.autre_enseignant.nom)
                self.assertEqual(response.context["total_heures_mois"], Decimal("13.5"))

    def test_compte_sans_ecole_ne_voit_ni_ne_pointe_autrui(self):
        self.user.profil.ecole = None
        self.user.profil.save()
        response = self.page_pointage(self.user)
        self.assertEqual(response.context["enseignants"].count(), 0)
        self.assertEqual(response.context["total_heures_mois"], 0)
        self.assertContains(response, "Aucune école n’est associée à votre compte")
        self.pointer(self.user, self.autre_enseignant)
        self.assertFalse(PresenceEnseignant.objects.filter(
            enseignant=self.autre_enseignant, date=date(2026, 9, 7)
        ).exists())

    def test_enseignant_inactif_non_affiche_et_pointage_refuse(self):
        self.autre_enseignant.statut = "INACTIF"
        self.autre_enseignant.save()
        response = self.page_pointage(self.admin)
        self.assertEqual(list(response.context["enseignants"]), [self.enseignant])
        self.pointer(self.admin, self.autre_enseignant)
        self.assertFalse(PresenceEnseignant.objects.filter(
            enseignant=self.autre_enseignant, date=date(2026, 9, 7)
        ).exists())

    def test_selection_melangeant_les_ecoles_est_refusee_sans_modification(self):
        self.pointer(self.user, self.enseignant, self.autre_enseignant)
        presence = PresenceEnseignant.objects.get(
            enseignant=self.enseignant, date=date(2026, 9, 7)
        )
        self.assertEqual(presence.heures_travaillees, Decimal("6"))
        self.assertFalse(PresenceEnseignant.objects.filter(
            enseignant=self.autre_enseignant, date=date(2026, 9, 7)
        ).exists())

    def test_superadmin_enregistre_et_recalcule_le_salaire_de_la_bonne_ecole(self):
        self.autre_enseignant.type_enseignant = TypeEnseignant.SECONDAIRE
        self.autre_enseignant.taux_horaire = Decimal("10000")
        self.autre_enseignant.save()
        periode = PeriodeSalaire.objects.create(
            ecole=self.autre_ecole, mois=9, annee=2026, cree_par=self.admin
        )
        response = self.pointer(self.admin, self.enseignant, self.autre_enseignant)
        self.assertRedirects(response, reverse("salaires:liste_presences"))
        self.assertEqual(PresenceEnseignant.objects.filter(
            date=date(2026, 9, 7), statut="PRESENT", heures_travaillees=4
        ).count(), 2)
        etat = EtatSalaire.objects.get(enseignant=self.autre_enseignant, periode=periode)
        self.assertEqual(etat.total_heures, Decimal("12"))
        self.assertEqual(etat.salaire_base, Decimal("120000"))

    def test_liste_rapport_et_csv_conservent_les_presences_autorisees(self):
        for user in (self.admin, self.user):
            self.client.force_login(user)
            for route in ("liste_presences", "rapport_presences", "export_presences_csv"):
                with self.subTest(user=user.username, route=route):
                    response = self.client.get(reverse("salaires:" + route), {
                        "date_debut": "2026-09-01", "date_fin": "2026-09-07",
                    })
                    self.assertContains(response, self.enseignant.nom)
                    if user.is_superuser:
                        self.assertContains(response, self.autre_enseignant.nom)
                    else:
                        self.assertNotContains(response, self.autre_enseignant.nom)

    def test_superadmin_peut_modifier_et_supprimer_un_pointage(self):
        self.client.force_login(self.admin)
        presence = PresenceEnseignant.objects.get(
            enseignant=self.autre_enseignant, date=date(2026, 9, 3)
        )
        response = self.client.post(
            reverse("salaires:modifier_presence", args=[presence.pk]), {
                "enseignant": self.autre_enseignant.pk, "date": "2026-09-03",
                "statut": "PRESENT", "heures_travaillees": "3",
            },
        )
        self.assertEqual(response.status_code, 302)
        presence.refresh_from_db()
        self.assertEqual(presence.heures_travaillees, Decimal("3"))
        response = self.client.post(reverse("salaires:supprimer_presence", args=[presence.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PresenceEnseignant.objects.filter(pk=presence.pk).exists())

    def test_pointages_autre_ecole_inaccessibles_en_modification_et_suppression(self):
        self.client.force_login(self.user)
        presence = PresenceEnseignant.objects.get(enseignant=self.autre_enseignant)
        for route in ("modifier_presence", "supprimer_presence"):
            with self.subTest(route=route):
                response = self.client.post(reverse("salaires:" + route, args=[presence.pk]))
                self.assertEqual(response.status_code, 404)
        self.assertTrue(PresenceEnseignant.objects.filter(pk=presence.pk).exists())
