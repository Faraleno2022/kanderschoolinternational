from datetime import date
from decimal import Decimal

from django.test import TestCase

from eleves.models import Classe, Ecole, Eleve, GrilleTarifaire
from paiements.models import (
    EcheancierPaiement, ModePaiement, Paiement, PaiementRemise,
    RemiseReduction, TypePaiement,
)
from paiements.views import _allocate_combined_payment


class TransfertClasseFinancesTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École origine', adresse='Conakry',
            telephone='+224620000001', directeur='Direction',
        )
        self.autre_ecole = Ecole.objects.create(
            nom='École accueil', adresse='Conakry',
            telephone='+224620000002', directeur='Direction',
        )
        self.ancienne_classe = self._classe(
            self.ecole, '7e A', 'COLLEGE_7', '2025-2026',
        )
        self.nouvelle_classe = self._classe(
            self.ecole, '8e A', 'COLLEGE_8', '2025-2026',
        )
        self.classe_annee_suivante = self._classe(
            self.ecole, '8e A 2026', 'COLLEGE_8', '2026-2027',
        )
        self.classe_autre_ecole = self._classe(
            self.autre_ecole, '8e B', 'COLLEGE_8', '2025-2026',
        )
        self._grille(self.ecole, 'COLLEGE_7', '2025-2026', 100000, 75000, 500000, 500000, 400000)
        self._grille(self.ecole, 'COLLEGE_8', '2025-2026', 200000, 150000, 600000, 600000, 400000)
        self._grille(self.ecole, 'COLLEGE_8', '2026-2027', 250000, 175000, 625000, 625000, 425000)
        self._grille(self.autre_ecole, 'COLLEGE_8', '2025-2026', 300000, 200000, 700000, 600000, 400000)

        self.eleve = Eleve.objects.create(
            matricule='TR-900', prenom='Aminata', nom='Diallo', sexe='F',
            classe=self.ancienne_classe, date_inscription=date(2025, 9, 1),
        )
        self.type_paiement = TypePaiement.objects.create(nom='Scolarité annuelle')
        self.mode_paiement = ModePaiement.objects.create(nom='Espèces transfert')
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve,
            annee_scolaire='2025-2026',
            ecole_reference=self.ecole,
            classe_reference=self.ancienne_classe,
            frais_inscription_du=Decimal('100000'),
            tranche_1_due=Decimal('500000'),
            tranche_2_due=Decimal('500000'),
            tranche_3_due=Decimal('400000'),
            date_echeance_inscription=date(2025, 9, 30),
            date_echeance_tranche_1=date(2026, 1, 15),
            date_echeance_tranche_2=date(2026, 3, 15),
            date_echeance_tranche_3=date(2026, 5, 15),
        )

    def _classe(self, ecole, nom, niveau, annee):
        return Classe.objects.create(
            ecole=ecole, nom=nom, niveau=niveau,
            annee_scolaire=annee, capacite_max=40,
        )

    def _grille(self, ecole, niveau, annee, inscription, reinscription, t1, t2, t3):
        return GrilleTarifaire.objects.create(
            ecole=ecole, niveau=niveau, annee_scolaire=annee,
            frais_inscription=Decimal(inscription),
            frais_reinscription=Decimal(reinscription),
            tranche_1=Decimal(t1), tranche_2=Decimal(t2), tranche_3=Decimal(t3),
        )

    def _paiement(self, montant='600000'):
        paiement = Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_paiement,
            mode_paiement=self.mode_paiement,
            numero_recu='', montant=Decimal(montant),
            date_paiement=date(2025, 10, 1), statut='VALIDE',
        )
        _allocate_combined_payment(paiement, self.echeancier)
        return paiement

    def test_meme_annee_recalcule_et_reaffecte_les_600000(self):
        paiement = self._paiement()

        self.eleve.classe = self.nouvelle_classe
        self.eleve.save()
        self.echeancier.refresh_from_db()
        paiement.refresh_from_db()

        self.assertEqual(self.echeancier.total_du, Decimal('1800000'))
        self.assertEqual(self.echeancier.total_paye, Decimal('600000'))
        self.assertEqual(self.echeancier.solde_restant, Decimal('1200000'))
        self.assertEqual(self.echeancier.classe_reference, self.nouvelle_classe)
        self.assertEqual(paiement.classe_encaissement, self.ancienne_classe)
        self.assertEqual(paiement.annee_scolaire, '2025-2026')

    def test_nouvelle_annee_conserve_ancien_echeancier_et_cree_le_nouveau(self):
        self._paiement()

        self.eleve.classe = self.classe_annee_suivante
        self.eleve.save()

        ancien = EcheancierPaiement.objects.get(
            eleve=self.eleve, annee_scolaire='2025-2026', ecole_reference=self.ecole,
        )
        nouveau = EcheancierPaiement.objects.get(
            eleve=self.eleve, annee_scolaire='2026-2027', ecole_reference=self.ecole,
        )
        self.assertEqual(ancien.total_paye, Decimal('600000'))
        self.assertEqual(nouveau.nature_frais, EcheancierPaiement.NATURE_REINSCRIPTION)
        self.assertEqual(nouveau.total_du, Decimal('1850000'))
        self.assertEqual(nouveau.total_paye, Decimal('0'))
        self.assertEqual(self.eleve.echeancier, nouveau)

    def test_autre_ecole_isole_paiements_et_echeanciers(self):
        paiement = self._paiement()

        self.eleve.classe = self.classe_autre_ecole
        self.eleve.save()
        paiement.refresh_from_db()

        ancien = EcheancierPaiement.objects.get(
            eleve=self.eleve, ecole_reference=self.ecole, annee_scolaire='2025-2026',
        )
        accueil = EcheancierPaiement.objects.get(
            eleve=self.eleve, ecole_reference=self.autre_ecole, annee_scolaire='2025-2026',
        )
        self.assertEqual(ancien.total_paye, Decimal('600000'))
        self.assertEqual(accueil.total_du, Decimal('2000000'))
        self.assertEqual(accueil.total_paye, Decimal('0'))
        self.assertEqual(paiement.ecole_encaissement, self.ecole)
        self.assertEqual(paiement.classe_encaissement, self.ancienne_classe)
        self.assertFalse(
            Paiement.objects.filter(pk=paiement.pk, ecole_encaissement=self.autre_ecole).exists()
        )

    def test_tarif_inferieur_signale_un_credit_sans_supprimer_le_paiement(self):
        GrilleTarifaire.objects.filter(
            ecole=self.ecole, niveau='COLLEGE_8', annee_scolaire='2025-2026',
        ).update(
            frais_inscription=Decimal('100000'), tranche_1=Decimal('200000'),
            tranche_2=Decimal('100000'), tranche_3=Decimal('100000'),
        )
        paiement = self._paiement()

        self.eleve.classe = self.nouvelle_classe
        self.eleve.save()
        self.echeancier.refresh_from_db()

        self.assertEqual(self.echeancier.total_du, Decimal('500000'))
        self.assertEqual(self.echeancier.total_paye, Decimal('500000'))
        self.assertEqual(
            self.eleve._financial_transfer_info['credit_non_affecte'],
            Decimal('100000'),
        )
        self.assertTrue(Paiement.objects.filter(pk=paiement.pk).exists())

    def test_remise_est_conservee_et_reaffectee_dans_la_meme_ecole(self):
        paiement = self._paiement()
        remise = RemiseReduction.objects.create(
            nom='Remise transfert', type_remise='MONTANT_FIXE',
            valeur=Decimal('100000'), motif='AUTRE',
            date_debut=date(2025, 9, 1), date_fin=date(2026, 7, 31),
        )
        PaiementRemise.objects.create(
            paiement=paiement, remise=remise,
            montant_remise=Decimal('100000'), portee_tranches='2',
        )

        self.eleve.classe = self.nouvelle_classe
        self.eleve.save()
        self.echeancier.refresh_from_db()

        # Le cumul de couverture comprend le versement et la remise ;
        # l'encaissement conservé reste uniquement l'argent reçu.
        self.assertEqual(self.echeancier.total_paye, Decimal('700000'))
        self.assertEqual(self.eleve._financial_transfer_info['encaissements_conserves'], 600000)
        self.assertEqual(self.echeancier.total_remises_valides, Decimal('100000'))
        self.assertEqual(self.echeancier.solde_restant, Decimal('1100000'))
        self.assertEqual(
            self.eleve._financial_transfer_info['remises_conservees'],
            Decimal('100000'),
        )

    def test_grille_cible_absente_ne_detruit_pas_ancien_echeancier(self):
        self._paiement()
        GrilleTarifaire.objects.filter(
            ecole=self.ecole, niveau='COLLEGE_8', annee_scolaire='2025-2026',
        ).delete()

        self.eleve.classe = self.nouvelle_classe
        self.eleve.save()
        self.echeancier.refresh_from_db()

        self.assertTrue(self.eleve._financial_transfer_info['grille_manquante'])
        self.assertEqual(self.echeancier.total_du, Decimal('1500000'))
        self.assertEqual(self.echeancier.total_paye, Decimal('600000'))
        self.assertEqual(self.echeancier.classe_reference, self.ancienne_classe)

    def _classe_b(self):
        return self._classe(self.ecole, '7e B', 'COLLEGE_7', '2025-2026')

    def _remise(self, paiement, montant=100000, portee='1', deduite=False):
        remise = RemiseReduction.objects.create(
            nom='Remise sections A/B', type_remise='MONTANT_FIXE',
            valeur=montant, motif='AUTRE',
            date_debut=date(2025, 9, 1), date_fin=date(2026, 7, 31),
        )
        return PaiementRemise.objects.create(
            paiement=paiement, remise=remise, montant_remise=montant,
            portee_tranches=portee, deduite_du_paiement=deduite,
        )

    def test_sections_a_b_a_conservent_cumuls_remise_et_recu(self):
        from paiements.soldes import recalculer_echeancier
        paiement = self._paiement()
        remise = self._remise(paiement)
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 700000)
        numero_recu = paiement.numero_recu
        for cible in (self._classe_b(), self.ancienne_classe):
            with self.subTest(classe=cible.nom):
                self.eleve.classe = cible
                self.eleve.save()
                self.echeancier.refresh_from_db()
                paiement.refresh_from_db()
                remise.refresh_from_db()
                self.assertEqual(self.echeancier.total_du, 1500000)
                self.assertEqual(self.echeancier.total_paye, 700000)
                self.assertEqual(self.echeancier.solde_restant, 800000)
                self.assertEqual(self.eleve._financial_transfer_info['solde_restant'], 800000)
                self.assertEqual(self.echeancier.classe_reference, cible)
                self.assertEqual(paiement.montant, 600000)
                self.assertEqual(paiement.numero_recu, numero_recu)
                self.assertEqual(paiement.classe_encaissement, self.ancienne_classe)
                self.assertEqual(remise.montant_remise, 100000)
                self.assertEqual(recalculer_echeancier(self.echeancier, enregistrer=False), {})
        self.assertEqual(self.eleve.echeanciers.count(), 1)

    def test_section_b_dossier_solde_avec_remise_reste_solde(self):
        paiement = self._paiement('1400000')
        self._remise(paiement, deduite=True)
        self.eleve.classe = self._classe_b()
        self.eleve.save()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.solde_restant, 0)
        self.assertEqual(self.echeancier.statut, 'PAYE_COMPLET')
        self.assertEqual(self.echeancier.total_paye, 1500000)
        self.assertEqual(self.eleve._financial_transfer_info['solde_restant'], 0)

    def test_modification_suppression_apres_transfert_section_b(self):
        paiement = self._paiement()
        self._remise(paiement)
        self.eleve.classe = self._classe_b()
        self.eleve.save()
        paiement.montant = 400000
        paiement.save()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 500000)
        self.assertEqual(self.echeancier.solde_restant, 1000000)
        paiement.delete()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 0)
        self.assertEqual(self.echeancier.solde_restant, 1500000)
        self.eleve.classe = self.ancienne_classe
        self.eleve.save()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 0)

    def test_section_b_conserve_tarif_reinscription(self):
        self.echeancier.nature_frais = 'REINSCRIPTION'
        self.echeancier.frais_inscription_du = 75000
        self.echeancier.save()
        self.type_paiement = TypePaiement.objects.create(nom='Réinscription + Annuel')
        self._paiement()
        self.eleve.classe = self._classe_b()
        self.eleve.save()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.nature_frais, 'REINSCRIPTION')
        self.assertEqual(self.echeancier.frais_inscription_du, 75000)
        self.assertEqual(self.echeancier.total_du, 1475000)
        self.assertEqual(self.echeancier.solde_restant, 875000)

    def test_tarif_inferieur_credit_tient_compte_remise_sans_changer_recu(self):
        GrilleTarifaire.objects.filter(
            ecole=self.ecole, niveau='COLLEGE_8', annee_scolaire='2025-2026',
        ).update(frais_inscription=100000, tranche_1=200000, tranche_2=200000, tranche_3=150000)
        paiement = self._paiement()
        self._remise(paiement)
        self.eleve.classe = self.nouvelle_classe
        self.eleve.save()
        self.echeancier.refresh_from_db()
        paiement.refresh_from_db()
        self.assertEqual(self.echeancier.total_du, 650000)
        self.assertEqual(self.echeancier.total_paye, 650000)
        self.assertEqual(self.echeancier.statut, 'PAYE_COMPLET')
        self.assertEqual(self.echeancier.solde_restant, 0)
        self.assertEqual(self.eleve._financial_transfer_info['credit_non_affecte'], 50000)
        self.assertEqual(paiement.montant, 600000)

    def test_section_b_ne_reprend_pas_cumul_perime_paiement_annule(self):
        paiement = self._paiement()
        paiement.statut = 'ANNULE'
        paiement.save()
        # Simuler un cumul hérité erroné : le reçu annulé fait foi.
        EcheancierPaiement.objects.filter(pk=self.echeancier.pk).update(
            frais_inscription_paye=100000, tranche_1_payee=500000,
        )
        self.eleve.classe = self._classe_b()
        self.eleve.save()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 0)
        self.assertEqual(self.echeancier.solde_restant, 1500000)
        self.assertEqual(self.eleve._financial_transfer_info['encaissements_conserves'], 0)
