"""Fermeture des sessions restées inactives.

Le contrôle existait mais ne s'exécutait jamais : `SessionSecurityMiddleware`
était inséré par position numérique, donc avant `SessionMiddleware` et
`AuthenticationMiddleware`. Son garde `hasattr(request, 'user')` échouait
silencieusement et laissait toutes les sessions ouvertes.
"""

import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

MIDDLEWARE_PRODUCTION = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'ecole_moderne.security_middleware.SessionSecurityMiddleware',
]


class OrdreDesMiddlewaresTests(TestCase):
    """L'ordre est la condition de fonctionnement, pas un détail de style."""

    @staticmethod
    def _middleware_production():
        import importlib
        import os

        ancien_debug = os.environ.get('DJANGO_DEBUG')
        os.environ['DJANGO_DEBUG'] = 'false'
        try:
            module = importlib.import_module('ecole_moderne.settings')
            module = importlib.reload(module)
            return list(module.MIDDLEWARE)
        finally:
            if ancien_debug is None:
                os.environ.pop('DJANGO_DEBUG', None)
            else:
                os.environ['DJANGO_DEBUG'] = ancien_debug
            importlib.reload(importlib.import_module('ecole_moderne.settings'))

    def test_le_controle_de_session_tourne_apres_authentification(self):
        middleware = self._middleware_production()

        position = middleware.index(
            'ecole_moderne.security_middleware.SessionSecurityMiddleware'
        )
        for prealable in (
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware',
            # Après les messages, pour pouvoir expliquer la déconnexion.
            'django.contrib.messages.middleware.MessageMiddleware',
        ):
            self.assertLess(
                middleware.index(prealable), position,
                f"{prealable} doit précéder le contrôle de session.",
            )


@override_settings(
    MIDDLEWARE=MIDDLEWARE_PRODUCTION,
    SESSION_INACTIVITY_TIMEOUT=1800,
    PHONE_VERIFY_ENFORCED=False,
)
class SessionInactiveTests(TestCase):
    def setUp(self):
        self.utilisateur = get_user_model().objects.create_user(
            username='agent_inactif', password='pass12345',
        )
        self.client.force_login(self.utilisateur)
        self.url = reverse('paiements:liste_paiements')
        self.login_url = reverse('utilisateurs:login')

    def _poser_derniere_activite(self, secondes_avant):
        session = self.client.session
        session['last_activity'] = time.time() - secondes_avant
        session.save()

    def test_une_session_inactive_est_fermee(self):
        self._poser_derniere_activite(1801)

        reponse = self.client.get(self.url)

        self.assertRedirects(
            reponse, self.login_url, fetch_redirect_response=False,
        )
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_une_session_active_est_conservee(self):
        self._poser_derniere_activite(60)

        reponse = self.client.get(self.url)

        self.assertNotEqual(reponse.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_chaque_requete_repousse_l_echeance(self):
        """Travailler doit prolonger la session, pas la laisser expirer."""
        self._poser_derniere_activite(1700)

        self.client.get(self.url)
        derniere = self.client.session.get('last_activity')

        self.assertIsNotNone(derniere)
        self.assertLess(time.time() - derniere, 60)

    def test_la_deconnexion_est_expliquee(self):
        self._poser_derniere_activite(1801)

        reponse = self.client.get(self.url, follow=True)

        textes = [str(message) for message in reponse.context['messages']]
        self.assertTrue(
            any("inactivité" in texte for texte in textes),
            textes,
        )

    def test_une_premiere_requete_sans_repere_ne_deconnecte_pas(self):
        session = self.client.session
        session.pop('last_activity', None)
        session.save()

        reponse = self.client.get(self.url)

        self.assertNotEqual(reponse.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_un_repere_illisible_ne_deconnecte_pas(self):
        session = self.client.session
        session['last_activity'] = 'jamais'
        session.save()

        reponse = self.client.get(self.url)

        self.assertNotEqual(reponse.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    @override_settings(SESSION_INACTIVITY_TIMEOUT=60)
    def test_le_delai_est_configurable(self):
        self._poser_derniere_activite(61)

        reponse = self.client.get(self.url)

        self.assertRedirects(
            reponse, self.login_url, fetch_redirect_response=False,
        )

    def test_un_visiteur_anonyme_traverse_sans_erreur(self):
        self.client.logout()

        reponse = self.client.get(self.url)

        # Redirigé vers la connexion par le décorateur de la vue, pas par une
        # exception du middleware.
        self.assertEqual(reponse.status_code, 302)


@override_settings(MIDDLEWARE=MIDDLEWARE_PRODUCTION)
class VerificationTelephoneTests(TestCase):
    """Le contrôle téléphonique ne doit pas s'activer par effet de bord."""

    def setUp(self):
        self.utilisateur = get_user_model().objects.create_user(
            username='agent_telephone', password='pass12345',
        )
        self.client.force_login(self.utilisateur)
        self.url = reverse('paiements:liste_paiements')

    def test_il_reste_desactive_par_defaut(self):
        self.assertFalse(getattr(settings, 'PHONE_VERIFY_ENFORCED', False))

        reponse = self.client.get(self.url)

        self.assertNotIn('verify-phone', reponse.get('Location', ''))

    @override_settings(PHONE_VERIFY_ENFORCED=True)
    def test_il_s_applique_lorsqu_on_l_active(self):
        reponse = self.client.get(self.url)

        self.assertEqual(reponse.status_code, 302)
        self.assertIn('verify-phone', reponse['Location'])
