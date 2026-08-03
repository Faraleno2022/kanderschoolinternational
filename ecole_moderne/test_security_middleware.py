from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase

from .security_middleware import SecurityMiddleware


class SecurityMiddlewarePathTraversalTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.middleware = SecurityMiddleware(lambda request: None)

    def tearDown(self):
        cache.clear()

    def test_encoded_slashes_in_normal_query_are_allowed(self):
        request = self.factory.get(
            '/notes/gestion/',
            {'next': '/paiements/liste/', 'periode': '2025/2026'},
        )
        request.META['REMOTE_ADDR'] = '197.149.244.1'

        self.assertFalse(self.middleware.detect_path_traversal(request))
        self.assertIsNone(self.middleware.process_request(request))
        self.assertFalse(self.middleware.is_ip_blocked('197.149.244.1'))

    def test_filename_containing_two_dots_is_allowed(self):
        request = self.factory.get('/documents/rapport..final.pdf')

        self.assertFalse(self.middleware.detect_path_traversal(request))

    def test_plain_parent_segment_is_detected(self):
        request = self.factory.get('/documents/../settings.py')

        self.assertTrue(self.middleware.detect_path_traversal(request))

    def test_encoded_parent_segment_in_query_is_detected(self):
        request = self.factory.get('/documents/?fichier=..%2Fsettings.py')

        self.assertTrue(self.middleware.detect_path_traversal(request))

    def test_windows_parent_segment_is_detected(self):
        request = self.factory.get('/documents/?fichier=..%5Csettings.py')

        self.assertTrue(self.middleware.detect_path_traversal(request))

    def test_double_encoded_parent_segment_is_detected(self):
        request = self.factory.get(
            '/documents/?fichier=%252e%252e%252fsettings.py'
        )

        self.assertTrue(self.middleware.detect_path_traversal(request))

    def test_confirmed_traversal_is_rejected_and_ip_is_blocked(self):
        request = self.factory.get('/documents/?fichier=..%2Fsettings.py')
        request.META['REMOTE_ADDR'] = '203.0.113.42'

        response = self.middleware.process_request(request)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.middleware.is_ip_blocked('203.0.113.42'))
