from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from eleves.models import Ecole, Classe, Responsable, Eleve
from paiements.models import (
    ModePaiement,
    TypePaiement,
    Paiement,
    RemiseReduction,
    PaiementRemise,
)

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ValiderEcheancierRedirectTests(TestCase):
    def setUp(self):
        # Auth user (superuser bypasses granular permission checks)
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass1234"
        )
        self.client.force_login(self.user)

        # Minimal school data
        self.ecole = Ecole.objects.create(
            nom="Ecole Test",
            adresse="Addr",
            telephone="+224123456789",
            email="ecole@test.com",
            directeur="Dir",
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole,
            nom="7ème année",
            niveau="COLLEGE_7",
            annee_scolaire="2024-2025",
            capacite_max=40,
        )
        self.responsable = Responsable.objects.create(
            prenom="Jean",
            nom="Doe",
            relation="PERE",
            telephone="+224123456789",
            email="p@example.com",
            adresse="Addr"
        )
        self.eleve = Eleve.objects.create(
            matricule="TEMP-001",
            prenom="Alice",
            nom="Test",
            sexe="F",
            date_naissance=timezone.now().date().replace(year=timezone.now().year - 10),
            lieu_naissance="Ville",
            classe=self.classe,
            date_inscription=timezone.now().date(),
            statut="ACTIF",
            responsable_principal=self.responsable,
        )
        self.mode = ModePaiement.objects.create(nom="Espèces")
        self.type = TypePaiement.objects.create(nom="Scolarité")

    def _create_pending_payment(self):
        return Paiement.objects.create(
            eleve=self.eleve,
            type_paiement=self.type,
            mode_paiement=self.mode,
            montant=100000,
            date_paiement=timezone.now().date(),
            statut="EN_ATTENTE",
            numero_recu="",  # let model auto-generate
        )

    def test_redirects_to_detail_when_no_remise(self):
        paiement = self._create_pending_payment()
        url = reverse("paiements:valider_echeancier", kwargs={"eleve_id": self.eleve.id})
        resp = self.client.post(url, follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(
            reverse("paiements:detail_paiement", kwargs={"paiement_id": paiement.id}),
            resp.url,
        )

    def test_redirects_back_to_echeancier_when_remise_exists(self):
        paiement = self._create_pending_payment()
        # Apply a remise to the payment
        today = timezone.now().date()
        remise = RemiseReduction.objects.create(
            nom="Remise fratrie",
            type_remise="POURCENTAGE",
            valeur=10,
            motif="FRATRIE",
            date_debut=today.replace(day=1),
            date_fin=today.replace(day=28 if today.month == 2 else 30),
            actif=True,
        )
        PaiementRemise.objects.create(paiement=paiement, remise=remise, montant_remise=5000)

        url = reverse("paiements:valider_echeancier", kwargs={"eleve_id": self.eleve.id})
        resp = self.client.post(url, follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(
            reverse("paiements:echeancier_eleve", kwargs={"eleve_id": self.eleve.id}),
            resp.url,
        )
