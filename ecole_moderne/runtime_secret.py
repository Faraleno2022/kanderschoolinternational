"""Clé de session locale : persistante si possible, toujours aléatoire."""
from pathlib import Path
import secrets


def load_or_create_secret(filename):
    path = Path(filename)
    try:
        existing = path.read_text(encoding='utf-8').strip()
        if existing:
            return existing
    except OSError:
        pass

    secret = secrets.token_urlsafe(48)
    try:
        path.write_text(secret, encoding='utf-8')
    except OSError:
        # Un répertoire protégé ne doit jamais imposer une clé prévisible.
        # La clé reste propre à ce processus si elle ne peut pas être conservée.
        pass
    return secret
