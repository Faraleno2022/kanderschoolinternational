from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from ecole_moderne.licence_middleware import LicenceMiddleware


class LicenceMiddlewareProductionTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/paiements/liste/')

    @override_settings(LICENCE_ENFORCEMENT_ENABLED=False)
    @patch('ecole_moderne.licence_middleware._check_license_cached')
    @patch('ecole_moderne.licence_middleware._check_integrity_cached')
    def test_production_ne_verifie_pas_la_licence_et_ne_bloque_pas(
        self,
        check_integrity,
        check_license,
    ):
        middleware = LicenceMiddleware(lambda request: HttpResponse('OK'))

        response = middleware(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'OK')
        check_integrity.assert_not_called()
        check_license.assert_not_called()

    @override_settings(LICENCE_ENFORCEMENT_ENABLED=False)
    @patch(
        'ecole_moderne.licence_middleware._check_license_cached',
        return_value={'valid': False, 'trial': True, 'days_left': 0},
    )
    def test_un_essai_expire_ne_peut_pas_bloquer_la_production(self, check_license):
        middleware = LicenceMiddleware(lambda request: HttpResponse('APPLICATION DISPONIBLE'))

        response = middleware(self.request)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Accès bloqué")
        self.assertNotContains(response, "Votre essai expire")
        check_license.assert_not_called()
