from datetime import date, timedelta

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from paiements.tests.support import TEST_MIDDLEWARE

from .forms import AbonnementBusForm, AbonnementCantineForm
from .models import (
    AbonnementBus,
    AbonnementCantine,
    TypePeriodiciteAbonnement,
    TypeRepasCantine,
)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class SelectionEtConfigurationAbonnementsTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Sélection', adresse='Conakry', telephone='+224620100001',
            directeur='Direction', etat='VALIDE',
        )
        self.classe_a = Classe.objects.create(
            ecole=self.ecole, nom='3ème A', niveau='PRIMAIRE_3', annee_scolaire='2026-2027',
        )
        self.classe_b = Classe.objects.create(
            ecole=self.ecole, nom='4ème B', niveau='PRIMAIRE_4', annee_scolaire='2026-2027',
        )
        self.eleve_a = Eleve.objects.create(
            matricule='SEL-001', prenom='Aminata', nom='Diallo', sexe='F', classe=self.classe_a,
        )
        self.eleve_b = Eleve.objects.create(
            matricule='SEL-002', prenom='Mamadou', nom='Bah', sexe='M', classe=self.classe_b,
        )
        autre_ecole = Ecole.objects.create(
            nom='Autre École', adresse='Kindia', telephone='+224620100002',
            directeur='Autre direction', etat='VALIDE',
        )
        autre_classe = Classe.objects.create(
            ecole=autre_ecole, nom='Classe privée', niveau='PRIMAIRE_1', annee_scolaire='2026-2027',
        )
        self.eleve_interdit = Eleve.objects.create(
            matricule='SECRET-999', prenom='Élève', nom='Interdit', sexe='M', classe=autre_classe,
        )
        self.user = User.objects.create_user('gestion-abonnements', password='secret')
        self.user.profil.role = 'COMPTABLE'
        self.user.profil.telephone = '+224620100003'
        self.user.profil.ecole = self.ecole
        self.user.profil.is_validated = True
        self.user.profil.save()
        self.client.force_login(self.user)

    def test_formulaires_affichent_matricule_nom_et_filtre_classe(self):
        for url in (reverse('bus:nouveau'), reverse('bus:creer_abonnement_cantine')):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id_classe_filtre')
                field = response.context['form'].fields['eleve']
                expected_a = f'SEL-001 — {self.eleve_a.prenom} {self.eleve_a.nom}'
                expected_b = f'SEL-002 — {self.eleve_b.prenom} {self.eleve_b.nom}'
                self.assertEqual(field.label_from_instance(self.eleve_a), expected_a)
                self.assertEqual(field.label_from_instance(self.eleve_b), expected_b)
                self.assertContains(response, 'SEL-001')
                self.assertContains(response, f'{self.eleve_a.prenom} {self.eleve_a.nom}')
                self.assertContains(response, 'SEL-002')
                self.assertContains(response, f'{self.eleve_b.prenom} {self.eleve_b.nom}')
                self.assertContains(response, f'data-classe-id="{self.classe_a.pk}"')
                self.assertNotContains(response, 'SECRET-999')

    def test_une_ecole_ne_peut_pas_abonner_un_eleve_d_une_autre_ecole(self):
        response = self.client.post(reverse('bus:nouveau'), {
            'eleve': self.eleve_interdit.pk,
            'montant': 100000,
            'periodicite': 'ANNUEL',
            'date_debut': date.today(),
            'date_expiration': date.today() + timedelta(days=365),
            'statut': 'ACTIF',
            'alerte_avant_jours': 7,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'eleve', 'Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.')
        self.assertFalse(AbonnementBus.objects.exists())

    def test_annuel_et_repas_14h_sont_disponibles_et_enregistrables(self):
        bus_form = AbonnementBusForm(user=self.user)
        cantine_form = AbonnementCantineForm(user=self.user)
        self.assertIn(('ANNUEL', 'Annuel'), list(bus_form.fields['periodicite'].choices))
        self.assertIn(('ANNUEL', 'Annuel'), list(cantine_form.fields['periodicite'].choices))
        self.assertIn(('REPAS_14H', 'Repas de 14 h'), list(cantine_form.fields['type_repas'].choices))

        response = self.client.post(reverse('bus:creer_abonnement_cantine'), {
            'classe_filtre': self.classe_a.pk,
            'eleve': self.eleve_a.pk,
            'montant': 900000,
            'periodicite': 'ANNUEL',
            'type_repas': 'REPAS_14H',
            'date_debut': date.today(),
            'date_expiration': date.today() + timedelta(days=365),
            'statut': 'ACTIF',
            'alerte_avant_jours': 7,
        })
        self.assertRedirects(response, reverse('bus:liste_abonnements_cantine'))
        abonnement = AbonnementCantine.objects.get()
        self.assertEqual(abonnement.periodicite, 'ANNUEL')
        self.assertEqual(abonnement.type_repas, 'REPAS_14H')
        self.assertEqual(abonnement.get_type_repas_display(), 'Repas de 14 h')

    def test_personnalisation_admin_alimente_les_formulaires_et_libelles(self):
        TypePeriodiciteAbonnement.objects.update_or_create(
            service=TypePeriodiciteAbonnement.Service.BUS,
            code='ANNUEL',
            defaults={
                'libelle': 'Année scolaire complète', 'duree_mois': 10,
                'duree_jours': 0, 'actif': True, 'ordre': 1,
            },
        )
        TypeRepasCantine.objects.create(
            code='DINER', libelle='Dîner personnalisé', actif=True, ordre=90,
        )
        form_bus = AbonnementBusForm(user=self.user)
        form_cantine = AbonnementCantineForm(user=self.user)
        self.assertIn(('ANNUEL', 'Année scolaire complète'), list(form_bus.fields['periodicite'].choices))
        self.assertIn(('DINER', 'Dîner personnalisé'), list(form_cantine.fields['type_repas'].choices))

        abonnement = AbonnementBus(
            eleve=self.eleve_a, montant=1, periodicite='ANNUEL',
            date_expiration=date.today(),
        )
        self.assertEqual(abonnement.get_periodicite_display(), 'Année scolaire complète')
        self.assertTrue(admin.site.is_registered(TypePeriodiciteAbonnement))
        self.assertTrue(admin.site.is_registered(TypeRepasCantine))
