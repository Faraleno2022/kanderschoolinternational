from decimal import Decimal
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from eleves.models import Ecole, Classe, Eleve, Responsable, GrilleTarifaire
from paiements.models import (
    EcheancierPaiement,  
    TypePaiement,
    ModePaiement,
    Paiement,
)
from paiements.views import _allocate_combined_payment, _get_payment_allocation_breakdown


class TestAllocationPaiements(TestCase):
    def setUp(self):
        # Contexte de base
        self.ecole = Ecole.objects.create(
            nom="Ecole Test",
            adresse="Adresse",
            telephone="+224622000000",
            email="ecole@test.local",
            directeur="Directeur Test",
        )
        annee = "2024-2025"
        self.classe = Classe.objects.create(
            ecole=self.ecole,
            nom="6ème A",
            niveau="PRIMAIRE_6",
            annee_scolaire=annee,
            capacite_max=40,
        )
        self.resp = Responsable.objects.create(
            prenom="Jean",
            nom="Dupont",
            relation="PERE",
            telephone="+224622111111",
            email="parent@test.local",
            adresse="Adresse parent",
            profession="Dev",
        )
        self.eleve = Eleve.objects.create(
            matricule="T0001",
            prenom="Ali",
            nom="Sy",
            sexe="M",
            date_naissance=date(2015, 1, 1),
            lieu_naissance="Conakry",
            photo=None,
            classe=self.classe,
            date_inscription=date(2024, 9, 15),
            responsable_principal=self.resp,
        )

        # Types et mode de paiement
        self.type_insc_t1 = TypePaiement.objects.create(nom="Frais d'inscription + 1ère tranche")
        self.type_insc_t1_t2 = TypePaiement.objects.create(nom="Frais d'inscription + 1ère tranche + 2ème tranche")
        self.type_t2 = TypePaiement.objects.create(nom="Scolarité - 2ème tranche")
        self.type_t3 = TypePaiement.objects.create(nom="Scolarité - 3ème tranche")
        self.type_insc_annuel = TypePaiement.objects.create(nom="Frais d'inscription + Annuel")
        self.mode_especes = ModePaiement.objects.create(nom="Espèces")

        # Echéancier
        # Frais: 30k + 500k + 500k + 500k
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve,
            annee_scolaire=annee,
            frais_inscription_du=Decimal("30000"),
            tranche_1_due=Decimal("500000"),
            tranche_2_due=Decimal("500000"),
            tranche_3_due=Decimal("500000"),
            date_echeance_inscription=date(2024, 9, 30),
            date_echeance_tranche_1=date(2025, 1, 10),
            date_echeance_tranche_2=date(2025, 3, 5),
            date_echeance_tranche_3=date(2025, 4, 6),
        )

    def _refresh(self):
        self.echeancier.refresh_from_db()

    @patch('paiements.views.timezone.localdate', return_value=date(2024, 9, 30))
    def test_inscription_plus_t1_puis_t2_puis_t3(self, _mock_localdate):
        # 1) Inscription + T1
        paiement1 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_t1,
            mode_paiement=self.mode_especes,
            numero_recu="REC_TEST_1",
            montant=Decimal("530000"),  # 30k + 500k
            date_paiement=date(2024, 9, 30),
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement1, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.frais_inscription_paye, Decimal("30000"))
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_2_payee, Decimal("0"))
        self.assertEqual(self.echeancier.tranche_3_payee, Decimal("0"))
        self.assertEqual(self.echeancier.statut, "PAYE_PARTIEL")

        # 2) T2
        paiement2 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_t2,
            mode_paiement=self.mode_especes,
            numero_recu="REC_TEST_2",
            montant=Decimal("500000"),
            date_paiement=date(2025, 1, 15),
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement2, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.tranche_2_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.statut, "PAYE_PARTIEL")

        # 3) T3
        paiement3 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_t3,
            mode_paiement=self.mode_especes,
            numero_recu="REC_TEST_3",
            montant=Decimal("500000"),
            date_paiement=date(2025, 3, 10),
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement3, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.tranche_3_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.solde_restant, Decimal("0"))
        self.assertEqual(self.echeancier.statut, "PAYE_COMPLET")

    @patch('paiements.views.timezone.localdate', return_value=date(2024, 9, 30))
    def test_inscription_plus_t1_t2_puis_t3(self, _mock_localdate):
        # 1) Inscription + T1 + T2
        paiement1 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_t1_t2,
            mode_paiement=self.mode_especes,
            numero_recu="REC_TEST_4",
            montant=Decimal("1030000"),  # 30k + 500k + 500k
            date_paiement=date(2024, 9, 30),
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement1, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.frais_inscription_paye, Decimal("30000"))
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_2_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_3_payee, Decimal("0"))
        self.assertEqual(self.echeancier.statut, "PAYE_PARTIEL")

        # 2) T3
        paiement2 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_t3,
            mode_paiement=self.mode_especes,
            numero_recu="REC_TEST_5",
            montant=Decimal("500000"),
            date_paiement=date(2025, 3, 10),
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement2, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.tranche_3_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.solde_restant, Decimal("0"))
        self.assertEqual(self.echeancier.statut, "PAYE_COMPLET")

    def test_inscription_plus_annuel(self):
        # Inscription + Annuel (tout payer)
        paiement1 = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_annuel,
            mode_paiement=self.mode_especes,
            numero_recu="REC_TEST_6",
            montant=Decimal("1530000"),  # 30k + (500k * 3)
            date_paiement=date(2024, 9, 30),
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement1, self.echeancier)
        self._refresh()
        # Dans ce cas, toutes les tranches doivent être soldées
        self.assertEqual(self.echeancier.frais_inscription_paye, Decimal("30000"))
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_2_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_3_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.solde_restant, Decimal("0"))
        self.assertEqual(self.echeancier.statut, "PAYE_COMPLET")

    def test_paiement_annuel_partiel_est_affecte_sequentiellement(self):
        paiement = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_annuel,
            mode_paiement=self.mode_especes,
            numero_recu="REC_SEQ_ANNUEL",
            montant=Decimal("730000"),
            date_paiement=date(2024, 9, 30),
            statut="VALIDE",
        )

        _allocate_combined_payment(paiement, self.echeancier)
        self._refresh()

        self.assertEqual(self.echeancier.frais_inscription_paye, Decimal("30000"))
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_2_payee, Decimal("200000"))
        self.assertEqual(self.echeancier.tranche_3_payee, Decimal("0"))

    def test_excedent_inscription_cascade_jusqua_la_derniere_tranche(self):
        type_inscription = TypePaiement.objects.create(nom="Frais d'inscription")
        paiement = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=type_inscription,
            mode_paiement=self.mode_especes,
            numero_recu="REC_CASCADE",
            montant=Decimal("1200000"),
            date_paiement=date(2024, 9, 30),
            statut="VALIDE",
        )

        _allocate_combined_payment(paiement, self.echeancier)
        self._refresh()

        self.assertEqual(self.echeancier.frais_inscription_paye, Decimal("30000"))
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_2_payee, Decimal("500000"))
        self.assertEqual(self.echeancier.tranche_3_payee, Decimal("170000"))
        breakdown = _get_payment_allocation_breakdown(paiement)
        self.assertEqual(breakdown['inscription'], Decimal("30000"))
        self.assertEqual(breakdown['tranche_1'], Decimal("500000"))
        self.assertEqual(breakdown['tranche_2'], Decimal("500000"))
        self.assertEqual(breakdown['tranche_3'], Decimal("170000"))

    def test_reinscription_utilise_son_tarif_et_reverse_sur_tranche_1(self):
        GrilleTarifaire.objects.create(
            ecole=self.ecole,
            niveau=self.classe.niveau,
            annee_scolaire=self.classe.annee_scolaire,
            frais_inscription=Decimal("30000"),
            frais_reinscription=Decimal("20000"),
            tranche_1=Decimal("500000"),
            tranche_2=Decimal("500000"),
            tranche_3=Decimal("500000"),
        )
        type_reinscription = TypePaiement.objects.create(nom="Frais de Ré-inscription")
        paiement = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=type_reinscription,
            mode_paiement=self.mode_especes,
            numero_recu="REC_REINSC",
            montant=Decimal("120000"),
            date_paiement=date(2024, 9, 30),
            statut="VALIDE",
        )

        _allocate_combined_payment(paiement, self.echeancier)
        self._refresh()

        self.assertEqual(self.echeancier.frais_inscription_du, Decimal("20000"))
        self.assertEqual(self.echeancier.frais_inscription_paye, Decimal("20000"))
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("100000"))
        breakdown = _get_payment_allocation_breakdown(paiement)
        self.assertEqual(breakdown['label_inscription'], "Réinscription")
        self.assertEqual(breakdown['inscription'], Decimal("20000"))
        self.assertEqual(breakdown['tranche_1'], Decimal("100000"))

    @patch('paiements.views.timezone.localdate', return_value=date(2025, 1, 10))
    def test_pas_retard_le_jour_echeance_si_partiel(self, _mock_localdate):
        """Un paiement partiel le jour exact de l'échéance ne doit pas être considéré en retard (strict >)."""
        # Payer l'inscription intégralement à sa date d'échéance
        paiement_insc = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_t1,  # utilisera 30k pour l'inscription
            mode_paiement=self.mode_especes,
            numero_recu="REC_EDGE_1",
            montant=Decimal("30000"),
            date_paiement=self.echeancier.date_echeance_inscription,  # 2024-09-30
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement_insc, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.frais_inscription_paye, Decimal("30000"))

        # Paiement partiel sur T1 exactement le jour d'échéance de T1
        type_t1 = TypePaiement.objects.create(nom="Scolarité - 1ère tranche")
        paiement_t1_partiel = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=type_t1,
            mode_paiement=self.mode_especes,
            numero_recu="REC_EDGE_2",
            montant=Decimal("200000"),
            date_paiement=self.echeancier.date_echeance_tranche_1,  # 2025-01-10
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement_t1_partiel, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("200000"))
        # Le jour J n'est pas > échéance, donc pas de retard
        self.assertEqual(self.echeancier.statut, "PAYE_PARTIEL")

    def test_retard_lendemain_echeance_si_partiel(self):
        """Un paiement partiel le lendemain de l'échéance avec solde restant doit être EN_RETARD."""
        # Payer l'inscription pour éviter un retard dû à l'inscription
        paiement_insc = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_t1,
            mode_paiement=self.mode_especes,
            numero_recu="REC_EDGE_3",
            montant=Decimal("30000"),
            date_paiement=self.echeancier.date_echeance_inscription,
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement_insc, self.echeancier)
        self._refresh()

        # Paiement partiel sur T1 le lendemain de l'échéance
        type_t1 = TypePaiement.objects.create(nom="Scolarité - 1ère tranche")
        paiement_t1_partiel = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=type_t1,
            mode_paiement=self.mode_especes,
            numero_recu="REC_EDGE_4",
            montant=Decimal("200000"),
            date_paiement=date(2025, 1, 11),  # lendemain de 2025-01-10
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement_t1_partiel, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal("200000"))
        self.assertEqual(self.echeancier.statut, "EN_RETARD")

    def test_annuel_tardif_partiel_est_en_retard(self):
        """Paiement combiné 'Inscription + Annuel' tardif mais insuffisant => EN_RETARD si une tranche reste due après son échéance."""
        paiement_annuel_partiel = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_annuel,
            mode_paiement=self.mode_especes,
            numero_recu="REC_EDGE_5",
            montant=Decimal("1030000"),  # 30k + 1,000,000 (insuffisant pour 1.5M tranches)
            date_paiement=date(2025, 3, 6),  # après échéance T2 (2025-03-05)
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement_annuel_partiel, self.echeancier)
        self._refresh()
        self.assertGreater(self.echeancier.solde_restant, 0)
        self.assertEqual(self.echeancier.statut, "EN_RETARD")

    def test_paiement_complet_meme_tard_est_complet(self):
        """Même si le paiement est effectué après des échéances, si tout est soldé, le statut doit être PAYE_COMPLET."""
        paiement_total_tard = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_insc_annuel,
            mode_paiement=self.mode_especes,
            numero_recu="REC_EDGE_6",
            montant=Decimal("1530000"),  # total complet
            date_paiement=date(2025, 4, 10),  # après toutes les échéances
            statut="VALIDE",
        )
        _allocate_combined_payment(paiement_total_tard, self.echeancier)
        self._refresh()
        self.assertEqual(self.echeancier.solde_restant, Decimal("0"))
        self.assertEqual(self.echeancier.statut, "PAYE_COMPLET")
