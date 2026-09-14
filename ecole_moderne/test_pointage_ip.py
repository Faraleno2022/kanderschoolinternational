"""Régressions des blocages IP injustifiés et du proxy de production."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.http import HttpResponse
from django.conf import settings
from axes.helpers import get_client_ip_address
from axes.models import AccessAttempt
from django.urls import reverse
from salaires import test_export_presences as export_support
from salaires.models import PresenceEnseignant
from salaires.tests import TEST_MIDDLEWARE
from .security_middleware import SecurityMiddleware, SessionSecurityMiddleware, CSRFSecurityMiddleware
from .security_decorators import get_client_ip as decorator_client_ip
from utilisateurs.security_views import get_client_ip


class PointageMiddlewareTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.middleware = SecurityMiddleware(lambda request: HttpResponse('ok'))
        self.ip = '203.0.113.42'

    def test_observation_normale_pointage_ne_bloque_pas_ip(self):
        for texte in ("Arrivée 08:00 ; départ 16:00", "Présent -- sortie autorisée", "Fin d'absence ; justificatif reçu"):
            with self.subTest(texte=texte):
                cache.clear()
                request = self.factory.post('/salaires/presences/pointer/', {'date':'2026-09-14', 'enseignants':['1'], 'observations_1':texte}, REMOTE_ADDR=self.ip)
                self.assertIsNone(self.middleware.process_request(request))
                self.assertFalse(self.middleware.is_ip_blocked(self.ip))

    def test_parametres_observations_ne_sont_pas_du_javascript(self):
        request = self.factory.get('/salaires/presences/', {'observations':'présent', 'options':'jour'}, REMOTE_ADDR=self.ip)
        self.assertIsNone(self.middleware.process_request(request))
        self.assertFalse(self.middleware.is_ip_blocked(self.ip))

    def test_sql_et_xss_reels_restent_refuses(self):
        for payload in ("' OR 1=1 --", 'UNION SELECT password FROM users', '<img src=x onerror=alert(1)>'):
            with self.subTest(payload=payload):
                cache.clear()
                request = self.factory.post('/salaires/presences/pointer/', {'observations_1':payload}, REMOTE_ADDR=self.ip)
                response = self.middleware.process_request(request)
                self.assertEqual(response.status_code, 403)
                self.assertTrue(self.middleware.is_ip_blocked(self.ip))

    def test_valeurs_get_encodees_et_repetees_restant_protegees(self):
        for payload in ("' OR 1=1 --", '<img src=x onerror=alert(1)>'):
            with self.subTest(payload=payload):
                cache.clear()
                request = self.factory.get('/salaires/presences/', {'observations': [payload, 'présent']}, REMOTE_ADDR=self.ip)
                self.assertEqual(self.middleware.process_request(request).status_code, 403)

    def test_mot_de_passe_complexe_ne_declenche_pas_blocage_ip(self):
        request = self.factory.post('/utilisateurs/login/', {'username': 'test', 'password': "fort;' OR 1=1 --<script>test</script>"}, REMOTE_ADDR=self.ip)
        self.assertIsNone(self.middleware.process_request(request))

    def test_centieme_requete_termine_la_fenetre(self):
        for _ in range(99):
            self.middleware.increment_request_count(self.ip)
        self.assertFalse(self.middleware.is_rate_limited(self.ip))
        self.middleware.increment_request_count(self.ip)
        self.assertTrue(self.middleware.is_rate_limited(self.ip))

    def test_navigation_reguliere_ne_cumule_pas_plusieurs_minutes(self):
        for step in range(130):
            with patch('time.time', return_value=1000 + step * 10):
                self.assertFalse(self.middleware.is_rate_limited(self.ip))
                self.middleware.increment_request_count(self.ip)

    def test_rafale_reste_limitee(self):
        with patch('time.time', return_value=1000):
            for _ in range(101):
                self.middleware.increment_request_count(self.ip)
            self.assertTrue(self.middleware.is_rate_limited(self.ip))
        with patch('time.time', return_value=1061):
            self.assertFalse(self.middleware.is_rate_limited(self.ip))


@override_settings(TRUSTED_PROXY_NETWORKS=['10.0.4.129/32'])
class AdresseClientTests(SimpleTestCase):
    def test_axes_et_connexion_identifient_le_meme_client_du_proxy(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.0.4.129', HTTP_X_REAL_IP='203.0.113.41', HTTP_X_FORWARDED_FOR='198.51.100.50, 203.0.113.41')
        self.assertEqual(get_client_ip(request), '203.0.113.41')
        self.assertEqual(get_client_ip_address(request), '203.0.113.41')
        for middleware in (SecurityMiddleware, SessionSecurityMiddleware, CSRFSecurityMiddleware):
            self.assertEqual(middleware(lambda r: None).get_client_ip(request), '203.0.113.41')
        self.assertEqual(decorator_client_ip(request), '203.0.113.41')

    def test_proxy_sans_x_real_ip_utilise_la_derniere_adresse(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.0.4.129', HTTP_X_FORWARDED_FOR='198.51.100.50, 203.0.113.214')
        self.assertEqual(get_client_ip(request), '203.0.113.214')

    def test_en_tete_falsifie_depuis_un_client_direct_est_ignore(self):
        request = RequestFactory().get('/', REMOTE_ADDR='203.0.113.214', HTTP_X_REAL_IP='127.0.0.1', HTTP_X_FORWARDED_FOR='127.0.0.1')
        self.assertEqual(get_client_ip(request), '203.0.113.214')

    def test_adresse_invalide_du_proxy_revient_a_adresse_reseau(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.0.4.129', HTTP_X_REAL_IP='invalide', HTTP_X_FORWARDED_FOR='invalide')
        self.assertEqual(get_client_ip(request), '10.0.4.129')

    @override_settings(TRUSTED_PROXY_NETWORKS=[])
    def test_liste_vide_desactive_la_confiance_dans_le_proxy(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.0.4.129', HTTP_X_REAL_IP='203.0.113.41')
        self.assertEqual(get_client_ip(request), '10.0.4.129')

    def test_client_ipv6_normalise_derriere_proxy(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.0.4.129', HTTP_X_REAL_IP='2001:db8:0:0::1')
        self.assertEqual(get_client_ip(request), '2001:db8::1')



class AxesIsolationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.user = User.objects.create_user('utilisateur-autorise', password='mot-de-passe-test')

    def request(self):
        return self.factory.post('/utilisateurs/login/', REMOTE_ADDR='10.0.4.129', HTTP_X_REAL_IP='203.0.113.41')

    def test_echecs_autre_compte_ne_bloquent_pas_utilisateur(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            authenticate(self.request(), username='autre-compte', password='incorrect')
        user = authenticate(self.request(), username=self.user.username, password='mot-de-passe-test')
        self.assertEqual(user, self.user)

    def test_compte_en_attaque_reste_bloque(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            authenticate(self.request(), username=self.user.username, password='incorrect')
        self.assertIsNone(authenticate(self.request(), username=self.user.username, password='mot-de-passe-test'))

    def test_meme_compte_depuis_autre_ip_reste_accessible(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            authenticate(self.request(), username=self.user.username, password='incorrect')
        other = self.request()
        other.META['HTTP_X_REAL_IP'] = '203.0.113.99'
        self.assertEqual(authenticate(other, username=self.user.username, password='mot-de-passe-test'), self.user)



# Ordre de production : filtrage IP avant les sessions et l'authentification.
POINTAGE_MIDDLEWARE = (
    'ecole_moderne.security_middleware.SecurityMiddleware',
    *[m for m in TEST_MIDDLEWARE if m != 'ecole_moderne.security_middleware.SecurityMiddleware'],
)


@override_settings(MIDDLEWARE=POINTAGE_MIDDLEWARE, TRUSTED_PROXY_NETWORKS=['10.0.4.129/32'])
class PointageHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        export_support.ExportPresencesExcelTests.setUpTestData.__func__(cls)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.token = 'a' * 32
        self.client.cookies['csrftoken'] = self.token
        self.ip = '203.0.113.41'

    def pointer(self, observation, token=None):
        enseignant = self.enseignant.pk
        return self.client.post(reverse('salaires:pointer_presence'), {
            'date': '2026-09-14', 'enseignants': [enseignant],
            f'statut_{enseignant}': 'PRESENT',
            f'heures_travaillees_{enseignant}': '8',
            f'observations_{enseignant}': observation,
        }, HTTP_X_CSRFTOKEN=token or self.token, REMOTE_ADDR='10.0.4.129', HTTP_X_REAL_IP=self.ip)

    def test_pointage_enregistre_avec_ponctuation_et_ip_client(self):
        observation = "Arrivée 08:00 ; départ 16:00 -- fin d'absence"
        response = self.pointer(observation)
        self.assertEqual(response.status_code, 302)
        presence = PresenceEnseignant.objects.get(enseignant=self.enseignant, date=date(2026, 9, 14))
        self.assertEqual(presence.observations, observation)
        self.assertEqual(presence.heures_travaillees, Decimal('8'))
        self.assertFalse(cache.get(f'blocked_ip_{self.ip}'))
        self.assertIsNone(cache.get('rate_limit_10.0.4.129'))
        self.assertEqual(cache.get(f'rate_limit_{self.ip}'), 1)

    def test_csrf_invalide_refuse_sans_pointage_ni_blocage_ip(self):
        self.assertEqual(self.pointer('Présent', token='b' * 32).status_code, 403)
        self.assertFalse(PresenceEnseignant.objects.filter(date=date(2026, 9, 14)).exists())
        self.assertFalse(cache.get(f'blocked_ip_{self.ip}'))

    def test_attaque_refusee_sans_pointage(self):
        self.assertEqual(self.pointer('<script>alert(1)</script>').status_code, 403)
        self.assertFalse(PresenceEnseignant.objects.filter(date=date(2026, 9, 14)).exists())
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))
        self.assertFalse(cache.get('blocked_ip_10.0.4.129'))


@override_settings(MIDDLEWARE=POINTAGE_MIDDLEWARE, SECURITY_VERIFICATION_CODE='code-test-uniquement')
class DeblocageIpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.ip = '203.0.113.41'
        self.admin = User.objects.create_superuser('admin-test', 'test@example.com', 'password-test')
        self.user = User.objects.create_user('CompteBloque', password='password-test')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.token = 'a' * 32
        self.client.cookies['csrftoken'] = self.token
        self.url = reverse('utilisateurs:admin_unlock')
        self.target_attempt = self.attempt(self.ip, self.user.username)
        self.other_attempt = self.attempt(self.ip, 'AutreCompte')
        cache.set(f'blocked_ip_{self.ip}', True, 86400)
        cache.set(f'blocked_login_{self.ip}_comptebloque', True, 1800)
        cache.set(f'blocked_login_{self.ip}_autrecompte', True, 1800)

    def attempt(self, ip, username):
        return AccessAttempt.objects.create(ip_address=ip, username=username, user_agent='test', failures_since_start=10)

    def unlock(self, **overrides):
        data = {'ip': self.ip, 'username': 'comptebloque', 'code': 'code-test-uniquement'}
        data.update(overrides)
        return self.client.post(self.url, data, REMOTE_ADDR=self.ip, HTTP_X_CSRFTOKEN=self.token)

    def test_formulaire_accessible_a_admin_connecte_depuis_ip_bloquee(self):
        response = self.client.get(self.url, REMOTE_ADDR=self.ip)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))

    def test_deblocage_cible_retire_cache_et_axes_en_respectant_la_casse(self):
        self.assertEqual(self.unlock().status_code, 302)
        self.assertFalse(cache.get(f'blocked_ip_{self.ip}'))
        self.assertFalse(cache.get(f'blocked_login_{self.ip}_comptebloque'))
        self.assertFalse(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())
        self.assertTrue(AccessAttempt.objects.filter(pk=self.other_attempt.pk).exists())
        self.assertTrue(cache.get(f'blocked_login_{self.ip}_autrecompte'))

    def test_deblocage_ip_seule_retire_les_couples_de_cette_ip(self):
        outside = self.attempt('203.0.113.99', self.user.username)
        self.assertEqual(self.unlock(username='').status_code, 302)
        self.assertFalse(AccessAttempt.objects.filter(ip_address=self.ip).exists())
        self.assertTrue(AccessAttempt.objects.filter(pk=outside.pk).exists())
        self.assertFalse(cache.get(f'blocked_login_{self.ip}_comptebloque'))
        self.assertFalse(cache.get(f'blocked_login_{self.ip}_autrecompte'))

    def test_deblocage_compte_seul_ne_touche_pas_aux_autres(self):
        self.assertEqual(self.unlock(ip='').status_code, 302)
        self.assertFalse(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())
        self.assertFalse(cache.get(f'blocked_login_{self.ip}_comptebloque'))
        self.assertTrue(AccessAttempt.objects.filter(pk=self.other_attempt.pk).exists())
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))
        self.assertTrue(cache.get(f'blocked_login_{self.ip}_autrecompte'))

    def test_formulaire_refuse_code_invalide_et_conserve_blocages(self):
        self.assertEqual(self.unlock(code='incorrect').status_code, 200)
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))
        self.assertTrue(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())

    def test_formulaire_refuse_non_staff(self):
        self.client.force_login(self.user)
        self.assertEqual(self.unlock().status_code, 403)
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))
        self.assertTrue(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())

    def test_formulaire_refuse_csrf_invalide(self):
        self.token = 'b' * 32
        self.assertEqual(self.unlock().status_code, 403)
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))
        self.assertTrue(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())

    def test_formulaire_anonyme_ne_debloque_rien(self):
        self.client.logout()
        self.client.cookies['csrftoken'] = self.token
        self.assertEqual(self.unlock().status_code, 302)
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))
        self.assertTrue(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())

    def test_deblocage_tableau_de_bord_retire_aussi_axes(self):
        self.url = reverse('utilisateurs:security_clear_login_lock')
        cache.delete(f'blocked_ip_{self.ip}')
        self.assertEqual(self.unlock().status_code, 302)
        self.assertFalse(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())
        self.assertTrue(AccessAttempt.objects.filter(pk=self.other_attempt.pk).exists())

    def test_criteres_vides_ne_debloquent_pas_tous_les_comptes(self):
        self.assertEqual(self.unlock(ip='', username='').status_code, 200)
        self.assertTrue(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())
        self.assertTrue(AccessAttempt.objects.filter(pk=self.other_attempt.pk).exists())
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))

    def test_adresse_invalide_ne_debloque_pas_le_compte(self):
        self.assertEqual(self.unlock(ip='adresse-invalide').status_code, 200)
        self.assertTrue(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())
        self.assertTrue(cache.get(f'blocked_ip_{self.ip}'))

    def test_code_administrateur_public_valide_retire_axes(self):
        self.url = reverse('utilisateurs:admin_verify')
        cache.delete(f'blocked_ip_{self.ip}')
        self.client.logout()
        self.client.cookies['csrftoken'] = self.token
        self.assertEqual(self.unlock().status_code, 302)
        self.assertFalse(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())
        self.assertTrue(AccessAttempt.objects.filter(pk=self.other_attempt.pk).exists())
        self.assertTrue(self.client.session.get('admin_verified'))

    def test_code_administrateur_public_invalide_ne_retire_pas_axes(self):
        self.url = reverse('utilisateurs:admin_verify')
        cache.delete(f'blocked_ip_{self.ip}')
        self.client.logout()
        self.client.cookies['csrftoken'] = self.token
        self.assertEqual(self.unlock(code='incorrect').status_code, 200)
        self.assertTrue(AccessAttempt.objects.filter(pk=self.target_attempt.pk).exists())
        self.assertFalse(self.client.session.get('admin_verified'))
