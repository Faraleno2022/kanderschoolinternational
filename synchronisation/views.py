import json
import secrets
import time
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from eleves.models import Ecole
from utilisateurs.utils import user_is_admin, user_school

from .engine import apply_sync_change, snapshot_changes_for_ecole
from .models import SyncChange, SyncDevice


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _current_school(user, data=None):
    if user and user.is_authenticated and user.is_superuser and data and data.get('ecole_id'):
        return Ecole.objects.filter(pk=data['ecole_id']).first()
    if user and user.is_authenticated:
        return user_school(user)
    if data and data.get('ecole_id'):
        return Ecole.objects.filter(pk=data['ecole_id']).first()
    return None


def _has_sync_admin_access(request):
    token = request.headers.get('X-Sync-Admin-Token', '')
    expected = getattr(settings, 'MYSCHOOL_SYNC_ADMIN_TOKEN', '')
    if expected and token and secrets.compare_digest(token, expected):
        return True
    user = getattr(request, 'user', None)
    return bool(user and user.is_authenticated and user_is_admin(user))


def _device_from_headers(request):
    device_id = request.headers.get('X-Sync-Device')
    token = request.headers.get('X-Sync-Token')
    if not device_id or not token:
        return None, JsonResponse({'ok': False, 'error': 'Identifiants de synchronisation manquants.'}, status=401)
    try:
        UUID(device_id)
    except ValueError:
        return None, JsonResponse({'ok': False, 'error': 'Identifiant appareil invalide.'}, status=400)

    device = SyncDevice.objects.select_related('ecole').filter(device_id=device_id, actif=True).first()
    if not device or not device.verifier_token(token):
        return None, JsonResponse({'ok': False, 'error': 'Appareil non autorise.'}, status=403)
    device.marquer_connexion()
    return device, None


def _schools_for_user(user):
    if user.is_superuser:
        return Ecole.objects.all().order_by('nom')
    ecole = user_school(user)
    if ecole:
        return Ecole.objects.filter(pk=ecole.pk)
    return Ecole.objects.none()


@require_GET
def health(request):
    return JsonResponse({
        'ok': True,
        'service': 'myschoolgn-sync',
        'version': 1,
        'server_time': timezone.now().isoformat(),
    })


@login_required
def device_setup(request):
    if not user_is_admin(request.user):
        return render(request, 'utilisateurs/permission_denied.html', status=403)

    ecoles = _schools_for_user(request.user)
    generated = None

    if request.method == 'POST':
        ecole_id = request.POST.get('ecole_id')
        nom = (request.POST.get('nom') or 'Poste local').strip()[:120]
        ecole = ecoles.filter(pk=ecole_id).first()

        if not ecole:
            messages.error(request, "Ecole introuvable ou non autorisee.")
        else:
            token = secrets.token_urlsafe(32)
            device = SyncDevice(ecole=ecole, nom=nom or 'Poste local')
            device.definir_token(token)
            device.save()

            server_url = request.build_absolute_uri('/').rstrip('/')
            generated = {
                'device': device,
                'token': token,
                'server_url': server_url,
                'env_block': "\n".join([
                    f"MYSCHOOL_SYNC_SERVER_URL={server_url}",
                    f"MYSCHOOL_SYNC_DEVICE_ID={device.device_id}",
                    f"MYSCHOOL_SYNC_TOKEN={token}",
                    f"MYSCHOOL_SYNC_ECOLE_ID={ecole.id}",
                ]),
            }
            messages.success(request, "Identifiants de synchronisation generes. Copiez-les maintenant.")

    return render(request, 'synchronisation/device_setup.html', {
        'titre_page': 'Connexion offline',
        'ecoles': ecoles,
        'generated': generated,
    })


@csrf_exempt
@require_POST
def register_device(request):
    if not _has_sync_admin_access(request):
        return JsonResponse({'ok': False, 'error': 'Permission refusee.'}, status=403)

    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'JSON invalide.'}, status=400)

    ecole = _current_school(request.user, data)
    if not ecole:
        return JsonResponse({'ok': False, 'error': 'Aucune ecole associee a cet utilisateur.'}, status=400)

    nom = (data.get('nom') or data.get('name') or 'Poste local').strip()[:120]
    token = secrets.token_urlsafe(32)
    device = SyncDevice(ecole=ecole, nom=nom)
    device.definir_token(token)
    device.save()

    return JsonResponse({
        'ok': True,
        'device_id': str(device.device_id),
        'sync_token': token,
        'ecole_id': ecole.id,
        'message': 'Conservez ce token sur le poste local. Il ne sera plus affiche.',
    }, status=201)


@csrf_exempt
@require_POST
def push(request):
    device, error_response = _device_from_headers(request)
    if error_response:
        return error_response

    data = _json_body(request)
    if data is None:
        return JsonResponse({'ok': False, 'error': 'JSON invalide.'}, status=400)

    changes = data.get('changes', [])
    if not isinstance(changes, list):
        return JsonResponse({'ok': False, 'error': 'Le champ changes doit etre une liste.'}, status=400)

    accepted = []
    rejected = []
    valid_operations = {choice[0] for choice in SyncChange.OPERATION_CHOICES}

    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            rejected.append({'index': index, 'error': 'Changement invalide.'})
            continue

        operation = (change.get('operation') or '').upper()
        model_label = (change.get('model') or change.get('model_label') or '').strip()
        payload = change.get('payload') or {}
        raw_uuid = change.get('object_uuid')

        if operation not in valid_operations:
            rejected.append({'index': index, 'error': 'Operation invalide.'})
            continue
        if not model_label:
            rejected.append({'index': index, 'error': 'Modele manquant.'})
            continue
        if not isinstance(payload, dict):
            rejected.append({'index': index, 'error': 'Payload invalide.'})
            continue

        object_uuid = None
        if raw_uuid:
            try:
                object_uuid = UUID(str(raw_uuid))
            except ValueError:
                rejected.append({'index': index, 'error': 'UUID objet invalide.'})
                continue

        if object_uuid and 'sync_uuid' not in payload:
            payload = {**payload, 'sync_uuid': str(object_uuid)}

        sync_change = SyncChange.objects.create(
            ecole=device.ecole,
            device=device,
            model_label=model_label[:120],
            object_uuid=object_uuid,
            operation=operation,
            payload=payload,
        )
        try:
            apply_sync_change(sync_change)
            accepted.append({'index': index, 'change_id': sync_change.id})
        except Exception as exc:
            sync_change.statut = SyncChange.STATUT_FAILED
            sync_change.erreur = str(exc)
            sync_change.save(update_fields=['statut', 'erreur'])
            rejected.append({'index': index, 'change_id': sync_change.id, 'error': str(exc)})

    return JsonResponse({
        'ok': True,
        'accepted_count': len(accepted),
        'rejected_count': len(rejected),
        'accepted': accepted,
        'rejected': rejected,
        'server_time': timezone.now().isoformat(),
    })


def _changements_a_envoyer(device, since_id):
    """Journal destine a ce poste, du plus ancien au plus recent.

    Les changements nes de l'usage web du serveur restent au statut PENDING :
    personne ne les « applique » ici puisqu'ils y sont deja. Les filtrer sur
    APPLIED revenait donc a ne jamais transmettre au poste ce qui est saisi
    sur le serveur. Seuls les echecs sont ecartes.
    """
    changements = (
        SyncChange.objects
        .filter(ecole=device.ecole)
        .exclude(statut=SyncChange.STATUT_FAILED)
        .exclude(device=device)
    )
    if since_id:
        changements = changements.filter(id__gt=since_id)
    return changements.order_by('id')


def _attendre_un_changement(device, since_id, attente):
    """Retient la requete jusqu'a l'arrivee d'un changement, ou expiration.

    Le poste obtient ainsi la donnee en une seconde environ au lieu d'attendre
    son prochain reveil, sans WebSocket ni broker : une seule requete HTTP
    tenue, que n'importe quel reseau domestique laisse passer.
    """
    plafond = int(getattr(settings, 'MYSCHOOL_SYNC_LONGPOLL_MAX', 30))
    pas = float(getattr(settings, 'MYSCHOOL_SYNC_LONGPOLL_INTERVAL', 1.0))
    attente = max(0, min(int(attente or 0), plafond))
    if attente <= 0:
        return

    echeance = time.monotonic() + attente
    while time.monotonic() < echeance:
        time.sleep(min(pas, max(0.0, echeance - time.monotonic())))
        if _changements_a_envoyer(device, since_id).exists():
            return


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def pull(request):
    device, error_response = _device_from_headers(request)
    if error_response:
        return error_response

    since = request.GET.get('since')
    since_id = request.GET.get('since_id')
    initial = request.GET.get('initial') in {'1', 'true', 'yes'}
    if request.method == 'POST':
        data = _json_body(request)
        if data is None:
            return JsonResponse({'ok': False, 'error': 'JSON invalide.'}, status=400)
        since = data.get('since') or since
        since_id = data.get('since_id') or since_id
        initial = data.get('initial') in {True, '1', 'true', 'yes'}

    if initial:
        # Le repere est pris AVANT de composer l'instantane : un changement
        # survenu pendant sa fabrication sera relu au prochain tour plutot
        # que saute definitivement.
        repere = (
            SyncChange.objects
            .filter(ecole=device.ecole)
            .order_by('-id')
            .values_list('id', flat=True)
            .first()
        ) or 0
        serialized_changes = snapshot_changes_for_ecole(device.ecole)
        return JsonResponse({
            'ok': True,
            'device_id': str(device.device_id),
            'ecole_id': device.ecole_id,
            'since': since,
            'since_id': since_id,
            'initial': True,
            'changes': serialized_changes,
            'latest_change_id': repere,
            'has_more': False,
            'server_time': timezone.now().isoformat(),
        })

    curseur = None
    if since_id:
        try:
            curseur = int(since_id)
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'since_id invalide.'}, status=400)
    elif since:
        # Compatibilite : un horodatage designe le dernier changement connu.
        parsed_since = parse_datetime(str(since))
        if not parsed_since:
            return JsonResponse({'ok': False, 'error': 'since invalide. Utilisez une date ISO ou since_id.'}, status=400)
        if timezone.is_naive(parsed_since):
            parsed_since = timezone.make_aware(parsed_since, timezone.get_current_timezone())
        dernier_connu = (
            SyncChange.objects
            .filter(ecole=device.ecole, date_creation__lte=parsed_since)
            .order_by('-id')
            .values_list('id', flat=True)
            .first()
        )
        curseur = dernier_connu or 0

    attente = request.GET.get('wait')
    if request.method == 'POST':
        attente = (data or {}).get('wait', attente)
    if attente and not _changements_a_envoyer(device, curseur).exists():
        _attendre_un_changement(device, curseur, attente)

    # 201 lignes demandees pour savoir s'il en reste : le poste enchaine alors
    # sans attendre, au lieu de dormir avec du retard accumule.
    lot = list(_changements_a_envoyer(device, curseur)[:201])
    has_more = len(lot) > 200
    changes = lot[:200]
    serialized_changes = [
        {
            'id': change.id,
            'model': change.model_label,
            'model_label': change.model_label,
            'object_uuid': str(change.object_uuid) if change.object_uuid else None,
            'operation': change.operation,
            'payload': change.payload,
            'device_id': str(change.device.device_id) if change.device else None,
            'device_name': change.device.nom if change.device else None,
            'date_creation': change.date_creation.isoformat(),
        }
        for change in changes
    ]

    return JsonResponse({
        'ok': True,
        'device_id': str(device.device_id),
        'ecole_id': device.ecole_id,
        'since': since,
        'since_id': since_id,
        'changes': serialized_changes,
        'latest_change_id': (
            serialized_changes[-1]['id'] if serialized_changes else (curseur or 0)
        ),
        'has_more': has_more,
        'server_time': timezone.now().isoformat(),
    })
