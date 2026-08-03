"""Configuration partagée pour rendre les tests de paiements déterministes."""

from django.conf import settings


TEST_MIDDLEWARE = [
    middleware
    for middleware in settings.MIDDLEWARE
    if middleware != "ecole_moderne.licence_middleware.LicenceMiddleware"
]
