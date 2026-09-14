"""Déblocage ciblé des compteurs applicatifs et des tentatives AXES."""
from ipaddress import ip_address

from axes.models import AccessAttempt
from axes.utils import reset as reset_axes
from django.core.cache import cache


def clear_login_locks(ip='', username=''):
    """Appelé après autorisation administrateur et contrôle CSRF des vues.

    Sans critères, aucun déblocage global n'est possible. Les noms AXES sont
    recherchés sans tenir compte de la casse, puis réinitialisés avec leur
    casse d'origine. Les clés applicatives utilisent toujours des minuscules.
    """
    ip = str(ip_address(ip.strip())) if ip.strip() else ''
    username = username.strip().lower()
    if not ip and not username:
        raise ValueError("Veuillez fournir au moins une IP ou un nom d'utilisateur.")

    attempts = AccessAttempt.objects.all()
    if ip:
        attempts = attempts.filter(ip_address=ip)
    if username:
        attempts = attempts.filter(username__iexact=username)
    pairs = set(attempts.values_list('ip_address', 'username'))
    keys = set()
    if ip:
        keys.update(f'{prefix}_{ip}' for prefix in (
            'failed_login', 'blocked_login', 'blocked_ip', 'rate_limit',
        ))
    if ip and username:
        # Le verrou en cache peut subsister après expiration de l'entrée AXES.
        pairs.add((ip, username))
    for attempt_ip, attempt_username in pairs:
        if attempt_username:
            keys.update(f'{prefix}_{attempt_ip}_{attempt_username.lower()}'
                        for prefix in ('failed_login', 'blocked_login'))

    if username:
        cleared = sum(reset_axes(ip=ip or None, username=original)
                      for original in {name for _, name in pairs if name})
    else:
        cleared = reset_axes(ip=ip)
    for key in keys:
        if cache.get(key) is not None:
            cache.delete(key)
            cleared += 1
    return cleared
