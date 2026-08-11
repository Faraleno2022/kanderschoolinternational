"""Le champ montant de l'écran de correction doit accepter un montant réel.

Le refus venait du navigateur, pas du serveur : en HTML, la base du pas d'un
`input type=number` est son `min`. Avec min=1 et step=1000, les seules
valeurs acceptées étaient 1, 1001, 2001… et toute correction normale était
rejetée sans jamais atteindre Django.
"""

from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole, Classe, Eleve, Responsable
from paiements.forms import ModificationPaiementForm
from paiements.models import (
    EcheancierPaiement, TypePaiement, ModePaiement, Paiement,
)
from paiements.tests.support import TEST_MIDDLEWARE
from utilisateurs.models import Profil


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ModificationMontantTest(TestCase):

    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Test", adresse="Conakry",
            telephone="+224620000004", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="CP3", ecole=self.ecole, niveau="PRIMAIRE_3",
            annee_scolaire="2025-2026",
        )
        self.resp = Responsable.objects.create(
            prenom="S", nom="Camara", relation="PERE",
            telephone="+224620000014", adresse="Adr",
        )
        self.eleve = Eleve.objects.create(
            nom="Camara", prenom="Sekou", matricule="KIN-040",
            classe=self.classe, sexe='M',
            date_naissance=date(2016, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        EcheancierPaiement.objects.create(
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
        self.type_t1 = TypePaiement.objects.create(nom="Scolarité - 1ère tranche")
        self.mode = ModePaiement.objects.create(nom="Espèces")
        self.paiement = Paiement.objects.create(
            eleve=self.eleve, type_paiement=self.type_t1, mode_paiement=self.mode,
            montant=Decimal("300000"), statut='EN_ATTENTE',
            date_paiement=date(2026, 8, 4),
        )

        User = get_user_model()
        self.user = User.objects.create_user(username="compta_modif", password="pass12345")
        Profil.objects.update_or_create(
            user=self.user,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': "+224620000024", 'peut_consulter_rapports': True,
                'is_validated': True,
            },
        )
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        self.url = reverse('paiements:modifier_paiement', kwargs={'paiement_id': self.paiement.id})

    def test_le_pas_du_champ_montant_est_compatible_avec_son_minimum(self):
        """Un pas de 1000 sur une base de 1 rendait tout montant rond invalide."""
        html = str(ModificationPaiementForm(instance=self.paiement)['montant'])

        self.assertIn('step="1"', html)
        self.assertIn('min="1"', html)

    def test_un_montant_rond_est_accepte(self):
        form = ModificationPaiementForm(
            data={
                'type_paiement': self.type_t1.id,
                'mode_paiement': self.mode.id,
                'montant': '500000',
                'date_paiement': '2026-08-04',
                'reference_externe': '',
                'observations': '',
                'motif_modification': 'Montant corrigé après recomptage',
            },
            instance=self.paiement,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_la_correction_est_enregistree(self):
        response = self.client.post(self.url, {
            'type_paiement': self.type_t1.id,
            'mode_paiement': self.mode.id,
            'montant': '500000',
            'date_paiement': '2026-08-04',
            'reference_externe': '',
            'observations': '',
            'motif_modification': 'Montant corrigé après recomptage',
        })

        self.assertEqual(response.status_code, 302)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("500000"))

    def test_le_montant_nul_reste_refuse(self):
        response = self.client.post(self.url, {
            'type_paiement': self.type_t1.id,
            'mode_paiement': self.mode.id,
            'montant': '0',
            'date_paiement': '2026-08-04',
            'reference_externe': '',
            'observations': '',
            'motif_modification': 'Tentative de mise à zéro',
        })

        self.assertEqual(response.status_code, 200)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("300000"))
