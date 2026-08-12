"""Moteur de calcul du montant exact attendu pour un type de paiement.

Le libellé d'un type s'écrit de vingt façons et se combine librement
(« Réinscription + Tranche 1 »). Trois décompositions concurrentes
existaient — le JS du formulaire, l'endpoint de suggestion et la validation
de la saisie — et elles ne tombaient pas d'accord : la cascade de `elif`
s'arrêtait au premier poste reconnu, si bien que « Tranche 1 + Tranche 2 »
ne valait que la T1. Ces tests verrouillent l'unique moteur.
"""

from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole, Classe, Eleve, Responsable
from paiements.models import (
    EcheancierPaiement, TypePaiement, ModePaiement,
)
from paiements.tests.support import TEST_MIDDLEWARE
from paiements.views import analyser_type_paiement, montant_exact_pour_type
from utilisateurs.models import Profil


class AnalyseTypePaiementTest(TestCase):
    """La décomposition d'un libellé en postes de l'échéancier."""

    def test_types_combines_cumulent_les_postes(self):
        cas = {
            "Réinscription + Tranche 1": (True, [1]),
            "Frais d'inscription + 1ère tranche": (True, [1]),
            "Frais d'inscription + Tranche 1 + Tranche 2": (True, [1, 2]),
            "Tranche 1 + Tranche 2": (False, [1, 2]),
            "Tranche 2 + Tranche 3": (False, [2, 3]),
            "Tranche 1 + Tranche 2 + Tranche 3": (False, [1, 2, 3]),
        }
        for libelle, (inscription, tranches) in cas.items():
            with self.subTest(libelle=libelle):
                postes = analyser_type_paiement(libelle)
                self.assertEqual(postes['inscription'], inscription)
                self.assertEqual(postes['tranches'], tranches)

    def test_annuel_couvre_les_trois_tranches(self):
        for libelle in ("Frais d'inscription + Annuel", "Réinscription + Annuel"):
            with self.subTest(libelle=libelle):
                postes = analyser_type_paiement(libelle)
                self.assertTrue(postes['inscription'])
                self.assertEqual(postes['tranches'], [1, 2, 3])

    def test_scolarite_seule_vaut_toute_la_scolarite(self):
        self.assertEqual(analyser_type_paiement("Scolarité")['tranches'], [1, 2, 3])

    def test_scolarite_suivie_d_une_tranche_ne_vaut_que_cette_tranche(self):
        """« Scolarité - 2ème tranche » ne doit pas devenir l'année entière."""
        postes = analyser_type_paiement("Scolarité - 2ème tranche")
        self.assertEqual(postes['tranches'], [2])
        self.assertFalse(postes['inscription'])

    def test_ecritures_alternatives_d_une_tranche(self):
        for libelle, attendu in (
            ("Tranche 1", [1]), ("1ère tranche", [1]), ("1ere tranche", [1]),
            ("T1", [1]), ("Première tranche", [1]),
            ("2ème tranche", [2]), ("Deuxième tranche", [2]), ("T 2", [2]),
            ("Tranche n°3", [3]), ("Troisième tranche", [3]),
        ):
            with self.subTest(libelle=libelle):
                self.assertEqual(analyser_type_paiement(libelle)['tranches'], attendu)

    def test_reinscription_est_distinguee_de_l_inscription(self):
        self.assertTrue(analyser_type_paiement("Réinscription")['reinscription'])
        self.assertFalse(analyser_type_paiement("Frais d'inscription")['reinscription'])
        # Dans les deux cas le poste inscription de l'échéancier est visé.
        self.assertTrue(analyser_type_paiement("Réinscription")['inscription'])

    def test_libelle_hors_scolarite_ne_vise_aucun_poste(self):
        postes = analyser_type_paiement("Frais divers")
        self.assertFalse(postes['inscription'])
        self.assertEqual(postes['tranches'], [])

    def test_casse_et_accents_indifferents(self):
        self.assertEqual(
            analyser_type_paiement("REINSCRIPTION + TRANCHE 1"),
            analyser_type_paiement("Réinscription + Tranche 1"),
        )


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class MontantExactPourTypeTest(TestCase):
    """Le montant renvoyé est le *reste* à payer, pas le tarif plein."""

    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Test", adresse="Conakry",
            telephone="+224620000005", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="CM1", ecole=self.ecole, niveau="PRIMAIRE_5",
            annee_scolaire="2025-2026",
        )
        self.resp = Responsable.objects.create(
            prenom="B", nom="Sylla", relation="MERE",
            telephone="+224620000015", adresse="Adr",
        )
        self.eleve = Eleve.objects.create(
            nom="Sylla", prenom="Aissatou", matricule="KIN-050",
            classe=self.classe, sexe='F',
            date_naissance=date(2015, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        # Réinscription 30 000 (10 000 déjà réglés), T1 700 000 (200 000 réglés),
        # T2 500 000, T3 20 000.
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire="2025-2026",
            frais_inscription_du=Decimal("30000"),
            frais_inscription_paye=Decimal("10000"),
            tranche_1_due=Decimal("700000"),
            tranche_1_payee=Decimal("200000"),
            tranche_2_due=Decimal("500000"),
            tranche_3_due=Decimal("20000"),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )

    def test_le_montant_deduit_ce_qui_est_deja_paye(self):
        """20 000 de réinscription + 500 000 de T1, et non 30 000 + 700 000."""
        calcul = montant_exact_pour_type(self.echeancier, "Réinscription + Tranche 1")

        self.assertEqual(calcul['total'], 520000)
        self.assertEqual(
            [(l['libelle'], l['montant']) for l in calcul['lignes']],
            [("Réinscription", 20000), ("1ère tranche", 500000)],
        )
        self.assertEqual(calcul['description'], "Réinscription + 1ère tranche")

    def test_tranches_combinees_sont_additionnees(self):
        """Le défaut d'origine : seule la première tranche était comptée."""
        self.assertEqual(
            montant_exact_pour_type(self.echeancier, "Tranche 1 + Tranche 2")['total'],
            1000000,
        )
        self.assertEqual(
            montant_exact_pour_type(self.echeancier, "Tranche 2 + Tranche 3")['total'],
            520000,
        )
        self.assertEqual(
            montant_exact_pour_type(self.echeancier, "Tranche 1 + Tranche 2 + Tranche 3")['total'],
            1020000,
        )

    def test_annuel_avec_reinscription_couvre_tout_le_reste(self):
        calcul = montant_exact_pour_type(self.echeancier, "Réinscription + Annuel")

        self.assertEqual(calcul['total'], 1040000)
        self.assertEqual(len(calcul['lignes']), 4)

    def test_un_poste_solde_ne_compte_plus(self):
        self.echeancier.tranche_1_payee = Decimal("700000")
        self.echeancier.save()

        calcul = montant_exact_pour_type(self.echeancier, "Tranche 1")

        self.assertEqual(calcul['total'], 0)

    def test_type_non_reconnu(self):
        calcul = montant_exact_pour_type(self.echeancier, "Frais divers")

        self.assertEqual(calcul['total'], 0)
        self.assertFalse(calcul['reconnu'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class SuggestionAjaxTest(TestCase):
    """L'écran de saisie propose ce que le serveur validera ensuite."""

    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Test", adresse="Conakry",
            telephone="+224620000006", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="CM2", ecole=self.ecole, niveau="PRIMAIRE_6",
            annee_scolaire="2025-2026",
        )
        self.resp = Responsable.objects.create(
            prenom="K", nom="Bah", relation="PERE",
            telephone="+224620000016", adresse="Adr",
        )
        self.eleve = Eleve.objects.create(
            nom="Bah", prenom="Mamadou", matricule="KIN-060",
            classe=self.classe, sexe='M',
            date_naissance=date(2014, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire="2025-2026",
            frais_inscription_du=Decimal("50000"),
            tranche_1_due=Decimal("400000"),
            tranche_2_due=Decimal("300000"),
            tranche_3_due=Decimal("200000"),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )
        self.type_t1_t2 = TypePaiement.objects.create(nom="Tranche 1 + Tranche 2")
        ModePaiement.objects.create(nom="Espèces")

        User = get_user_model()
        self.user = User.objects.create_user(username="compta_moteur", password="pass12345")
        Profil.objects.update_or_create(
            user=self.user,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': "+224620000025", 'peut_consulter_rapports': True,
                'is_validated': True,
            },
        )
        self.user.refresh_from_db()
        self.client.force_login(self.user)

    def test_la_suggestion_additionne_les_tranches_du_type(self):
        response = self.client.post(
            reverse('paiements:ajax_montant_suggere'),
            {'eleve_id': self.eleve.id, 'type_id': self.type_t1_t2.id},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['suggested'], 700000)
        self.assertEqual(
            [(l['libelle'], l['montant']) for l in data['breakdown']['lignes']],
            [("1ère tranche", 400000), ("2ème tranche", 300000)],
        )

    def test_la_suggestion_est_acceptee_telle_quelle_a_la_saisie(self):
        """Le montant proposé ne doit déclencher aucune confirmation."""
        suggestion = self.client.post(
            reverse('paiements:ajax_montant_suggere'),
            {'eleve_id': self.eleve.id, 'type_id': self.type_t1_t2.id},
        ).json()['suggested']

        response = self.client.post(reverse('paiements:ajouter_paiement'), {
            'eleve': self.eleve.id,
            'type_paiement': self.type_t1_t2.id,
            'mode_paiement': ModePaiement.objects.first().id,
            'montant': suggestion,
            'date_paiement': '2026-08-04',
            'observations': '',
            'reference_externe': '',
        })

        self.assertEqual(response.status_code, 302)
