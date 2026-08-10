"""Modification d'un paiement, mémoire des modifications et corbeille admin."""
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from administration.models import ObjetSupprime
from eleves.models import Ecole, Classe, Eleve, Responsable
from paiements.models import (
    EcheancierPaiement, HistoriqueModificationPaiement, ModePaiement,
    Paiement, TypePaiement,
)
from utilisateurs.models import Profil


TEST_MIDDLEWARE = [
    middleware for middleware in settings.MIDDLEWARE
    if middleware != 'ecole_moderne.licence_middleware.LicenceMiddleware'
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ModificationPaiementTest(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Historique", adresse="Conakry",
            telephone="+224620000002", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="Petite Section", ecole=self.ecole, niveau="MATERNELLE",
            annee_scolaire="2025-2026",
        )
        self.resp = Responsable.objects.create(
            prenom="P", nom="Resp", relation="PERE",
            telephone="+224620000012", adresse="Adr",
        )
        self.eleve = Eleve.objects.create(
            nom="Camara", prenom="Sekou", matricule="KIN-050",
            classe=self.classe, sexe='M',
            date_naissance=date(2021, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        self.type_paiement = TypePaiement.objects.create(nom="Tranche 1")
        self.mode = ModePaiement.objects.create(nom="Espèces")
        self.paiement = Paiement.objects.create(
            eleve=self.eleve, type_paiement=self.type_paiement,
            mode_paiement=self.mode, montant=Decimal("300000"),
            statut='EN_ATTENTE', date_paiement=date(2026, 8, 4),
        )

        User = get_user_model()
        self.user = User.objects.create_user(username="compta_modif", password="pass12345")
        Profil.objects.update_or_create(
            user=self.user,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': "+224620000022", 'peut_modifier_paiements': True,
                'is_validated': True,
            },
        )
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        self.url = reverse('paiements:modifier_paiement', kwargs={'paiement_id': self.paiement.id})

    def _payload(self, **extra):
        data = {
            'type_paiement': self.type_paiement.id,
            'mode_paiement': self.mode.id,
            'montant': '450000',
            'date_paiement': '2026-08-04',
            'reference_externe': '',
            'observations': '',
            'motif_modification': "Montant oublié lors de l'encaissement",
        }
        data.update(extra)
        return data

    def test_formulaire_de_correction_s_affiche(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="motif_modification"')
        self.assertContains(response, 'name="montant"')

    def test_detail_paiement_affiche_la_memoire_des_modifications(self):
        self.client.post(self.url, self._payload())
        response = self.client.get(
            reverse('paiements:detail_paiement', kwargs={'paiement_id': self.paiement.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mémoire des modifications')
        self.assertContains(response, 'Montant oublié lors de')
        self.assertContains(response, 'montant')

    def test_modification_corrige_le_paiement_et_garde_la_memoire(self):
        response = self.client.post(self.url, self._payload())
        self.assertRedirects(
            response,
            reverse('paiements:detail_paiement', kwargs={'paiement_id': self.paiement.id}),
        )
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("450000"))

        historique = HistoriqueModificationPaiement.objects.get(paiement=self.paiement)
        self.assertEqual(historique.utilisateur, self.user)
        self.assertEqual(historique.motif, "Montant oublié lors de l'encaissement")
        self.assertIn('montant', historique.champs_modifies)
        self.assertEqual(historique.donnees_avant['montant'], '300000')
        self.assertEqual(historique.donnees_apres['montant'], '450000')

    def test_montant_negatif_refuse(self):
        response = self.client.post(self.url, self._payload(montant='-1000'))
        self.assertEqual(response.status_code, 200)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("300000"))
        self.assertFalse(HistoriqueModificationPaiement.objects.exists())

    def test_motif_obligatoire(self):
        response = self.client.post(self.url, self._payload(motif_modification=''))
        self.assertEqual(response.status_code, 200)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("300000"))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class CorbeilleAdminTest(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Corbeille", adresse="Conakry",
            telephone="+224620000003", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="Petite Section", ecole=self.ecole, niveau="MATERNELLE",
            annee_scolaire="2025-2026",
        )
        self.eleve = Eleve.objects.create(
            nom="Bah", prenom="Aissatou", matricule="KIN-060",
            classe=self.classe, sexe='F',
            date_naissance=date(2021, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1),
        )
        self.paiement = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=TypePaiement.objects.create(nom="Tranche 1"),
            mode_paiement=ModePaiement.objects.create(nom="Espèces"),
            montant=Decimal("120000"), statut='VALIDE',
            date_paiement=date(2026, 8, 4),
        )
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire="2025-2026",
            frais_inscription_du=Decimal("20000"),
            tranche_1_due=Decimal("500000"),
            tranche_2_due=Decimal("600000"),
            tranche_3_due=Decimal("400000"),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            'root_corbeille', 'root@corbeille.gn', 'Motdepasse!2026',
        )
        self.client.force_login(self.admin)

    def test_suppression_admin_paiement_va_dans_la_corbeille_et_se_restaure(self):
        numero = self.paiement.numero_recu
        url = reverse('admin:paiements_paiement_delete', args=[self.paiement.pk])
        self.client.post(url, {'post': 'yes'}, follow=True)

        self.assertFalse(Paiement.objects.filter(pk=self.paiement.pk).exists())
        archive = ObjetSupprime.objects.get(model_label='paiements.paiement')
        self.assertEqual(archive.object_pk, str(self.paiement.pk))
        self.assertEqual(archive.supprime_par, self.admin)

        self.assertTrue(archive.restaurer())
        restaure = Paiement.objects.get(pk=self.paiement.pk)
        self.assertEqual(restaure.numero_recu, numero)
        self.assertEqual(restaure.montant, Decimal("120000"))

    def test_suppression_admin_echeancier_va_dans_la_corbeille(self):
        url = reverse('admin:paiements_echeancierpaiement_delete', args=[self.echeancier.pk])
        self.client.post(url, {'post': 'yes'}, follow=True)

        self.assertFalse(EcheancierPaiement.objects.filter(pk=self.echeancier.pk).exists())
        archive = ObjetSupprime.objects.get(model_label='paiements.echeancierpaiement')
        self.assertTrue(archive.restaurer())
        self.assertTrue(EcheancierPaiement.objects.filter(pk=self.echeancier.pk).exists())

    def test_suppression_admin_abonnement_bus_va_dans_la_corbeille(self):
        from bus.models import AbonnementBus

        abonnement = AbonnementBus.objects.create(
            eleve=self.eleve, montant=50000, date_expiration=date(2026, 12, 31),
            statut='ACTIF', zone='Zone A',
        )
        url = reverse('admin:bus_abonnementbus_delete', args=[abonnement.pk])
        self.client.post(url, {'post': 'yes'}, follow=True)

        self.assertFalse(AbonnementBus.objects.filter(pk=abonnement.pk).exists())
        archive = ObjetSupprime.objects.get(model_label='bus.abonnementbus')
        self.assertTrue(archive.restaurer())
        self.assertTrue(AbonnementBus.objects.filter(pk=abonnement.pk).exists())
