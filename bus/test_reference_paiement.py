from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from paiements.tests.support import TEST_MIDDLEWARE

from .models import AbonnementBus, AbonnementCantine


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ReferencePaiementAbonnementTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École abonnements', adresse='Conakry',
            telephone='+224620005001', directeur='Direction', etat='VALIDE',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='2ème A', niveau='PRIMAIRE_2',
            annee_scolaire='2026-2027',
        )
        self.student = Eleve.objects.create(
            matricule='ABO-001', prenom='Élève', nom='Abonné',
            sexe='M', classe=self.classe,
        )
        self.user = User.objects.create_user('abonnements', password='secret')
        self.user.profil.role = 'COMPTABLE'
        self.user.profil.telephone = '+224620005002'
        self.user.profil.ecole = self.ecole
        self.user.profil.is_validated = True
        self.user.profil.save()
        self.client.force_login(self.user)

    def test_reference_est_enregistree_et_visible_pour_bus(self):
        response = self.client.post(reverse('bus:nouveau'), {
            'eleve': self.student.pk,
            'montant': 100000,
            'reference_paiement': 'REC-BUS-2026-001',
            'periodicite': 'MENSUEL',
            'date_debut': date.today(),
            'date_expiration': date.today() + timedelta(days=30),
            'statut': 'ACTIF',
            'alerte_avant_jours': 7,
        })
        self.assertRedirects(response, reverse('bus:liste'))
        self.assertEqual(AbonnementBus.objects.get().reference_paiement, 'REC-BUS-2026-001')
        listing = self.client.get(reverse('bus:liste'), {'q': 'REC-BUS-2026-001'})
        self.assertContains(listing, 'REC-BUS-2026-001')

    def test_reference_est_enregistree_pour_cantine(self):
        response = self.client.post(reverse('bus:creer_abonnement_cantine'), {
            'eleve': self.student.pk,
            'montant': 70000,
            'reference_paiement': 'OM-998877',
            'periodicite': 'MENSUEL',
            'type_repas': 'DEJEUNER',
            'date_debut': date.today(),
            'date_expiration': date.today() + timedelta(days=30),
            'statut': 'ACTIF',
            'alerte_avant_jours': 7,
        })
        self.assertRedirects(response, reverse('bus:liste_abonnements_cantine'))
        self.assertEqual(AbonnementCantine.objects.get().reference_paiement, 'OM-998877')
