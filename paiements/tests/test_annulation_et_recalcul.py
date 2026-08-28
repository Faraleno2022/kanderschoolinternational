"""Correction et annulation d'un paiement doivent recalculer les bons soldes.

Deux pièges couverts ici : l'échéancier visé après un transfert (celui de
l'encaissement, pas celui de la classe actuelle) et l'annulation, qui doit
libérer la dette que le paiement couvrait sans effacer sa trace.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from paiements.models import (
    EcheancierPaiement, ModePaiement, Paiement, PaiementRemise,
    RemiseReduction, TypePaiement,
)
from utilisateurs.models import Profil

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class AnnulationEtRecalculTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Source', adresse='Conakry', telephone='620000901',
            directeur='Direction',
        )
        self.ecole_arrivee = Ecole.objects.create(
            nom='École Arrivée', adresse='Conakry', telephone='620000902',
            directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='CP1', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.classe_arrivee = Classe.objects.create(
            ecole=self.ecole_arrivee, nom='CP2', niveau='PRIMAIRE_2',
            annee_scolaire='2026-2027',
        )
        self.eleve = Eleve.objects.create(
            matricule='ANN-001', prenom='Aissatou', nom='Bah', sexe='F',
            date_naissance=date(2016, 1, 1), lieu_naissance='Conakry',
            classe=self.classe, date_inscription=date(2025, 9, 1),
        )
        self.echeancier = self._echeancier(
            self.classe, '2025-2026', Decimal('500000'),
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

        self.user = get_user_model().objects.create_superuser(
            username='admin_annulation', email='admin.annulation@example.com',
            password='pass12345',
        )
        self.client.force_login(self.user)

    def _echeancier(self, classe, annee, tranche_1_due):
        return EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire=annee,
            ecole_reference=classe.ecole, classe_reference=classe,
            frais_inscription_du=Decimal('0'), tranche_1_due=tranche_1_due,
            tranche_2_due=Decimal('0'), tranche_3_due=Decimal('0'),
            date_echeance_inscription=date(2025, 9, 1),
            date_echeance_tranche_1=date(2025, 10, 1),
            date_echeance_tranche_2=date(2026, 1, 1),
            date_echeance_tranche_3=date(2026, 4, 1),
        )

    def _corriger(self, montant):
        return self.client.post(
            reverse(
                'paiements:modifier_paiement',
                kwargs={'paiement_id': self.paiement.id},
            ),
            {
                'type_paiement': self.type_t1.id, 'mode_paiement': self.mode.id,
                'montant': montant, 'date_paiement': '2025-10-02',
                'reference_externe': '', 'observations': '',
                'motif_modification': 'Erreur de saisie constatée en caisse',
            },
        )

    def _annuler(self, motif='Double saisie du même encaissement'):
        return self.client.post(
            reverse(
                'paiements:annuler_paiement',
                kwargs={'paiement_id': self.paiement.id},
            ),
            {'motif_annulation': motif},
        )

    def test_baisser_le_montant_libere_la_dette_correspondante(self):
        self._corriger('200000')

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('200000'))
        self.assertEqual(self.echeancier.statut, 'EN_RETARD')

    def test_corriger_un_ancien_paiement_vise_son_propre_echeancier(self):
        """Après un transfert, c'est l'échéancier de l'encaissement qui bouge."""
        echeancier_arrivee = self._echeancier(
            self.classe_arrivee, '2026-2027', Decimal('800000'),
        )
        self.eleve.classe = self.classe_arrivee
        self.eleve.save()

        self._corriger('200000')

        self.echeancier.refresh_from_db()
        echeancier_arrivee.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('200000'))
        self.assertEqual(echeancier_arrivee.tranche_1_payee, Decimal('0'))

    def test_annuler_un_paiement_libere_toute_la_dette(self):
        reponse = self._annuler()

        self.assertEqual(reponse.status_code, 302)
        self.paiement.refresh_from_db()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.paiement.statut, 'ANNULE')
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('0'))
        self.assertEqual(self.echeancier.statut, 'EN_RETARD')

    def test_annuler_conserve_le_recu_et_trace_le_motif(self):
        numero_recu = self.paiement.numero_recu

        self._annuler(motif='Encaissement enregistré deux fois')

        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.numero_recu, numero_recu)
        self.assertTrue(
            Paiement.objects.filter(pk=self.paiement.pk).exists(),
            "L'annulation ne doit jamais effacer la ligne comptable.",
        )
        motifs = [
            entree.motif or ''
            for entree in self.paiement.historique_modifications.all()
        ]
        self.assertTrue(
            any('Encaissement enregistré deux fois' in motif for motif in motifs),
            motifs,
        )

    def test_annuler_retire_aussi_les_remises_portees_par_le_paiement(self):
        remise = RemiseReduction.objects.create(
            nom='Fratrie', type_remise='MONTANT_FIXE', valeur=Decimal('100000'),
            motif='FRATRIE', date_debut=date(2025, 9, 1), date_fin=date(2026, 8, 31),
        )
        PaiementRemise.objects.create(
            paiement=self.paiement, remise=remise,
            montant_remise=Decimal('100000'),
        )

        self._annuler()

        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('0'))

    def test_le_motif_est_obligatoire(self):
        reponse = self._annuler(motif='ok')

        self.assertEqual(reponse.status_code, 302)
        self.paiement.refresh_from_db()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.paiement.statut, 'VALIDE')
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('500000'))

    def test_annuler_deux_fois_ne_change_rien(self):
        self._annuler()
        self._annuler(motif='Seconde tentative involontaire')

        self.paiement.refresh_from_db()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.paiement.statut, 'ANNULE')
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('0'))

    def test_un_utilisateur_sans_permission_ne_peut_pas_annuler(self):
        caissier = get_user_model().objects.create_user(
            username='caissier_sans_droit', password='pass12345',
        )
        Profil.objects.update_or_create(
            user=caissier,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': '+224620000903', 'is_validated': True,
                'peut_supprimer_paiements': False,
            },
        )
        self.client.force_login(caissier)

        self._annuler()

        self.paiement.refresh_from_db()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.paiement.statut, 'VALIDE')
        self.assertEqual(self.echeancier.tranche_1_payee, Decimal('500000'))
        # Le formulaire ne doit pas non plus lui être proposé.
        self.assertNotContains(self._detail(), 'id="annulationModal"')

    def _detail(self):
        return self.client.get(
            reverse(
                'paiements:detail_paiement',
                kwargs={'paiement_id': self.paiement.id},
            )
        )

    def test_la_page_de_detail_propose_l_annulation(self):
        reponse = self._detail()

        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, 'id="annulationModal"')
        self.assertContains(reponse, 'name="motif_annulation"')
        self.assertContains(
            reponse,
            reverse(
                'paiements:annuler_paiement',
                kwargs={'paiement_id': self.paiement.id},
            ),
        )

    def test_le_bouton_disparait_une_fois_le_paiement_annule(self):
        self._annuler()

        reponse = self._detail()

        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, 'id="annulationModal"')

    def test_l_annulation_exige_une_requete_post(self):
        reponse = self.client.get(
            reverse(
                'paiements:annuler_paiement',
                kwargs={'paiement_id': self.paiement.id},
            )
        )

        self.assertEqual(reponse.status_code, 405)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.statut, 'VALIDE')
