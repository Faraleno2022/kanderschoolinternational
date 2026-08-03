from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eleves.models import Classe, Ecole, Eleve

from .models_bibliotheque import CategorieLivre, Emprunt, Livre, Reservation


TEST_MIDDLEWARE = [
    middleware
    for middleware in settings.MIDDLEWARE
    if middleware != 'ecole_moderne.licence_middleware.LicenceMiddleware'
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE)
class ReservationBibliothequeTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École bibliothèque',
            adresse='Conakry',
            telephone='+224620000021',
            directeur='Direction',
        )
        self.autre_ecole = Ecole.objects.create(
            nom='Autre école bibliothèque',
            adresse='Conakry',
            telephone='+224620000022',
            directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole,
            nom='7e A',
            niveau='COLLEGE_7',
            annee_scolaire='2026-2027',
        )
        self.autre_classe = Classe.objects.create(
            ecole=self.autre_ecole,
            nom='8e B',
            niveau='COLLEGE_8',
            annee_scolaire='2026-2027',
        )
        self.eleve = Eleve.objects.create(
            matricule='BIB-001',
            prenom='Aminata',
            nom='Diallo',
            sexe='F',
            classe=self.classe,
        )
        self.eleve_2 = Eleve.objects.create(
            matricule='BIB-002',
            prenom='Mamadou',
            nom='Bah',
            sexe='M',
            classe=self.classe,
        )
        self.eleve_autre = Eleve.objects.create(
            matricule='BIB-003',
            prenom='Ibrahima',
            nom='Camara',
            sexe='M',
            classe=self.autre_classe,
        )
        self.user = User.objects.create_user('bibliothecaire', password='secret')
        profil = self.user.profil
        profil.role = 'ADMIN'
        profil.telephone = '+224620000023'
        profil.ecole = self.ecole
        profil.is_validated = True
        profil.save()
        self.autre_user = User.objects.create_user('autre-bibliothecaire', password='secret')
        autre_profil = self.autre_user.profil
        autre_profil.role = 'ADMIN'
        autre_profil.telephone = '+224620000024'
        autre_profil.ecole = self.autre_ecole
        autre_profil.is_validated = True
        autre_profil.save()

        self.categorie = CategorieLivre.objects.create(nom='Roman', code='ROMAN')
        self.livre = Livre.objects.create(
            code_livre='LIV-001',
            titre='Le Petit Prince',
            auteur='Antoine de Saint-Exupéry',
            categorie=self.categorie,
            emplacement='Rayon A',
            nombre_exemplaires=1,
            exemplaires_disponibles=1,
            statut='DISPONIBLE',
            cree_par=self.user,
        )
        self.livre_autre = Livre.objects.create(
            code_livre='LIV-002',
            titre='Livre autre école',
            auteur='Auteur',
            categorie=self.categorie,
            emplacement='Rayon B',
            nombre_exemplaires=1,
            exemplaires_disponibles=1,
            statut='DISPONIBLE',
            cree_par=self.autre_user,
        )
        self.client.force_login(self.user)

    def creer_reservation(self, livre=None, eleve=None, duree=7):
        return self.client.post(
            reverse('depenses:creer_reservation'),
            {
                'livre': (livre or self.livre).pk,
                'eleve': (eleve or self.eleve).pk,
                'duree_jours': duree,
                'observations': 'Demande du parent',
            },
        )

    def test_creation_met_un_exemplaire_disponible_de_cote(self):
        response = self.creer_reservation()

        self.assertRedirects(response, reverse('depenses:liste_reservations'))
        reservation = Reservation.objects.get(livre=self.livre, eleve=self.eleve)
        self.assertEqual(reservation.statut, 'DISPONIBLE')
        self.assertTrue(reservation.exemplaire_bloque)
        self.assertIsNotNone(reservation.date_mise_disponible)
        self.livre.refresh_from_db()
        self.assertEqual(self.livre.exemplaires_disponibles, 0)
        self.assertEqual(self.livre.statut, 'RESERVE')

    def test_livre_indisponible_place_la_reservation_en_file_attente(self):
        self.livre.exemplaires_disponibles = 0
        self.livre.statut = 'EMPRUNTE'
        self.livre.save()

        self.creer_reservation(eleve=self.eleve)
        self.creer_reservation(eleve=self.eleve_2)

        premiere = Reservation.objects.get(eleve=self.eleve)
        seconde = Reservation.objects.get(eleve=self.eleve_2)
        self.assertEqual(premiere.statut, 'EN_ATTENTE')
        self.assertFalse(premiere.exemplaire_bloque)
        self.assertEqual(premiere.rang_attente, 1)
        self.assertEqual(seconde.rang_attente, 2)

    def test_annulation_reattribue_exemplaire_au_premier_en_attente(self):
        self.creer_reservation(eleve=self.eleve)
        premiere = Reservation.objects.get(eleve=self.eleve)
        self.creer_reservation(eleve=self.eleve_2)
        seconde = Reservation.objects.get(eleve=self.eleve_2)

        response = self.client.post(
            reverse('depenses:annuler_reservation', args=[premiere.pk])
        )

        self.assertRedirects(response, reverse('depenses:liste_reservations'))
        premiere.refresh_from_db()
        seconde.refresh_from_db()
        self.livre.refresh_from_db()
        self.assertEqual(premiere.statut, 'ANNULEE')
        self.assertEqual(seconde.statut, 'DISPONIBLE')
        self.assertTrue(seconde.exemplaire_bloque)
        self.assertEqual(self.livre.exemplaires_disponibles, 0)
        self.assertEqual(self.livre.statut, 'RESERVE')

    def test_conversion_reservation_cree_emprunt_sans_double_decompter_stock(self):
        self.creer_reservation()
        reservation = Reservation.objects.get(eleve=self.eleve)

        response = self.client.post(
            reverse('depenses:emprunter_reservation', args=[reservation.pk])
        )

        self.assertRedirects(response, reverse('depenses:liste_emprunts'))
        reservation.refresh_from_db()
        self.livre.refresh_from_db()
        self.assertEqual(reservation.statut, 'EMPRUNTEE')
        self.assertFalse(reservation.exemplaire_bloque)
        self.assertIsNotNone(reservation.emprunt)
        self.assertEqual(Emprunt.objects.filter(livre=self.livre).count(), 1)
        self.assertEqual(self.livre.exemplaires_disponibles, 0)
        self.assertEqual(self.livre.statut, 'EMPRUNTE')

    def test_retour_livre_promeut_automatiquement_file_attente(self):
        self.livre.exemplaires_disponibles = 0
        self.livre.statut = 'EMPRUNTE'
        self.livre.save()
        emprunt = Emprunt.objects.create(
            numero_emprunt='EMP-TEST-001',
            livre=self.livre,
            eleve=self.eleve,
            date_retour_prevue=timezone.localdate() + timedelta(days=7),
            cree_par=self.user,
        )
        self.creer_reservation(eleve=self.eleve_2)
        reservation = Reservation.objects.get(eleve=self.eleve_2)

        response = self.client.post(
            reverse('depenses:retourner_livre', args=[emprunt.pk]),
            {'etat_retour': 'BON', 'observations': ''},
        )

        self.assertRedirects(response, reverse('depenses:liste_emprunts'))
        reservation.refresh_from_db()
        self.livre.refresh_from_db()
        self.assertEqual(reservation.statut, 'DISPONIBLE')
        self.assertTrue(reservation.exemplaire_bloque)
        self.assertEqual(self.livre.exemplaires_disponibles, 0)
        self.assertEqual(self.livre.statut, 'RESERVE')

    def test_expiration_libere_exemplaire_bloque(self):
        self.creer_reservation()
        reservation = Reservation.objects.get(eleve=self.eleve)
        reservation.date_expiration = timezone.now() - timedelta(minutes=1)
        reservation.save()

        response = self.client.get(reverse('depenses:liste_reservations'))

        self.assertEqual(response.status_code, 200)
        reservation.refresh_from_db()
        self.livre.refresh_from_db()
        self.assertEqual(reservation.statut, 'EXPIREE')
        self.assertFalse(reservation.exemplaire_bloque)
        self.assertEqual(self.livre.exemplaires_disponibles, 1)
        self.assertEqual(self.livre.statut, 'DISPONIBLE')

    def test_ecole_ne_peut_pas_reserver_livre_ou_eleve_autre_ecole(self):
        response_livre = self.creer_reservation(livre=self.livre_autre)
        response_eleve = self.creer_reservation(eleve=self.eleve_autre)

        self.assertEqual(response_livre.status_code, 404)
        self.assertEqual(response_eleve.status_code, 404)
        self.assertFalse(Reservation.objects.exists())
