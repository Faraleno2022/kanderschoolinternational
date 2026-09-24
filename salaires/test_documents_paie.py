from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from . import tests as support
from .documents_paie import (
    lignes_bulletin,
    montant_en_lettres,
    nombre_en_lettres,
    synthese_masse_salariale,
)
from .forms import EtatSalaireAjustementForm
from .models import AvanceSalaire, CategoriePaie, Enseignant, EtatSalaire, TypeEnseignant
from .services import appliquer_ajustement_etat_salaire, calculer_etat_salaire


class MontantEnLettresTests(TestCase):
    def test_nombres_du_classeur(self):
        cas = {
            0: 'zéro',
            21: 'vingt-et-un',
            71: 'soixante-et-onze',
            80: 'quatre-vingts',
            91: 'quatre-vingt-onze',
            200: 'deux cents',
            280000: 'deux cent quatre-vingt mille',
            1000: 'mille',
            7982500: 'sept millions neuf cent quatre-vingt-deux mille cinq cents',
            20867500: 'vingt millions huit cent soixante-sept mille cinq cents',
            1000000: 'un million',
        }
        for nombre, attendu in cas.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(nombre_en_lettres(nombre), attendu)

    def test_montant_en_lettres_majuscule_et_devise(self):
        self.assertEqual(
            montant_en_lettres(Decimal('6039000.00')),
            'Six millions trente-neuf mille francs guinéens',
        )


@override_settings(MIDDLEWARE=support.TEST_MIDDLEWARE)
class DocumentsPaieTests(TestCase):
    setUp = support.MoteurPaieTests.setUp

    def creer_employe(self, nom, type_enseignant, **extra):
        donnees = dict(
            nom=nom, prenoms='Test', ecole=self.ecole, type_enseignant=type_enseignant,
            statut='ACTIF', date_embauche=date(2021, 1, 1), matricule=f"M-{nom}",
        )
        if type_enseignant == TypeEnseignant.SECONDAIRE:
            donnees.update(taux_horaire=Decimal('13500'), heures_mensuelles=Decimal('40'))
        else:
            donnees.update(salaire_fixe=Decimal('550000'))
        donnees.update(extra)
        return Enseignant.objects.create(**donnees)

    def preparer_periode(self):
        self.directeur = self.creer_employe('Bamba', TypeEnseignant.CADRE, fonction='DG')
        self.maitre = self.creer_employe('Gamy', TypeEnseignant.PRIMAIRE)
        self.prof = self.creer_employe('Diallo', TypeEnseignant.SECONDAIRE)
        AvanceSalaire.objects.create(
            enseignant=self.maitre, periode=self.periode, montant=Decimal('100000'),
            date_avance=date(2026, 7, 5), motif='Bon 1', statut=AvanceSalaire.Statut.APPROUVEE,
        )
        AvanceSalaire.objects.create(
            enseignant=self.maitre, periode=self.periode, montant=Decimal('45000'),
            date_avance=date(2026, 7, 12), motif='Bon 2', statut=AvanceSalaire.Statut.APPROUVEE,
        )
        etats = {}
        for employe in (self.directeur, self.maitre, self.prof):
            etats[employe.pk], _ = calculer_etat_salaire(employe, self.periode, self.user)
        return etats

    def test_ajustement_ventile_les_primes_par_rubrique(self):
        employe = self.creer_employe('Gamy', TypeEnseignant.PRIMAIRE)
        etat, _ = calculer_etat_salaire(employe, self.periode, self.user)
        form = EtatSalaireAjustementForm({
            'salaire_base': '550000', 'jours_travailles': '20',
            'prime_fonction': '300000', 'prime_craie_revision': '0',
            'prime_anciennete': '30000', 'prime_eloignement': '4000',
            'prime_performance': '80000', 'prime_exceptionnelle': '50000',
            'primes': '10000', 'deductions': '0', 'observations': '',
        }, instance=etat)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['primes'], Decimal('474000'))

        etat = appliquer_ajustement_etat_salaire(
            etat, self.user, salaire_base=Decimal('550000'),
            primes=form.cleaned_data['primes'], deductions=Decimal('0'),
            details_primes=form.details_primes, jours_travailles=20,
        )
        etat.refresh_from_db()
        self.assertEqual(etat.prime_fonction, Decimal('300000'))
        self.assertEqual(etat.prime_autres, Decimal('10000'))
        self.assertEqual(etat.jours_travailles, 20)
        self.assertEqual(etat.salaire_brut, Decimal('1024000'))
        self.assertEqual(etat.salaire_net, Decimal('1024000'))
        # Le formulaire réaffiche la seule part « autres primes ».
        self.assertEqual(EtatSalaireAjustementForm(instance=etat).initial['primes'], Decimal('10000'))

    def test_vue_ajustement_enregistre_les_rubriques(self):
        employe = self.creer_employe('Mamy', TypeEnseignant.MATERNELLE)
        etat, _ = calculer_etat_salaire(employe, self.periode, self.user)
        response = self.client.post(reverse('salaires:ajuster_etat_salaire', args=[etat.pk]), {
            'salaire_base': '550000', 'jours_travailles': '',
            'prime_fonction': '200000', 'prime_craie_revision': '25500',
            'prime_anciennete': '', 'prime_eloignement': '', 'prime_performance': '',
            'prime_exceptionnelle': '', 'primes': '', 'deductions': '0', 'observations': '',
        })
        self.assertEqual(response.status_code, 302)
        etat.refresh_from_db()
        self.assertEqual(etat.primes, Decimal('225500'))
        self.assertEqual(etat.prime_craie_revision, Decimal('25500'))
        self.assertIsNone(etat.jours_travailles)

    def test_categories_et_masse_salariale(self):
        etats = self.preparer_periode()
        self.assertEqual(self.directeur.categorie_paie, CategoriePaie.DIRECTION)
        self.assertEqual(self.prof.categorie_paie, CategoriePaie.SECONDAIRE)
        lignes, total = synthese_masse_salariale(self.periode)
        par_categorie = {ligne['categorie']: ligne for ligne in lignes}
        self.assertEqual(set(par_categorie), {
            CategoriePaie.DIRECTION, CategoriePaie.PRIMAIRE, CategoriePaie.SECONDAIRE,
        })
        self.assertEqual(par_categorie[CategoriePaie.PRIMAIRE]['acompte'], Decimal('145000'))
        self.assertEqual(total['effectif'], 3)
        self.assertEqual(total['net'], sum(e.salaire_net for e in etats.values()))

        response = self.client.get(reverse('salaires:masse_salariale', args=[self.periode.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Maternelle / Primaire')

    def test_documents_pdf_generes(self):
        self.preparer_periode()
        noms = ['masse_salariale_pdf', 'etat_paie_pdf', 'emargement_pdf', 'acomptes_pdf', 'bulletins_periode_pdf']
        for nom in noms:
            for categorie in ('', *CategoriePaie.values):
                with self.subTest(document=nom, categorie=categorie):
                    url = reverse(f'salaires:{nom}', args=[self.periode.pk])
                    response = self.client.get(url, {'categorie': categorie} if categorie else {})
                    if nom == 'bulletins_periode_pdf' and categorie == CategoriePaie.APPUI:
                        self.assertEqual(response.status_code, 404)
                        continue
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response['Content-Type'], 'application/pdf')
                    self.assertTrue(response.content.startswith(b'%PDF'))

    def test_categorie_inconnue_refusee(self):
        response = self.client.get(
            reverse('salaires:etat_paie_pdf', args=[self.periode.pk]), {'categorie': 'XYZ'}
        )
        self.assertEqual(response.status_code, 404)

    def test_lignes_bulletin_soldent_au_net(self):
        etats = self.preparer_periode()
        etat = EtatSalaire.objects.get(pk=etats[self.maitre.pk].pk)
        lignes = lignes_bulletin(etat)
        self.assertEqual(lignes[0][1], 'Salaire de base')
        self.assertEqual(lignes[-1][4], '145 000')
        self.assertEqual(lignes[-1][5], f"{etat.salaire_net:,.0f}".replace(',', ' '))
        response = self.client.get(reverse('salaires:fiche_paie_pdf', args=[etat.pk]))
        self.assertEqual(response.status_code, 200)
