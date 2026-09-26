from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from administration.models import ObjetSupprime
from eleves.models import Classe, Ecole, Eleve
from paiements.tests.support import TEST_MIDDLEWARE

from .models import AbonnementCantine


def _utilisateur(username, ecole):
    user = User.objects.create_user(username, password='secret')
    user.profil.role = 'COMPTABLE'
    user.profil.telephone = '+224620007' + str(User.objects.count()).zfill(3)
    user.profil.ecole = ecole
    user.profil.is_validated = True
    user.profil.peut_supprimer_abonnements = True
    user.profil.save()
    return user


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class CorbeilleCantineTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École cantine', adresse='Conakry',
            telephone='+224620007001', directeur='Direction', etat='VALIDE',
        )
        classe = Classe.objects.create(
            ecole=self.ecole, nom='CP A', niveau='PRIMAIRE_1', annee_scolaire='2026-2027',
        )
        self.eleve = Eleve.objects.create(
            matricule='CAN-001', prenom='Awa', nom='Keita', sexe='F', classe=classe,
        )
        self.abonnement = AbonnementCantine.objects.create(
            eleve=self.eleve, montant=70000, type_repas='DEJEUNER', periodicite='MENSUEL',
            date_debut=date.today(), date_expiration=date.today() + timedelta(days=30),
        )
        self.user = _utilisateur('cantine', self.ecole)
        self.client.force_login(self.user)

    def _supprimer(self):
        return self.client.post(reverse('bus:supprimer_abonnement_cantine', args=[self.abonnement.pk]))

    def test_suppression_place_dans_la_corbeille_puis_restauration(self):
        response = self._supprimer()
        self.assertRedirects(response, reverse('bus:liste_abonnements_cantine'))
        self.assertFalse(AbonnementCantine.objects.filter(pk=self.abonnement.pk).exists())

        archive = ObjetSupprime.objects.get(model_label='bus.abonnementcantine')
        self.assertEqual(archive.object_pk, str(self.abonnement.pk))
        corbeille = self.client.get(reverse('bus:corbeille_cantine'))
        self.assertContains(corbeille, 'CAN-001')
        self.assertContains(corbeille, '70')

        response = self.client.post(reverse('bus:restaurer_abonnement_cantine', args=[archive.pk]))
        self.assertRedirects(response, reverse('bus:corbeille_cantine'))
        restaure = AbonnementCantine.objects.get(pk=self.abonnement.pk)
        self.assertEqual(restaure.eleve, self.eleve)
        self.assertEqual(restaure.montant, 70000)
        archive.refresh_from_db()
        self.assertTrue(archive.restaure)
        self.assertNotContains(self.client.get(reverse('bus:corbeille_cantine')), 'CAN-001')

    def test_autre_ecole_ne_voit_ni_ne_restaure_la_corbeille(self):
        self._supprimer()
        archive = ObjetSupprime.objects.get(model_label='bus.abonnementcantine')
        autre_ecole = Ecole.objects.create(
            nom='Autre école', adresse='Kindia',
            telephone='+224620007099', directeur='Direction', etat='VALIDE',
        )
        self.client.force_login(_utilisateur('autre', autre_ecole))

        corbeille = self.client.get(reverse('bus:corbeille_cantine'))
        self.assertEqual(corbeille.context['archives'], [])
        self.client.post(reverse('bus:restaurer_abonnement_cantine', args=[archive.pk]))
        self.assertFalse(AbonnementCantine.objects.filter(pk=self.abonnement.pk).exists())
