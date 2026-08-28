"""Descente rapide des données du serveur vers le poste hors-ligne.

Trois défauts se cumulaient : `pull` ne renvoyait que les changements poussés
par un autre poste, jamais ceux nés de l'usage web du serveur ; le poste ne
mémorisait pas son repère et repartait du début à chaque passage ; et rien ne
tournait tout seul, donc rien ne descendait « dès l'ajout ».
"""

import time
from datetime import date
from threading import Thread

from django.db import connection
from django.test import (
    Client, TestCase, TransactionTestCase, override_settings,
)
from django.urls import reverse

from eleves.models import Classe, Ecole, Eleve
from synchronisation.models import SyncChange, SyncCursor, SyncDevice


class BaseSync(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Sync', adresse='Conakry', telephone='620000941',
            directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='CP1', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.device = SyncDevice(ecole=self.ecole, nom='Poste caisse')
        self.device.definir_token('jeton-secret')
        self.device.save()
        self.url = reverse('synchronisation:pull')

    def _entetes(self, device=None):
        device = device or self.device
        return {
            'HTTP_X_SYNC_DEVICE': str(device.device_id),
            'HTTP_X_SYNC_TOKEN': 'jeton-secret',
        }

    def _creer_eleve(self, matricule):
        """Une saisie web ordinaire : les signaux journalisent le changement."""
        return Eleve.objects.create(
            matricule=matricule, prenom='Élève', nom=matricule, sexe='F',
            date_naissance=date(2016, 1, 1), lieu_naissance='Conakry',
            classe=self.classe, date_inscription=date(2025, 9, 1),
        )

    def _pull(self, **params):
        return self.client.get(self.url, params, **self._entetes())


class DonneesDuServeurTests(BaseSync):
    def test_une_saisie_sur_le_serveur_descend_vers_le_poste(self):
        self._creer_eleve('SYN-001')

        reponse = self._pull()

        corps = reponse.json()
        self.assertTrue(corps['ok'])
        modeles = {change['model_label'] for change in corps['changes']}
        self.assertIn('eleves.Eleve', modeles)

    def test_les_changements_en_echec_ne_sont_pas_transmis(self):
        self._creer_eleve('SYN-002')
        SyncChange.objects.filter(model_label='eleves.Eleve').update(
            statut=SyncChange.STATUT_FAILED, erreur='cassé',
        )

        corps = self._pull().json()

        modeles = {change['model_label'] for change in corps['changes']}
        self.assertNotIn('eleves.Eleve', modeles)

    def test_un_poste_ne_recoit_pas_ses_propres_changements(self):
        self._creer_eleve('SYN-003')
        SyncChange.objects.filter(model_label='eleves.Eleve').update(device=self.device)

        corps = self._pull().json()

        modeles = {change['model_label'] for change in corps['changes']}
        self.assertNotIn('eleves.Eleve', modeles)

    def test_le_repere_evite_de_tout_retelecharger(self):
        self._creer_eleve('SYN-004')
        premier = self._pull().json()
        repere = premier['latest_change_id']
        self.assertGreater(repere, 0)

        vide = self._pull(since_id=repere).json()
        self.assertEqual(vide['changes'], [])
        self.assertEqual(vide['latest_change_id'], repere)

        self._creer_eleve('SYN-005')
        suite = self._pull(since_id=repere).json()
        self.assertTrue(suite['changes'])
        self.assertTrue(
            all(change['id'] > repere for change in suite['changes']),
            "Aucun changement déjà connu ne doit être renvoyé.",
        )

    def test_l_instantane_initial_pose_le_repere(self):
        """Sans repère, le poste retéléchargerait tout au passage suivant."""
        self._creer_eleve('SYN-006')

        corps = self._pull(initial='1').json()

        self.assertTrue(corps['initial'])
        self.assertGreater(corps['latest_change_id'], 0)

    def test_le_poste_sait_qu_il_reste_des_lots(self):
        for numero in range(205):
            SyncChange.objects.create(
                ecole=self.ecole, model_label='eleves.Eleve',
                operation=SyncChange.OPERATION_UPDATE, payload={'n': numero},
            )

        corps = self._pull().json()

        self.assertEqual(len(corps['changes']), 200)
        self.assertTrue(corps['has_more'])


@override_settings(
    MYSCHOOL_SYNC_LONGPOLL_MAX=3,
    MYSCHOOL_SYNC_LONGPOLL_INTERVAL=0.05,
)
class AttenteLongueTests(BaseSync):
    """Le poste part d'un repère à jour : sans cela il n'attendrait jamais."""

    def setUp(self):
        super().setUp()
        self.repere = self._pull().json()['latest_change_id']

    def test_l_attente_expire_proprement_sans_changement(self):
        depart = time.monotonic()

        corps = self._pull(since_id=self.repere, wait='1').json()

        self.assertTrue(corps['ok'])
        self.assertEqual(corps['changes'], [])
        self.assertGreaterEqual(time.monotonic() - depart, 0.5)

    def test_l_attente_est_plafonnee(self):
        """Une valeur absurde ne doit pas immobiliser un thread du serveur."""
        depart = time.monotonic()

        self._pull(since_id=self.repere, wait='9999')

        self.assertLess(time.monotonic() - depart, 10)

    def test_c_est_bien_le_parametre_wait_qui_retient_la_reponse(self):
        """Comparaison relative : un seuil en secondes ne mesurerait que la machine."""
        self._pull(since_id=self.repere)  # chauffe le client de test

        depart = time.monotonic()
        self._pull(since_id=self.repere)
        sans_attente = time.monotonic() - depart

        depart = time.monotonic()
        self._pull(since_id=self.repere, wait='2')
        avec_attente = time.monotonic() - depart

        self.assertLess(sans_attente, avec_attente)
        self.assertGreaterEqual(avec_attente - sans_attente, 1)


@override_settings(
    MYSCHOOL_SYNC_LONGPOLL_MAX=30,
    MYSCHOOL_SYNC_LONGPOLL_INTERVAL=0.05,
)
class AttenteDebloqueeTests(TransactionTestCase):
    """La requête retenue doit rendre la main à l'ajout, pas à l'expiration.

    `TransactionTestCase` est indispensable ici : le thread qui interroge
    utilise sa propre connexion, et ne verrait jamais une écriture restée
    dans la transaction de test.
    """

    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Attente', adresse='Conakry', telephone='620000943',
            directeur='Direction',
        )
        self.classe = Classe.objects.create(
            ecole=self.ecole, nom='CP1', niveau='PRIMAIRE_1',
            annee_scolaire='2025-2026',
        )
        self.device = SyncDevice(ecole=self.ecole, nom='Poste caisse')
        self.device.definir_token('jeton-secret')
        self.device.save()
        self.entetes = {
            'HTTP_X_SYNC_DEVICE': str(self.device.device_id),
            'HTTP_X_SYNC_TOKEN': 'jeton-secret',
        }
        self.url = reverse('synchronisation:pull')
        self.repere = Client().get(self.url, **self.entetes).json()['latest_change_id']

    def test_la_requete_rend_la_main_des_qu_un_changement_arrive(self):
        resultat = {}

        def interroger():
            # Le chronometre entoure la seule requete retenue. Mesurer le
            # thread entier reviendrait a chronometrer son demarrage et la
            # charge de la machine, pas le deblocage.
            try:
                depart = time.monotonic()
                resultat['corps'] = Client().get(
                    self.url,
                    {'since_id': self.repere, 'wait': '30'},
                    **self.entetes
                ).json()
                resultat['duree'] = time.monotonic() - depart
            finally:
                connection.close()

        # Rien n'attend le poste au moment ou il se met a l'ecoute : ce que la
        # requete rapportera ne peut donc venir que de l'ajout qui suit.
        self.assertEqual(
            Client().get(
                self.url, {'since_id': self.repere}, **self.entetes
            ).json()['changes'],
            [],
        )

        ecoute = Thread(target=interroger)
        ecoute.start()
        time.sleep(0.3)
        Eleve.objects.create(
            matricule='SYN-ATT', prenom='Élève', nom='Attente', sexe='F',
            date_naissance=date(2016, 1, 1), lieu_naissance='Conakry',
            classe=self.classe, date_inscription=date(2025, 9, 1),
        )
        ecoute.join(timeout=60)

        self.assertIn('corps', resultat, "La requête retenue n'a jamais répondu.")
        self.assertTrue(
            resultat['corps']['changes'],
            "Le changement ajouté pendant l'attente doit être renvoyé.",
        )
        self.assertLess(
            resultat['duree'], 25,
            "La réponse doit arriver à l'ajout, pas à l'expiration des 30 s.",
        )


class CurseurTests(TestCase):
    def setUp(self):
        self.ecole = Ecole.objects.create(
            nom='École Curseur', adresse='Conakry', telephone='620000942',
            directeur='Direction',
        )

    def test_le_curseur_avance(self):
        curseur = SyncCursor.objects.create(ecole=self.ecole)

        self.assertTrue(curseur.avancer(42))
        curseur.refresh_from_db()
        self.assertEqual(curseur.server_change_id, 42)
        self.assertIsNotNone(curseur.derniere_synchro)

    def test_le_curseur_ne_recule_jamais(self):
        """Un lot hors séquence ferait sinon rejouer des changements déjà appliqués."""
        curseur = SyncCursor.objects.create(ecole=self.ecole, server_change_id=100)

        self.assertFalse(curseur.avancer(50))
        curseur.refresh_from_db()
        self.assertEqual(curseur.server_change_id, 100)

    def test_un_seul_curseur_par_ecole(self):
        SyncCursor.objects.create(ecole=self.ecole)
        curseur, cree = SyncCursor.objects.get_or_create(ecole=self.ecole)

        self.assertFalse(cree)
        self.assertEqual(SyncCursor.objects.filter(ecole=self.ecole).count(), 1)
