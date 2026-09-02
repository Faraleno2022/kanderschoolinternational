from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole

from .forms import EnseignantForm, EtatSalaireAjustementForm, PresenceForm
from .models import (
    AffectationClasse,
    Enseignant,
    EtatSalaire,
    PeriodeSalaire,
    PresenceEnseignant,
    SourceHeuresSalaire,
    TypeEnseignant,
)
from .services import (
    calculer_etat_salaire as calculer_etat_salaire_reel,
    nombre_jours_presence,
)


LICENCE_MIDDLEWARE = 'ecole_moderne.licence_middleware.LicenceMiddleware'
TEST_MIDDLEWARE = tuple(
    middleware for middleware in settings.MIDDLEWARE
    if middleware != LICENCE_MIDDLEWARE
)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class MoteurPaieTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='audit-paie',
            email='audit-paie@example.com',
            password='mot-de-passe-test',
        )
        self.ecole = Ecole.objects.create(
            nom='École test paie',
            adresse='Conakry',
            telephone='+224610000000',
            directeur='Direction test',
        )
        if hasattr(self.user, 'profil'):
            self.user.profil.ecole = self.ecole
            self.user.profil.save(update_fields=['ecole'])
        self.classe_a = Classe.objects.create(
            ecole=self.ecole,
            nom='Classe A',
            niveau='COLLEGE_7',
            annee_scolaire='2025-2026',
        )
        self.classe_b = Classe.objects.create(
            ecole=self.ecole,
            nom='Classe B',
            niveau='COLLEGE_8',
            annee_scolaire='2025-2026',
        )
        self.periode = PeriodeSalaire.objects.create(
            mois=7,
            annee=2026,
            ecole=self.ecole,
            nombre_semaines=Decimal('4'),
            cree_par=self.user,
        )
        self.client.force_login(self.user)

    def creer_secondaire(self, nom='Secondaire', taux='10000'):
        return Enseignant.objects.create(
            nom=nom,
            prenoms='Test',
            ecole=self.ecole,
            type_enseignant=TypeEnseignant.SECONDAIRE,
            statut='ACTIF',
            taux_horaire=Decimal(taux),
            heures_mensuelles=Decimal('120'),
            date_embauche=date(2025, 1, 1),
            cree_par=self.user,
        )

    def creer_fixe(self, nom='Fixe', salaire='1000000', embauche=date(2025, 1, 1)):
        return Enseignant.objects.create(
            nom=nom,
            prenoms='Test',
            ecole=self.ecole,
            type_enseignant=TypeEnseignant.PRIMAIRE,
            statut='ACTIF',
            salaire_fixe=Decimal(salaire),
            heures_mensuelles=Decimal('160'),
            date_embauche=embauche,
            cree_par=self.user,
        )

    def affecter(self, enseignant, classe, heures, **kwargs):
        valeurs = {
            'enseignant': enseignant,
            'classe': classe,
            'heures_par_semaine': Decimal(heures),
            'date_debut': date(2025, 1, 1),
            'actif': True,
        }
        valeurs.update(kwargs)
        return AffectationClasse.objects.create(**valeurs)

    def pointer(self, enseignant, jours, heures=8):
        for jour in jours:
            PresenceEnseignant.objects.create(
                enseignant=enseignant,
                date=date(2026, 7, jour),
                statut='PRESENT',
                heures_travaillees=Decimal(heures),
                pointe_par=self.user,
            )

    def calculer(self):
        return self.client.post(
            reverse('salaires:calculer_salaires', args=[self.periode.id])
        )

    def test_net_egale_base_plus_primes_moins_retenues(self):
        enseignant = self.creer_fixe()
        etat = EtatSalaire.objects.create(
            enseignant=enseignant,
            periode=self.periode,
            salaire_base=Decimal('1000000'),
            primes=Decimal('100000'),
            deductions=Decimal('25000'),
            salaire_net=Decimal('0'),
            calcule_par=self.user,
        )
        self.assertEqual(etat.salaire_net, Decimal('1075000.00'))

    def test_salaire_horaire_utilise_le_pointage_reel(self):
        enseignant = self.creer_secondaire()
        self.affecter(enseignant, self.classe_a, '10')
        self.pointer(enseignant, range(1, 6))

        self.calculer()

        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        self.assertEqual(etat.total_heures, Decimal('40.00'))
        self.assertEqual(etat.taux_horaire_applique, Decimal('10000.00'))
        self.assertEqual(etat.salaire_base, Decimal('400000.00'))
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.POINTAGE)

    def test_pointage_recalcule_immediatement_le_salaire_du_mois(self):
        enseignant = self.creer_secondaire()

        response = self.client.post(
            reverse('salaires:pointer_presence'),
            {
                'date': '2026-07-03',
                'enseignants': [str(enseignant.id)],
                f'statut_{enseignant.id}': 'PRESENT',
                f'heure_arrivee_{enseignant.id}': '08:00',
                f'heure_depart_{enseignant.id}': '12:30',
                f'observations_{enseignant.id}': '',
            },
        )

        self.assertEqual(response.status_code, 302)
        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        self.assertEqual(etat.total_heures, Decimal('4.50'))
        self.assertEqual(etat.salaire_base, Decimal('45000.00'))
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.POINTAGE)

    def test_saisie_globale_mensuelle_calcule_et_preserve_le_salaire(self):
        enseignant = self.creer_secondaire()
        self.pointer(enseignant, [1], heures=8)

        response = self.client.post(
            reverse('salaires:saisir_heures_mensuelles', args=[self.periode.id]),
            {
                f'source_{enseignant.id}': SourceHeuresSalaire.MENSUEL,
                f'heures_{enseignant.id}': '125.5',
            },
        )

        self.assertEqual(response.status_code, 302)
        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.MENSUEL)
        self.assertEqual(etat.total_heures, Decimal('125.50'))
        self.assertEqual(etat.salaire_base, Decimal('1255000.00'))

        # Le recalcul général ne doit pas écraser une saisie mensuelle choisie.
        self.calculer()
        etat.refresh_from_db()
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.MENSUEL)
        self.assertEqual(etat.total_heures, Decimal('125.50'))

    def test_saisie_mensuelle_peut_revenir_aux_pointages(self):
        enseignant = self.creer_secondaire()
        self.pointer(enseignant, [1, 2], heures=6)
        calculer_etat_salaire_reel(
            enseignant,
            self.periode,
            self.user,
            source_heures=SourceHeuresSalaire.MENSUEL,
            heures_mensuelles=Decimal('100'),
        )

        response = self.client.post(
            reverse('salaires:saisir_heures_mensuelles', args=[self.periode.id]),
            {f'source_{enseignant.id}': SourceHeuresSalaire.POINTAGE},
        )

        self.assertEqual(response.status_code, 302)
        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.POINTAGE)
        self.assertEqual(etat.total_heures, Decimal('12.00'))
        self.assertEqual(etat.salaire_base, Decimal('120000.00'))

    def test_secondaire_sans_affectation_ne_plante_pas(self):
        enseignant = self.creer_secondaire()
        self.pointer(enseignant, [1])

        response = self.calculer()

        self.assertEqual(response.status_code, 302)
        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        self.assertEqual(etat.salaire_base, Decimal('80000.00'))
        self.assertFalse(etat.details_heures.exists())

    def test_absence_de_pointage_donne_zero_heure(self):
        enseignant = self.creer_secondaire()

        self.calculer()

        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        self.assertEqual(etat.total_heures, Decimal('0.00'))
        self.assertEqual(etat.salaire_base, Decimal('0.00'))

    def test_repartition_respecte_les_heures_hebdomadaires(self):
        enseignant = self.creer_secondaire()
        self.affecter(enseignant, self.classe_a, '10')
        self.affecter(enseignant, self.classe_b, '20')
        self.pointer(enseignant, range(1, 16))

        self.calculer()

        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        details = list(
            etat.details_heures.order_by('affectation_classe__classe__nom')
            .values_list('heures_prevues', 'heures_realisees')
        )
        self.assertEqual(
            details,
            [
                (Decimal('40.00'), Decimal('40.00')),
                (Decimal('80.00'), Decimal('80.00')),
            ],
        )

    def test_affectation_historique_cloturee_est_utilisee(self):
        enseignant = self.creer_secondaire()
        self.affecter(
            enseignant,
            self.classe_a,
            '10',
            date_debut=date(2026, 7, 1),
            date_fin=date(2026, 7, 31),
            actif=False,
        )
        self.pointer(enseignant, range(1, 6))

        self.calculer()

        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        detail = etat.details_heures.get()
        self.assertEqual(detail.heures_prevues, Decimal('40.00'))
        self.assertEqual(detail.heures_realisees, Decimal('40.00'))

    def test_forfait_est_proratise_selon_date_embauche(self):
        enseignant = self.creer_fixe(
            salaire='3100000', embauche=date(2026, 7, 16)
        )

        self.calculer()

        etat = EtatSalaire.objects.get(enseignant=enseignant, periode=self.periode)
        self.assertEqual(etat.salaire_base, Decimal('1600000.00'))

    def test_cadre_conserve_un_salaire_fixe_negocie(self):
        cadre = Enseignant.objects.create(
            nom='Cadre',
            prenoms='Administratif',
            ecole=self.ecole,
            type_enseignant=TypeEnseignant.CADRE,
            statut='ACTIF',
            salaire_fixe=Decimal('2500000'),
            date_embauche=date(2025, 1, 1),
            cree_par=self.user,
        )

        self.calculer()

        etat = EtatSalaire.objects.get(enseignant=cadre, periode=self.periode)
        self.assertEqual(etat.salaire_base, Decimal('2500000.00'))
        self.assertIsNone(etat.total_heures)
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.FIXE)

    def test_embauche_apres_periode_est_exclue(self):
        enseignant = self.creer_fixe(embauche=date(2026, 8, 1))

        self.calculer()

        self.assertFalse(
            EtatSalaire.objects.filter(
                enseignant=enseignant, periode=self.periode
            ).exists()
        )

    def test_calcul_du_lot_est_atomique(self):
        self.creer_fixe(nom='A enseignant')
        self.creer_fixe(nom='B enseignant')
        appels = 0

        def calcul_avec_erreur(enseignant, periode, utilisateur):
            nonlocal appels
            appels += 1
            if appels == 2:
                raise RuntimeError('erreur simulée')
            return calculer_etat_salaire_reel(enseignant, periode, utilisateur)

        with patch('salaires.services.calculer_etat_salaire', side_effect=calcul_avec_erreur):
            self.calculer()

        self.assertEqual(EtatSalaire.objects.count(), 0)

    def test_salaire_negatif_est_refuse_par_le_formulaire(self):
        form = EnseignantForm(
            data={
                'nom': 'Fixe',
                'prenoms': 'Négatif',
                'ecole': self.ecole.id,
                'type_enseignant': TypeEnseignant.PRIMAIRE,
                'statut': 'ACTIF',
                'salaire_fixe': '-100000',
                'heures_mensuelles': '160',
                'date_embauche': '2025-01-01',
            },
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('salaire_fixe', form.errors)

    def test_heures_mensuelles_sont_optionnelles_avec_le_pointage(self):
        form = EnseignantForm(
            data={
                'nom': 'Horaire',
                'prenoms': 'Sans forfait mensuel',
                'ecole': self.ecole.id,
                'type_enseignant': TypeEnseignant.SECONDAIRE,
                'statut': 'ACTIF',
                'taux_horaire': '15000',
                'heures_mensuelles': '',
                'date_embauche': '2025-01-01',
            },
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_retenue_superieure_au_brut_est_refusee(self):
        enseignant = self.creer_fixe()
        etat = EtatSalaire.objects.create(
            enseignant=enseignant,
            periode=self.periode,
            salaire_base=Decimal('1000000'),
            salaire_net=Decimal('1000000'),
            calcule_par=self.user,
        )
        etat.deductions = Decimal('1000001')
        with self.assertRaises(ValidationError):
            etat.save()

    def test_ajustement_primes_retenues_recalcule_le_net(self):
        enseignant = self.creer_fixe()
        etat = EtatSalaire.objects.create(
            enseignant=enseignant,
            periode=self.periode,
            salaire_base=Decimal('1000000'),
            salaire_net=Decimal('1000000'),
            calcule_par=self.user,
        )

        response = self.client.post(
            reverse('salaires:ajuster_etat_salaire', args=[etat.id]),
            {
                'salaire_base': '1200000',
                'primes': '100000',
                'deductions': '25000',
                'observations': 'Ajustement contrôlé',
            },
        )

        self.assertEqual(response.status_code, 302)
        etat.refresh_from_db()
        self.assertEqual(etat.salaire_base, Decimal('1200000.00'))
        self.assertEqual(etat.salaire_net, Decimal('1275000.00'))
        self.assertEqual(etat.observations, 'Ajustement contrôlé')

    def test_ajustement_horaire_manuel_modifie_heures_et_taux_de_la_periode(self):
        enseignant = self.creer_secondaire(taux='10000')
        self.affecter(enseignant, self.classe_a, '10')
        self.pointer(enseignant, [1], heures=6)
        self.calculer()
        etat = EtatSalaire.objects.get(
            enseignant=enseignant,
            periode=self.periode,
        )

        response = self.client.post(
            reverse('salaires:ajuster_etat_salaire', args=[etat.id]),
            {
                'source_heures': SourceHeuresSalaire.MENSUEL,
                'total_heures': '42.5',
                'taux_horaire_applique': '12000',
                'primes': '30000',
                'deductions': '10000',
                'observations': 'Heures mensuelles confirmées',
            },
        )

        self.assertEqual(response.status_code, 302)
        etat.refresh_from_db()
        enseignant.refresh_from_db()
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.MENSUEL)
        self.assertEqual(etat.total_heures, Decimal('42.50'))
        self.assertEqual(etat.taux_horaire_applique, Decimal('12000.00'))
        self.assertEqual(etat.salaire_base, Decimal('510000.00'))
        self.assertEqual(etat.salaire_net, Decimal('530000.00'))
        self.assertEqual(
            sum(
                (detail.heures_realisees for detail in etat.details_heures.all()),
                Decimal('0'),
            ),
            Decimal('42.50'),
        )
        self.assertEqual(enseignant.taux_horaire, Decimal('10000.00'))

    def test_ajustement_pointage_ignore_les_heures_saisies_et_recalcule_le_mois(self):
        enseignant = self.creer_secondaire(taux='10000')
        self.pointer(enseignant, [1, 2], heures=6)
        self.calculer()
        etat = EtatSalaire.objects.get(
            enseignant=enseignant,
            periode=self.periode,
        )

        response = self.client.post(
            reverse('salaires:ajuster_etat_salaire', args=[etat.id]),
            {
                'source_heures': SourceHeuresSalaire.POINTAGE,
                'total_heures': '700',
                'taux_horaire_applique': '11000',
                'primes': '0',
                'deductions': '0',
                'observations': 'Calcul depuis le pointage',
            },
        )

        self.assertEqual(response.status_code, 302)
        etat.refresh_from_db()
        self.assertEqual(etat.source_heures, SourceHeuresSalaire.POINTAGE)
        self.assertEqual(etat.total_heures, Decimal('12.00'))
        self.assertEqual(etat.taux_horaire_applique, Decimal('11000.00'))
        self.assertEqual(etat.salaire_base, Decimal('132000.00'))

    def test_recu_salaire_affiche_le_nombre_de_jours_de_presence(self):
        enseignant = self.creer_fixe()
        etat = EtatSalaire.objects.create(
            enseignant=enseignant,
            periode=self.periode,
            salaire_base=Decimal('1000000'),
            salaire_net=Decimal('1000000'),
            calcule_par=self.user,
        )
        PresenceEnseignant.objects.create(
            enseignant=enseignant,
            date=date(2026, 7, 1),
            statut='PRESENT',
            heures_travaillees=Decimal('8'),
            pointe_par=self.user,
        )
        PresenceEnseignant.objects.create(
            enseignant=enseignant,
            date=date(2026, 7, 2),
            statut='RETARD',
            heures_travaillees=Decimal('4'),
            pointe_par=self.user,
        )
        PresenceEnseignant.objects.create(
            enseignant=enseignant,
            date=date(2026, 7, 3),
            statut='ABSENT',
            pointe_par=self.user,
        )

        self.assertEqual(nombre_jours_presence(enseignant, self.periode), 2)
        with patch(
            'salaires.views.nombre_jours_presence',
            wraps=nombre_jours_presence,
        ) as compteur:
            response = self.client.get(
                reverse('salaires:fiche_paie_pdf', args=[etat.id])
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        compteur.assert_called_once()

    def test_formulaire_presence_sans_heures_ne_plante_plus(self):
        enseignant = self.creer_secondaire()
        form = PresenceForm(
            data={
                'enseignant': enseignant.id,
                'date': '2026-07-01',
                'statut': 'PRESENT',
                'observations': '',
            },
            ecole=self.ecole,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_presence_calcule_les_heures_et_limite_les_statuts_absents(self):
        enseignant = self.creer_secondaire()
        presence = PresenceEnseignant.objects.create(
            enseignant=enseignant,
            date=date(2026, 7, 1),
            statut='PRESENT',
            heure_arrivee=time(8, 0),
            heure_depart=time(16, 30),
            pointe_par=self.user,
        )
        self.assertEqual(presence.heures_travaillees, Decimal('8.50'))

        presence.statut = 'ABSENT'
        with self.assertRaises(ValidationError):
            presence.save()

    def test_creation_periode_regroupe_automatiquement_les_enseignants_actifs(self):
        fixe = self.creer_fixe(nom='Fixe regroupé', salaire='1000000')
        horaire = self.creer_secondaire(nom='Horaire regroupé', taux='10000')
        inactif = self.creer_fixe(nom='En congé')
        inactif.statut = 'CONGE'
        inactif.save(update_fields=['statut'])
        self.creer_fixe(
            nom='Embauché plus tard',
            embauche=date(2026, 9, 1),
        )

        response = self.client.post(
            reverse('salaires:creer_periode'),
            {
                'mois': '8',
                'annee': '2026',
                'ecole': str(self.ecole.id),
                'nombre_semaines': '4.33',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        periode = PeriodeSalaire.objects.get(
            ecole=self.ecole,
            mois=8,
            annee=2026,
        )
        etats = EtatSalaire.objects.filter(periode=periode)
        self.assertEqual(set(etats.values_list('enseignant_id', flat=True)), {fixe.id, horaire.id})
        self.assertEqual(etats.get(enseignant=fixe).salaire_base, Decimal('1000000.00'))
        etat_horaire = etats.get(enseignant=horaire)
        self.assertEqual(etat_horaire.total_heures, Decimal('0.00'))
        self.assertEqual(etat_horaire.salaire_base, Decimal('0.00'))
        self.assertEqual(etat_horaire.source_heures, SourceHeuresSalaire.POINTAGE)
        self.assertContains(response, '2 état(s) de salaire regroupé(s)')

    def test_cloture_regroupe_les_enseignants_dans_la_periode_suivante(self):
        enseignant = self.creer_fixe(nom='Période suivante')

        response = self.client.post(
            reverse('salaires:cloturer_periode', args=[self.periode.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.periode.refresh_from_db()
        self.assertTrue(self.periode.cloturee)
        periode_suivante = PeriodeSalaire.objects.get(
            ecole=self.ecole,
            mois=8,
            annee=2026,
        )
        self.assertTrue(EtatSalaire.objects.filter(
            enseignant=enseignant,
            periode=periode_suivante,
        ).exists())
        self.assertContains(response, '1 enseignant(s) regroupé(s)')

    def test_echec_regroupement_annule_aussi_la_creation_de_periode(self):
        self.creer_fixe(nom='Erreur atomique')

        with patch(
            'salaires.views.calculer_etats_salaire_periode',
            side_effect=RuntimeError('calcul interrompu'),
        ):
            response = self.client.post(
                reverse('salaires:creer_periode'),
                {
                    'mois': '8',
                    'annee': '2026',
                    'ecole': str(self.ecole.id),
                    'nombre_semaines': '4.33',
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(PeriodeSalaire.objects.filter(
            ecole=self.ecole,
            mois=8,
            annee=2026,
        ).exists())

    def test_nombre_semaines_invalide_est_refuse(self):
        response = self.client.post(
            reverse('salaires:creer_periode'),
            {
                'mois': '8',
                'annee': '2026',
                'ecole': str(self.ecole.id),
                'nombre_semaines': '-1',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            PeriodeSalaire.objects.filter(
                ecole=self.ecole, mois=8, annee=2026
            ).exists()
        )

    def test_formulaire_ajustement_refuse_les_valeurs_negatives(self):
        enseignant = self.creer_fixe()
        etat = EtatSalaire.objects.create(
            enseignant=enseignant,
            periode=self.periode,
            salaire_base=Decimal('1000000'),
            salaire_net=Decimal('1000000'),
            calcule_par=self.user,
        )
        form = EtatSalaireAjustementForm(
            data={'primes': '-1', 'deductions': '0', 'observations': ''},
            instance=etat,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('primes', form.errors)

    def test_pages_salaires_modifiees_s_affichent(self):
        """Les gabarits retouchés doivent se rendre sans erreur."""
        enseignant = self.creer_fixe()
        etat = EtatSalaire.objects.create(
            enseignant=enseignant,
            periode=self.periode,
            salaire_base=Decimal('1000000'),
            primes=Decimal('50000'),
            deductions=Decimal('10000'),
            salaire_net=Decimal('0'),
            calcule_par=self.user,
        )

        response = self.client.get(reverse('salaires:etats_salaire'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, enseignant.nom)

        response = self.client.get(
            reverse('salaires:ajuster_etat_salaire', args=[etat.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="primes"')
        self.assertContains(response, 'name="deductions"')

        self.assertEqual(
            self.client.get(reverse('salaires:gestion_periodes')).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse('salaires:pointer_presence')).status_code, 200
        )
