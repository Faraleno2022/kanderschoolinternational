"""Rattrapage des échéanciers déjà faussés en base.

Le correctif du recalcul empêche de nouvelles divergences ; cette commande
répare celles qui existent déjà, sans jamais toucher aux échéanciers justes.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from eleves.models import Classe, Ecole, Eleve
from paiements.models import (
    EcheancierPaiement, ModePaiement, Paiement, TypePaiement,
)
from paiements.soldes import recalculer_echeancier

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class RecalculSoldesTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Source', adresse='Conakry', telephone='620000921',
            directeur='Direction',
        )
        self.ecole_arrivee = Ecole.objects.create(
            nom='École Arrivée', adresse='Conakry', telephone='620000922',
            directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='CP1', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.classe_arrivee = Classe.objects.create(
            ecole=self.ecole_arrivee, nom='CP2', niveau='PRIMAIRE_2',
            annee_scolaire='2026-2027',
        )
        self.eleve = Eleve.objects.create(
            matricule='REC-001', prenom='Fatoumata', nom='Sylla', sexe='F',
            date_naissance=date(2016, 1, 1), lieu_naissance='Conakry',
            classe=self.classe, date_inscription=date(2025, 9, 1),
        )
        self.type_t1 = TypePaiement.objects.create(nom='Scolarité - 1ère tranche')
        self.mode = ModePaiement.objects.create(nom='Espèces')

        # Situation héritée : l'échéancier annonce 500 000 payés alors que le
        # paiement encaissé n'en vaut que 200 000.
        self.echeancier = self._echeancier(self.classe, '2025-2026')
        Paiement.objects.create(
            eleve=self.eleve, type_paiement=self.type_t1, mode_paiement=self.mode,
            montant=Decimal('200000'), statut='VALIDE',
            date_paiement=date(2025, 10, 2),
        )
        EcheancierPaiement.objects.filter(pk=self.echeancier.pk).update(
            tranche_1_payee=Decimal('500000'), statut='PAYE_COMPLET',
        )
        self.echeancier.refresh_from_db()

    def _echeancier(self, classe, annee):
        return EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire=annee,
            ecole_reference=classe.ecole, classe_reference=classe,
            frais_inscription_du=Decimal('0'), tranche_1_due=Decimal('500000'),
            tranche_2_due=Decimal('0'), tranche_3_due=Decimal('0'),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )

    def _lancer(self, *arguments):
        sortie = StringIO()
        call_command('recalculer_soldes', *arguments, stdout=sortie)
        return sortie.getvalue()

    def test_la_commande_repare_un_echeancier_fausse(self):
        rapport = self._lancer()

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('200000'))
        self.assertEqual(self.echeancier.statut, 'EN_RETARD')
        self.assertIn('REC-001', rapport)
        self.assertIn('500000', rapport)
        self.assertIn('200000', rapport)

    def test_la_simulation_mesure_sans_rien_ecrire(self):
        rapport = self._lancer('--simulation')

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('500000'))
        self.assertIn('Aucune écriture', rapport)
        self.assertIn('1 à corriger', rapport)

    def test_un_echeancier_deja_juste_reste_intact(self):
        recalculer_echeancier(self.echeancier)
        self.echeancier.refresh_from_db()
        date_avant = self.echeancier.date_modification

        rapport = self._lancer()

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.date_modification, date_avant)
        self.assertIn('tous déjà justes', rapport)

    def test_le_rattrapage_est_idempotent(self):
        self._lancer()
        self.echeancier.refresh_from_db()
        premier_passage = self.echeancier.tranche_1_payee

        self._lancer()

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, premier_passage)

    def test_le_filtre_par_annee_epargne_les_autres(self):
        """Un échéancier hors périmètre ne doit pas être touché."""
        echeancier_arrivee = self._echeancier(self.classe_arrivee, '2026-2027')
        EcheancierPaiement.objects.filter(pk=echeancier_arrivee.pk).update(
            tranche_1_payee=Decimal('500000'), statut='PAYE_COMPLET',
        )

        self._lancer('--annee', '2025-2026')

        self.echeancier.refresh_from_db()
        echeancier_arrivee.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('200000'))
        self.assertEqual(echeancier_arrivee.tranche_1_payee, Decimal('500000'))

    def test_le_filtre_par_ecole_epargne_les_autres(self):
        echeancier_arrivee = self._echeancier(self.classe_arrivee, '2026-2027')
        EcheancierPaiement.objects.filter(pk=echeancier_arrivee.pk).update(
            tranche_1_payee=Decimal('500000'), statut='PAYE_COMPLET',
        )

        self._lancer('--ecole', str(self.ecole_arrivee.id))

        self.echeancier.refresh_from_db()
        echeancier_arrivee.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('500000'))
        self.assertEqual(echeancier_arrivee.tranche_1_payee, Decimal('0'))

    def test_un_paiement_annule_ne_couvre_plus_rien(self):
        Paiement.objects.filter(eleve=self.eleve).update(statut='ANNULE')

        self._lancer()

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('0'))
        self.assertEqual(self.echeancier.statut, 'EN_RETARD')

    def test_un_surplus_ne_gonfle_pas_les_tranches(self):
        """Payer plus que le dû laisse un crédit, pas une tranche surévaluée."""
        Paiement.objects.create(
            eleve=self.eleve, type_paiement=self.type_t1, mode_paiement=self.mode,
            montant=Decimal('600000'), statut='VALIDE',
            date_paiement=date(2025, 10, 3),
        )

        self._lancer()

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('500000'))
        self.assertEqual(self.echeancier.statut, 'PAYE_COMPLET')
