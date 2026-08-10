from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from eleves.models import Ecole, Classe, Eleve, GrilleTarifaire, Responsable


class SuppressionEcoleTest(TestCase):
    def _ecole(self, nom="Ecole Test Suppression"):
        ecole = Ecole.objects.create(
            nom=nom,
            adresse="Conakry",
            telephone="+224620000000",
        )
        classe = Classe.objects.create(
            ecole=ecole,
            nom="CP1 A",
            niveau="PRIMAIRE_1",
            annee_scolaire="2025-2026",
        )
        GrilleTarifaire.objects.create(
            ecole=ecole,
            niveau="PRIMAIRE_1",
            annee_scolaire="2025-2026",
            frais_inscription=Decimal("100000"),
            tranche_1=Decimal("100000"),
            tranche_2=Decimal("100000"),
            tranche_3=Decimal("100000"),
        )
        responsable = Responsable.objects.create(
            prenom="Papa",
            nom="Test",
            relation="PERE",
            telephone="+224620000001",
            adresse="Conakry",
        )
        Eleve.objects.create(
            matricule=f"TST{Eleve.objects.count() + 1:04d}",
            prenom="Test",
            nom="Eleve",
            sexe="M",
            date_naissance=date(2015, 1, 1),
            lieu_naissance="Conakry",
            classe=classe,
            date_inscription=date(2025, 9, 1),
            responsable_principal=responsable,
        )
        return ecole

    def test_delete_instance(self):
        ecole = self._ecole()
        pk = ecole.pk
        ecole.delete()
        self.assertFalse(Ecole.objects.filter(pk=pk).exists())

    def test_delete_queryset(self):
        from synchronisation.models import SyncChange  # noqa: F401

        ecole = self._ecole()
        pk = ecole.pk
        Ecole.objects.filter(pk=pk).delete()
        self.assertFalse(Ecole.objects.filter(pk=pk).exists())
        self.assertEqual(SyncChange.objects.filter(ecole_id=pk).count(), 0)


class SuppressionEcoleAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root_tmp", "root@tmp.gn", "Motdepasse!2026")
        self.client.force_login(self.admin)

    def _ecole(self, nom, matricule):
        ecole = Ecole.objects.create(nom=nom, adresse="Conakry", telephone="+224620000000")
        classe = Classe.objects.create(
            ecole=ecole, nom="CP1 A", niveau="PRIMAIRE_1", annee_scolaire="2025-2026"
        )
        Eleve.objects.create(
            matricule=matricule,
            prenom="Test",
            nom="Eleve",
            sexe="M",
            date_naissance=date(2015, 1, 1),
            lieu_naissance="Conakry",
            classe=classe,
            date_inscription=date(2025, 9, 1),
        )
        return ecole

    def test_admin_delete_single(self):
        ecole = self._ecole("Ecole Admin Simple", "ADM0001")
        url = reverse("admin:eleves_ecole_delete", args=[ecole.pk])
        response = self.client.post(url, {"post": "yes"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Ecole.objects.filter(pk=ecole.pk).exists())

    def test_admin_delete_bulk(self):
        e1 = self._ecole("Ecole Admin Masse 1", "ADM0002")
        e2 = self._ecole("Ecole Admin Masse 2", "ADM0003")
        url = reverse("admin:eleves_ecole_changelist")
        response = self.client.post(
            url,
            {
                "action": "delete_selected",
                "_selected_action": [str(e1.pk), str(e2.pk)],
                "post": "yes",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Ecole.objects.filter(pk__in=[e1.pk, e2.pk]).exists())
