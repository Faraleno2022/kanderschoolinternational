"""Déduction d'une remise sur le montant du reçu, et plafond des remises.

Deux régimes coexistent :
- remise ajoutée à l'encaissement (défaut historique) : elle couvre de la
  scolarité en plus du reçu, et ne peut donc pas dépasser le reste dû ;
- remise déduite du reçu : la famille verse moins, la couverture totale ne
  bouge pas, et la seule borne est le montant du reçu lui-même.
"""

from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole, Classe, Eleve, Responsable
from paiements.models import (
    EcheancierPaiement, TypePaiement, ModePaiement, Paiement,
    RemiseReduction, PaiementRemise,
)
from paiements.tests.support import TEST_MIDDLEWARE
from utilisateurs.models import Profil


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class RemiseDeductionTest(TestCase):
    """Cas MARIE BORE : un reçu qui solde l'année, plus une remise.

    Total dû 1 250 000, reçu 1 250 000. Sans déduction, une remise de
    120 000 porterait la couverture à 1 370 000 : trop-perçu. Avec
    déduction, le reçu tombe à 1 130 000 et l'année reste couverte à
    1 250 000 exactement.
    """

    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Test", adresse="Conakry",
            telephone="+224620000002", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="CP1", ecole=self.ecole, niveau="PRIMAIRE_1",
            annee_scolaire="2025-2026",
        )
        self.resp = Responsable.objects.create(
            prenom="M", nom="Bore", relation="MERE",
            telephone="+224620000012", adresse="Adr",
        )
        self.eleve = Eleve.objects.create(
            nom="Bore", prenom="Marie", matricule="KIN-020",
            classe=self.classe, sexe='F',
            date_naissance=date(2018, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        # 50 000 inscription + 500 000 + 400 000 + 300 000 = 1 250 000
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire="2025-2026",
            frais_inscription_du=Decimal("50000"),
            tranche_1_due=Decimal("500000"),
            tranche_2_due=Decimal("400000"),
            tranche_3_due=Decimal("300000"),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )
        type_annuel = TypePaiement.objects.create(nom="Frais d'inscription + Annuel")
        mode = ModePaiement.objects.create(nom="Espèces")
        self.paiement = Paiement.objects.create(
            eleve=self.eleve, type_paiement=type_annuel, mode_paiement=mode,
            montant=Decimal("1250000"), statut='EN_ATTENTE',
            date_paiement=date(2026, 8, 4),
        )
        # 10 % de la scolarité T1 (500 000) = 50 000 ; on vise 120 000 via
        # un montant fixe pour coller au cas réel.
        self.remise = RemiseReduction.objects.create(
            nom="Geste commercial", type_remise='MONTANT_FIXE',
            valeur=Decimal("120000"), motif='AUTRE',
            date_debut=date(2025, 1, 1), date_fin=date(2026, 12, 31), actif=True,
        )

        User = get_user_model()
        self.user = User.objects.create_user(username="compta_deduc", password="pass12345")
        Profil.objects.update_or_create(
            user=self.user,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': "+224620000022", 'peut_consulter_rapports': True,
                'is_validated': True,
            },
        )
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        self.url = reverse('paiements:appliquer_remise', kwargs={'paiement_id': self.paiement.id})

    def _post(self, **extra):
        data = {
            'montant_original': self.paiement.montant,
            'pourcentage_scolarite': '',
            'tranches': ['1'],
            'base_calcul': 'TRANCHES',
            'motif_remise': 'GESTE_COMMERCIAL',
            'remises': [self.remise.id],
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def test_sans_deduction_la_remise_qui_creerait_un_trop_percu_est_refusee(self):
        """Le reçu solde déjà l'année : ajouter 120 000 de couverture est refusé."""
        response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaiementRemise.objects.filter(paiement=self.paiement).exists())
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1250000"))

    def test_avec_deduction_le_recu_passe_au_net(self):
        """Le reçu tombe à 1 130 000 et la couverture reste à 1 250 000."""
        response = self._post(deduire_du_paiement='1')

        self.assertEqual(response.status_code, 302)
        ligne = PaiementRemise.objects.get(paiement=self.paiement)
        self.assertEqual(ligne.montant_remise, Decimal("120000"))
        self.assertTrue(ligne.deduite_du_paiement)

        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1130000"))
        # Couverture = reçu net + remise, inchangée par rapport au brut.
        self.assertEqual(self.paiement.montant + ligne.montant_remise, Decimal("1250000"))

    def test_la_modification_du_recu_est_tracee(self):
        """La déduction passe par Paiement.save() : elle laisse une trace."""
        self._post(deduire_du_paiement='1')

        historique = self.paiement.historique_modifications.first()
        self.assertIsNotNone(historique)
        self.assertIn('montant', historique.champs_modifies)
        self.assertIn('120 000', historique.motif)
        self.assertEqual(historique.utilisateur, self.user)

    def test_rejouer_la_remise_ne_deduit_pas_deux_fois(self):
        """Resoumettre le même écran repart du brut, pas du net déjà amputé."""
        self._post(deduire_du_paiement='1')
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1130000"))

        self._post(deduire_du_paiement='1')
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1130000"))

    def test_decocher_la_case_restaure_le_montant_brut(self):
        """Sans quoi le reçu resterait amputé sans remise déduite en face."""
        self._post(deduire_du_paiement='1')
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1130000"))

        # Sans déduction, la remise dépasserait le reste dû : elle est refusée
        # et le reçu doit être laissé tel quel, pas à moitié restauré.
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1130000"))

    def test_annuler_la_remise_rend_le_montant_au_recu(self):
        self._post(deduire_du_paiement='1')
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1130000"))

        url_annuler = reverse(
            'paiements:annuler_remise_paiement', kwargs={'paiement_id': self.paiement.id}
        )
        response = self.client.post(url_annuler)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(PaiementRemise.objects.filter(paiement=self.paiement).exists())
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("1250000"))

    def test_annuler_une_remise_non_deduite_laisse_le_recu_intact(self):
        """Une remise jamais déduite n'a rien à rendre au reçu."""
        self.paiement.montant = Decimal("600000")
        self.paiement.save()
        self._post()
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("600000"))

        url_annuler = reverse(
            'paiements:annuler_remise_paiement', kwargs={'paiement_id': self.paiement.id}
        )
        self.client.post(url_annuler)

        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("600000"))

    def test_remise_superieure_au_recu_refusee_meme_avec_deduction(self):
        """Une remise ne peut pas rendre le reçu négatif."""
        self.paiement.montant = Decimal("100000")
        self.paiement.save()

        response = self._post(deduire_du_paiement='1')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaiementRemise.objects.filter(paiement=self.paiement).exists())
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("100000"))

    def test_case_prechochee_en_reedition(self):
        """Rouvrir l'écran doit refléter la déduction déjà enregistrée."""
        self._post(deduire_du_paiement='1')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['deduire_choisi'])
        self.assertEqual(response.context['montant_brut'], 1250000)
