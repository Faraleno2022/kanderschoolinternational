from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bus.models import AbonnementBus, AbonnementCantine
from eleves.models import Classe, Ecole, Eleve, Responsable
from paiements.models import EcheancierPaiement, ModePaiement, Paiement, TypePaiement
from paiements.views import _compute_stats
from utilisateurs.models import Profil

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class TableauBordCategoriesTests(TestCase):
    today = date(2026, 8, 26)  # mercredi

    def setUp(self):
        self.ecole = self._school("École tableau de bord", "+224620001001")
        self.other_school = self._school("École hors périmètre", "+224620001002")
        self.classe = Classe.objects.create(
            ecole=self.ecole,
            nom="1ère année",
            niveau="PRIMAIRE_1",
            annee_scolaire="2026-2027",
        )
        self.other_class = Classe.objects.create(
            ecole=self.other_school,
            nom="Classe externe",
            niveau="PRIMAIRE_1",
            annee_scolaire="2026-2027",
        )
        self.responsable = Responsable.objects.create(
            prenom="Parent",
            nom="Dashboard",
            relation="PERE",
            telephone="+224620001003",
            adresse="Conakry",
        )
        self.mode = ModePaiement.objects.create(nom="Espèces dashboard")
        self.type_inscription = TypePaiement.objects.create(
            nom="Inscription + Tranche 1 dashboard",
        )
        self.type_reinscription = TypePaiement.objects.create(
            nom="Réinscription + Tranche 1 dashboard",
        )

        user = get_user_model().objects.create_user(
            username="comptable_dashboard",
            password="pass12345",
        )
        Profil.objects.update_or_create(
            user=user,
            defaults={
                'role': 'COMPTABLE',
                'ecole': self.ecole,
                'telephone': '+224620001004',
                'is_validated': True,
            },
        )
        # Le signal de création a pu mettre en cache le profil initial sans
        # école sur l'instance User ; le recharger reproduit l'état d'une requête.
        user.refresh_from_db()
        self.user = user
        self.client.force_login(user)

        self._create_financial_data()
        self._create_bus_and_cantine_data()

    @staticmethod
    def _school(name, phone):
        return Ecole.objects.create(
            nom=name,
            adresse="Conakry",
            telephone=phone,
            directeur="Direction",
        )

    def _student(self, suffix, classe=None):
        return Eleve.objects.create(
            matricule=f"DASH-{suffix}",
            prenom="Élève",
            nom=suffix,
            sexe="F",
            date_naissance=date(2018, 1, 1),
            lieu_naissance="Conakry",
            classe=classe or self.classe,
            date_inscription=date(2026, 7, 1),
            responsable_principal=self.responsable,
        )

    def _schedule(
        self,
        student,
        admission,
        tranche_1,
        *,
        nature=EcheancierPaiement.NATURE_INSCRIPTION,
        admission_paid=0,
        tranche_1_paid=0,
        tranche_2=0,
        tranche_2_paid=0,
        admission_due_date=None,
        tranche_1_due_date=None,
        tranche_2_due_date=None,
    ):
        return EcheancierPaiement.objects.create(
            eleve=student,
            annee_scolaire="2026-2027",
            nature_frais=nature,
            frais_inscription_du=Decimal(admission),
            tranche_1_due=Decimal(tranche_1),
            tranche_2_due=Decimal(tranche_2),
            frais_inscription_paye=Decimal(admission_paid),
            tranche_1_payee=Decimal(tranche_1_paid),
            tranche_2_payee=Decimal(tranche_2_paid),
            date_echeance_inscription=admission_due_date or self.today - timedelta(days=60),
            date_echeance_tranche_1=tranche_1_due_date or self.today - timedelta(days=30),
            date_echeance_tranche_2=tranche_2_due_date or self.today + timedelta(days=60),
            date_echeance_tranche_3=self.today + timedelta(days=120),
        )

    def _payment(self, student, payment_type, amount, payment_date, status="VALIDE"):
        return Paiement.objects.create(
            eleve=student,
            type_paiement=payment_type,
            mode_paiement=self.mode,
            montant=Decimal(amount),
            date_paiement=payment_date,
            statut=status,
        )

    def _create_financial_data(self):
        today_student = self._student("AUJOURDHUI")
        self._schedule(
            today_student, "50000", "500000",
            admission_paid="50000", tranche_1_paid="500000",
            tranche_2="500000", tranche_2_due_date=self.today - timedelta(days=1),
        )
        self._payment(
            today_student, self.type_inscription, "550000", self.today,
        )

        week_student = self._student("SEMAINE")
        self._schedule(
            week_student, "30000", "400000",
            nature=EcheancierPaiement.NATURE_REINSCRIPTION,
            admission_paid="30000", tranche_1_paid="200000",
        )
        self._payment(
            week_student,
            self.type_reinscription,
            "230000",
            self.today - timedelta(days=2),
        )

        month_student = self._student("MOIS")
        self._schedule(
            month_student, "40000", "60000",
            admission_paid="40000", tranche_1_paid="60000",
        )
        self._payment(
            month_student, self.type_inscription, "100000", date(2026, 8, 5),
        )

        year_student = self._student("ANNEE")
        self._schedule(
            year_student, "20000", "100000",
            nature=EcheancierPaiement.NATURE_REINSCRIPTION,
            admission_paid="20000", tranche_1_paid="100000",
        )
        self._payment(
            year_student, self.type_reinscription, "120000", date(2026, 7, 10),
        )

        due_today_student = self._student("ECHEANCE-AUJOURDHUI")
        self._schedule(
            due_today_student, "70000", "0",
            admission_due_date=self.today,
            tranche_1_due_date=self.today + timedelta(days=30),
        )

        # Un paiement rejeté ne doit alimenter aucune carte d'encaissement.
        self._payment(
            month_student, self.type_inscription, "999999", self.today, "REJETE",
        )

        other_student = self._student("AUTRE-ECOLE", self.other_class)
        self._schedule(
            other_student, "90000", "410000",
            admission_due_date=self.today - timedelta(days=1),
        )
        self._payment(
            other_student, self.type_inscription, "500000", self.today,
        )

    def _set_created_at(self, model, pk, day):
        moment = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        model.objects.filter(pk=pk).update(created_at=moment)

    def _create_bus_and_cantine_data(self):
        student = Eleve.objects.get(matricule="DASH-AUJOURDHUI")
        bus_today = AbonnementBus.objects.create(
            eleve=student,
            montant=Decimal("100000"),
            date_debut=self.today,
            date_expiration=self.today + timedelta(days=30),
        )
        self._set_created_at(AbonnementBus, bus_today.pk, self.today)
        bus_month = AbonnementBus.objects.create(
            eleve=student,
            montant=Decimal("50000"),
            date_debut=date(2026, 8, 5),
            date_expiration=date(2026, 9, 5),
        )
        self._set_created_at(AbonnementBus, bus_month.pk, date(2026, 8, 5))

        cantine_week = AbonnementCantine.objects.create(
            eleve=student,
            montant=Decimal("60000"),
            date_debut=self.today - timedelta(days=2),
            date_expiration=self.today + timedelta(days=28),
        )
        self._set_created_at(
            AbonnementCantine, cantine_week.pk, self.today - timedelta(days=2),
        )

        other_student = Eleve.objects.get(matricule="DASH-AUTRE-ECOLE")
        other_bus = AbonnementBus.objects.create(
            eleve=other_student,
            montant=Decimal("900000"),
            date_debut=self.today,
            date_expiration=self.today + timedelta(days=30),
        )
        self._set_created_at(AbonnementBus, other_bus.pk, self.today)

    @patch("django.utils.timezone.localdate")
    def test_categories_sont_ventilees_par_periode_et_par_ecole(self, localdate):
        localdate.return_value = self.today

        stats = _compute_stats(self.user)

        self.assertEqual(
            stats['categories']['scolarite'],
            {'today': 500000, 'week': 700000, 'month': 760000, 'year': 860000},
        )
        self.assertEqual(
            stats['categories']['inscription'],
            {'today': 50000, 'week': 50000, 'month': 90000, 'year': 90000},
        )
        self.assertEqual(
            stats['categories']['reinscription'],
            {'today': 0, 'week': 30000, 'month': 30000, 'year': 50000},
        )
        self.assertEqual(
            stats['categories']['bus'],
            {'today': 100000, 'week': 100000, 'month': 150000, 'year': 150000},
        )
        self.assertEqual(
            stats['categories']['cantine'],
            {'today': 0, 'week': 60000, 'month': 60000, 'year': 60000},
        )

    @patch("django.utils.timezone.localdate")
    def test_retard_exclut_echeance_du_jour_et_autre_ecole(self, localdate):
        localdate.return_value = self.today

        stats = _compute_stats(self.user)

        self.assertEqual(stats['eleves_en_retard'], 2)
        self.assertEqual(stats['montant_en_retard'], 700000)

    @patch("django.utils.timezone.localdate")
    def test_page_et_ajax_exposent_les_memes_statistiques(self, localdate):
        localdate.return_value = self.today

        response = self.client.get(reverse('paiements:tableau_bord'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Encaissements par catégorie')
        self.assertContains(response, 'Bus scolaire')
        self.assertContains(response, 'Cantine')
        self.assertEqual(response.context['stats']['categories']['scolarite']['today'], 500000)

        ajax = self.client.get(reverse('paiements:ajax_statistiques_paiements'))
        self.assertEqual(ajax.status_code, 200)
        payload = ajax.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['stats']['categories']['reinscription']['week'], 30000)
        self.assertEqual(payload['stats']['montant_en_retard'], 700000)
