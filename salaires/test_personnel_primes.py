from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from . import tests as support
from .forms import EnseignantForm
from .models import Enseignant, TypeEnseignant, PeriodeSalaire
from .services import calculer_etat_salaire, appliquer_ajustement_etat_salaire


@override_settings(MIDDLEWARE=support.TEST_MIDDLEWARE)
class PersonnelPrimesTests(TestCase):
    setUp = support.MoteurPaieTests.setUp
    types = [TypeEnseignant.CHAUFFEUR, TypeEnseignant.VIGILE,
             TypeEnseignant.ENTRETIEN, TypeEnseignant.NOUNOU, TypeEnseignant.RESTAURATION]

    def donnees(self, type_personnel=TypeEnseignant.CHAUFFEUR, **extra):
        data = dict(nom='Travailleur', prenoms='Test', ecole=self.ecole.pk,
                    type_enseignant=type_personnel, statut='ACTIF', fonction='Responsable service',
                    salaire_fixe='1000000', primes_mensuelles='50000', date_embauche='2025-01-01')
        data.update(extra)
        return data

    def creer(self):
        form = EnseignantForm(self.donnees(), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def test_categories_creees_sans_classe_et_remunerees(self):
        for type_personnel in self.types:
            with self.subTest(type=type_personnel):
                response = self.client.post(reverse('salaires:ajouter_enseignant'), self.donnees(type_personnel))
                self.assertEqual(response.status_code, 302)
                employe = Enseignant.objects.get(type_enseignant=type_personnel)
                self.assertTrue(employe.est_salaire_fixe)
                self.assertFalse(employe.est_affectable_classe)
                self.assertEqual(employe.fonction, 'Responsable service')
                self.assertEqual(employe.calculer_salaire_mensuel(), Decimal('1000000'))
                etat, _ = calculer_etat_salaire(employe, self.periode, self.user)
                self.assertEqual(etat.primes, Decimal('50000'))
                self.assertEqual(etat.salaire_net, Decimal('1050000'))

    def test_primes_negatives_refusees_et_champ_vide_zero(self):
        form = EnseignantForm(self.donnees(primes_mensuelles='-1'), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('primes_mensuelles', form.errors)
        form = EnseignantForm(self.donnees(primes_mensuelles=''), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().primes_mensuelles, 0)

    def test_salaire_fixe_obligatoire(self):
        form = EnseignantForm(self.donnees(salaire_fixe=''), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('salaire_fixe', form.errors)

    def test_prime_ajustee_conservee_au_recalcul(self):
        employe = self.creer()
        etat, _ = calculer_etat_salaire(employe, self.periode, self.user)
        appliquer_ajustement_etat_salaire(etat, self.user, salaire_base=Decimal('1000000'),
                                        primes=Decimal('75000'), deductions=Decimal('10000'))
        employe.primes_mensuelles = Decimal('20000')
        employe.save()
        etat, _ = calculer_etat_salaire(employe, self.periode, self.user)
        self.assertEqual(etat.primes, Decimal('75000'))
        self.assertEqual(etat.salaire_net, Decimal('1065000'))
        periode = PeriodeSalaire.objects.create(mois=8, annee=2026, ecole=self.ecole, cree_par=self.user)
        suivant, _ = calculer_etat_salaire(employe, periode, self.user)
        self.assertEqual(suivant.primes, Decimal('20000'))

    def test_ajout_modification_et_filtre_affichent_primes_et_categories(self):
        response = self.client.get(reverse('salaires:ajouter_enseignant'))
        self.assertContains(response, 'name="primes_mensuelles"')
        for choix in self.types:
            self.assertContains(response, choix.label)
        employe = self.creer()
        response = self.client.post(reverse('salaires:modifier_enseignant', args=[employe.pk]),
                                    self.donnees(primes_mensuelles='80000'))
        self.assertEqual(response.status_code, 302)
        employe.refresh_from_db()
        self.assertEqual(employe.primes_mensuelles, 80000)
        response = self.client.get(reverse('salaires:liste_enseignants'), {'type_enseignant': 'CHAUFFEUR'})
        self.assertContains(response, 'Chauffeur')
        self.assertEqual(list(response.context['enseignants']), [employe])
