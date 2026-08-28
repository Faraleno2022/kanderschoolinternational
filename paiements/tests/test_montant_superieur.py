"""Confirmation d'un montant supérieur au type de paiement sélectionné.

Le montant inférieur au type demandait déjà confirmation ; le montant
supérieur passait sans un mot, l'excédent glissant en silence sur les
tranches suivantes. Les deux sens sont désormais symétriques.
"""

from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole, Classe, Eleve, Responsable, GrilleTarifaire
from paiements.models import (
    EcheancierPaiement, TypePaiement, ModePaiement, Paiement,
)
from paiements.tests.support import TEST_MIDDLEWARE
from utilisateurs.models import Profil


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class MontantSuperieurConfirmationTest(TestCase):

    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Test", adresse="Conakry",
            telephone="+224620000003", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="CP2", ecole=self.ecole, niveau="PRIMAIRE_2",
            annee_scolaire="2025-2026",
        )
        self.resp = Responsable.objects.create(
            prenom="A", nom="Diallo", relation="PERE",
            telephone="+224620000013", adresse="Adr",
        )
        self.eleve = Eleve.objects.create(
            nom="Diallo", prenom="Fatou", matricule="KIN-030",
            classe=self.classe, sexe='F',
            date_naissance=date(2017, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        # Un type « Réinscription » fait recharger la grille tarifaire par la
        # vue : sans grille, l'échéancier serait remis à zéro et les contrôles
        # de montant n'auraient plus rien à comparer.
        GrilleTarifaire.objects.create(
            ecole=self.ecole, niveau="PRIMAIRE_2", annee_scolaire="2025-2026",
            frais_inscription=Decimal("50000"),
            frais_reinscription=Decimal("30000"),
            tranche_1=Decimal("700000"),
            tranche_2=Decimal("500000"),
            tranche_3=Decimal("20000"),
        )
        # 30 000 réinscription + 700 000 + 500 000 + 20 000 = 1 250 000
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire="2025-2026",
            frais_inscription_du=Decimal("30000"),
            tranche_1_due=Decimal("700000"),
            tranche_2_due=Decimal("500000"),
            tranche_3_due=Decimal("20000"),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )
        self.type_reinsc_t1 = TypePaiement.objects.create(nom="Réinscription + Tranche 1")
        self.mode = ModePaiement.objects.create(nom="Espèces")

        User = get_user_model()
        self.user = User.objects.create_user(username="compta_sup", password="pass12345")
        Profil.objects.update_or_create(
            user=self.user,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': "+224620000023", 'peut_consulter_rapports': True,
                'is_validated': True,
            },
        )
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        self.url = reverse('paiements:ajouter_paiement')

    def _post(self, montant, **extra):
        data = {
            'eleve': self.eleve.id,
            'type_paiement': self.type_reinsc_t1.id,
            'mode_paiement': self.mode.id,
            'montant': montant,
            'date_paiement': '2026-08-04',
            'observations': '',
            'reference_externe': '',
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def test_montant_superieur_demande_confirmation(self):
        """1 230 000 pour un type à 730 000 : plus de passage silencieux."""
        response = self._post(1230000)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['show_overflow_confirmation'])
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_la_repartition_reelle_est_affichee(self):
        """L'agent voit où part l'excédent avant d'enregistrer."""
        response = self._post(1230000)

        lignes = response.context['repartition_previsionnelle']
        self.assertEqual(
            [(ligne['libelle'], ligne['montant']) for ligne in lignes],
            [
                ('Réinscription', 30000),
                ('1ère tranche', 700000),
                ('2ème tranche', 500000),
            ],
        )
        self.assertEqual(response.context['montant_non_alloue'], 0)

    def test_confirmation_cochee_enregistre_le_paiement(self):
        response = self._post(1230000, confirmation_montant_superieur='1')

        self.assertEqual(response.status_code, 302)
        paiement = Paiement.objects.get(eleve=self.eleve)
        self.assertEqual(paiement.montant, Decimal("1230000"))

    def test_montant_exact_passe_sans_confirmation(self):
        """730 000 correspond au type : rien ne doit gêner la saisie."""
        response = self._post(730000)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_montant_inferieur_est_accepte_du_premier_coup(self):
        """Le contrôle n'est pas symétrique, et c'est voulu.

        Un excédent engage de l'argent sur des postes que l'agent n'a pas
        choisis, d'où la confirmation. Un versement incomplet ne fait que
        moins remplir le poste visé : rien à confirmer.
        """
        response = self._post(400000)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Paiement.objects.get(eleve=self.eleve).montant, Decimal("400000"),
        )

    def test_plafond_annuel_reste_bloquant(self):
        """Confirmer la répartition n'autorise pas à dépasser le total dû."""
        response = self._post(1300000, confirmation_montant_superieur='1')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())
