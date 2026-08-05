from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Classe, Ecole, Eleve


TEST_MIDDLEWARE = [
    middleware
    for middleware in settings.MIDDLEWARE
    if middleware != 'ecole_moderne.licence_middleware.LicenceMiddleware'
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ChoixApresAjoutEleveTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École principale',
            adresse='Conakry',
            telephone='+224620000031',
            directeur='Direction',
            etat='VALIDE',
        )
        self.autre_ecole = Ecole.objects.create(
            nom='Autre école',
            adresse='Conakry',
            telephone='+224620000032',
            directeur='Direction',
            etat='VALIDE',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole,
            nom='8e A',
            niveau='COLLEGE_8',
            code_matricule='CL8',
            annee_scolaire='2026-2027',
        )
        self.autre_classe = Classe.objects.create(
            ecole=self.autre_ecole,
            nom='7e B',
            niveau='COLLEGE_7',
            code_matricule='CL7',
            annee_scolaire='2026-2027',
        )

        self.user = User.objects.create_user('secretaire', password='secret')
        self.user.profil.role = 'SECRETAIRE'
        self.user.profil.telephone = '+224620000033'
        self.user.profil.ecole = self.ecole
        self.user.profil.is_validated = True
        self.user.profil.save()

        self.autre_eleve = Eleve.objects.create(
            matricule='CL7-001',
            prenom='AUTRE',
            nom='ÉLÈVE',
            sexe='F',
            classe=self.autre_classe,
        )
        self.client.force_login(self.user)

    def test_creation_redirige_vers_le_choix(self):
        response = self.client.post(
            reverse('eleves:ajouter_eleve'),
            {
                'matricule': 'CL8-002',
                'saisie_manuelle_matricule': 'on',
                'prenom': 'ALPHONS',
                'nom': 'THÉA',
                'sexe': 'M',
                'classe': self.classe.pk,
                'statut': 'ACTIF',
            },
        )

        eleve = Eleve.objects.get(matricule='CL8-002')
        self.assertRedirects(
            response,
            reverse('eleves:ajout_eleve_reussi', kwargs={'eleve_id': eleve.pk}),
        )

    def test_page_propose_paiement_ou_nouvel_eleve(self):
        eleve = Eleve.objects.create(
            matricule='CL8-002',
            prenom='ALPHONS',
            nom='THÉA',
            sexe='M',
            classe=self.classe,
        )

        response = self.client.get(
            reverse('eleves:ajout_eleve_reussi', kwargs={'eleve_id': eleve.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ALPHONS')
        self.assertContains(response, 'THÉA')
        self.assertContains(response, 'CL8-002')
        self.assertContains(
            response,
            reverse('paiements:ajouter_paiement_eleve', kwargs={'eleve_id': eleve.pk}),
        )
        self.assertContains(
            response,
            f"{reverse('eleves:ajouter_eleve')}?classe_id={self.classe.pk}",
        )

    def test_page_refuse_un_eleve_d_une_autre_ecole(self):
        response = self.client.get(
            reverse(
                'eleves:ajout_eleve_reussi',
                kwargs={'eleve_id': self.autre_eleve.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
