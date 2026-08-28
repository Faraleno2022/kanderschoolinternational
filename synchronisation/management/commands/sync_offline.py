"""Synchronisation bidirectionnelle du poste hors-ligne avec le serveur.

Un passage unique par defaut, ou une boucle continue avec `--boucle`. Dans ce
mode le poste tient une requete ouverte que le serveur debloque des qu'un
changement arrive : la donnee saisie sur le serveur descend en une seconde
environ, sans WebSocket ni broker.
"""

import json
import time
from urllib import parse, request as urlrequest
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from eleves.models import Ecole
from synchronisation.engine import apply_sync_change
from synchronisation.models import SyncChange, SyncCursor


class ErreurReseau(Exception):
    """Panne joignable a nouveau plus tard : la boucle doit survivre."""


class Command(BaseCommand):
    help = (
        "Envoie les changements locaux et recupere ceux du serveur. "
        "Avec --boucle, reste a l'ecoute et applique les nouveautes en continu."
    )

    def add_arguments(self, parser):
        parser.add_argument('--server-url', default=getattr(settings, 'MYSCHOOL_SYNC_SERVER_URL', ''))
        parser.add_argument('--device-id', default=getattr(settings, 'MYSCHOOL_SYNC_DEVICE_ID', ''))
        parser.add_argument('--token', default=getattr(settings, 'MYSCHOOL_SYNC_TOKEN', ''))
        parser.add_argument('--ecole-id', default=getattr(settings, 'MYSCHOOL_SYNC_ECOLE_ID', ''))
        parser.add_argument(
            '--since-id', default='',
            help="Force le repere de depart au lieu du curseur memorise.",
        )
        parser.add_argument(
            '--initial', action='store_true',
            help="Demande l'instantane complet de l'ecole avant de suivre le journal.",
        )
        parser.add_argument('--pull-only', action='store_true')
        parser.add_argument('--push-only', action='store_true')
        parser.add_argument(
            '--boucle', action='store_true',
            help="Reste en ecoute continue au lieu d'un passage unique.",
        )
        parser.add_argument(
            '--attente', type=int,
            default=getattr(settings, 'MYSCHOOL_SYNC_WAIT', 25),
            help="Secondes pendant lesquelles le serveur retient la requete (0 desactive).",
        )

    # ------------------------------------------------------------------ socle

    def handle(self, *args, **options):
        self.server_url = (options['server_url'] or '').rstrip('/')
        self.device_id = options['device_id'] or ''
        self.token = options['token'] or ''
        ecole_id = options['ecole_id'] or ''

        if not self.server_url or not self.device_id or not self.token or not ecole_id:
            raise CommandError(
                'Configuration incomplete. Definissez MYSCHOOL_SYNC_SERVER_URL, '
                'MYSCHOOL_SYNC_DEVICE_ID, MYSCHOOL_SYNC_TOKEN et MYSCHOOL_SYNC_ECOLE_ID.'
            )

        ecole = Ecole.objects.filter(pk=ecole_id).first()
        if not ecole:
            raise CommandError(f"Ecole locale introuvable: {ecole_id}")

        curseur, _ = SyncCursor.objects.get_or_create(ecole=ecole)
        if options['since_id']:
            curseur.server_change_id = int(options['since_id'])
            curseur.save(update_fields=['server_change_id', 'date_modification'])

        if options['boucle']:
            self._boucler(ecole, curseur, options)
        else:
            self._un_passage(ecole, curseur, options, options['initial'])

    def _un_passage(self, ecole, curseur, options, initial):
        """Retourne True si du travail a ete fait (donc pas de pause a prendre)."""
        actif = False
        if not options['pull_only']:
            envoyes = self._envoyer_en_attente(ecole)
            if envoyes:
                actif = True
                self.stdout.write(self.style.SUCCESS(f'{envoyes} changement(s) envoye(s).'))

        if not options['push_only']:
            recus, encore = self._recuperer(ecole, curseur, initial, options['attente'])
            if recus:
                actif = True
                self.stdout.write(self.style.SUCCESS(f'{recus} changement(s) recu(s).'))
            if encore:
                actif = True
        return actif

    def _boucler(self, ecole, curseur, options):
        self.stdout.write(self.style.SUCCESS(
            f"Ecoute continue de {self.server_url} (Ctrl+C pour arreter)."
        ))
        initial = options['initial']
        pause = 1
        while True:
            try:
                close_old_connections()
                self._un_passage(ecole, curseur, options, initial)
                initial = False
                pause = 1
            except ErreurReseau as exc:
                # Le serveur peut etre injoignable des heures : on ralentit
                # sans jamais abandonner, et sans noyer le journal.
                self.stderr.write(f'Serveur injoignable ({exc}). Nouvel essai dans {pause} s.')
                time.sleep(pause)
                pause = min(pause * 2, 300)
            except KeyboardInterrupt:
                self.stdout.write('\nArret demande.')
                return

    # ---------------------------------------------------------------- reseau

    def _appel_json(self, url, payload=None, method='POST', timeout=60):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        requete = urlrequest.Request(
            url,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Sync-Device': self.device_id,
                'X-Sync-Token': self.token,
            },
            method=method,
        )
        try:
            with urlrequest.urlopen(requete, timeout=timeout) as reponse:
                return json.loads(reponse.read().decode('utf-8'))
        except HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='replace')
            if exc.code in (401, 403):
                # Identifiants refuses : reessayer en boucle ne servirait a rien.
                raise CommandError(f"Appareil non autorise ({exc.code}): {detail}") from exc
            raise ErreurReseau(f'erreur serveur {exc.code}: {detail}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ErreurReseau(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ErreurReseau(f'reponse illisible: {exc}') from exc

    # ------------------------------------------------------------------ push

    def _envoyer_en_attente(self, ecole):
        en_attente = list(
            SyncChange.objects
            .filter(ecole=ecole, statut=SyncChange.STATUT_PENDING)
            .order_by('id')[:200]
        )
        if not en_attente:
            return 0

        reponse = self._appel_json(
            f'{self.server_url}/api/v1/sync/push/',
            {
                'changes': [
                    {
                        'model': change.model_label,
                        'object_uuid': str(change.object_uuid) if change.object_uuid else None,
                        'operation': change.operation,
                        'payload': change.payload,
                    }
                    for change in en_attente
                ]
            },
        )
        if not reponse.get('ok'):
            raise ErreurReseau(reponse.get('error') or 'push refuse')

        acceptes = {item['index'] for item in reponse.get('accepted', [])}
        refuses = {item['index']: item.get('error', '') for item in reponse.get('rejected', [])}
        maintenant = timezone.now()
        envoyes = 0
        for index, change in enumerate(en_attente):
            if index in acceptes:
                change.statut = SyncChange.STATUT_APPLIED
                change.date_application = maintenant
                change.save(update_fields=['statut', 'date_application'])
                envoyes += 1
            elif index in refuses:
                # Marque en echec plutot que laisse en attente : sinon le meme
                # changement serait renvoye a chaque tour, indefiniment.
                change.statut = SyncChange.STATUT_FAILED
                change.erreur = refuses[index]
                change.save(update_fields=['statut', 'erreur'])
                self.stderr.write(
                    f'Changement {change.id} refuse par le serveur: {refuses[index]}'
                )
        return envoyes

    # ------------------------------------------------------------------ pull

    def _recuperer(self, ecole, curseur, initial, attente):
        """Retourne (nombre applique, reste-t-il des lots a recuperer)."""
        parametres = {}
        if initial:
            parametres['initial'] = '1'
        else:
            parametres['since_id'] = str(curseur.server_change_id)
            if attente:
                parametres['wait'] = str(attente)

        suffixe = f'?{parse.urlencode(parametres)}' if parametres else ''
        reponse = self._appel_json(
            f'{self.server_url}/api/v1/sync/pull/{suffixe}',
            payload=None,
            method='GET',
            # La requete est retenue par le serveur : le delai doit lui laisser
            # le temps d'expirer de lui-meme, sinon le poste coupe le premier.
            timeout=(attente or 0) + 30,
        )
        if not reponse.get('ok'):
            raise ErreurReseau(reponse.get('error') or 'pull refuse')

        appliques = 0
        dernier_applique = curseur.server_change_id
        for item in reponse.get('changes', []):
            identifiant = item.get('id')
            change = SyncChange.objects.create(
                ecole=ecole,
                model_label=item['model_label'],
                object_uuid=item.get('object_uuid') or None,
                operation=item['operation'],
                payload={**(item.get('payload') or {}), 'server_change_id': identifiant},
            )
            try:
                apply_sync_change(change)
                appliques += 1
            except Exception as exc:
                change.statut = SyncChange.STATUT_FAILED
                change.erreur = str(exc)
                change.save(update_fields=['statut', 'erreur'])
                self.stderr.write(f'Changement {identifiant} non applique: {exc}')
            if identifiant:
                # Le repere avance meme sur echec : un changement irrecuperable
                # ne doit pas bloquer eternellement tout ce qui le suit.
                dernier_applique = max(dernier_applique, int(identifiant))

        repere = reponse.get('latest_change_id')
        curseur.avancer(max(dernier_applique, int(repere or 0)))
        return appliques, bool(reponse.get('has_more'))
