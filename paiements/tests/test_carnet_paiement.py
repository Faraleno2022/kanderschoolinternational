from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from paiements.carnet_paiement import _construire_donnees_carnet
from paiements.models import (
    EcheancierPaiement,
    ModePaiement,
    Paiement,
    PaiementRemise,
    RemiseReduction,
    TypePaiement,
)

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class CarnetPaiementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin-carnet',
            email='carnet@example.com',
            password='mot-de-passe-test',
        )
        self.client.force_login(self.user)
        self.ecole = Ecole.objects.create(
            nom='École carnet professionnel',
            adresse='Conakry',
            telephone='+224620000901',
            directeur='Direction carnet',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole,
            nom='6ème année carnet',
            niveau='PRIMAIRE_6',
            annee_scolaire='2026-2027',
        )
        self.eleve = Eleve.objects.create(
            matricule='CAR-001',
            prenom='Fatoumata',
            nom='Camara',
            sexe='F',
            date_naissance=date(2015, 1, 1),
            classe=self.classe,
            date_inscription=date(2026, 9, 1),
        )
        self.type_paiement = TypePaiement.objects.create(nom='Tranche carnet')
        self.mode_paiement = ModePaiement.objects.create(nom='Espèces carnet')
        self.paiement_1 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_paiement,
            mode_paiement=self.mode_paiement,
            montant=Decimal('120000'),
            date_paiement=date(2026, 9, 10),
            statut='VALIDE',
            cree_par=self.user,
            valide_par=self.user,
        )
        self.paiement_2 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_paiement,
            mode_paiement=self.mode_paiement,
            montant=Decimal('50000'),
            date_paiement=date(2026, 10, 5),
            statut='VALIDE',
            cree_par=self.user,
            valide_par=self.user,
        )
        Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_paiement,
            mode_paiement=self.mode_paiement,
            montant=Decimal('999999'),
            date_paiement=date(2026, 10, 6),
            statut='EN_ATTENTE',
            cree_par=self.user,
        )
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve,
            annee_scolaire='2026-2027',
            frais_inscription_du=Decimal('20000'),
            tranche_1_due=Decimal('100000'),
            tranche_2_due=Decimal('100000'),
            tranche_3_due=Decimal('100000'),
            date_echeance_inscription=date(2026, 9, 1),
            date_echeance_tranche_1=date(2026, 10, 1),
            date_echeance_tranche_2=date(2027, 1, 1),
            date_echeance_tranche_3=date(2027, 3, 1),
        )
        remise = RemiseReduction.objects.create(
            nom='Remise carnet',
            type_remise='MONTANT_FIXE',
            valeur=Decimal('20000'),
            motif='SOCIALE',
            date_debut=date(2026, 9, 1),
            date_fin=date(2027, 6, 30),
            cree_par=self.user,
        )
        PaiementRemise.objects.create(
            paiement=self.paiement_1,
            remise=remise,
            montant_remise=Decimal('20000'),
            motif_application='GESTE_COMMERCIAL',
        )

    def test_reste_progressif_utilise_paiements_valides_et_remises(self):
        donnees = _construire_donnees_carnet(self.paiement_1)

        self.assertEqual(donnees['total_du'], Decimal('320000'))
        self.assertEqual(donnees['total_encaisse'], Decimal('170000'))
        self.assertEqual(donnees['total_remises'], Decimal('20000'))
        self.assertEqual(donnees['reste_final'], Decimal('130000'))
        self.assertEqual([ligne['mois'] for ligne in donnees['lignes']], ['Septembre', 'Octobre'])
        self.assertEqual(
            [ligne['reste'] for ligne in donnees['lignes']],
            [Decimal('180000'), Decimal('130000')],
        )

    def test_pdf_et_bouton_carnet_sont_disponibles(self):
        carnet_url = reverse(
            'paiements:generer_carnet_paiement_pdf',
            kwargs={'paiement_id': self.paiement_1.pk},
        )
        response = self.client.get(carnet_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('Carnet_paiement_CAR-001_2026-2027.pdf', response['Content-Disposition'])

        detail = self.client.get(reverse(
            'paiements:detail_paiement',
            kwargs={'paiement_id': self.paiement_1.pk},
        ))
        self.assertContains(detail, carnet_url)
        self.assertContains(detail, 'Carnet de paiement')

    def test_carnet_refuse_un_paiement_non_valide(self):
        paiement_en_attente = Paiement.objects.filter(statut='EN_ATTENTE').get()
        response = self.client.get(reverse(
            'paiements:generer_carnet_paiement_pdf',
            kwargs={'paiement_id': paiement_en_attente.pk},
        ))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse('paiements:detail_paiement', kwargs={'paiement_id': paiement_en_attente.pk}),
        )
