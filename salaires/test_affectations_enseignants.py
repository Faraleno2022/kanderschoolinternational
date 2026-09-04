from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole

from .forms import AffectationClasseForm, EnseignantForm
from .models import AffectationClasse, Enseignant, TypeEnseignant


LICENCE_MIDDLEWARE = 'ecole_moderne.licence_middleware.LicenceMiddleware'
TEST_MIDDLEWARE = tuple(
    middleware for middleware in settings.MIDDLEWARE
    if middleware != LICENCE_MIDDLEWARE
)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class AffectationsEnseignantsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='gestion-affectations',
            email='affectations@example.com',
            password='mot-de-passe-test',
        )
        self.ecole = Ecole.objects.create(
            nom='École des affectations',
            adresse='Conakry',
            telephone='+224620000010',
            directeur='Direction test',
        )
        self.autre_ecole = Ecole.objects.create(
            nom='Autre école',
            adresse='Conakry',
            telephone='+224620000011',
            directeur='Autre direction',
        )
        self.primaire_a = self.creer_classe('Primaire A', 'PRIMAIRE_1')
        self.primaire_b = self.creer_classe('Primaire B', 'PRIMAIRE_2')
        self.maternelle = self.creer_classe('Grande section', 'MATERNELLE')
        self.secondaire_a = self.creer_classe('7e A', 'COLLEGE_7')
        self.secondaire_b = self.creer_classe('8e B', 'COLLEGE_8')
        self.classe_autre_ecole = Classe.objects.create(
            ecole=self.autre_ecole,
            nom='Primaire externe',
            niveau='PRIMAIRE_1',
            annee_scolaire='2026-2027',
        )
        self.client.force_login(self.user)

    def creer_classe(self, nom, niveau):
        return Classe.objects.create(
            ecole=self.ecole,
            nom=nom,
            niveau=niveau,
            annee_scolaire='2026-2027',
        )

    def donnees_enseignant(self, type_enseignant, **overrides):
        data = {
            'nom': 'CAMARA',
            'prenoms': 'Aminata',
            'telephone': '',
            'email': 'aminata@example.com',
            'adresse': '',
            'ecole': self.ecole.pk,
            'type_enseignant': type_enseignant,
            'statut': 'ACTIF',
            'fonction': '',
            'taux_horaire': '',
            'salaire_fixe': '1500000',
            'heures_mensuelles': '160',
            'date_embauche': '2026-01-02',
            'classe_affectee': '',
            'matiere_affectee': '',
            'heures_par_semaine_affectation': '',
        }
        if type_enseignant == TypeEnseignant.SECONDAIRE:
            data.update({
                'taux_horaire': '25000',
                'salaire_fixe': '',
                'heures_mensuelles': '',
            })
        data.update(overrides)
        return data

    def enregistrer_formulaire(self, data, instance=None):
        form = EnseignantForm(data=data, instance=instance, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        enseignant = form.save()
        form.save_affectation(enseignant)
        return enseignant

    def test_primaire_peut_recevoir_une_classe_principale(self):
        enseignant = self.enregistrer_formulaire(
            self.donnees_enseignant(
                TypeEnseignant.PRIMAIRE,
                classe_affectee=str(self.primaire_a.pk),
            )
        )

        affectation = enseignant.affectations.get(actif=True)
        self.assertEqual(affectation.classe, self.primaire_a)
        self.assertIsNone(affectation.heures_par_semaine)
        self.assertEqual(affectation.matiere, '')

    def test_changer_la_classe_primaire_clot_l_ancienne(self):
        enseignant = self.enregistrer_formulaire(
            self.donnees_enseignant(
                TypeEnseignant.PRIMAIRE,
                classe_affectee=str(self.primaire_a.pk),
            )
        )

        self.enregistrer_formulaire(
            self.donnees_enseignant(
                TypeEnseignant.PRIMAIRE,
                classe_affectee=str(self.primaire_b.pk),
            ),
            instance=enseignant,
        )

        self.assertEqual(
            list(enseignant.affectations.filter(actif=True).values_list('classe_id', flat=True)),
            [self.primaire_b.pk],
        )
        ancienne = enseignant.affectations.get(classe=self.primaire_a)
        self.assertFalse(ancienne.actif)
        self.assertIsNotNone(ancienne.date_fin)

    def test_classe_d_un_autre_cycle_ou_ecole_est_refusee(self):
        for classe in (self.secondaire_a, self.classe_autre_ecole):
            form = EnseignantForm(
                data=self.donnees_enseignant(
                    TypeEnseignant.PRIMAIRE,
                    classe_affectee=str(classe.pk),
                ),
                user=self.user,
            )
            self.assertFalse(form.is_valid())
            self.assertIn('classe_affectee', form.errors)

    def test_secondaire_reste_creable_sans_affectation_initiale(self):
        form = EnseignantForm(
            data=self.donnees_enseignant(TypeEnseignant.SECONDAIRE),
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_heures_sont_obligatoires_si_classe_secondaire_selectionnee(self):
        form = EnseignantForm(
            data=self.donnees_enseignant(
                TypeEnseignant.SECONDAIRE,
                classe_affectee=str(self.secondaire_a.pk),
            ),
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('heures_par_semaine_affectation', form.errors)

    def test_secondaire_peut_cumuler_plusieurs_affectations(self):
        enseignant = self.enregistrer_formulaire(
            self.donnees_enseignant(
                TypeEnseignant.SECONDAIRE,
                classe_affectee=str(self.secondaire_a.pk),
                matiere_affectee='Mathématiques',
                heures_par_semaine_affectation='6',
            )
        )
        form = AffectationClasseForm(
            data={
                'classe': self.secondaire_b.pk,
                'heures_par_semaine': '4',
                'matiere': 'Physique',
                'date_debut': '2026-02-01',
                'date_fin': '',
                'actif': 'on',
            },
            enseignant=enseignant,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertEqual(enseignant.affectations.filter(actif=True).count(), 2)
        self.assertSetEqual(
            set(enseignant.affectations.values_list('matiere', flat=True)),
            {'Mathématiques', 'Physique'},
        )

    def test_administrateur_peut_avoir_une_fonction_sans_classe(self):
        enseignant = self.enregistrer_formulaire(
            self.donnees_enseignant(
                TypeEnseignant.ADMINISTRATEUR,
                fonction='Directrice administrative',
            )
        )

        self.assertEqual(enseignant.fonction, 'Directrice administrative')
        self.assertFalse(enseignant.est_affectable_classe)
        self.assertFalse(enseignant.affectations.exists())

    def test_detail_affiche_affectation_et_fonction(self):
        enseignant = self.enregistrer_formulaire(
            self.donnees_enseignant(
                TypeEnseignant.PRIMAIRE,
                classe_affectee=str(self.primaire_a.pk),
            )
        )
        response = self.client.get(
            reverse('salaires:detail_enseignant', args=[enseignant.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Affectations de classes')
        self.assertContains(response, self.primaire_a.nom)

    def test_ajax_classes_expose_le_cycle_et_l_annee(self):
        response = self.client.get(
            reverse('eleves:ajax_classes_par_ecole', args=[self.ecole.pk])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['classes'])
        self.assertIn('niveau', data['classes'][0])
        self.assertIn('annee_scolaire', data['classes'][0])
