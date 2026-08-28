"""Suppression définitive d'un paiement, réservée à l'administration.

L'annulation garde le reçu consultable ; la suppression efface la ligne.
Les deux doivent recalculer les soldes, et la suppression doit laisser
derrière elle de quoi expliquer la disparition du reçu.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from paiements.models import (
    EcheancierPaiement, HistoriqueModificationPaiement, ModePaiement,
    Paiement, PaiementRemise, RemiseReduction, TypePaiement,
)
from utilisateurs.models import Profil

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class SuppressionDefinitiveTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Test', adresse='Conakry', telephone='620000911',
            directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='CP1', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.eleve = Eleve.objects.create(
            matricule='SUP-001', prenom='Mariama', nom='Diallo', sexe='F',
            date_naissance=date(2016, 1, 1), lieu_naissance='Conakry',
            classe=self.classe, date_inscription=date(2025, 9, 1),
        )
        self.echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire='2025-2026',
            ecole_reference=self.ecole, classe_reference=self.classe,
            frais_inscription_du=Decimal('0'), tranche_1_due=Decimal('500000'),
            tranche_2_due=Decimal('0'), tranche_3_due=Decimal('0'),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )
        self.type_t1 = TypePaiement.objects.create(nom='Scolarité - 1ère tranche')
        self.mode = ModePaiement.objects.create(nom='Espèces')
        self.paiement = Paiement.objects.create(
            eleve=self.eleve, type_paiement=self.type_t1, mode_paiement=self.mode,
            montant=Decimal('500000'), statut='VALIDE',
            date_paiement=date(2025, 10, 2),
        )
        self.echeancier.tranche_1_payee = Decimal('500000')
        self.echeancier.statut = 'PAYE_COMPLET'
        self.echeancier.save()

        self.admin = get_user_model().objects.create_superuser(
            username='admin_suppression', email='admin.suppression@example.com',
            password='pass12345',
        )
        self.url = reverse(
            'paiements:supprimer_paiement',
            kwargs={'paiement_id': self.paiement.id},
        )
        self.client.force_login(self.admin)

    def _supprimer(self, motif='Saisie de test créée par erreur'):
        return self.client.post(self.url, {'motif_suppression': motif})

    def _caissier(self, peut_supprimer=True):
        """Un profil non-administrateur, même autorisé à annuler."""
        utilisateur = get_user_model().objects.create_user(
            username=f'caissier_{peut_supprimer}', password='pass12345',
        )
        Profil.objects.update_or_create(
            user=utilisateur,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': '+224620000912', 'is_validated': True,
                'peut_supprimer_paiements': peut_supprimer,
            },
        )
        return utilisateur

    def test_l_administrateur_efface_la_ligne_et_libere_la_dette(self):
        reponse = self._supprimer()

        self.assertEqual(reponse.status_code, 302)
        self.assertFalse(Paiement.objects.filter(pk=self.paiement.pk).exists())
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('0'))
        self.assertEqual(self.echeancier.statut, 'EN_RETARD')

    def test_la_suppression_laisse_une_trace_explicable(self):
        numero_recu = self.paiement.numero_recu

        self._supprimer(motif='Doublon confirmé avec la caisse')

        trace = HistoriqueModificationPaiement.objects.filter(
            numero_recu=numero_recu,
        ).order_by('-date_modification').first()
        self.assertIsNotNone(trace)
        self.assertIn('Doublon confirmé avec la caisse', trace.motif)
        self.assertEqual(trace.utilisateur, self.admin)
        self.assertIn('SUP-001', trace.eleve)
        # La ligne est partie, mais son montant reste lisible dans la trace.
        self.assertIsNone(trace.paiement)
        self.assertEqual(str(trace.donnees_avant.get('montant')), '500000')

    def test_la_suppression_emporte_les_remises_du_paiement(self):
        remise = RemiseReduction.objects.create(
            nom='Fratrie', type_remise='MONTANT_FIXE', valeur=Decimal('100000'),
            motif='FRATRIE', date_debut=date(2025, 9, 1), date_fin=date(2026, 8, 31),
        )
        PaiementRemise.objects.create(
            paiement=self.paiement, remise=remise,
            montant_remise=Decimal('100000'),
        )

        self._supprimer()

        self.assertFalse(PaiementRemise.objects.exists())
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('0'))

    def test_un_caissier_autorise_a_annuler_ne_peut_pas_supprimer(self):
        """`peut_supprimer_paiements` ouvre l'annulation, pas l'effacement."""
        self.client.force_login(self._caissier(peut_supprimer=True))

        self._supprimer()

        self.assertTrue(Paiement.objects.filter(pk=self.paiement.pk).exists())
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('500000'))

    def test_le_motif_est_obligatoire(self):
        self._supprimer(motif='ok')

        self.assertTrue(Paiement.objects.filter(pk=self.paiement.pk).exists())

    def test_la_suppression_exige_une_requete_post(self):
        reponse = self.client.get(self.url)

        self.assertEqual(reponse.status_code, 405)
        self.assertTrue(Paiement.objects.filter(pk=self.paiement.pk).exists())

    def test_seul_l_administrateur_voit_le_bouton_de_suppression(self):
        detail = reverse(
            'paiements:detail_paiement',
            kwargs={'paiement_id': self.paiement.id},
        )

        self.assertContains(self.client.get(detail), 'id="suppressionModal"')

        self.client.force_login(self._caissier(peut_supprimer=True))
        reponse = self.client.get(detail)
        self.assertNotContains(reponse, 'id="suppressionModal"')
        # Il garde en revanche l'annulation, qui laisse le reçu consultable.
        self.assertContains(reponse, 'id="annulationModal"')
