from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from eleves.models import Classe, Ecole, Eleve, GrilleTarifaire
from paiements.models import (
    EcheancierPaiement, ModePaiement, Paiement, TypePaiement,
)

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class TranchesParClasseExportsTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='Ecole export tranches', adresse='Conakry',
            telephone='+224620000701', directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='Classe export', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        GrilleTarifaire.objects.create(
            ecole=self.ecole, niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
            frais_inscription=Decimal('30000'),
            frais_reinscription=Decimal('20000'),
            tranche_1=Decimal('100000'),
            tranche_2=Decimal('110000'),
            tranche_3=Decimal('120000'),
        )
        self.mode = ModePaiement.objects.create(nom='Especes export')
        self.type_inscription = TypePaiement.objects.create(nom='Inscription')
        self.type_reinscription = TypePaiement.objects.create(
            nom='Réinscription + Tranche 1'
        )
        self._creer_eleve(
            'EXP-INS', Decimal('30000'), Decimal('30000'),
            Decimal('50000'), self.type_inscription,
        )
        self._creer_eleve(
            'EXP-REI', Decimal('20000'), Decimal('20000'),
            Decimal('60000'), self.type_reinscription,
        )
        self.user = get_user_model().objects.create_superuser(
            username='admin_export_tranches',
            email='admin.export.tranches@example.com',
            password='pass12345',
        )
        self.client.force_login(self.user)

    def _creer_eleve(self, matricule, admission_due, admission_paid, t1_paid, type_paiement):
        eleve = Eleve.objects.create(
            matricule=matricule, prenom='Eleve', nom=matricule,
            sexe='F', date_naissance=date(2018, 1, 1),
            lieu_naissance='Conakry', classe=self.classe,
            date_inscription=date(2025, 9, 1),
        )
        EcheancierPaiement.objects.create(
            eleve=eleve, annee_scolaire='2025-2026',
            frais_inscription_du=admission_due,
            tranche_1_due=Decimal('100000'),
            tranche_2_due=Decimal('110000'),
            tranche_3_due=Decimal('120000'),
            frais_inscription_paye=admission_paid,
            tranche_1_payee=t1_paid,
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2026, 1, 15),
            date_echeance_tranche_2=date(2026, 3, 15),
            date_echeance_tranche_3=date(2026, 5, 15),
        )
        Paiement.objects.create(
            eleve=eleve, type_paiement=type_paiement,
            mode_paiement=self.mode,
            montant=admission_paid + t1_paid,
            date_paiement=date(2025, 9, 10), statut='VALIDE',
        )

    def _params(self):
        return {
            'classe': self.classe.id,
            'annee_scolaire': '2025-2026',
        }

    def test_excel_separe_inscription_et_reinscription(self):
        response = self.client.get(
            reverse('paiements:export_tranches_par_classe_excel'),
            self._params(),
        )
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        sheet = workbook[self.classe.nom]
        self.assertEqual(
            list(next(sheet.iter_rows(min_row=2, max_row=2, values_only=True))),
            [
                'Élève', 'Inscription payée', 'Réinscription payée',
                'Tranche 1 payée', 'Tranche 2 payée', 'Tranche 3 payée',
                'Total dû', 'Total payé', 'Reste',
            ],
        )
        lignes = list(sheet.iter_rows(min_row=3, values_only=True))
        inscription = next(row for row in lignes if 'EXP-INS' in row[0])
        self.assertEqual(inscription[1], 30000)
        self.assertEqual(inscription[2], 0)
        self.assertEqual(inscription[3], 50000)

        reinscription = next(row for row in lignes if 'EXP-REI' in row[0])
        self.assertEqual(reinscription[1], 0)
        self.assertEqual(reinscription[2], 20000)
        self.assertEqual(reinscription[3], 60000)
        self.assertEqual(reinscription[7], 80000)

    def test_pdf_contient_la_colonne_reinscription(self):
        from reportlab.platypus import Table as RealTable

        tables = []

        def capturer_table(data, *args, **kwargs):
            tables.append(data)
            return RealTable(data, *args, **kwargs)

        with patch('reportlab.platypus.Table', side_effect=capturer_table):
            response = self.client.get(
                reverse('paiements:export_tranches_par_classe_pdf'),
                self._params(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertTrue(tables)
        self.assertEqual(tables[0][0][2], 'Réinscription payée')
        # La réinscription n'est jamais recopiée dans la colonne inscription.
        ligne_reinscription = next(
            row for row in tables[0][1:]
            if 'EXP-REI' in row[0].getPlainText()
        )
        self.assertEqual(ligne_reinscription[1], '0')
        self.assertEqual(ligne_reinscription[2], '20 000')
