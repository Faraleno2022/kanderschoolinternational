from datetime import date
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole, Classe, Eleve, Responsable
from paiements.models import Paiement, TypePaiement, ModePaiement
from utilisateurs.models import Profil


TEST_MIDDLEWARE = [
    middleware for middleware in settings.MIDDLEWARE
    if middleware != 'ecole_moderne.licence_middleware.LicenceMiddleware'
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class RapportComptableDefautPeriodeTest(TestCase):
    """Reproduit le cas signalé : le rapport paraissait vide en tout début de
    mois alors que des paiements existaient bien, datés du mois précédent."""

    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom="Kinder Test", adresse="Conakry",
            telephone="+224620000001", directeur="Directrice",
        )
        self.classe = Classe.objects.create(
            nom="Petite Section", ecole=self.ecole, niveau="MATERNELLE",
            annee_scolaire="2025-2026",
        )
        self.resp = Responsable.objects.create(
            prenom="P", nom="Resp", relation="PERE",
            telephone="+224620000011", adresse="Adr",
        )
        self.eleve = Eleve.objects.create(
            nom="Komara", prenom="Hadiza", matricule="KIN-014",
            classe=self.classe, sexe='F',
            date_naissance=date(2021, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        type_insc = TypePaiement.objects.create(nom="Frais d'inscription")
        mode = ModePaiement.objects.create(nom="Espèces")
        self.paiement = Paiement.objects.create(
            eleve=self.eleve, type_paiement=type_insc, mode_paiement=mode,
            montant=4150000, statut='VALIDE', date_paiement=date(2026, 7, 31),
        )

        User = get_user_model()
        self.comptable = User.objects.create_user(username="comptable_test", password="pass12345")
        Profil.objects.update_or_create(
            user=self.comptable,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': "+224620000021", 'peut_consulter_rapports': True,
                'is_validated': True,
            },
        )
        self.comptable.refresh_from_db()

    @patch('paiements.views_rapport_comptable.timezone.localdate', return_value=date(2026, 8, 2))
    def test_paiement_de_juillet_visible_sans_dates_explicites_le_2_aout(self, _mock_localdate):
        self.client.force_login(self.comptable)
        response = self.client.get(reverse('paiements:rapport_comptable'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['nombre_paiements'], 1)
        self.assertEqual(response.context['total_paiements'], self.paiement.montant)
        self.assertContains(response, self.paiement.numero_recu)
        # La période par défaut doit remonter avant le paiement de juillet,
        # pas se limiter au mois calendaire en cours (vide le 1er/2 du mois).
        self.assertLessEqual(response.context['date_debut'], date(2026, 7, 31))

    @patch('paiements.views_rapport_comptable.timezone.localdate', return_value=date(2026, 8, 2))
    def test_dates_explicites_restent_prioritaires(self, _mock_localdate):
        self.client.force_login(self.comptable)
        response = self.client.get(
            reverse('paiements:rapport_comptable'),
            {'date_debut': '2026-08-01', 'date_fin': '2026-08-02'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['nombre_paiements'], 0)
