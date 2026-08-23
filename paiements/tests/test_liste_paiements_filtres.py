from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eleves.models import Classe, Ecole, Eleve
from paiements.models import (
    EcheancierPaiement, ModePaiement, Paiement, TypePaiement,
)

from .support import TEST_MIDDLEWARE


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ListePaiementsFiltresTests(TestCase):
    def setUp(self):
        self.ecole_1 = Ecole.objects.create(
            nom='École Alpha', adresse='Conakry', telephone='620000811',
            directeur='Direction Alpha',
        )
        self.ecole_2 = Ecole.objects.create(
            nom='École Bêta', adresse='Conakry', telephone='620000812',
            directeur='Direction Bêta',
        )
        self.classe_1 = Classe.objects.create(
            ecole=self.ecole_1, nom='1ÈRE ANNÉE', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.classe_2 = Classe.objects.create(
            ecole=self.ecole_2, nom='1ÈRE ANNÉE', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.especes = ModePaiement.objects.create(nom='Espèces')
        self.cheque = ModePaiement.objects.create(nom='Chèque')
        self.inscription = TypePaiement.objects.create(nom='Inscription filtre')
        self.tranche = TypePaiement.objects.create(nom='Tranche 1 filtre')

        today = timezone.localdate()
        self.retard = self._creer_dossier(
            self.classe_1, 'FIL-RET', Decimal('0'), today - timedelta(days=1),
            self.especes, self.tranche,
        )
        self.reste = self._creer_dossier(
            self.classe_1, 'FIL-RES', Decimal('40000'), today + timedelta(days=1),
            self.cheque, self.tranche,
        )
        self.solde = self._creer_dossier(
            self.classe_1, 'FIL-SOL', Decimal('100000'), today - timedelta(days=1),
            self.especes, self.inscription,
        )
        self.autre_ecole = self._creer_dossier(
            self.classe_2, 'FIL-AUT', Decimal('100000'), today - timedelta(days=1),
            self.especes, self.inscription,
        )

        self.user = get_user_model().objects.create_superuser(
            username='admin_filtres_paiements',
            email='admin.filtres.paiements@example.com',
            password='pass12345',
        )
        self.client.force_login(self.user)
        self.url = reverse('paiements:liste_paiements')

    def _creer_dossier(self, classe, matricule, montant_paye, echeance, mode, nature):
        eleve = Eleve.objects.create(
            matricule=matricule, prenom='Élève', nom=matricule,
            sexe='F', date_naissance=date(2018, 1, 1),
            lieu_naissance='Conakry', classe=classe,
            date_inscription=date(2025, 9, 1),
        )
        EcheancierPaiement.objects.create(
            eleve=eleve, annee_scolaire='2025-2026',
            frais_inscription_du=Decimal('0'),
            tranche_1_due=Decimal('100000'),
            tranche_1_payee=montant_paye,
            date_echeance_inscription=echeance,
            date_echeance_tranche_1=echeance,
            date_echeance_tranche_2=echeance,
            date_echeance_tranche_3=echeance,
        )
        return Paiement.objects.create(
            eleve=eleve, type_paiement=nature, mode_paiement=mode,
            montant=max(montant_paye, Decimal('1000')),
            date_paiement=date(2026, 8, 20), statut='VALIDE',
        )

    @staticmethod
    def _ids(response):
        return {
            paiement.id for paiement in response.context['page_obj'].object_list
        }

    @staticmethod
    def _zone_recherche(response):
        """Isole la zone de recherche, où les filtres doivent être visibles."""
        html = response.content.decode('utf-8')
        debut = html.index('<div class="search-card">')
        return html[debut:html.index('id="paiements-results"', debut)]

    def test_la_zone_de_recherche_expose_les_quatre_filtres(self):
        response = self.client.get(self.url)
        zone = self._zone_recherche(response)

        for identifiant, libelle, defaut in (
            ('filtreClasseRapide', 'Classe', 'Toutes les classes'),
            ('filtreNiveauRapide', 'Niveau de paiement', 'Tous'),
            ('filtreModeRapide', 'Type de paiement (mode)', 'Tous les modes'),
            ('filtreNatureRapide', 'Nature (type)', 'Toutes les natures'),
        ):
            self.assertIn(f'id="{identifiant}"', zone)
            self.assertIn(libelle, zone)
            self.assertIn(f'>{defaut}</option>', zone)

    def test_les_filtres_de_la_zone_de_recherche_gardent_la_selection(self):
        response = self.client.get(self.url, {
            'classe': self.classe_1.id,
            'niveau': 'RESTE',
            'mode': self.cheque.id,
            'nature': self.tranche.id,
        })
        zone = self._zone_recherche(response)

        # Sans cela, appliquer un filtre puis en changer un autre effacerait
        # silencieusement le premier.
        self.assertIn(f'value="{self.classe_1.id}" selected', zone)
        self.assertIn('value="RESTE" selected', zone)
        self.assertIn(f'value="{self.cheque.id}" selected', zone)
        self.assertIn(f'value="{self.tranche.id}" selected', zone)
        self.assertNotIn('type="hidden" name="classe"', zone)

    def test_modal_affiche_les_cinq_filtres_et_distingue_les_classes(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="filtresModal"')
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'name="classe"')
        self.assertContains(response, 'name="niveau"')
        self.assertContains(response, 'name="mode"')
        self.assertContains(response, 'name="nature"')
        self.assertEqual(len(response.context['classes_filtre']), 2)
        self.assertEqual(
            {classe.ecole_id for classe in response.context['classes_filtre']},
            {self.ecole_1.id, self.ecole_2.id},
        )

    def test_classe_mode_et_nature_filtrent_reellement_la_liste(self):
        classe = self.client.get(self.url, {'classe': self.classe_1.id})
        self.assertEqual(
            self._ids(classe), {self.retard.id, self.reste.id, self.solde.id},
        )

        mode = self.client.get(self.url, {
            'classe': self.classe_1.id, 'mode': self.cheque.id,
        })
        self.assertEqual(self._ids(mode), {self.reste.id})

        nature = self.client.get(self.url, {
            'classe': self.classe_1.id, 'nature': self.inscription.id,
        })
        self.assertEqual(self._ids(nature), {self.solde.id})

    def test_niveaux_retard_reste_et_solde_utilisent_le_solde_reel(self):
        commun = {'classe': self.classe_1.id}

        retard = self.client.get(self.url, {**commun, 'niveau': 'RETARD'})
        self.assertEqual(self._ids(retard), {self.retard.id})

        reste = self.client.get(self.url, {**commun, 'niveau': 'RESTE'})
        self.assertEqual(self._ids(reste), {self.retard.id, self.reste.id})

        solde = self.client.get(self.url, {**commun, 'niveau': 'SOLDE'})
        self.assertEqual(self._ids(solde), {self.solde.id})

    def test_les_filtres_restent_dans_la_pagination(self):
        response = self.client.get(self.url, {
            'classe': self.classe_1.id,
            'niveau': 'RESTE',
            'mode': self.especes.id,
            'nature': self.tranche.id,
        })

        query = response.context['filter_query']
        self.assertIn(f'classe={self.classe_1.id}', query)
        self.assertIn('niveau=RESTE', query)
        self.assertIn(f'mode={self.especes.id}', query)
        self.assertIn(f'nature={self.tranche.id}', query)
