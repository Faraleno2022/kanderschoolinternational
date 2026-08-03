from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole

from .models_fournitures import ProduitFourniture, VenteFourniture


TEST_MIDDLEWARE = [
    middleware
    for middleware in settings.MIDDLEWARE
    if middleware != 'ecole_moderne.licence_middleware.LicenceMiddleware'
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class FournituresScolairesTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École fournitures',
            adresse='Conakry',
            telephone='+224620000011',
            directeur='Direction',
        )
        self.autre_ecole = Ecole.objects.create(
            nom='Autre école',
            adresse='Conakry',
            telephone='+224620000012',
            directeur='Direction',
        )
        self.user = User.objects.create_user('boutique', password='secret')
        profil = self.user.profil
        profil.role = 'ADMIN'
        profil.telephone = '+224620000013'
        profil.ecole = self.ecole
        profil.is_validated = True
        profil.save()
        self.client.force_login(self.user)

        self.produit = ProduitFourniture.objects.create(
            ecole=self.ecole,
            nom='Cahier 100 pages',
            quantite_stock=10,
            prix_achat_unitaire=Decimal('1000'),
            prix_vente_unitaire=Decimal('1500'),
            seuil_alerte=2,
            cree_par=self.user,
        )
        self.produit_autre_ecole = ProduitFourniture.objects.create(
            ecole=self.autre_ecole,
            nom='Stylo bleu',
            quantite_stock=20,
            prix_achat_unitaire=Decimal('500'),
            prix_vente_unitaire=Decimal('750'),
        )

    def enregistrer_vente(self, quantite=4):
        return self.client.post(
            reverse('depenses:vendre_fourniture', args=[self.produit.pk]),
            {
                'quantite': quantite,
                'date_vente': '2026-08-03',
                'acheteur': 'Aminata Diallo',
                'observations': '',
            },
        )

    def test_vente_calcule_stock_montants_et_solde(self):
        response = self.enregistrer_vente(4)

        self.assertRedirects(response, reverse('depenses:dashboard_fournitures'))
        vente = VenteFourniture.objects.get(produit=self.produit)
        self.assertEqual(vente.montant_achat, Decimal('4000'))
        self.assertEqual(vente.montant_vente, Decimal('6000'))
        self.assertEqual(vente.solde, Decimal('2000'))

        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite_vendue, 4)
        self.assertEqual(self.produit.quantite_restante, 6)

        dashboard = self.client.get(reverse('depenses:dashboard_fournitures'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['stats']['quantite_vendue'], 4)
        self.assertEqual(dashboard.context['stats']['quantite_restante'], 6)
        self.assertEqual(dashboard.context['stats']['solde'], Decimal('2000'))

    def test_vente_refuse_une_quantite_superieure_au_stock_disponible(self):
        self.enregistrer_vente(4)
        response = self.enregistrer_vente(7)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stock insuffisant')
        self.assertEqual(
            VenteFourniture.objects.filter(
                produit=self.produit,
                statut=VenteFourniture.STATUT_CONFIRMEE,
            ).count(),
            1,
        )
        self.assertEqual(self.produit.quantite_restante, 6)

    def test_annulation_vente_restitue_le_stock_et_annule_le_solde(self):
        self.enregistrer_vente(4)
        vente = VenteFourniture.objects.get(produit=self.produit)

        response = self.client.post(
            reverse('depenses:annuler_vente_fourniture', args=[vente.pk])
        )

        self.assertRedirects(response, reverse('depenses:dashboard_fournitures'))
        vente.refresh_from_db()
        self.assertEqual(vente.statut, VenteFourniture.STATUT_ANNULEE)
        self.assertEqual(vente.annulee_par, self.user)
        self.assertIsNotNone(vente.date_annulation)
        self.assertEqual(self.produit.quantite_vendue, 0)
        self.assertEqual(self.produit.quantite_restante, 10)

        dashboard = self.client.get(reverse('depenses:dashboard_fournitures'))
        self.assertEqual(dashboard.context['stats']['quantite_vendue'], 0)
        self.assertEqual(dashboard.context['stats']['solde'], Decimal('0'))

    def test_les_produits_sont_strictement_isoles_par_ecole(self):
        dashboard = self.client.get(reverse('depenses:dashboard_fournitures'))

        self.assertContains(dashboard, self.produit.nom)
        self.assertNotContains(dashboard, self.produit_autre_ecole.nom)
        vente_autre_ecole = self.client.get(
            reverse('depenses:vendre_fourniture', args=[self.produit_autre_ecole.pk])
        )
        self.assertEqual(vente_autre_ecole.status_code, 404)

    def test_stock_total_ne_peut_pas_descendre_sous_la_quantite_vendue(self):
        self.enregistrer_vente(4)
        response = self.client.post(
            reverse('depenses:modifier_produit_fourniture', args=[self.produit.pk]),
            {
                'ecole': self.ecole.pk,
                'nom': self.produit.nom,
                'description': '',
                'unite': 'PIECE',
                'quantite_stock': 3,
                'prix_achat_unitaire': '1000',
                'prix_vente_unitaire': '1500',
                'seuil_alerte': 2,
                'actif': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'déjà vendue')
        self.produit.refresh_from_db()
        self.assertEqual(self.produit.quantite_stock, 10)
