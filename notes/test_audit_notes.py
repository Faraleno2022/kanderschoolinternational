"""Régressions des pages de notes, de leur impression et de leur sauvegarde."""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from .models import ClasseNote, MatiereNote, NoteMensuelle, CompositionNote
from .utils_rangs import calculer_rangs_classe_periode


@override_settings(MIDDLEWARE=tuple(m for m in settings.MIDDLEWARE if 'LicenceMiddleware' not in m))
class AuditNotesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.ecole = Ecole.objects.create(nom='Ecole audit notes', etat='VALIDE')
        self.autre_ecole = Ecole.objects.create(nom='Ecole externe notes', etat='VALIDE')
        self.classe = Classe.objects.create(ecole=self.ecole, nom='7ème année', niveau='COLLEGE_7', annee_scolaire='2026-2027')
        autre = Classe.objects.create(ecole=self.autre_ecole, nom='7ème année', niveau='COLLEGE_7', annee_scolaire='2026-2027')
        self.cn = ClasseNote.objects.create(ecole=self.ecole, nom=self.classe.nom, niveau='COLLEGE_7', annee_scolaire='2026-2027')
        self.cn_autre = ClasseNote.objects.create(ecole=self.autre_ecole, nom=autre.nom, niveau='COLLEGE_7', annee_scolaire='2026-2027')
        self.matiere = MatiereNote.objects.create(classe=self.cn, nom='Mathématiques', coefficient=1)
        self.eleve = Eleve.objects.create(classe=self.classe, matricule='NOT-001', prenom='Aminata', nom='Diallo', sexe='F', statut='ACTIF')
        self.autre_eleve = Eleve.objects.create(classe=autre, matricule='PRIVE-002', prenom='Prive', nom='Externe', sexe='M', statut='ACTIF')
        self.user = User.objects.create_user('audit-notes')
        self.user.profil.ecole = self.ecole
        self.user.profil.role = 'ADMIN'
        self.user.profil.is_validated = True
        self.user.profil.save()
        self.client.force_login(self.user)

    def note(self, valeur, mois='OCTOBRE'):
        return NoteMensuelle.objects.create(eleve=self.eleve, matiere=self.matiere, mois=mois, annee_scolaire=self.cn.annee_scolaire, note=valeur)

    def imprimer(self, periode='OCTOBRE', pdf=False, classe=None):
        return self.client.get(reverse('notes:imprimer_tableau_notes_' + ('pdf' if pdf else 'html')), {'classe_id': (classe or self.cn).pk, 'periode': periode})

    def enregistrer(self, **kwargs):
        data = {'eleve_id': self.eleve.pk, 'matiere_id': self.matiere.pk, 'annee_scolaire': self.cn.annee_scolaire}
        data.update(kwargs)
        return self.client.post(reverse('notes:sauvegarder_notes_guineen'), json.dumps(data), content_type='application/json')

    def test_page_saisie_accessible(self):
        response = self.client.get(reverse('notes:saisie_notes_guineen'), {'classe_id': self.cn.pk, 'eleve_id': self.eleve.pk, 'matiere_id': self.matiere.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.eleve.matricule)

    def test_saisie_ne_selectionne_pas_eleve_externe(self):
        response = self.client.get(reverse('notes:saisie_notes_guineen'), {'classe_id': self.cn.pk, 'eleve_id': self.autre_eleve.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['eleve_selectionne'])

    def test_bulletin_web_accessible(self):
        self.note(12)
        response = self.client.get(reverse('notes:bulletin_intelligent', args=[self.eleve.pk, self.cn.pk, 'OCTOBRE']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.eleve.prenom)

    def test_bulletin_refuse_classe_externe(self):
        response = self.client.get(reverse('notes:bulletin_intelligent', args=[self.eleve.pk, self.cn_autre.pk, 'OCTOBRE']))
        self.assertEqual(response.status_code, 404)

    def test_impression_affiche_eleve_et_zero(self):
        self.note(0)
        response = self.imprimer()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.eleve.matricule)
        self.assertContains(response, self.eleve.prenom)
        self.assertContains(response, '<span class="note">0,0</span>', html=True)
        self.assertNotContains(response, self.autre_eleve.matricule)

    def test_impression_trimestre_reprend_moyenne_calculee(self):
        self.note(10)
        self.note(14, 'NOVEMBRE')
        CompositionNote.objects.create(eleve=self.eleve, matiere=self.matiere, periode='TRIMESTRE_1', annee_scolaire=self.cn.annee_scolaire, note=16)
        response = self.imprimer('TRIMESTRE_1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span class="note">14,4</span>', html=True)

    def test_impressions_refusent_classe_externe(self):
        for pdf in (False, True):
            with self.subTest(pdf=pdf):
                with patch.dict('sys.modules', {'weasyprint': SimpleNamespace(HTML=Mock(), CSS=Mock())}):
                    response = self.imprimer(pdf=pdf, classe=self.cn_autre)
                self.assertEqual(response.status_code, 404)

    def test_pdf_ex_aequo_utilise_rang_numerique(self):
        self.note(12)
        autre = Eleve.objects.create(classe=self.classe, matricule='NOT-003', prenom='Exaequo', nom='Test', sexe='M', statut='ACTIF')
        NoteMensuelle.objects.create(eleve=autre, matiere=self.matiere, mois='OCTOBRE', annee_scolaire=self.cn.annee_scolaire, note=12)
        html = Mock()
        html.return_value.write_pdf.return_value = b'%PDF-test'
        with patch.dict('sys.modules', {'weasyprint': SimpleNamespace(HTML=html, CSS=Mock())}):
            response = self.imprimer(pdf=True)
        self.assertEqual(response.status_code, 200)
        contenu = html.call_args.kwargs['string']
        self.assertIn(self.eleve.matricule, contenu)
        self.assertIn(autre.matricule, contenu)

    def test_rangs_n_utilisent_pas_identifiants_historiques(self):
        # L'ancien mapping 61 -> 56 pouvait désigner une autre école.
        Classe.objects.create(pk=56, ecole=self.autre_ecole, nom='Classe historique', niveau='COLLEGE_7', annee_scolaire='2026-2027')
        self.cn = ClasseNote.objects.create(pk=61, ecole=self.ecole, nom='7EME ANNEE', niveau='COLLEGE_7', annee_scolaire='2026-2027')
        self.matiere.classe = self.cn
        self.matiere.save()
        self.note(12)
        resultats = calculer_rangs_classe_periode(self.cn, 'OCTOBRE', use_cache=False)
        self.assertIn(self.eleve.pk, resultats)
        self.assertEqual(resultats[self.eleve.pk]['moyenne'], Decimal('12'))

    def test_refus_note_hors_bareme_ne_modifie_rien(self):
        note = self.note(8)
        response = self.enregistrer(notes_mois={'OCTOBRE': {'note': 12}, 'NOVEMBRE': {'note': 30}})
        self.assertEqual(response.status_code, 400)
        note.refresh_from_db()
        self.assertEqual(note.note, Decimal('8'))
        self.assertEqual(NoteMensuelle.objects.count(), 1)

    def test_refus_composition_ne_modifie_pas_notes_mensuelles(self):
        response = self.enregistrer(notes_mois={'OCTOBRE': {'note': 12}}, compositions={'composition1': {'note': 30}})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(NoteMensuelle.objects.exists())
        self.assertFalse(CompositionNote.objects.exists())

    def test_valeur_non_numerique_refusee(self):
        response = self.enregistrer(notes_mois={'OCTOBRE': {'note': 'abc'}})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(NoteMensuelle.objects.exists())

    def test_utilisateur_sans_ecole_ne_peut_pas_modifier(self):
        self.user.profil.ecole = None
        self.user.profil.save()
        response = self.enregistrer(notes_mois={'OCTOBRE': {'note': 12}})
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(NoteMensuelle.objects.exists())

    def test_sauvegarde_valide_et_recalcul_immediat(self):
        self.note(8)
        self.assertEqual(calculer_rangs_classe_periode(self.cn, 'OCTOBRE')[self.eleve.pk]['moyenne'], Decimal('8'))
        response = self.enregistrer(notes_mois={'OCTOBRE': {'note': '12,5'}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calculer_rangs_classe_periode(self.cn, 'OCTOBRE')[self.eleve.pk]['moyenne'], Decimal('12.5'))

    def test_classement_annuel_recalcule_apres_modification_et_suppression(self):
        from .calculs_moyennes import calculer_classement_classe
        composition = CompositionNote.objects.create(eleve=self.eleve, matiere=self.matiere, periode='TRIMESTRE_1', annee_scolaire=self.cn.annee_scolaire, note=12)
        def moyenne():
            return calculer_classement_classe(Eleve.objects.filter(pk=self.eleve.pk), MatiereNote.objects.filter(pk=self.matiere.pk), 'ANNUEL_TRIM', 'annuel_trimestriel')['moyennes_par_eleve'][self.eleve.pk]
        self.assertEqual(moyenne(), 4)
        composition.note = 18
        composition.save()
        self.assertEqual(moyenne(), 6)
        composition.delete()
        self.assertEqual(moyenne(), 0)

    def test_classement_maternelle_cinquieme_periode(self):
        from .models import AppreciationMaternelle
        self.cn.nom = self.classe.nom = 'Petite section'
        self.cn.niveau = self.classe.niveau = 'MATERNELLE'
        self.classe.save()
        self.cn.save()
        AppreciationMaternelle.objects.create(eleve=self.eleve, matiere=self.matiere, trimestre='PERIODE_5', annee_scolaire=self.cn.annee_scolaire, appreciation='A')
        rangs = calculer_rangs_classe_periode(self.cn, 'PERIODE_5', use_cache=False)
        self.assertEqual(rangs[self.eleve.pk]['moyenne'], Decimal('95'))
        response = self.imprimer('PERIODE_5')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span class="note">A</span>', html=True)

    def test_sauvegarde_semestre_garde_la_bonne_periode(self):
        response = self.enregistrer(compositions={'composition1': {'note': 12}}, system_type='semestre')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CompositionNote.objects.get().periode, 'SEMESTRE_1')

    def test_notes_non_finies_et_periodes_inconnues_refusees(self):
        for notes in ({'OCTOBRE': {'note': 'NaN'}}, {'OCTOBRE': {'note': 'Infinity'}}, {'FAUX_MOIS': {'note': 12}}):
            with self.subTest(notes=notes):
                response = self.enregistrer(notes_mois=notes)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(NoteMensuelle.objects.exists())

    def test_page_configuration_ecole_accessible(self):
        response = self.client.get(reverse('eleves:configurer_ecole', args=[self.ecole.pk]))
        self.assertEqual(response.status_code, 200)
