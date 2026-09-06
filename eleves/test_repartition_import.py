from datetime import date
from decimal import Decimal
from io import BytesIO

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.import_eleves import ImportElevesProcessor
from eleves.models import Classe, Ecole, Eleve, GrilleTarifaire
from paiements.forms import PaiementForm
from paiements.models import Paiement, TypePaiement, ModePaiement
from paiements.tests.support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class RepartitionImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('repartition', 'test@example.com', 'test')
        self.ecole = Ecole.objects.create(nom='École répartition', adresse='Conakry', telephone='620000001', directeur='Direction')
        self.classe = self.creer_classe('Petite section A')
        self.classe_b = self.creer_classe('Petite section B')
        self.classe_c = self.creer_classe('Petite section (C)')
        self.grande = self.creer_classe('Grande section A')
        self.autre_annee = self.creer_classe('Petite section D', annee='2027-2028')
        self.autre_ecole = Ecole.objects.create(nom='Autre école', adresse='Conakry', telephone='620000002', directeur='Direction')
        self.externe = self.creer_classe('Petite section E', ecole=self.autre_ecole)
        self.eleve = Eleve.objects.create(matricule='IMPORT-001', prenom='Aminata', nom='Bah', sexe='F',
                                         classe=self.classe, statut='ATTENTE_PAIEMENT')
        self.grille = GrilleTarifaire.objects.create(ecole=self.ecole, niveau='MATERNELLE', annee_scolaire='2026-2027',
                                                    frais_inscription=50000, frais_reinscription=30000,
                                                    tranche_1=100000, tranche_2=100000, tranche_3=100000)
        self.type_paiement = TypePaiement.objects.create(nom='Inscription')
        self.mode = ModePaiement.objects.create(nom='Espèces')
        self.url = reverse('eleves:repartir_eleves')
        self.client.force_login(self.user)

    def creer_classe(self, nom, annee='2026-2027', ecole=None):
        return Classe.objects.create(nom=nom, niveau='MATERNELLE', ecole=ecole or self.ecole, annee_scolaire=annee)

    def payer(self, **extra):
        data = dict(eleve=self.eleve, type_paiement=self.type_paiement, mode_paiement=self.mode,
                    montant=Decimal('50000'), date_paiement=date(2026, 9, 6), statut='EN_ATTENTE')
        data.update(extra)
        return Paiement.objects.create(**data)

    def test_liste_limitee_aux_sections_equivalentes(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        eleve = list(response.context['page_obj'])[0]
        self.assertEqual({c.pk for c in eleve.sections_disponibles}, {self.classe.pk, self.classe_b.pk, self.classe_c.pk})
        self.assertContains(response, 'Affecter et faire le premier paiement')

    def test_affecter_puis_payer_conserve_matricule_et_attente(self):
        response = self.client.post(self.url, {'eleve_id': self.eleve.pk, 'classe_id': self.classe_b.pk, 'action': 'payer'})
        self.assertRedirects(response, reverse('paiements:ajouter_paiement_eleve', args=[self.eleve.pk]))
        self.eleve.refresh_from_db()
        self.assertEqual(self.eleve.classe_id, self.classe_b.pk)
        self.assertEqual(self.eleve.matricule, 'IMPORT-001')
        self.assertEqual(self.eleve.statut, 'ATTENTE_PAIEMENT')
        self.assertEqual(self.eleve.echeanciers.get().classe_reference_id, self.classe_b.pk)

    def test_autre_niveau_annee_refuses(self):
        for cible in (self.grande, self.autre_annee, self.externe):
            with self.subTest(cible=cible.nom):
                self.client.post(self.url, {'eleve_id': self.eleve.pk, 'classe_id': cible.pk})
                self.eleve.refresh_from_db()
                self.assertEqual(self.eleve.classe_id, self.classe.pk)

    def test_premier_paiement_valide_active_dossier(self):
        paiement = self.payer()
        self.eleve.refresh_from_db()
        self.assertEqual(self.eleve.statut, 'ATTENTE_PAIEMENT')
        paiement.statut = 'VALIDE'
        paiement.save()
        self.eleve.refresh_from_db()
        self.assertEqual(self.eleve.statut, 'ACTIF')

    def test_paiement_zero_ancien_ou_autre_ecole_nactive_pas(self):
        for extra in ({'montant': 0}, {'annee_scolaire': '2025-2026'}, {'ecole_encaissement': self.autre_ecole}):
            self.payer(statut='VALIDE', **extra)
            self.eleve.refresh_from_db()
            self.assertEqual(self.eleve.statut, 'ATTENTE_PAIEMENT')

    def test_paiement_ne_reactive_pas_suspendu(self):
        self.eleve.statut = 'SUSPENDU'
        self.eleve.save()
        self.payer(statut='VALIDE')
        self.eleve.refresh_from_db()
        self.assertEqual(self.eleve.statut, 'SUSPENDU')

    def test_formulaire_paiement_accepte_eleve_en_attente(self):
        form = PaiementForm({'eleve': self.eleve.pk, 'type_paiement': self.type_paiement.pk,
                             'mode_paiement': self.mode.pk, 'montant': '50000', 'date_paiement': '2026-09-06'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_import_reel_redirige_vers_lot_et_nactive_pas(self):
        fichier = BytesIO()
        pd.DataFrame([{'Prénom': 'Nouveau', 'Nom': 'Diallo', 'Sexe': 'M'}]).to_excel(fichier, index=False)
        response = self.client.post(reverse('eleves:importer_eleves'), {
            'classe_id': self.classe.pk, 'generer_matricules': 'on',
            'fichier': SimpleUploadedFile('eleves.xlsx', fichier.getvalue()),
        })
        self.assertRedirects(response, self.url + '?lot=dernier')
        nouveau = Eleve.objects.get(prenom='Nouveau')
        self.assertEqual(nouveau.statut, 'ATTENTE_PAIEMENT')
        self.assertEqual(self.client.session['derniers_eleves_importes'], [nouveau.pk])
        response = self.client.get(self.url + '?lot=dernier')
        self.assertEqual([e.pk for e in response.context['page_obj']], [nouveau.pk])

    def test_reimport_conserve_statut(self):
        for statut in ['ACTIF', 'ATTENTE_PAIEMENT', 'SUSPENDU']:
            self.eleve.statut = statut
            self.eleve.save()
            processor = ImportElevesProcessor(pd.DataFrame([{'Prénom': 'Aminata', 'Nom': 'Bah', 'Sexe': 'F'}]), self.classe.pk)
            processor.importer()
            self.eleve.refresh_from_db()
            self.assertEqual(self.eleve.statut, statut)
            self.assertEqual(processor.eleves_importes, [self.eleve.pk])

    def test_isolation_ecole(self):
        user = get_user_model().objects.create_user('comptable-repartition', password='test')
        profil = user.profil
        profil.role = 'COMPTABLE'; profil.ecole = self.ecole; profil.is_validated = True
        profil.save()
        self.client.force_login(user)
        response = self.client.post(self.url, {'eleve_id': self.eleve.pk, 'classe_id': self.externe.pk})
        self.assertEqual(response.status_code, 404)
        eleve_externe = Eleve.objects.create(matricule='EXTERNE', prenom='Autre', nom='École', sexe='M', classe=self.externe, statut='ATTENTE_PAIEMENT')
        response = self.client.get(self.url)
        self.assertNotIn(eleve_externe.pk, [e.pk for e in response.context['page_obj']])
        response = self.client.post(self.url, {'eleve_id': eleve_externe.pk, 'classe_id': self.classe_b.pk})
        self.assertEqual(response.status_code, 404)

    def test_permission_et_identifiants_invalides(self):
        self.assertEqual(self.client.post(self.url, {'eleve_id': 'x', 'classe_id': self.classe.pk}).status_code, 400)
        user = get_user_model().objects.create_user('sans-droit', password='test')
        user.profil.role = 'ENSEIGNANT'
        user.profil.peut_importer_eleves = False
        user.profil.save()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_parcours_paiement_puis_validation(self):
        from unittest.mock import patch
        response = self.client.post(reverse('paiements:ajouter_paiement_eleve', args=[self.eleve.pk]), {
            'eleve': self.eleve.pk, 'type_paiement': self.type_paiement.pk,
            'mode_paiement': self.mode.pk, 'montant': '50000', 'date_paiement': '2026-09-06',
        })
        self.assertEqual(response.status_code, 302)
        paiement = Paiement.objects.get(eleve=self.eleve)
        self.eleve.refresh_from_db()
        self.assertEqual(self.eleve.statut, 'ATTENTE_PAIEMENT')
        with patch('paiements.views.send_payment_receipt'):
            response = self.client.post(reverse('paiements:valider_paiement', args=[paiement.pk]))
        self.assertEqual(response.status_code, 302)
        self.eleve.refresh_from_db()
        self.assertEqual(self.eleve.statut, 'ACTIF')

    def test_repartition_section_b_conserve_dossier_solde_avec_remise(self):
        from paiements.models import EcheancierPaiement, PaiementRemise, RemiseReduction
        echeancier = EcheancierPaiement.objects.create(
            eleve=self.eleve, annee_scolaire='2026-2027',
            frais_inscription_du=50000, tranche_1_due=100000,
            tranche_2_due=100000, tranche_3_due=100000,
            date_echeance_inscription=date(2026, 9, 1),
            date_echeance_tranche_1=date(2027, 1, 15),
            date_echeance_tranche_2=date(2027, 3, 15),
            date_echeance_tranche_3=date(2027, 5, 15),
        )
        paiement = self.payer(montant=300000, statut='VALIDE')
        remise = RemiseReduction.objects.create(
            nom='Remise section', type_remise='MONTANT_FIXE', valeur=50000,
            motif='AUTRE', date_debut=date(2026, 9, 1), date_fin=date(2027, 7, 1),
        )
        PaiementRemise.objects.create(paiement=paiement, remise=remise, montant_remise=50000, portee_tranches='1')
        response = self.client.post(self.url, {'eleve_id': self.eleve.pk, 'classe_id': self.classe_b.pk})
        self.assertRedirects(response, self.url)
        self.eleve.refresh_from_db()
        echeancier.refresh_from_db()
        self.assertEqual(self.eleve.classe, self.classe_b)
        self.assertEqual(self.eleve.matricule, 'IMPORT-001')
        self.assertEqual(self.eleve.statut, 'ACTIF')
        self.assertEqual(echeancier.classe_reference, self.classe_b)
        self.assertEqual(echeancier.total_paye, 350000)
        self.assertEqual(echeancier.solde_restant, 0)
        self.assertEqual(echeancier.statut, 'PAYE_COMPLET')
