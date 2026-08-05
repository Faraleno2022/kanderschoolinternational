from decimal import Decimal
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Ecole, Classe, Eleve, Responsable
from paiements.models import (
    EcheancierPaiement, TypePaiement, ModePaiement, Paiement,
    RemiseReduction, PaiementRemise,
)
from utilisateurs.models import Profil


TEST_MIDDLEWARE = [
    middleware for middleware in settings.MIDDLEWARE
    if middleware != 'ecole_moderne.licence_middleware.LicenceMiddleware'
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class AppliquerRemiseTest(TestCase):
    """Une remise porte sur les tranches de scolarité cochées et jamais sur les
    frais d'inscription/réinscription. Le motif est obligatoire."""

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
            nom="Mansare", prenom="Ibrahima", matricule="KIN-014",
            classe=self.classe, sexe='M',
            date_naissance=date(2021, 1, 1), lieu_naissance="Conakry",
            date_inscription=date(2025, 9, 1), responsable_principal=self.resp,
        )
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire="2025-2026",
            frais_inscription_du=Decimal("20000"),
            tranche_1_due=Decimal("500000"),
            tranche_2_due=Decimal("600000"),
            tranche_3_due=Decimal("400000"),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )
        type_insc_t1 = TypePaiement.objects.create(nom="Réinscription + Tranche 1")
        mode = ModePaiement.objects.create(nom="Espèces")
        # Reçu combiné : 20 000 réinscription + 500 000 tranche 1 = 520 000
        self.paiement = Paiement.objects.create(
            eleve=self.eleve, type_paiement=type_insc_t1, mode_paiement=mode,
            montant=Decimal("520000"), statut='EN_ATTENTE',
            date_paiement=date(2026, 8, 4),
        )
        self.remise = RemiseReduction.objects.create(
            nom="Remise fratrie 5%", type_remise='POURCENTAGE', valeur=Decimal("5"),
            motif='FRATRIE', date_debut=date(2025, 1, 1), date_fin=date(2026, 12, 31),
            actif=True,
        )

        User = get_user_model()
        self.user = User.objects.create_user(username="compta_remise", password="pass12345")
        Profil.objects.update_or_create(
            user=self.user,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': "+224620000021", 'peut_consulter_rapports': True,
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
        }
        data.update(extra)
        return self.client.post(self.url, data)

    def test_remise_catalogue_sur_tranche_cochee_hors_inscription(self):
        """5 % sur T1 = 25 000, et non 5 % de 520 000 qui inclurait la réinscription."""
        response = self._post(remises=[self.remise.id])

        self.assertEqual(response.status_code, 302)
        pr = PaiementRemise.objects.get(paiement=self.paiement, remise=self.remise)
        self.assertEqual(pr.montant_remise, Decimal("25000"))
        self.assertEqual(pr.portee_tranches, '1')
        self.assertEqual(pr.motif_application, 'GESTE_COMMERCIAL')

        # Le reçu lui-même ne doit jamais être modifié par la remise.
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, Decimal("520000"))

    def test_base_echeance_exclut_aussi_l_inscription(self):
        """Sur ce reçu, la part affectée à T1 vaut 500 000 (et non 520 000)."""
        response = self._post(remises=[self.remise.id], base_calcul='ECHEANCE')

        self.assertEqual(response.status_code, 302)
        pr = PaiementRemise.objects.get(paiement=self.paiement, remise=self.remise)
        self.assertEqual(pr.montant_remise, Decimal("25000"))

    def test_plusieurs_tranches_cumulent_la_base(self):
        """T1 + T2 : 5 % de (500 000 + 600 000) = 55 000."""
        response = self._post(remises=[self.remise.id], tranches=['1', '2'])

        self.assertEqual(response.status_code, 302)
        pr = PaiementRemise.objects.get(paiement=self.paiement, remise=self.remise)
        self.assertEqual(pr.montant_remise, Decimal("55000"))
        self.assertEqual(pr.portee_tranches, '1,2')

    def test_pourcentage_scolarite_utilise_la_base_des_tranches_cochees(self):
        """100 % sur les trois tranches = 1 500 000, sans toucher aux 20 000 d'inscription."""
        response = self._post(pourcentage_scolarite='100', tranches=['1', '2', '3'])

        self.assertEqual(response.status_code, 302)
        pr = PaiementRemise.objects.get(paiement=self.paiement)
        self.assertEqual(pr.montant_remise, Decimal("1500000"))
        self.assertEqual(pr.portee_tranches, '1,2,3')

    def test_motif_obligatoire(self):
        response = self._post(remises=[self.remise.id], motif_remise='')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaiementRemise.objects.filter(paiement=self.paiement).exists())
        self.assertIn('motif_remise', response.context['form'].errors)

    def test_tranche_obligatoire(self):
        response = self._post(remises=[self.remise.id], tranches=[])

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaiementRemise.objects.filter(paiement=self.paiement).exists())
        self.assertIn('tranches', response.context['form'].errors)

    def test_base_nulle_refusee(self):
        """T2 ne reçoit rien de ce reçu : en base « paiement à l'échéance »,
        la remise serait nulle, on refuse plutôt que d'enregistrer 0."""
        response = self._post(
            remises=[self.remise.id], tranches=['2'], base_calcul='ECHEANCE',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaiementRemise.objects.filter(paiement=self.paiement).exists())

    def test_libelle_portee(self):
        self._post(remises=[self.remise.id], tranches=['1', '3'])
        pr = PaiementRemise.objects.get(paiement=self.paiement, remise=self.remise)
        self.assertEqual(pr.portee_libelle, "T1 + T3")
