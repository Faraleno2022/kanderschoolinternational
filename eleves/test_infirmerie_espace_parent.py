from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from notes.bulletin_public import verifier_token_bulletin
from notes.models import ActiviteJournaliere, ClasseNote, MatiereNote, NoteMensuelle
from notes.rapport_scolaire import _make_token
from paiements.models import ModePaiement, Paiement, TypePaiement
from paiements.tests.support import TEST_MIDDLEWARE

from .models import Classe, Ecole, Eleve, Responsable, VisiteMedicale


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class InfirmerieListeElevesTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École santé', adresse='Conakry', telephone='+224620004001',
            directeur='Direction santé', etat='VALIDE',
        )
        self.autre_ecole = Ecole.objects.create(
            nom='Autre école santé', adresse='Conakry', telephone='+224620004002',
            directeur='Autre direction', etat='VALIDE',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='2ème année A', niveau='PRIMAIRE_2',
            annee_scolaire='2026-2027',
        )
        autre_classe = Classe.objects.create(
            ecole=self.autre_ecole, nom='2ème année B', niveau='PRIMAIRE_2',
            annee_scolaire='2026-2027',
        )
        self.eleve = Eleve.objects.create(
            matricule='SAN-001', prenom='Aminata', nom='Diallo', sexe='F',
            classe=self.classe,
        )
        self.eleve_externe = Eleve.objects.create(
            matricule='SAN-EXT', prenom='Élève', nom='Externe', sexe='M',
            classe=autre_classe,
        )
        self.user = User.objects.create_user('infirmiere', password='secret')
        self.user.profil.role = 'ADMIN'
        self.user.profil.telephone = '+224620004003'
        self.user.profil.ecole = self.ecole
        self.user.profil.is_validated = True
        self.user.profil.save()
        self.client.force_login(self.user)

    def test_liste_affiche_tous_les_eleves_de_lecole_sans_recherche(self):
        visite = VisiteMedicale.objects.create(
            eleve=self.eleve,
            date_visite=timezone.now(),
            motif='Contrôle du matin',
            statut='RETOUR_CLASSE',
            cree_par=self.user,
        )

        response = self.client.get(reverse('eleves:infirmerie'))

        self.assertEqual(response.status_code, 200)
        eleves = list(response.context['page_eleves'].object_list)
        self.assertEqual(eleves, [self.eleve])
        self.assertEqual(eleves[0].visites_du_jour, [visite])
        self.assertContains(response, self.eleve.matricule)
        self.assertContains(response, "Noter l'état de santé")
        self.assertNotContains(response, self.eleve_externe.matricule)

    def test_ajout_note_de_sante_depuis_la_liste(self):
        response = self.client.post(
            reverse('eleves:ajouter_visite', args=[self.eleve.pk]),
            {
                'date_visite': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
                'motif': 'Fatigue durant la journée',
                'temperature': '37.2',
                'symptomes': 'Fatigue légère',
                'soins': 'Repos et hydratation',
                'statut': 'RETOUR_CLASSE',
                'parent_contacte': 'on',
                'observations': 'État amélioré après le repos',
            },
        )

        self.assertRedirects(response, reverse('eleves:sante_eleve', args=[self.eleve.pk]))
        visite = VisiteMedicale.objects.get(eleve=self.eleve)
        self.assertEqual(visite.motif, 'Fatigue durant la journée')
        self.assertTrue(visite.parent_contacte)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class EspaceParentSanteDocumentsTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École portail parent', adresse='Conakry',
            telephone='+224620004101', directeur='Direction parents', etat='VALIDE',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='3ème année A', niveau='PRIMAIRE_3',
            annee_scolaire='2026-2027',
        )
        self.responsable = Responsable.objects.create(
            prenom='Mamadou', nom='Bah', relation='PERE',
            telephone='+224620004102', adresse='Conakry',
        )
        self.eleve = Eleve.objects.create(
            matricule='PAR-001', prenom='Fatou', nom='Bah', sexe='F',
            date_naissance=date(2017, 3, 12), classe=self.classe,
            responsable_principal=self.responsable,
        )
        self.classe_note = ClasseNote.objects.create(
            ecole=self.ecole, nom=self.classe.nom, niveau='PRIMAIRE_3',
            niveau_enseignement='PRIMAIRE', annee_scolaire='2026-2027',
        )
        self.matiere = MatiereNote.objects.create(
            classe=self.classe_note, nom='Français', code='FR', coefficient=1,
        )
        NoteMensuelle.objects.create(
            eleve=self.eleve, matiere=self.matiere, mois='OCTOBRE',
            annee_scolaire='2026-2027', note=Decimal('15'),
        )
        self.user = User.objects.create_user('personnel-parent', password='secret')
        ActiviteJournaliere.objects.create(
            classe=self.classe_note, eleve=self.eleve, date=date(2026, 9, 3),
            type_activite='CULTURELLE', titre='Atelier de lecture',
            description='Lecture collective', appreciation='Très bonne participation',
            cree_par=self.user,
        )
        VisiteMedicale.objects.create(
            eleve=self.eleve, date_visite=timezone.now(), motif='Fièvre légère',
            temperature=Decimal('37.8'), symptomes='Maux de tête',
            soins='Repos et eau', statut='RETOUR_CLASSE',
            parent_contacte=True, cree_par=self.user,
        )
        type_paiement = TypePaiement.objects.create(nom='Tranche portail parent')
        mode_paiement = ModePaiement.objects.create(nom='Espèces portail parent')
        self.paiement = Paiement.objects.create(
            eleve=self.eleve, type_paiement=type_paiement,
            mode_paiement=mode_paiement, montant=Decimal('250000'),
            date_paiement=date(2026, 9, 2), statut='VALIDE',
            cree_par=self.user, valide_par=self.user,
        )
        self.token = _make_token(self.eleve.pk)

    def test_portail_parent_affiche_sante_activites_et_documents(self):
        response = self.client.get(
            reverse('rapport_scolaire_detail'),
            {'token': self.token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fièvre légère')
        self.assertContains(response, 'Repos et eau')
        self.assertContains(response, 'Atelier de lecture')
        self.assertContains(response, 'Bulletins de notes')
        self.assertContains(response, 'Octobre')
        self.assertContains(response, 'Télécharger le carnet de paiement')

        bulletin = response.context['bulletins_disponibles'][0]
        parsed = urlparse(bulletin['url'])
        bulletin_token = parse_qs(parsed.query)['token'][0]
        self.assertTrue(verifier_token_bulletin(
            self.eleve.pk, self.classe_note.pk, 'OCTOBRE', bulletin_token,
        ))

        bulletin_pdf = self.client.get(bulletin['url'])
        self.assertEqual(bulletin_pdf.status_code, 200)
        self.assertEqual(bulletin_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(bulletin_pdf.content.startswith(b'%PDF'))

        rapport_pdf = self.client.get(
            reverse('rapport_scolaire_pdf'),
            {'token': self.token},
        )
        self.assertEqual(rapport_pdf.status_code, 200)
        self.assertEqual(rapport_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(rapport_pdf.content.startswith(b'%PDF'))

    def test_parent_peut_telecharger_le_carnet_sans_connexion(self):
        response = self.client.get(
            reverse('rapport_scolaire_carnet_pdf'),
            {'token': self.token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('Carnet_paiement_PAR-001_2026-2027.pdf', response['Content-Disposition'])

    def test_jeton_invalide_ne_divulgue_aucune_donnee(self):
        response = self.client.get(
            reverse('rapport_scolaire_detail'),
            {'token': 'jeton-invalide'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lien expiré ou invalide')
        self.assertNotContains(response, self.eleve.matricule)
        self.assertNotContains(response, 'Fièvre légère')


