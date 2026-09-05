from datetime import date
from decimal import Decimal

from django.urls import reverse
from eleves.models import GrilleTarifaire
from paiements.models import Paiement, PaiementRemise, RemiseReduction, TypePaiement
from paiements.soldes import recalculer_echeancier
from . import test_modification_montant as support


class CorrectionAdmissionTests(support.ModificationMontantTest):
    def setUp(self):
        super().setUp()
        self.ech = self.eleve.echeanciers.get()
        self.grille = GrilleTarifaire.objects.create(
            ecole=self.ecole, niveau=self.classe.niveau, annee_scolaire='2025-2026',
            frais_inscription=50000, frais_reinscription=30000,
            tranche_1=500000, tranche_2=400000, tranche_3=300000,
        )
        self.inscription = TypePaiement.objects.create(nom='Inscription + Annuel')
        self.reinscription = TypePaiement.objects.create(nom='Réinscription + Annuel')

    def preparer(self, montant=1130000, remise=True):
        self.paiement.type_paiement = self.inscription
        self.paiement.montant = Decimal(montant)
        self.paiement.statut = 'VALIDE'
        self.paiement.save()
        if remise:
            reduction = RemiseReduction.objects.create(
                nom='Remise scolarité 10%', type_remise='POURCENTAGE', valeur=10,
                motif='AUTRE', date_debut=date(2025, 1, 1), date_fin=date(2027, 1, 1),
            )
            self.remise = PaiementRemise.objects.create(
                paiement=self.paiement, remise=reduction, montant_remise=120000,
                portee_tranches='1,2,3', deduite_du_paiement=True,
            )
        recalculer_echeancier(self.ech)

    def corriger(self, type_paiement=None, montant=None):
        self.paiement.refresh_from_db()
        return self.client.post(self.url, {
            'type_paiement': (type_paiement or self.reinscription).pk,
            'mode_paiement': self.mode.pk,
            'montant': self.paiement.montant if montant is None else montant,
            'date_paiement': '2026-08-04', 'reference_externe': '', 'observations': '',
            'motif_modification': 'Correction du type admission',
        })

    def test_reinscription_avec_remise_et_retour_inscription(self):
        self.preparer()
        self.assertEqual(self.corriger().status_code, 302)
        self.paiement.refresh_from_db(); self.ech.refresh_from_db(); self.remise.refresh_from_db()
        self.assertEqual(self.paiement.montant, 1110000)
        self.assertEqual(self.remise.montant_remise, 120000)
        self.assertEqual(self.ech.nature_frais, 'REINSCRIPTION')
        self.assertEqual(self.ech.total_du, 1230000)
        self.assertEqual(self.ech.solde_restant, 0)
        self.assertEqual(self.ech.statut, 'PAYE_COMPLET')
        historique = self.paiement.historique_modifications.first()
        self.assertIn('montant', historique.champs_modifies)
        self.assertIn('type_paiement_id', historique.champs_modifies)
        self.assertEqual(self.corriger(self.inscription).status_code, 302)
        self.paiement.refresh_from_db(); self.ech.refresh_from_db()
        self.assertEqual(self.paiement.montant, 1130000)
        self.assertEqual(self.ech.frais_inscription_du, 50000)

    def test_reedition_ne_deduit_pas_deux_fois(self):
        self.preparer()
        self.corriger(); self.corriger()
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, 1110000)

    def test_montant_explicitement_corrige(self):
        self.preparer()
        self.assertEqual(self.corriger(montant=1000000).status_code, 302)
        self.paiement.refresh_from_db(); self.ech.refresh_from_db()
        self.assertEqual(self.paiement.montant, 1000000)
        self.assertEqual(self.ech.solde_restant, 110000)
        self.assertEqual(self.ech.total_paye, 1120000)

    def test_versement_partiel_conserve(self):
        self.preparer(montant=200000, remise=False)
        self.assertEqual(self.corriger().status_code, 302)
        self.paiement.refresh_from_db(); self.ech.refresh_from_db()
        self.assertEqual(self.paiement.montant, 200000)
        self.assertEqual(self.ech.solde_restant, 1030000)

    def test_grille_absente_aucune_ecriture(self):
        self.preparer()
        self.grille.delete()
        self.assertEqual(self.corriger().status_code, 200)
        self.paiement.refresh_from_db(); self.ech.refresh_from_db()
        self.assertEqual(self.paiement.type_paiement, self.inscription)
        self.assertEqual(self.ech.frais_inscription_du, 50000)

    def test_suppression_en_lot_retire_paiement_et_remise(self):
        self.preparer(); self.corriger()
        Paiement.objects.filter(pk=self.paiement.pk).delete()
        self.ech.refresh_from_db()
        self.assertEqual(self.ech.total_paye, 0)
        self.assertEqual(self.ech.solde_restant, 1230000)
        self.assertFalse(PaiementRemise.objects.filter(pk=self.remise.pk).exists())

    def test_modification_et_suppression_remise_recalculent(self):
        self.preparer(montant=500000)
        self.remise.montant_remise = 100000
        self.remise.save()
        self.ech.refresh_from_db()
        self.assertEqual(self.ech.total_paye, 600000)
        self.assertEqual(self.ech.solde_restant, 650000)
        self.remise.delete()
        self.ech.refresh_from_db()
        self.assertEqual(self.ech.total_paye, 500000)
        self.assertEqual(self.ech.solde_restant, 750000)

    def test_cartes_apres_correction_puis_suppression(self):
        from paiements.views import _compute_stats
        self.preparer(); self.corriger()
        stats = _compute_stats(self.user)['categories']
        self.assertEqual(stats['inscription']['year'], 0)
        self.assertEqual(stats['reinscription']['year'], 30000)
        self.assertEqual(stats['scolarite']['year'], 1080000)
        Paiement.objects.filter(pk=self.paiement.pk).delete()
        stats = _compute_stats(self.user)['categories']
        self.assertEqual(stats['reinscription']['year'], 0)
        self.assertEqual(stats['scolarite']['year'], 0)

    def test_inscription_seule_sans_remise(self):
        self.preparer(montant=50000, remise=False)
        self.paiement.type_paiement = TypePaiement.objects.create(nom='Inscription')
        self.paiement.save()
        type_retour = TypePaiement.objects.create(nom='Réinscription')
        self.assertEqual(self.corriger(type_retour).status_code, 302)
        self.paiement.refresh_from_db(); self.ech.refresh_from_db()
        self.assertEqual(self.paiement.montant, 30000)
        self.assertEqual(self.ech.frais_inscription_paye, 30000)
        self.assertEqual(self.ech.solde_restant, 1200000)

    def test_detail_recu_apres_correction(self):
        self.preparer(); self.corriger()
        response = self.client.get(reverse(
            'paiements:detail_paiement', kwargs={'paiement_id': self.paiement.pk},
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['paiement'].montant, 1110000)
        self.assertEqual(response.context['remises_total'], 120000)

    def test_correction_historique_apres_changement_annee(self):
        from eleves.models import Classe
        self.preparer()
        nouvelle_classe = Classe.objects.create(
            ecole=self.ecole, niveau=self.classe.niveau, nom='Nouvelle année',
            annee_scolaire='2026-2027',
        )
        GrilleTarifaire.objects.create(
            ecole=self.ecole, niveau=self.classe.niveau, annee_scolaire='2026-2027',
            frais_inscription=200000, frais_reinscription=100000,
            tranche_1=600000, tranche_2=500000, tranche_3=400000,
        )
        self.eleve.classe = nouvelle_classe
        self.eleve.save()
        nouveau = self.eleve.echeanciers.get(annee_scolaire='2026-2027')
        total_avant = nouveau.total_du
        self.assertEqual(self.corriger().status_code, 302)
        self.paiement.refresh_from_db(); self.ech.refresh_from_db(); nouveau.refresh_from_db()
        self.assertEqual(self.paiement.montant, 1110000)
        self.assertEqual(self.ech.frais_inscription_du, 30000)
        self.assertEqual(nouveau.total_du, total_avant)
        self.assertEqual(nouveau.total_paye, 0)
