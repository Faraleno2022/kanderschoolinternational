from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve, Responsable
from paiements.models import (
    EcheancierPaiement,
    ModePaiement,
    Paiement,
    PaiementRemise,
    Relance,
    RemiseReduction,
    TypePaiement,
)
from utilisateurs.models import Profil

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ComptaTempsReelTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='Ecole temps reel', adresse='Conakry',
            telephone='+224620000101', directeur='Direction',
        )
        self.classe = Classe.objects.create(
            nom='PS A', ecole=self.ecole, niveau='MATERNELLE',
            annee_scolaire='2025-2026',
        )
        responsable = Responsable.objects.create(
            prenom='Parent', nom='Test', relation='PERE',
            telephone='+224620000102', adresse='Conakry',
        )
        self.eleve_impaye = Eleve.objects.create(
            nom='Impaye', prenom='Eleve', matricule='TR-IMP', classe=self.classe,
            sexe='M', date_naissance=date(2021, 1, 1), lieu_naissance='Conakry',
            date_inscription=date(2025, 9, 1), responsable_principal=responsable,
        )
        self.eleve_solde = Eleve.objects.create(
            nom='Solde', prenom='Eleve', matricule='TR-SOL', classe=self.classe,
            sexe='F', date_naissance=date(2021, 2, 1), lieu_naissance='Conakry',
            date_inscription=date(2025, 9, 1), responsable_principal=responsable,
        )

        type_paiement = TypePaiement.objects.create(nom='Frais de scolarite')
        mode = ModePaiement.objects.create(nom='Especes')
        self.paiement_impaye = Paiement.objects.create(
            eleve=self.eleve_impaye, type_paiement=type_paiement, mode_paiement=mode,
            numero_recu='TR0001', montant=Decimal('40'),
            date_paiement=date(2026, 7, 31), statut='VALIDE',
        )
        self.paiement_solde = Paiement.objects.create(
            eleve=self.eleve_solde, type_paiement=type_paiement, mode_paiement=mode,
            numero_recu='TR0002', montant=Decimal('80'),
            date_paiement=date(2026, 7, 31), statut='VALIDE',
        )

        dates = {
            'date_echeance_inscription': date(2025, 9, 1),
            'date_echeance_tranche_1': date(2026, 1, 15),
            'date_echeance_tranche_2': date(2026, 3, 15),
            'date_echeance_tranche_3': date(2026, 5, 15),
        }
        EcheancierPaiement.objects.create(
            eleve=self.eleve_impaye, annee_scolaire='2025-2026',
            frais_inscription_du=Decimal('100'), frais_inscription_paye=Decimal('40'),
            **dates,
        )
        EcheancierPaiement.objects.create(
            eleve=self.eleve_solde, annee_scolaire='2025-2026',
            frais_inscription_du=Decimal('100'), frais_inscription_paye=Decimal('100'),
            **dates,
        )

        for index in range(2):
            remise = RemiseReduction.objects.create(
                nom=f'Remise {index + 1}', type_remise='MONTANT_FIXE',
                valeur=Decimal('10'), motif='AUTRE',
                date_debut=date(2025, 9, 1), date_fin=date(2026, 8, 31),
            )
            PaiementRemise.objects.create(
                paiement=self.paiement_solde, remise=remise, montant_remise=Decimal('10'),
            )

        self.relance = Relance.objects.create(
            eleve=self.eleve_impaye, canal='SMS', statut='ENVOYEE',
            message='Regularisation demandee', solde_estime=Decimal('60'),
        )

        User = get_user_model()
        self.comptable = User.objects.create_user(username='comptable_temps_reel', password='pass12345')
        Profil.objects.update_or_create(
            user=self.comptable,
            defaults={
                'role': 'COMPTABLE', 'ecole': self.ecole,
                'telephone': '+224620000103', 'peut_consulter_rapports': True,
                'is_validated': True,
            },
        )
        self.comptable.refresh_from_db()
        self.client.force_login(self.comptable)

    def test_comptable_voit_les_donnees_sur_tous_les_ecrans(self):
        rapport = self.client.get(reverse('paiements:rapport_comptable'))
        self.assertEqual(rapport.status_code, 200)
        self.assertEqual(rapport.context['nombre_paiements'], 2)
        self.assertEqual(rapport.context['total_paiements'], Decimal('120'))

        impayes = self.client.get(reverse('paiements:liste_eleves_impayes'))
        self.assertEqual(impayes.status_code, 200)
        impayes_ids = [row['eleve'].id for row in impayes.context['eleves_avec_soldes']]
        self.assertIn(self.eleve_impaye.id, impayes_ids)
        self.assertNotIn(self.eleve_solde.id, impayes_ids)

        soldes = self.client.get(reverse('paiements:liste_eleves_soldes'))
        self.assertEqual(soldes.status_code, 200)
        soldes_ids = [item.eleve_id for item in soldes.context['page_obj'].object_list]
        self.assertIn(self.eleve_solde.id, soldes_ids)
        self.assertNotIn(self.eleve_impaye.id, soldes_ids)
        solde = next(item for item in soldes.context['page_obj'].object_list if item.eleve_id == self.eleve_solde.id)
        self.assertEqual(solde.total_du_calc, Decimal('100'))
        self.assertEqual(solde.total_paye_calc, Decimal('100'))
        self.assertEqual(solde.total_remises_calc, Decimal('20'))

        relances = self.client.get(reverse('paiements:liste_relances'))
        self.assertEqual(relances.status_code, 200)
        self.assertIn(self.relance.id, [item.id for item in relances.context['page_obj'].object_list])

        remises = self.client.get(reverse('rapports:rapport_remises'))
        self.assertEqual(remises.status_code, 200)
        self.assertEqual(remises.context['stats_remises']['total_remises'], Decimal('20'))
        self.assertEqual(remises.context['stats_remises']['total_montants_finals'], Decimal('80'))
        self.assertEqual(remises.context['stats_remises']['nombre_paiements_avec_remise'], 1)
