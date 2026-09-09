"""Régressions de l'audit : matricules et isolation des cartes scolaires."""
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import Classe, Ecole, Eleve, _code_classe_from_nom_ou_niveau, _normalize_code_prefixe


class CodesMatriculesTests(SimpleTestCase):
    def test_code_personnalise_prioritaire(self):
        classe = SimpleNamespace(code_matricule=' SPEC ', nom='Garderie', niveau='GARDERIE')
        self.assertEqual(_code_classe_from_nom_ou_niveau(classe), 'SPEC')

    def test_codes_par_nom_normalise_et_niveau(self):
        cas = [
            (' Petite   section ', 'MATERNELLE', 'MPS'),
            ('GRANDE SECTION', 'MATERNELLE', 'MGS'),
            ('Petite section A', 'MATERNELLE', 'MPS'),
            ('Moyenne section B', 'MATERNELLE', 'MMS'),
            ('11ÈME SÉRIE LITTÉRAIRE', 'LYCEE_11', 'L11SL'),
            ('2EME ANNEE', 'PRIMAIRE_2', 'PN2'),
            ('Classe A', 'COLLEGE_8', 'CN8'),
            ('Inconnue', '', ''),
        ]
        for nom, niveau, attendu in cas:
            with self.subTest(nom=nom):
                classe = SimpleNamespace(code_matricule=None, nom=nom, niveau=niveau)
                self.assertEqual(_code_classe_from_nom_ou_niveau(classe), attendu)

    def test_prefixe_ecole_conserve_et_dedoublonne(self):
        self.assertEqual(_normalize_code_prefixe(' ECOLE / ECOLE / '), 'ECOLE/')
        self.assertEqual(_normalize_code_prefixe(''), '')


@override_settings(MIDDLEWARE=tuple(m for m in settings.MIDDLEWARE if 'LicenceMiddleware' not in m))
class CartesIsolationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.ecole = Ecole.objects.create(nom='Audit A', etat='VALIDE')
        self.autre_ecole = Ecole.objects.create(nom='Audit B', etat='VALIDE')
        self.classe = Classe.objects.create(ecole=self.ecole, nom='Grande section', niveau='MATERNELLE', annee_scolaire='2026-2027')
        autre_classe = Classe.objects.create(ecole=self.autre_ecole, nom='Grande section', niveau='MATERNELLE', annee_scolaire='2026-2027')
        self.eleve = Eleve.objects.create(classe=self.classe, matricule='AUD-001', prenom='Aminata', nom='Diallo', sexe='F', statut='ACTIF')
        self.autre_eleve = Eleve.objects.create(classe=autre_classe, matricule='AUD-002', prenom='Prive', nom='Autre', sexe='M', statut='ACTIF')
        self.user = User.objects.create_user('audit-cartes')
        self.user.profil.ecole = self.ecole
        self.user.profil.role = 'ADMIN'
        self.user.profil.is_validated = True
        self.user.profil.save()
        self.client.force_login(self.user)

    def test_nouveau_matricule_et_matricule_existant(self):
        nouveau = Eleve.objects.create(classe=self.classe, prenom='Nouveau', nom='Test', sexe='M')
        self.assertTrue(nouveau.matricule.startswith('MGS-'), nouveau.matricule)
        self.eleve.nom = 'Corrige'
        self.eleve.save()
        self.eleve.refresh_from_db()
        self.assertEqual(self.eleve.matricule, 'AUD-001')

    def test_admin_ecole_ne_peut_pas_lire_carte_autre_ecole(self):
        for vue in ('carte_scolaire_preview', 'carte_scolaire_pdf'):
            with self.subTest(vue=vue):
                response = self.client.get(reverse('eleves:' + vue, args=[self.autre_eleve.pk]))
                self.assertEqual(response.status_code, 404)

    def test_carte_propre_ecole_reste_accessible(self):
        response = self.client.get(reverse('eleves:carte_scolaire_pdf', args=[self.eleve.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_liste_et_detail_sont_limites_a_ecole(self):
        response = self.client.get(reverse('eleves:liste_eleves'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.eleve.matricule)
        self.assertNotContains(response, self.autre_eleve.matricule)
        response = self.client.get(reverse('eleves:detail_eleve', args=[self.autre_eleve.pk]))
        self.assertEqual(response.status_code, 404)

    def test_formulaire_ne_propose_pas_classe_externe(self):
        from .forms import EleveForm
        form = EleveForm(instance=self.eleve, user=self.user)
        self.assertNotIn(self.autre_eleve.classe, form.fields['classe'].queryset)
        self.assertIn(self.classe, form.fields['classe'].queryset)

    def test_exports_et_cartes_de_classe_refusent_autre_ecole(self):
        for vue in ('export_eleves_classe_pdf', 'export_eleves_classe_excel', 'cartes_scolaires_classe_pdf', 'tickets_retrait_classe_pdf', 'tickets_bus_classe_pdf', 'tickets_cantine_classe_pdf'):
            with self.subTest(vue=vue):
                response = self.client.get(reverse('eleves:' + vue, args=[self.autre_eleve.classe_id]))
                self.assertIn(response.status_code, (302, 403, 404))
                self.assertNotEqual(response.get('Content-Type'), 'application/pdf')

    def test_compteurs_liste_apres_modification_et_suppression(self):
        url = reverse('eleves:liste_eleves')
        self.assertEqual(self.client.get(url).context['stats']['eleves_actifs'], 1)
        self.eleve.statut = 'SUSPENDU'
        self.eleve.save()
        stats = self.client.get(url).context['stats']
        self.assertEqual(stats['eleves_actifs'], 0)
        self.assertEqual(stats['eleves_suspendus'], 1)
        self.eleve.delete()
        self.assertEqual(self.client.get(url).context['stats']['total_eleves'], 0)

    def test_sans_ecole_liste_vide_et_superadmin_acces_global(self):
        self.user.profil.ecole = None
        self.user.profil.save()
        cache.clear()
        response = self.client.get(reverse('eleves:liste_eleves'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stats']['total_eleves'], 0)
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse('eleves:liste_eleves'))
        self.assertEqual(response.context['stats']['total_eleves'], 2)
