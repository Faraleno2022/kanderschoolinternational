from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from paiements.models import (
    EcheancierPaiement, ModePaiement, Paiement, TypePaiement,
)
from paiements.rapports_professionnels import _draw_school_watermark

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class PaiementsPdfLogoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin-pdf-logo',
            email='pdf.logo@example.com',
            password='mot-de-passe-test',
        )
        self.client.force_login(self.user)
        self.ecole = Ecole.objects.create(
            nom='École avec logo PDF',
            adresse='Conakry',
            telephone='+224620000801',
            directeur='Direction PDF',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole,
            nom='Classe PDF',
            niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.eleve = Eleve.objects.create(
            matricule='LOGO-PDF-001',
            prenom='Aminata',
            nom='Logo',
            sexe='F',
            date_naissance=date(2018, 1, 1),
            classe=self.classe,
            date_inscription=date(2025, 9, 1),
        )
        self.type_paiement = TypePaiement.objects.create(
            nom='Inscription et tranche PDF',
        )
        self.mode_paiement = ModePaiement.objects.create(nom='Espèces PDF')
        Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type_paiement,
            mode_paiement=self.mode_paiement,
            numero_recu='LOGO-REC-001',
            montant=Decimal('120000'),
            date_paiement=date(2026, 1, 15),
            statut='VALIDE',
            reference_externe='LOGO-TXN-001',
            cree_par=self.user,
            valide_par=self.user,
        )
        EcheancierPaiement.objects.create(
            eleve=self.eleve,
            annee_scolaire='2025-2026',
            frais_inscription_du=Decimal('20000'),
            frais_inscription_paye=Decimal('20000'),
            tranche_1_due=Decimal('100000'),
            tranche_1_payee=Decimal('100000'),
            tranche_2_due=Decimal('100000'),
            tranche_3_due=Decimal('100000'),
            date_echeance_inscription=date(2025, 9, 30),
            date_echeance_tranche_1=date(2026, 1, 10),
            date_echeance_tranche_2=date(2026, 3, 10),
            date_echeance_tranche_3=date(2026, 5, 10),
        )
        self.logo_path = str(
            Path(settings.BASE_DIR) / 'static' / 'logos' / 'logo.png'
        )
        self.assertTrue(Path(self.logo_path).is_file())

    def _logo_resolver(self, observed_schools):
        def resolve(school=None):
            observed_schools.append(school)
            return self.logo_path

        return resolve

    def _assert_pdf_with_image(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn(b'/Subtype /Image', response.content)

    def test_export_liste_pdf_contient_le_logo_de_ecole(self):
        observed_schools = []
        resolver = self._logo_resolver(observed_schools)
        with (
            patch('paiements.views_exports_pdf._get_logo_path', side_effect=resolver),
            patch('rapports.utils._get_logo_path', side_effect=resolver),
        ):
            response = self.client.get(
                reverse('paiements:export_liste_paiements_pdf'),
                {'q': 'LOGO-PDF-001', 'annee': '2025-2026'},
            )

        self._assert_pdf_with_image(response)
        self.assertIn(self.ecole, observed_schools)

    def test_export_tranches_pdf_contient_le_logo_de_ecole(self):
        observed_schools = []
        resolver = self._logo_resolver(observed_schools)
        with (
            patch('paiements.views_tranches._get_logo_path', side_effect=resolver),
            patch('rapports.utils._get_logo_path', side_effect=resolver),
        ):
            response = self.client.get(
                reverse('paiements:export_tranches_par_classe_pdf'),
                {
                    'classe': self.classe.pk,
                    'annee_scolaire': '2025-2026',
                },
            )

        self._assert_pdf_with_image(response)
        self.assertIn(self.ecole, observed_schools)

    def test_rapports_professionnels_contiennent_le_logo_de_ecole(self):
        observed_schools = []
        resolver = self._logo_resolver(observed_schools)
        params = {
            'classe_id': self.classe.pk,
            'annee_scolaire': '2025-2026',
            'au': '2026-08-16',
        }
        with patch(
            'paiements.rapports_professionnels._get_logo_path',
            side_effect=resolver,
        ):
            accounting = self.client.get(
                reverse('paiements:export_comptabilite_pdf'), params,
            )
            recovery = self.client.get(
                reverse('paiements:export_recouvrement_pdf'), params,
            )

        self._assert_pdf_with_image(accounting)
        self._assert_pdf_with_image(recovery)
        self.assertIn(self.ecole, observed_schools)

    def test_filigrane_professionnel_est_grand_centre_et_discret(self):
        canvas = MagicMock()
        page_width = 841.89
        page_height = 595.28

        _draw_school_watermark(
            canvas, self.logo_path, page_width, page_height,
        )

        canvas.saveState.assert_called_once_with()
        canvas.restoreState.assert_called_once_with()
        canvas.setFillAlpha.assert_called_once_with(0.04)
        canvas.drawImage.assert_called_once_with(
            self.logo_path,
            (page_width - (page_width * 0.62)) / 2,
            (page_height - (page_height * 0.62)) / 2,
            width=page_width * 0.62,
            height=page_height * 0.62,
            preserveAspectRatio=True,
            mask='auto',
        )
