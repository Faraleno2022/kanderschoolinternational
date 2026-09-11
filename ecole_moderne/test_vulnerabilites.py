"""Tests HTTP de sécurité sur des écoles et comptes fictifs."""
from datetime import date
from io import BytesIO
from unittest.mock import patch
from django.http import HttpResponse
from django.test import SimpleTestCase

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from abonnements.models import AbonnementCantine, PresenceCantine
from eleves.models import Classe, Ecole, Eleve
from notes.models import BulletinMaternelle, ClasseNote, MatiereNote, AppreciationMaternelle, NoteMensuelle, EvaluationMaternelle
from salaires.forms import EnseignantForm
from salaires.models import Enseignant, PeriodeSalaire
from synchronisation.models import SyncDevice

MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]


@override_settings(MIDDLEWARE=MIDDLEWARE)
class VulnerabilitesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.ecole = Ecole.objects.create(nom='Ecole autorisee', etat='VALIDE')
        self.autre = Ecole.objects.create(nom='Ecole confidentielle', etat='VALIDE')
        self.user = User.objects.create_user('audit-securite', password='audit-only-password')
        self.user.profil.ecole = self.ecole
        self.user.profil.role = 'ADMIN'
        self.user.profil.telephone = '+224600000001'
        self.user.profil.is_validated = True
        self.user.profil.save()
        self.client.force_login(self.user)
        self.classe = Classe.objects.create(ecole=self.ecole, nom='Petite section A', niveau='MATERNELLE_PS', annee_scolaire='2026-2027')
        self.classe_autre = Classe.objects.create(ecole=self.autre, nom='Petite section CONFIDENTIELLE', niveau='MATERNELLE_PS', annee_scolaire='2026-2027')
        self.cn = ClasseNote.objects.create(ecole=self.ecole, nom=self.classe.nom, niveau=self.classe.niveau, annee_scolaire='2026-2027')
        self.cn_autre = ClasseNote.objects.create(ecole=self.autre, nom=self.classe_autre.nom, niveau=self.classe_autre.niveau, annee_scolaire='2026-2027')
        self.eleve = Eleve.objects.create(classe=self.classe, matricule='SEC-001', prenom='Local', nom='Test', sexe='F', statut='ACTIF')
        self.eleve_autre = Eleve.objects.create(classe=self.classe_autre, matricule='SECRET-002', prenom='Externe', nom='Test', sexe='M', statut='ACTIF')
        self.enseignant = Enseignant.objects.create(ecole=self.ecole, nom='SALARIE LOCAL', prenoms='Test', type_enseignant='CHAUFFEUR', salaire_fixe=100000, date_embauche=date(2025, 1, 1))
        self.enseignant_autre = Enseignant.objects.create(ecole=self.autre, nom='SALARIE CONFIDENTIEL', prenoms='Test', type_enseignant='CHAUFFEUR', salaire_fixe=200000, date_embauche=date(2025, 1, 1))
        self.abonnement = AbonnementCantine.objects.create(eleve=self.eleve_autre, duree='MENSUEL', date_debut=date(2026, 9, 1), date_fin=date(2026, 9, 30), montant=10000)

    def sans_ecole(self):
        self.user.profil.ecole = None
        self.user.profil.save()

    def test_liste_et_csv_salaires_isolent_admin_ecole(self):
        for name in ('liste_enseignants', 'export_enseignants_csv'):
            with self.subTest(page=name):
                response = self.client.get(reverse('salaires:' + name))
                self.assertContains(response, self.enseignant.nom)
                self.assertNotContains(response, self.enseignant_autre.nom)

    def test_salaire_sans_ecole_ne_divulgue_rien(self):
        self.sans_ecole()
        response = self.client.get(reverse('salaires:export_enseignants_csv'))
        self.assertNotIn(self.enseignant_autre.nom.encode(), response.content)
        self.assertNotIn(self.enseignant.nom.encode(), response.content)

    def test_statut_salarie_externe_inchange(self):
        response = self.client.post(reverse('salaires:changer_statut_enseignant', args=[self.enseignant_autre.pk]), {'nouveau_statut': 'SUSPENDU'})
        self.enseignant_autre.refresh_from_db()
        self.assertEqual(self.enseignant_autre.statut, 'ACTIF')
        self.assertIn(response.status_code, (403, 404))

    def test_statut_salarie_local_modifiable(self):
        response = self.client.post(reverse('salaires:changer_statut_enseignant', args=[self.enseignant.pk]), {'nouveau_statut': 'CONGE'})
        self.enseignant.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.enseignant.statut, 'CONGE')

    def test_formulaire_enseignant_refuse_ecole_falsifiee(self):
        form = EnseignantForm({'nom': 'Falsifie', 'prenoms': 'Test', 'ecole': self.autre.pk, 'type_enseignant': 'CHAUFFEUR', 'statut': 'ACTIF', 'salaire_fixe': '100000', 'date_embauche': '2025-01-01'}, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('ecole', form.errors)
        self.assertNotIn(self.autre, form.fields['ecole'].queryset)

    def test_formulaire_sans_ecole_ne_propose_aucune_ecole(self):
        self.sans_ecole()
        self.assertFalse(EnseignantForm(user=self.user).fields['ecole'].queryset.exists())

    def test_superadministrateur_conserve_acces_global(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse('salaires:export_enseignants_csv'))
        self.assertContains(response, self.enseignant_autre.nom)

    def test_creation_periode_externe_refusee(self):
        self.client.post(reverse('salaires:creer_periode'), {'ecole': self.autre.pk, 'mois': '9', 'annee': '2026'})
        self.assertFalse(PeriodeSalaire.objects.filter(ecole=self.autre).exists())

    def test_export_paiements_excel_ne_divulgue_pas_autre_ecole(self):
        response = self.client.get(reverse('paiements:export_tranches_par_classe_excel'), {'annee_scolaire': '2026-2027'})
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        valeurs = ' '.join(str(v) for sheet in workbook for row in sheet.values for v in row)
        self.assertNotIn(self.classe_autre.nom, valeurs)
        self.assertIn(self.classe.nom, valeurs)

    def test_bulletin_externe_non_modifiable(self):
        response = self.client.post(reverse('notes:saisie_bulletin_maternelle', args=[self.eleve_autre.pk, self.cn_autre.pk, 'TRIMESTRE_1']), {'appreciation_generale': 'Injection inter-ecoles'})
        self.assertFalse(BulletinMaternelle.objects.filter(eleve=self.eleve_autre).exists())
        self.assertIn(response.status_code, (403, 404))

    def test_bulletin_classe_externe_refusee(self):
        response = self.client.get(reverse('notes:bulletin_maternelle_v2', args=[self.eleve.pk, self.cn_autre.pk, 'TRIMESTRE_1']))
        self.assertIn(response.status_code, (403, 404))

    def test_bulletin_get_ne_cree_aucun_dossier(self):
        response = self.client.get(reverse('notes:saisie_bulletin_maternelle', args=[self.eleve.pk, self.cn.pk, 'TRIMESTRE_1']))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BulletinMaternelle.objects.exists())

    def test_bulletin_local_enregistrable(self):
        response = self.client.post(reverse('notes:saisie_bulletin_maternelle', args=[self.eleve.pk, self.cn.pk, 'TRIMESTRE_1']), {'appreciation_generale': 'Progres'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BulletinMaternelle.objects.get(eleve=self.eleve).appreciation_generale, 'Progres')

    def test_abonnement_externe_non_visible(self):
        # Ce module conserve des routes de service mais ses anciens templates
        # ne sont pas distribués : vérifier le contexte effectivement préparé.
        with patch('abonnements.views.render', return_value=HttpResponse()) as render:
            response = self.client.get(reverse('abonnements:liste_cantine'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.abonnement, render.call_args.args[2]['abonnements'])

    def test_presence_cantine_externe_non_modifiable(self):
        response = self.client.post(reverse('abonnements:enregistrer_presence'), {'abonnement_id': self.abonnement.pk, 'date': '2026-09-09', 'present': 'true'})
        self.assertFalse(PresenceCantine.objects.exists())
        self.assertIn(response.status_code, (403, 404))

    def test_presence_cantine_sans_ecole_refusee(self):
        self.sans_ecole()
        self.test_presence_cantine_externe_non_modifiable()

    def test_sync_session_sans_csrf_refusee(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse('synchronisation:register_device'), {'nom': 'Requete tierce'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SyncDevice.objects.exists())

    def test_sync_session_avec_csrf_acceptee(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        token = 'a' * 32
        client.cookies['csrftoken'] = token
        response = client.post(reverse('synchronisation:register_device'), {'nom': 'Poste autorise'}, content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(SyncDevice.objects.get().ecole_id, self.ecole.pk)

    @override_settings(MYSCHOOL_SYNC_ADMIN_TOKEN='test-only-sync-token')
    def test_sync_jeton_machine_sans_session_accepte(self):
        response = Client(enforce_csrf_checks=True).post(reverse('synchronisation:register_device'), {'nom': 'Machine', 'ecole_id': self.ecole.pk}, content_type='application/json', HTTP_X_SYNC_ADMIN_TOKEN='test-only-sync-token')
        self.assertEqual(response.status_code, 201)

    @override_settings(MYSCHOOL_SYNC_ADMIN_TOKEN='test-only-sync-token')
    def test_sync_json_non_objet_refuse_sans_erreur_500(self):
        response = Client(enforce_csrf_checks=True).post(reverse('synchronisation:register_device'), [], content_type='application/json', HTTP_X_SYNC_ADMIN_TOKEN='test-only-sync-token')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SyncDevice.objects.exists())

    def test_verification_telephone_refuse_redirection_externe(self):
        for target in ('//evil.example/path', '/\\evil.example/path', '///evil.example/path'):
            with self.subTest(target=target):
                response = self.client.post(reverse('utilisateurs:verify_phone'), {'telephone': self.user.profil.telephone, 'next': target})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('eleves:liste_eleves'))
                session = self.client.session
                session['phone_verified'] = False
                session.save()

    def test_telephone_deja_verifie_refuse_redirection_externe(self):
        session = self.client.session
        session['phone_verified'] = True
        session.save()
        response = self.client.get(reverse('utilisateurs:verify_phone'), {'next': '//evil.example'})
        self.assertEqual(response.url, reverse('eleves:liste_eleves'))

    def test_telephone_conserve_redirection_locale(self):
        response = self.client.post(reverse('utilisateurs:verify_phone'), {'telephone': self.user.profil.telephone, 'next': '/salaires/'})
        self.assertEqual(response.url, '/salaires/')

    def matiere(self):
        return MatiereNote.objects.create(classe=self.cn, nom='Activite', coefficient=1)

    def test_appreciation_refuse_eleve_externe_avec_matiere_locale(self):
        matiere = self.matiere()
        for data in (
            {'eleve_id': self.eleve_autre.pk, 'matiere_id': matiere.pk, 'appreciations': {'trimestre1': {'appreciation': 'A'}}},
            {'appreciations': [{'eleve_id': self.eleve_autre.pk, 'matiere_id': matiere.pk, 'trimestre': 'TRIMESTRE_1', 'appreciation': 'A'}]},
        ):
            with self.subTest(format=type(data['appreciations']).__name__):
                response = self.client.post(reverse('notes:sauvegarder_appreciations_maternelle'), data, content_type='application/json')
                self.assertFalse(AppreciationMaternelle.objects.exists())
                self.assertLess(response.status_code, 500)

    def test_appreciation_locale_enregistrable(self):
        response = self.client.post(reverse('notes:sauvegarder_appreciations_maternelle'), {'eleve_id': self.eleve.pk, 'matiere_id': self.matiere().pk, 'appreciations': {'trimestre1': {'appreciation': 'A'}}}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AppreciationMaternelle.objects.get().appreciation, 'A')

    def test_appreciation_sans_ecole_refusee(self):
        self.sans_ecole()
        self.test_appreciation_refuse_eleve_externe_avec_matiere_locale()

    def test_permissions_notes_appliquees_aux_api(self):
        self.user.profil.role = 'ENSEIGNANT'
        self.user.profil.peut_gerer_notes = False
        self.user.profil.save()
        matiere = self.matiere()
        for name, data in (
            ('sauvegarder_notes_guineen', {'eleve_id': self.eleve.pk, 'matiere_id': matiere.pk, 'notes_mois': {'OCTOBRE': '8'}}),
            ('sauvegarder_appreciations_maternelle', {'eleve_id': self.eleve.pk, 'matiere_id': matiere.pk, 'appreciations': {'trimestre1': {'appreciation': 'A'}}}),
        ):
            with self.subTest(api=name):
                response = self.client.post(reverse('notes:' + name), data, content_type='application/json')
                self.assertEqual(response.status_code, 403)
        self.assertFalse(AppreciationMaternelle.objects.exists())
        self.assertFalse(NoteMensuelle.objects.exists())

    def test_permission_enseignant_requise_pour_changement_statut(self):
        self.user.profil.role = 'ENSEIGNANT'
        self.user.profil.peut_ajouter_enseignants = False
        self.user.profil.save()
        response = self.client.post(reverse('salaires:changer_statut_enseignant', args=[self.enseignant.pk]), {'nouveau_statut': 'SUSPENDU'})
        self.enseignant.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.enseignant.statut, 'ACTIF')

    def test_maternelle_classique_refuse_selection_classe_externe(self):
        response = self.client.get(reverse('notes:saisie_evaluation_maternelle'), {'classe': self.cn_autre.pk})
        self.assertEqual(response.status_code, 404)

    def test_maternelle_classique_refuse_eleve_externe(self):
        response = self.client.get(reverse('notes:saisie_eleve_maternelle', args=[self.eleve_autre.pk]), {'classe': self.cn_autre.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(EvaluationMaternelle.objects.exists())

    def test_maternelle_classique_get_ne_cree_pas_evaluation(self):
        response = self.client.get(reverse('notes:saisie_eleve_maternelle', args=[self.eleve.pk]), {'classe': self.cn.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EvaluationMaternelle.objects.exists())

    def test_connexion_refuse_redirection_externe(self):
        self.client.logout()
        response = self.client.post(reverse('utilisateurs:login') + '?next=//evil.example', {'username': self.user.username, 'password': 'audit-only-password'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('eleves:liste_eleves'))

    def test_cloture_periode_externe_refusee(self):
        periode = PeriodeSalaire.objects.create(ecole=self.autre, mois=9, annee=2026)
        self.client.post(reverse('salaires:cloturer_periode', args=[periode.pk]))
        periode.refresh_from_db()
        self.assertFalse(periode.cloturee)

    def test_exports_maternelle_refusent_classe_externe(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        for name in ('bulletins_classe_maternelle_v2_pdf', 'fiches_recommandations_pdf', 'bulletins_classe_maternelle_modele2_pdf'):
            with self.subTest(export=name), patch.dict('sys.modules', {'weasyprint': SimpleNamespace(HTML=Mock())}):
                response = self.client.get(reverse('notes:' + name), {'classe': self.cn_autre.pk})
                self.assertEqual(response.status_code, 404)

    def test_exports_maternelle_ne_recherchent_pas_classe_hors_ecole(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        self.cn.nom = self.cn_autre.nom
        self.cn.niveau = 'LYCEE'
        self.cn.save()
        self.classe.delete()
        for name in ('bulletins_classe_maternelle_v2_pdf', 'fiches_recommandations_pdf', 'bulletins_classe_maternelle_modele2_pdf'):
            with self.subTest(export=name), patch.dict('sys.modules', {'weasyprint': SimpleNamespace(HTML=Mock())}):
                response = self.client.get(reverse('notes:' + name), {'classe': self.cn.pk})
                self.assertEqual(response.status_code, 302)

    def creer_depense(self):
        from depenses.models import Depense, CategorieDepense, Fournisseur
        return Depense.objects.create(
            numero_facture='SEC-DEPENSE', libelle='Fournitures fictives',
            categorie=CategorieDepense.objects.create(nom='Audit'),
            fournisseur=Fournisseur.objects.create(nom='Fournisseur fictif'),
            montant_ht=10000, statut='VALIDEE', cree_par=self.user,
            date_facture=date(2026, 9, 1), date_echeance=date(2026, 9, 30),
        )

    def test_permission_paiement_depense_requise(self):
        depense = self.creer_depense()
        self.user.profil.role = 'ENSEIGNANT'
        self.user.profil.peut_valider_depenses = False
        self.user.profil.save()
        response = self.client.post(reverse('depenses:marquer_payee', args=[depense.pk]))
        depense.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(depense.statut, 'VALIDEE')
        self.assertIsNone(depense.date_paiement)
        self.assertEqual(depense.montant_ttc, 10000)

    def test_paiement_depense_autorise_fonctionne(self):
        depense = self.creer_depense()
        response = self.client.post(reverse('depenses:marquer_payee', args=[depense.pk]))
        depense.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(depense.statut, 'PAYEE')
        self.assertEqual(depense.montant_ttc, 10000)


class ImageInjectionTests(SimpleTestCase):
    def test_attributs_image_echappes(self):
        from eleves.templatetags.static_versioned import image_with_reload
        from html.parser import HTMLParser

        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                self.tag = tag
                self.attrs = dict(attrs)

        payload = '\" onload=\"alert(1)'
        html = image_with_reload('images/test.png', alt_text=payload, css_class=payload, title=payload)
        parser = Parser()
        parser.feed(html)
        self.assertEqual(parser.attrs['alt'], payload)
        self.assertEqual(parser.attrs['title'], payload)
        self.assertNotIn('onload', parser.attrs)


class RuntimeSecretTests(SimpleTestCase):
    def test_cle_locale_conservee_entre_demarrages(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from .runtime_secret import load_or_create_secret

        with TemporaryDirectory() as directory:
            path = Path(directory) / '.secret_key'
            first = load_or_create_secret(path)
            self.assertGreaterEqual(len(first), 64)
            self.assertEqual(first, load_or_create_secret(path))

    def test_ecriture_refusee_conserve_une_cle_aleatoire(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from .runtime_secret import load_or_create_secret

        with TemporaryDirectory() as directory:
            path = Path(directory) / '.secret_key'
            with patch.object(Path, 'write_text', side_effect=PermissionError):
                first = load_or_create_secret(path)
                second = load_or_create_secret(path)
            self.assertGreaterEqual(len(first), 64)
            self.assertNotEqual(first, second)
            self.assertFalse(path.exists())

    def test_fichier_vide_remplace_par_une_cle_valide(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from .runtime_secret import load_or_create_secret

        with TemporaryDirectory() as directory:
            path = Path(directory) / '.secret_key'
            path.touch()
            self.assertGreaterEqual(len(load_or_create_secret(path)), 64)
