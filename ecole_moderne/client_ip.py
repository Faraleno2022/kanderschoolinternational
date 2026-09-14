"""Adresse client commune à AXES, aux sessions et aux limites de requêtes."""
from ipaddress import ip_address, ip_network

from django.conf import settings


def _address(value):
    try:
        return ip_address((value or '').strip())
    except ValueError:
        return None


def get_client_ip(request):
    """Accepte les en-têtes client uniquement depuis un proxy configuré.

    Le proxy PythonAnywhere remplace X-Real-IP et ajoute l'adresse client à la
    fin de X-Forwarded-For. Les premières valeurs de X-Forwarded-For peuvent
    être fournies par le visiteur et ne doivent pas décider d'un blocage.
    """
    remote = _address(request.META.get('REMOTE_ADDR'))
    if remote is None:
        return None
    trusted = any(
        remote in ip_network(network, strict=False)
        for network in getattr(settings, 'TRUSTED_PROXY_NETWORKS', [])
    )
    if trusted:
        real = _address(request.META.get('HTTP_X_REAL_IP'))
        if real is not None:
            return str(real)
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        last = _address(forwarded.split(',')[-1])
        if last is not None:
            return str(last)
    return str(remote)
