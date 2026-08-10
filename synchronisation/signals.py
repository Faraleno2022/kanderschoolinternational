from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.apps import apps as django_apps

from .context import sync_is_muted
from .engine import ecole_for_instance, is_sync_model, model_label_for, serialize_instance
from .models import SyncChange


def _is_historical_model(sender):
    """Ignore migration-time model classes from Django's historical app registry."""
    return getattr(sender._meta, 'apps', django_apps) is not django_apps


@receiver(post_save)
def create_sync_change_on_save(sender, instance, created, **kwargs):
    if kwargs.get('raw') or sync_is_muted() or _is_historical_model(sender) or not is_sync_model(instance):
        return

    ecole = ecole_for_instance(instance)
    if not ecole or not getattr(ecole, 'pk', None):
        return

    SyncChange.objects.create(
        ecole_id=ecole.pk,
        model_label=model_label_for(instance),
        object_uuid=instance.sync_uuid,
        operation=SyncChange.OPERATION_CREATE if created else SyncChange.OPERATION_UPDATE,
        payload=serialize_instance(instance),
    )


@receiver(pre_delete)
def create_sync_change_on_delete(sender, instance, **kwargs):
    if sync_is_muted() or _is_historical_model(sender) or not is_sync_model(instance):
        return

    # Lorsqu'une école est supprimée, Django supprime en cascade toutes ses
    # données. Créer ici de nouveaux SyncChange rattachés à cette même école
    # laisse des lignes enfants après le passage du Collector et provoque une
    # erreur de contrainte de clé étrangère au moment de supprimer l'école.
    from eleves.models import Ecole
    origin = kwargs.get('origin')
    origin_model = getattr(origin, 'model', None)
    if isinstance(instance, Ecole) or isinstance(origin, Ecole) or origin_model is Ecole:
        return

    ecole = ecole_for_instance(instance)
    if not ecole or not getattr(ecole, 'pk', None):
        return

    SyncChange.objects.create(
        ecole_id=ecole.pk,
        model_label=model_label_for(instance),
        object_uuid=instance.sync_uuid,
        operation=SyncChange.OPERATION_DELETE,
        payload={'sync_uuid': str(instance.sync_uuid)},
    )
