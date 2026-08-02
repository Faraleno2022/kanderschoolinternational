from django.test import TestCase

from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from decimal import Decimal

from eleves.models import Ecole, Classe, Eleve
from .forms import SuiviPapierRamForm
from .models_logistique import BienEtablissement, SuiviPapierRam


class LogistiqueSimplifieeTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='Ecole test', adresse='Conakry', telephone='+224620000001', directeur='Direction'
        )
        self.autre_ecole = Ecole.objects.create(
            nom='Autre ecole', adresse='Conakry', telephone='+224620000002', directeur='Direction'
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='3e A', niveau='COLLEGE_9', annee_scolaire='2026-2027'
        )
        autre_classe = Classe.objects.create(
            ecole=self.autre_ecole, nom='4e B', niveau='COLLEGE_8', annee_scolaire='2026-2027'
        )
        self.eleve = Eleve.objects.create(
            matricule='TST-001', prenom='Aminata', nom='Diallo', sexe='F', classe=self.classe
        )
        self.autre_eleve = Eleve.objects.create(
            matricule='TST-002', prenom='Mamadou', nom='Bah', sexe='M', classe=autre_classe
        )
        self.user = User.objects.create_user('logistique', password='secret')
        profil = self.user.profil
        profil.role = 'ADMIN'
        profil.telephone = '+224620000003'
        profil.ecole = self.ecole
        profil.is_validated = True
        profil.save()

    def test_quantites_bien_et_valeur_totale(self):
        bien = BienEtablissement(
            ecole=self.ecole, code_bien='BIEN-TEST', nom='Marqueurs', type_bien='MARQUEUR',
            localisation='Magasin', quantite_achetee=20, quantite_utilisee=12,
            quantite_gate=3, prix_achat_unitaire=Decimal('5000'),
        )
        bien.full_clean()
        self.assertEqual(bien.quantite_disponible, 5)
        self.assertEqual(bien.valeur_achat_totale, Decimal('100000'))

    def test_un_bien_ne_peut_pas_consommer_plus_que_la_quantite_achetee(self):
        bien = BienEtablissement(
            ecole=self.ecole, code_bien='BIEN-INVALIDE', nom='Tables', type_bien='TABLE',
            localisation='Classe', quantite_achetee=10, quantite_utilisee=8, quantite_gate=3,
        )
        with self.assertRaises(ValidationError):
            bien.full_clean()

    def test_formulaire_ram_ne_propose_que_les_eleves_de_ecole(self):
        form = SuiviPapierRamForm(ecole=self.ecole)
        self.assertIn(self.eleve, form.fields['eleve'].queryset)
        self.assertNotIn(self.autre_eleve, form.fields['eleve'].queryset)

    def test_contributions_papier_et_argent_sont_normalisees(self):
        papier = SuiviPapierRam(
            ecole=self.ecole, eleve=self.eleve, mode='PAPIER', nombre_paquets=2,
            montant_paye=Decimal('25000'), cree_par=self.user,
        )
        papier.full_clean()
        self.assertEqual(papier.montant_paye, Decimal('0'))
        argent = SuiviPapierRam(
            ecole=self.ecole, eleve=self.eleve, mode='ARGENT', nombre_paquets=4,
            montant_paye=Decimal('30000'), cree_par=self.user,
        )
        argent.full_clean()
        self.assertEqual(argent.nombre_paquets, 0)

# Create your tests here.
