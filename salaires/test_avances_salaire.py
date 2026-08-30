from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole

from .models import AvanceSalaire, Enseignant, PeriodeSalaire, TypeEnseignant
from .services import calculer_etat_salaire


LICENCE_MIDDLEWARE = 'ecole_moderne.licence_middleware.LicenceMiddleware'
TEST_MIDDLEWARE = tuple(
    middleware for middleware in settings.MIDDLEWARE
    if middleware != LICENCE_MIDDLEWARE
)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class AvanceSalaireTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='gestionnaire-avances',
            email='avances@example.com',
            password='mot-de-passe-test',
        )
        self.ecole = Ecole.objects.create(
            nom='École test avances',
            adresse='Conakry',
            telephone='+224620000001',
            directeur='Direction test',
        )
        if hasattr(self.user, 'profil'):
            self.user.profil.ecole = self.ecole
            self.user.profil.save(update_fields=['ecole'])
        self.enseignant = Enseignant.objects.create(
            nom='CAMARA',
            prenoms='Mamadou',
            ecole=self.ecole,
            type_enseignant=TypeEnseignant.PRIMAIRE,
            statut='ACTIF',
            salaire_fixe=Decimal('1000000'),
            heures_mensuelles=Decimal('160'),
            date_embauche=date(2025, 1, 1),
            cree_par=self.user,
        )
        self.periode = PeriodeSalaire.objects.create(
            mois=8,
            annee=2026,
            ecole=self.ecole,
            nombre_semaines=Decimal('4'),
            cree_par=self.user,
        )
        self.etat, _ = calculer_etat_salaire(
            self.enseignant, self.periode, self.user
        )
        self.client.force_login(self.user)

    def donnees_avance(self, montant='200000', *, approuver=True):
        donnees = {
            'enseignant': self.enseignant.pk,
            'periode': self.periode.pk,
            'montant': montant,
            'date_avance': '2026-08-10',
            'mode_paiement': AvanceSalaire.ModePaiement.ESPECES,
            'reference_paiement': 'AV-001',
            'motif': 'Besoin familial',
            'observations': '',
        }
        if approuver:
            donnees['approuver_immediatement'] = 'on'
        return donnees

    def creer_avance(self, montant='200000', *, approuver=True):
        response = self.client.post(
            reverse('salaires:ajouter_avance_salaire'),
            self.donnees_avance(montant, approuver=approuver),
        )
        self.assertRedirects(response, reverse('salaires:liste_avances_salaire'))
        return AvanceSalaire.objects.get()

    def test_avance_approuvee_recalcule_immediatement_le_salaire(self):
        avance = self.creer_avance()

        self.assertEqual(avance.statut, AvanceSalaire.Statut.APPROUVEE)
        self.etat.refresh_from_db()
        self.assertEqual(self.etat.montant_avances, Decimal('200000'))
        self.assertEqual(self.etat.salaire_net, Decimal('800000'))

    def test_avance_en_attente_ne_reduit_pas_la_paie_avant_approbation(self):
        avance = self.creer_avance(approuver=False)

        self.assertEqual(avance.statut, AvanceSalaire.Statut.EN_ATTENTE)
        self.etat.refresh_from_db()
        self.assertEqual(self.etat.montant_avances, Decimal('0'))
        self.assertEqual(self.etat.salaire_net, Decimal('1000000'))

        response = self.client.post(
            reverse('salaires:approuver_avance_salaire', args=[avance.pk])
        )
        self.assertRedirects(response, reverse('salaires:liste_avances_salaire'))
        avance.refresh_from_db()
        self.etat.refresh_from_db()
        self.assertEqual(avance.statut, AvanceSalaire.Statut.APPROUVEE)
        self.assertEqual(self.etat.salaire_net, Decimal('800000'))

    def test_annulation_exige_un_motif_et_retablit_le_salaire(self):
        avance = self.creer_avance()

        self.client.post(
            reverse('salaires:annuler_avance_salaire', args=[avance.pk]),
            {'motif_annulation': ''},
        )
        avance.refresh_from_db()
        self.assertEqual(avance.statut, AvanceSalaire.Statut.APPROUVEE)

        self.client.post(
            reverse('salaires:annuler_avance_salaire', args=[avance.pk]),
            {'motif_annulation': 'Erreur de saisie'},
        )
        avance.refresh_from_db()
        self.etat.refresh_from_db()
        self.assertEqual(avance.statut, AvanceSalaire.Statut.ANNULEE)
        self.assertEqual(avance.motif_annulation, 'Erreur de saisie')
        self.assertEqual(self.etat.montant_avances, Decimal('0'))
        self.assertEqual(self.etat.salaire_net, Decimal('1000000'))

    def test_avance_superieure_au_salaire_est_refusee(self):
        response = self.client.post(
            reverse('salaires:ajouter_avance_salaire'),
            self.donnees_avance('1000001'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dépasse le salaire disponible')
        self.assertFalse(AvanceSalaire.objects.exists())

    def test_retenues_et_avances_ne_peuvent_pas_depasser_le_salaire_brut(self):
        self.creer_avance()

        response = self.client.post(
            reverse('salaires:ajuster_etat_salaire', args=[self.etat.pk]),
            {
                'primes': '0',
                'deductions': '900000',
                'observations': 'Retenue exceptionnelle',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'retenues et avances')
        self.etat.refresh_from_db()
        self.assertEqual(self.etat.deductions, Decimal('0'))
        self.assertEqual(self.etat.salaire_net, Decimal('800000'))

    def test_paiement_de_la_paie_marque_l_avance_comme_deduite(self):
        avance = self.creer_avance()
        self.client.post(
            reverse('salaires:valider_etat_salaire', args=[self.etat.pk])
        )
        self.client.post(reverse('salaires:marquer_paye', args=[self.etat.pk]))

        avance.refresh_from_db()
        self.etat.refresh_from_db()
        self.assertEqual(avance.statut, AvanceSalaire.Statut.DEDUITE)
        self.assertIsNotNone(avance.date_deduction)
        self.assertTrue(self.etat.paye)
        self.assertEqual(self.etat.salaire_net, Decimal('800000'))

    def test_pages_de_gestion_des_avances_s_affichent(self):
        avance = self.creer_avance()

        for url in (
            reverse('salaires:tableau_bord'),
            reverse('salaires:liste_avances_salaire'),
            reverse('salaires:ajouter_avance_salaire'),
            reverse('salaires:detail_enseignant', args=[self.enseignant.pk]),
            reverse('salaires:modifier_avance_salaire', args=[avance.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
