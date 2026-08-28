"""Un versement incomplet doit être accepté du premier coup.

Le paiement partiel d'une tranche simple passait déjà sans friction, mais
les frais d'inscription et les types combinés étaient bloqués au premier
envoi : message d'erreur, case à cocher, puis second envoi. Le moteur
d'allocation répartissant déjà correctement un montant incomplet, cette
confirmation ne protégeait de rien — elle coûtait juste une manipulation.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from paiements.models import (
    EcheancierPaiement, ModePaiement, Paiement, TypePaiement,
)

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class PaiementPartielTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Test', adresse='Conakry', telephone='620000931',
            directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='CP1', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.eleve = Eleve.objects.create(
            matricule='PAR-001', prenom='Ibrahima', nom='Barry', sexe='M',
            date_naissance=date(2016, 1, 1), lieu_naissance='Conakry',
            classe=self.classe, date_inscription=date(2025, 9, 1),
        )
        EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire='2025-2026',
            ecole_reference=self.ecole, classe_reference=self.classe,
            frais_inscription_du=Decimal('300000'),
            tranche_1_due=Decimal('500000'),
            tranche_2_due=Decimal('400000'),
            tranche_3_due=Decimal('300000'),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )
        self.mode = ModePaiement.objects.create(nom='Espèces')
        self.inscription = TypePaiement.objects.create(nom='Inscription')
        self.tranche_1 = TypePaiement.objects.create(nom='Scolarité - 1ère tranche')
        self.combine = TypePaiement.objects.create(
            nom='Scolarité - Tranche 1 + Tranche 2',
        )

        self.user = get_user_model().objects.create_superuser(
            username='caissier_partiel', email='caissier.partiel@example.com',
            password='pass12345',
        )
        self.client.force_login(self.user)
        self.url = reverse(
            'paiements:ajouter_paiement_eleve', kwargs={'eleve_id': self.eleve.id},
        )

    def _payer(self, type_paiement, montant):
        """Un seul envoi, sans aucune case de confirmation."""
        return self.client.post(self.url, {
            'eleve': self.eleve.id,
            'type_paiement': type_paiement.id,
            'mode_paiement': self.mode.id,
            'montant': str(montant),
            'date_paiement': '2025-10-02',
            'reference_externe': '',
            'observations': '',
        }, follow=True)

    def _dernier_paiement(self):
        return Paiement.objects.filter(eleve=self.eleve).order_by('-pk').first()

    def test_une_inscription_partielle_passe_du_premier_coup(self):
        reponse = self._payer(self.inscription, 100000)

        paiement = self._dernier_paiement()
        self.assertIsNotNone(paiement, "Le versement aurait dû être enregistré.")
        self.assertEqual(paiement.montant, Decimal('100000'))
        self.assertNotContains(reponse, 'confirmation_paiement_partiel')

    def test_un_type_combine_partiel_passe_du_premier_coup(self):
        reponse = self._payer(self.combine, 200000)

        paiement = self._dernier_paiement()
        self.assertIsNotNone(paiement)
        self.assertEqual(paiement.montant, Decimal('200000'))
        self.assertNotContains(reponse, 'confirmation_paiement_partiel')

    def test_une_tranche_simple_partielle_reste_acceptee(self):
        """Non-régression : ce cas passait déjà, il doit continuer."""
        self._payer(self.tranche_1, 150000)

        paiement = self._dernier_paiement()
        self.assertIsNotNone(paiement)
        self.assertEqual(paiement.montant, Decimal('150000'))

    def test_l_agent_est_informe_du_reste_a_payer(self):
        reponse = self._payer(self.inscription, 100000)

        textes = [str(message) for message in reponse.context['messages']]
        partiel = [texte for texte in textes if 'partiel' in texte.lower()]
        self.assertTrue(partiel, textes)
        self.assertIn('200 000', partiel[0])

    def test_le_message_informe_sans_bloquer(self):
        """Le versement est enregistré : l'information ne doit pas être une erreur."""
        reponse = self._payer(self.inscription, 100000)

        niveaux = {
            message.level_tag
            for message in reponse.context['messages']
            if 'partiel' in str(message).lower()
        }
        self.assertEqual(niveaux, {'info'})
        self.assertIsNotNone(self._dernier_paiement())

    def test_le_plafond_anti_surpaiement_reste_actif(self):
        """Retirer la confirmation ne doit pas ouvrir la porte au surpaiement."""
        total_du = 300000 + 500000 + 400000 + 300000

        self._payer(self.inscription, total_du + 1)

        self.assertIsNone(
            self._dernier_paiement(),
            "Un montant supérieur au reste total doit rester refusé.",
        )
