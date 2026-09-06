from datetime import date
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.forms.models import model_to_dict
from django.test import RequestFactory, TestCase, override_settings

from administration.corbeille import archiver_avant_suppression
from administration.models import ObjetSupprime
from eleves.models import Eleve, GrilleTarifaire
from paiements.admin import PaiementAdmin, PaiementAdminForm, RemiseReductionAdmin
from paiements.models import EcheancierPaiement, Paiement, PaiementRemise, RemiseReduction, TypePaiement
from . import test_modification_montant as support
from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class AuditRecalculAdminTests(TestCase):
    setUp = support.ModificationMontantTest.setUp

    def preparer(self):
        self.echeancier = self.eleve.echeanciers.get()
        self.paiement.montant = Decimal('200000')
        self.paiement.statut = 'VALIDE'
        self.paiement.save()
        self.remise = RemiseReduction.objects.create(
            nom='Réduction audit', type_remise='MONTANT_FIXE', valeur=100000,
            motif='AUTRE', date_debut=date(2025, 1, 1), date_fin=date(2027, 1, 1),
        )
        self.ligne = PaiementRemise.objects.create(
            paiement=self.paiement, remise=self.remise, montant_remise=100000, portee_tranches='1',
        )
        self.request = RequestFactory().post('/')
        self.request.user = self.user

    def test_restauration_catalogue_remise_recalcule_cumuls(self):
        self.preparer()
        RemiseReductionAdmin(RemiseReduction, AdminSite()).delete_model(self.request, self.remise)
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 200000)
        archive = ObjetSupprime.objects.get(model_label='paiements.remisereduction')
        self.assertTrue(archive.restaurer())
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 300000)
        self.assertEqual(self.echeancier.solde_restant, 950000)
        self.assertFalse(archive.restaurer())

    def test_restauration_ligne_remise_recalcule_cumuls(self):
        self.preparer()
        archive = archiver_avant_suppression(self.ligne, self.user)
        self.ligne.delete()
        archive.restaurer()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 300000)

    def test_admin_suppression_paiement_et_restauration_avec_remise(self):
        self.preparer()
        PaiementAdmin(Paiement, AdminSite()).delete_model(self.request, self.paiement)
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 0)
        archive = ObjetSupprime.objects.get(model_label='paiements.paiement')
        archive.restaurer()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 300000)
        self.assertEqual(self.echeancier.solde_restant, 950000)

    def test_modification_eleve_recalcule_les_deux_dossiers(self):
        self.preparer()
        autre = Eleve.objects.create(nom='Autre', prenom='Élève', matricule='AUDIT-AUTRE', sexe='F', classe=self.classe)
        valeurs = {field: getattr(self.echeancier, field) for field in (
            'annee_scolaire', 'frais_inscription_du', 'tranche_1_due', 'tranche_2_due', 'tranche_3_due',
            'date_echeance_inscription', 'date_echeance_tranche_1', 'date_echeance_tranche_2', 'date_echeance_tranche_3',
        )}
        cible = EcheancierPaiement.objects.create(eleve=autre, **valeurs)
        self.paiement.eleve = autre
        PaiementAdmin(Paiement, AdminSite()).save_model(self.request, self.paiement, None, True)
        self.echeancier.refresh_from_db(); cible.refresh_from_db()
        self.assertEqual(self.echeancier.total_paye, 0)
        self.assertEqual(cible.total_paye, 300000)

    def preparer_admission(self):
        self.preparer()
        self.grille = GrilleTarifaire.objects.create(
            ecole=self.ecole, niveau=self.classe.niveau, annee_scolaire='2025-2026',
            frais_inscription=50000, frais_reinscription=30000,
            tranche_1=500000, tranche_2=400000, tranche_3=300000,
        )
        self.inscription = TypePaiement.objects.create(nom='Inscription + Annuel')
        self.reinscription = TypePaiement.objects.create(nom='Réinscription + Annuel')
        self.paiement.type_paiement = self.inscription
        self.paiement.montant = Decimal('1130000')
        self.paiement.save()
        self.ligne.montant_remise = 120000
        self.ligne.deduite_du_paiement = True
        self.ligne.portee_tranches = '1,2,3'
        self.ligne.save()

    def formulaire_admin(self, type_paiement):
        donnees = model_to_dict(self.paiement)
        donnees.update(type_paiement=type_paiement.pk, date_paiement='2026-08-04')
        return PaiementAdminForm(data=donnees, instance=self.paiement)

    def test_admin_reinscription_avec_remise_et_retour_inscription(self):
        self.preparer_admission()
        administration = PaiementAdmin(Paiement, AdminSite())
        for type_paiement, net, frais in (
            (self.reinscription, 1110000, 30000),
            (self.inscription, 1130000, 50000),
        ):
            form = self.formulaire_admin(type_paiement)
            self.assertTrue(form.is_valid(), form.errors)
            administration.save_model(self.request, form.save(commit=False), form, True)
            self.paiement.refresh_from_db()
            self.echeancier.refresh_from_db()
            self.ligne.refresh_from_db()
            self.assertEqual(self.paiement.montant, net)
            self.assertEqual(self.ligne.montant_remise, 120000)
            self.assertEqual(self.echeancier.frais_inscription_du, frais)
            self.assertEqual(self.echeancier.solde_restant, 0)
            self.assertEqual(self.echeancier.statut, 'PAYE_COMPLET')

    def test_admin_grille_absente_refuse_correction_sans_ecriture(self):
        self.preparer_admission()
        self.grille.delete()
        form = self.formulaire_admin(self.reinscription)
        self.assertFalse(form.is_valid())
        self.assertIn('grille tarifaire', str(form.non_field_errors()))
        self.paiement.refresh_from_db()
        self.echeancier.refresh_from_db()
        self.assertEqual(self.paiement.type_paiement, self.inscription)
        self.assertEqual(self.paiement.montant, 1130000)
        self.assertEqual(self.echeancier.frais_inscription_du, 50000)
