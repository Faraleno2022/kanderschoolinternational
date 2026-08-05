"""Tests du module Recouvrement : registres simples et abonnements informatique."""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eleves.models import Classe, Ecole, Eleve

from .models_recouvrement import (
    AbonnementInformatique, DepenseCuisine, DepenseDocument, Versement,
)


TEST_MIDDLEWARE = [
    middleware
    for middleware in settings.MIDDLEWARE
    if middleware != 'ecole_moderne.licence_middleware.LicenceMiddleware'
]


def _creer_ecole(nom, telephone):
    return Ecole.objects.create(
        nom=nom, adresse='Conakry', telephone=telephone, directeur='Direction',
    )


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class RecouvrementBaseTests(TestCase):
    def setUp(self):
        self.ecole = _creer_ecole('École recouvrement', '+224620000021')
        self.autre_ecole = _creer_ecole('École voisine', '+224620000022')

        self.user = User.objects.create_user('gestionnaire', password='secret')
        profil = self.user.profil
        profil.role = 'ADMIN'
        profil.telephone = '+224620000023'
        profil.ecole = self.ecole
        profil.is_validated = True
        profil.save()
        self.client.force_login(self.user)


class OperationsSimplesTests(RecouvrementBaseTests):
    def test_hub_liste_les_modules(self):
        reponse = self.client.get(reverse('depenses:hub'))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Dépenses de la cuisine")
        self.assertContains(reponse, "Dépenses de documents")
        self.assertContains(reponse, "Versements")
        self.assertContains(reponse, "Informatique")

    def test_creation_depense_cuisine_pose_ecole_et_auteur(self):
        reponse = self.client.post(
            reverse('depenses:recouvrement_ajouter', kwargs={'module': 'cuisine'}),
            {
                'date': '2026-08-04',
                'designation': 'Sacs de riz',
                'montant': '450000',
                'observation': 'Livraison du lundi',
            },
        )
        self.assertRedirects(
            reponse,
            reverse('depenses:recouvrement_dashboard_module', kwargs={'module': 'cuisine'}),
        )
        depense = DepenseCuisine.objects.get()
        self.assertEqual(depense.designation, 'Sacs de riz')
        self.assertEqual(depense.montant, Decimal('450000'))
        self.assertEqual(depense.ecole, self.ecole)
        self.assertEqual(depense.cree_par, self.user)

    def test_versement_enregistre_le_lieu(self):
        self.client.post(
            reverse('depenses:recouvrement_ajouter', kwargs={'module': 'versement'}),
            {
                'date': '2026-08-04',
                'montant': '1200000',
                'lieu_versement': 'Ecobank Matam',
                'observation': '',
            },
        )
        versement = Versement.objects.get()
        self.assertEqual(versement.lieu_versement, 'Ecobank Matam')
        self.assertEqual(versement.libelle, 'Ecobank Matam')

    def test_module_inconnu_renvoie_404(self):
        reponse = self.client.get(
            reverse('depenses:recouvrement_dashboard_module', kwargs={'module': 'inexistant'})
        )
        self.assertEqual(reponse.status_code, 404)

    def test_dashboard_cloisonne_par_ecole(self):
        DepenseDocument.objects.create(
            date=timezone.localdate(), designation='Ramettes A4',
            montant=Decimal('300000'), ecole=self.ecole,
        )
        DepenseDocument.objects.create(
            date=timezone.localdate(), designation='Toner voisin',
            montant=Decimal('900000'), ecole=self.autre_ecole,
        )

        reponse = self.client.get(
            reverse('depenses:recouvrement_dashboard_module', kwargs={'module': 'document'})
        )
        self.assertContains(reponse, 'Ramettes A4')
        self.assertNotContains(reponse, 'Toner voisin')
        # Le total affiché ne doit compter que l'école de l'utilisateur.
        self.assertEqual(reponse.context['stats']['total'], 300000)

    def test_operation_d_une_autre_ecole_inaccessible(self):
        autre = DepenseCuisine.objects.create(
            date=timezone.localdate(), designation='Gaz voisin',
            montant=Decimal('100000'), ecole=self.autre_ecole,
        )
        reponse = self.client.get(
            reverse('depenses:recouvrement_modifier',
                    kwargs={'module': 'cuisine', 'pk': autre.pk})
        )
        self.assertEqual(reponse.status_code, 404)

    def test_filtre_par_dates(self):
        DepenseCuisine.objects.create(
            date='2026-07-01', designation='Huile', montant=Decimal('100000'), ecole=self.ecole,
        )
        DepenseCuisine.objects.create(
            date='2026-08-01', designation='Poisson', montant=Decimal('250000'), ecole=self.ecole,
        )
        reponse = self.client.get(
            reverse('depenses:recouvrement_dashboard_module', kwargs={'module': 'cuisine'}),
            {'du': '2026-07-15', 'au': '2026-08-15'},
        )
        self.assertContains(reponse, 'Poisson')
        self.assertNotContains(reponse, 'Huile')
        self.assertEqual(reponse.context['stats']['total'], 250000)

    def test_montant_negatif_refuse(self):
        reponse = self.client.post(
            reverse('depenses:recouvrement_ajouter', kwargs={'module': 'cuisine'}),
            {'date': '2026-08-04', 'designation': 'Erreur', 'montant': '-5000', 'observation': ''},
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(DepenseCuisine.objects.exists())

    def test_pages_de_saisie_et_de_suppression_s_affichent(self):
        """Rend chaque gabarit du module : une erreur de template casserait l'écran."""
        for module in ('cuisine', 'document', 'versement'):
            with self.subTest(module=module):
                creation = self.client.get(
                    reverse('depenses:recouvrement_ajouter', kwargs={'module': module})
                )
                self.assertEqual(creation.status_code, 200)

        operation = DepenseCuisine.objects.create(
            date=timezone.localdate(), designation='Charbon',
            montant=Decimal('75000'), ecole=self.ecole,
        )
        modification = self.client.get(
            reverse('depenses:recouvrement_modifier',
                    kwargs={'module': 'cuisine', 'pk': operation.pk})
        )
        self.assertContains(modification, 'Charbon')

        suppression = self.client.get(
            reverse('depenses:recouvrement_supprimer',
                    kwargs={'module': 'cuisine', 'pk': operation.pk})
        )
        self.assertContains(suppression, 'Supprimer définitivement')

        self.client.post(
            reverse('depenses:recouvrement_supprimer',
                    kwargs={'module': 'cuisine', 'pk': operation.pk})
        )
        self.assertFalse(DepenseCuisine.objects.filter(pk=operation.pk).exists())

    def test_exports_excel_et_pdf(self):
        DepenseCuisine.objects.create(
            date=timezone.localdate(), designation='Sacs de riz',
            montant=Decimal('450000'), ecole=self.ecole,
        )

        excel = self.client.get(
            reverse('depenses:recouvrement_export_excel', kwargs={'module': 'cuisine'})
        )
        self.assertEqual(excel.status_code, 200)
        self.assertIn('spreadsheetml', excel['Content-Type'])

        pdf = self.client.get(
            reverse('depenses:recouvrement_export_pdf', kwargs={'module': 'cuisine'})
        )
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))


class AbonnementInformatiqueTests(RecouvrementBaseTests):
    def setUp(self):
        super().setUp()
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='CM2 A', niveau='PRIMAIRE_6', annee_scolaire='2025-2026',
        )
        self.eleve = Eleve.objects.create(
            matricule='KSI-2026-001', prenom='Ibrahima', nom='Mansaré',
            sexe='M', classe=self.classe,
        )
        classe_voisine = Classe.objects.create(
            ecole=self.autre_ecole, nom='CM2 B', niveau='PRIMAIRE_6', annee_scolaire='2025-2026',
        )
        self.eleve_voisin = Eleve.objects.create(
            matricule='VOIS-2026-001', prenom='Fatou', nom='Camara',
            sexe='F', classe=classe_voisine,
        )
        self.aujourdhui = timezone.localdate()

    def _creer_abonnement(self, eleve=None, jours_restants=30, montant='150000'):
        return AbonnementInformatique.objects.create(
            eleve=eleve or self.eleve,
            date=self.aujourdhui,
            montant=Decimal(montant),
            date_debut=self.aujourdhui - timedelta(days=10),
            date_fin=self.aujourdhui + timedelta(days=jours_restants),
        )

    def test_statuts_selon_les_dates(self):
        actif = self._creer_abonnement(jours_restants=30)
        bientot = self._creer_abonnement(jours_restants=3)
        expire = self._creer_abonnement(jours_restants=-2)

        self.assertEqual(actif.statut, 'ACTIF')
        self.assertEqual(bientot.statut, 'BIENTOT')
        self.assertEqual(expire.statut, 'EXPIRE')
        self.assertTrue(expire.est_expire)
        self.assertFalse(actif.est_proche_expiration)

    def test_creation_via_le_formulaire(self):
        reponse = self.client.post(
            reverse('depenses:recouvrement_informatique_ajouter'),
            {
                'eleve': self.eleve.pk,
                'date': self.aujourdhui.isoformat(),
                'montant': '150000',
                'date_debut': self.aujourdhui.isoformat(),
                'date_fin': (self.aujourdhui + timedelta(days=90)).isoformat(),
                'alerte_avant_jours': '7',
                'observation': 'Trimestre 1',
            },
        )
        self.assertRedirects(reponse, reverse('depenses:recouvrement_informatique_liste'))
        abonnement = AbonnementInformatique.objects.get()
        self.assertEqual(abonnement.eleve, self.eleve)
        self.assertEqual(abonnement.cree_par, self.user)

    def test_date_fin_anterieure_refusee(self):
        reponse = self.client.post(
            reverse('depenses:recouvrement_informatique_ajouter'),
            {
                'eleve': self.eleve.pk,
                'date': self.aujourdhui.isoformat(),
                'montant': '150000',
                'date_debut': self.aujourdhui.isoformat(),
                'date_fin': (self.aujourdhui - timedelta(days=1)).isoformat(),
                'alerte_avant_jours': '7',
                'observation': '',
            },
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(AbonnementInformatique.objects.exists())

    def test_eleve_d_une_autre_ecole_refuse(self):
        reponse = self.client.post(
            reverse('depenses:recouvrement_informatique_ajouter'),
            {
                'eleve': self.eleve_voisin.pk,
                'date': self.aujourdhui.isoformat(),
                'montant': '150000',
                'date_debut': self.aujourdhui.isoformat(),
                'date_fin': (self.aujourdhui + timedelta(days=30)).isoformat(),
                'alerte_avant_jours': '7',
                'observation': '',
            },
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(AbonnementInformatique.objects.exists())

    def test_recherche_par_matricule(self):
        self._creer_abonnement()
        self._creer_abonnement(eleve=self.eleve_voisin)

        reponse = self.client.get(
            reverse('depenses:recouvrement_informatique_liste'), {'q': 'KSI-2026-001'}
        )
        self.assertContains(reponse, 'KSI-2026-001')
        self.assertNotContains(reponse, 'VOIS-2026-001')

    def test_dashboard_compte_les_alertes(self):
        self._creer_abonnement(jours_restants=30)
        self._creer_abonnement(jours_restants=2)
        self._creer_abonnement(jours_restants=-5)

        reponse = self.client.get(reverse('depenses:recouvrement_informatique_dashboard'))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context['total'], 3)
        self.assertEqual(reponse.context['actifs'], 2)
        self.assertEqual(reponse.context['expires'], 1)
        self.assertEqual(reponse.context['alertes_nombre'], 1)

    def test_recherche_eleve_json_cloisonnee(self):
        reponse = self.client.get(
            reverse('depenses:recouvrement_informatique_recherche_eleve'), {'q': 'Camara'}
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()['resultats'], [])

    def test_carte_abonnement_pdf(self):
        abonnement = self._creer_abonnement()
        reponse = self.client.get(
            reverse('depenses:recouvrement_informatique_carte', kwargs={'pk': abonnement.pk})
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse['Content-Type'], 'application/pdf')
        self.assertTrue(reponse.content.startswith(b'%PDF'))

    def test_carte_d_une_autre_ecole_inaccessible(self):
        abonnement = self._creer_abonnement(eleve=self.eleve_voisin)
        reponse = self.client.get(
            reverse('depenses:recouvrement_informatique_carte', kwargs={'pk': abonnement.pk})
        )
        self.assertEqual(reponse.status_code, 404)

    def test_pages_informatique_s_affichent(self):
        creation = self.client.get(reverse('depenses:recouvrement_informatique_ajouter'))
        self.assertContains(creation, "Rechercher un élève")

        abonnement = self._creer_abonnement()
        modification = self.client.get(
            reverse('depenses:recouvrement_informatique_modifier', kwargs={'pk': abonnement.pk})
        )
        self.assertEqual(modification.status_code, 200)

        suppression = self.client.get(
            reverse('depenses:recouvrement_informatique_supprimer', kwargs={'pk': abonnement.pk})
        )
        self.assertContains(suppression, 'KSI-2026-001')

        self.client.post(
            reverse('depenses:recouvrement_informatique_supprimer', kwargs={'pk': abonnement.pk})
        )
        self.assertFalse(AbonnementInformatique.objects.filter(pk=abonnement.pk).exists())

    def test_exports_informatique(self):
        self._creer_abonnement()

        excel = self.client.get(reverse('depenses:recouvrement_informatique_export_excel'))
        self.assertEqual(excel.status_code, 200)
        self.assertIn('spreadsheetml', excel['Content-Type'])

        pdf = self.client.get(reverse('depenses:recouvrement_informatique_export_pdf'))
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))
