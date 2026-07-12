from decimal import Decimal

from django.test import SimpleTestCase

from .calculs_intelligent import calculer_moyenne_annuelle


class CalculMoyenneAnnuelleTests(SimpleTestCase):
    def test_periode_manquante_compte_comme_zero(self):
        moyenne = calculer_moyenne_annuelle(
            [Decimal('12'), None, Decimal('15')]
        )

        self.assertEqual(moyenne, Decimal('9.00'))

    def test_aucune_periode_evaluee_retourne_none(self):
        self.assertIsNone(calculer_moyenne_annuelle([None, None, None]))
