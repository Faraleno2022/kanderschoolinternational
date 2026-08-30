from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from administration.models import ObjetSupprime
from eleves.models import Classe, Ecole, Eleve
from paiements.models import (
    EcheancierPaiement, HistoriqueModificationPaiement,
    ModePaiement, Paiement, TypePaiement,
)
from paiements.views import _compute_stats
from utilisateurs.models import Profil

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class AuditOperationsDashboardTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.school = Ecole.objects.create(
            nom='École audit caisse', adresse='Conakry',
            telephone='+224620006001', directeur='Direction', etat='VALIDE',
        )
        self.classe = Classe.objects.create(
            ecole=self.school, nom='3ème A', niveau='PRIMAIRE_3',
            annee_scolaire=f'{self.today.year}-{self.today.year + 1}',
        )
        self.student = Eleve.objects.create(
            matricule='AUD-001', prenom='Audit', nom='Élève',
            sexe='F', classe=self.classe,
        )
        self.schedule = EcheancierPaiement.objects.create(
            eleve=self.student, annee_scolaire=self.classe.annee_scolaire,
            ecole_reference=self.school, classe_reference=self.classe,
            frais_inscription_du=0, tranche_1_due=Decimal('500000'),
            tranche_2_due=0, tranche_3_due=0,
            tranche_1_payee=Decimal('500000'), statut='PAYE_COMPLET',
            date_echeance_inscription=self.today - timedelta(days=60),
            date_echeance_tranche_1=self.today - timedelta(days=30),
            date_echeance_tranche_2=self.today + timedelta(days=60),
            date_echeance_tranche_3=self.today + timedelta(days=120),
        )
        self.payment_type = TypePaiement.objects.create(nom='Scolarité - 1ère tranche audit')
        self.mode = ModePaiement.objects.create(nom='Espèces audit')
        self.payment = Paiement.objects.create(
            eleve=self.student, type_paiement=self.payment_type,
            mode_paiement=self.mode, montant=Decimal('500000'),
            date_paiement=self.today, statut='VALIDE',
        )
        self.admin = get_user_model().objects.create_superuser(
            'admin_audit_caisse', 'audit@example.com', 'pass12345',
        )
        self.client.force_login(self.admin)

    def _modify(self, amount='300000', reason='Correction après contrôle de caisse'):
        return self.client.post(
            reverse('paiements:modifier_paiement', args=[self.payment.pk]),
            {
                'type_paiement': self.payment_type.pk,
                'mode_paiement': self.mode.pk,
                'montant': amount,
                'date_paiement': self.today.isoformat(),
                'reference_externe': '', 'observations': '',
                'motif_modification': reason,
            },
        )

    def test_modification_et_suppression_recalculent_toutes_les_cartes(self):
        self._modify()
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.tranche_1_payee, Decimal('300000'))

        modified_stats = _compute_stats(self.admin)
        self.assertEqual(modified_stats['total_paiements_mois'], 300000)
        self.assertEqual(modified_stats['categories']['scolarite']['today'], 300000)
        self.assertEqual(modified_stats['operations']['today']['montant_modifie'], 200000)
        self.assertEqual(modified_stats['operations']['today']['nombre_modifications'], 1)
        self.assertEqual(modified_stats['operations']['today']['impact_net'], -200000)

        number = self.payment.numero_recu
        response = self.client.post(
            reverse('paiements:supprimer_paiement', args=[self.payment.pk]),
            {'motif_suppression': 'Doublon confirmé dans le journal de caisse'},
        )
        self.assertEqual(response.status_code, 302)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.tranche_1_payee, Decimal('0'))

        deleted_stats = _compute_stats(self.admin)
        self.assertEqual(deleted_stats['total_paiements_mois'], 0)
        self.assertEqual(deleted_stats['categories']['scolarite']['today'], 0)
        self.assertEqual(deleted_stats['operations']['today']['montant_supprime'], 300000)
        self.assertEqual(deleted_stats['operations']['today']['nombre_suppressions'], 1)
        self.assertEqual(deleted_stats['operations']['today']['impact_net'], -500000)

        history = self.client.get(reverse('paiements:historique_operations'))
        self.assertContains(history, number)
        self.assertContains(history, 'Correction après contrôle de caisse')
        self.assertContains(history, 'Doublon confirmé dans le journal de caisse')
        self.assertContains(history, 'Suppression')

    def test_suppression_admin_et_restauration_recalculent_echeancier(self):
        delete_url = reverse('admin:paiements_paiement_delete', args=[self.payment.pk])
        response = self.client.post(delete_url, {'post': 'yes'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.tranche_1_payee, Decimal('0'))
        self.assertTrue(
            HistoriqueModificationPaiement.objects.filter(
                numero_recu=self.payment.numero_recu,
                motif__icontains='administration Django',
            ).exists()
        )

        archive = ObjetSupprime.objects.get(model_label='paiements.paiement')
        self.assertTrue(archive.restaurer())
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.tranche_1_payee, Decimal('500000'))

    def test_tableau_de_bord_affiche_la_carte_et_le_bouton_registre(self):
        self._modify(reason='Montant corrigé pour test affichage')
        response = self.client.get(reverse('paiements:tableau_bord'))
        self.assertContains(response, 'Montants corrigés, annulés et supprimés')
        self.assertContains(response, reverse('paiements:historique_operations'))

    def test_registre_reste_visible_a_l_ecole_apres_suppression(self):
        self._modify(reason='Correction visible uniquement dans cette école')
        self.client.post(
            reverse('paiements:supprimer_paiement', args=[self.payment.pk]),
            {'motif_suppression': 'Suppression vérifiée pour cette école'},
        )
        school_user = get_user_model().objects.create_user(
            'comptable_audit_ecole', password='pass12345',
        )
        Profil.objects.update_or_create(
            user=school_user,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.school,
                'telephone': '+224620006002', 'is_validated': True,
            },
        )
        school_user.refresh_from_db()
        self.client.force_login(school_user)

        response = self.client.get(
            reverse('paiements:historique_operations'),
            {'operation': 'SUPPRESSION'},
        )
        self.assertContains(response, 'Suppression vérifiée pour cette école')
        stats = _compute_stats(school_user)
        self.assertEqual(stats['operations']['today']['montant_supprime'], 300000)
