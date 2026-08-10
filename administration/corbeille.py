"""Corbeille générique pour les suppressions faites dans l'administration Django.

Toute classe d'administration qui hérite de `CorbeilleAdminMixin` archive
l'objet (et ses dépendances en cascade) avant de le supprimer réellement.
Les objets archivés sont visibles et restaurables dans
« Administration > Corbeille des suppressions ».
"""
import json

from django.contrib import admin
from django.core import serializers
from django.db import transaction
from django.db.models.deletion import Collector

from .models import ObjetSupprime


def _objets_lies(instance):
    """Retourne l'objet et tout ce que Django supprimerait en cascade."""
    collector = Collector(using=instance._state.db)
    collector.collect([instance])
    objets = []
    for model, instances in collector.data.items():
        if model._meta.auto_created:
            continue
        objets.extend(instances)
    # L'objet principal doit être restauré en premier.
    objets.sort(key=lambda obj: 0 if obj == instance else 1)
    return objets


def archiver_avant_suppression(instance, utilisateur=None):
    """Sérialise l'objet et ses dépendances, puis enregistre l'archive."""
    objets = _objets_lies(instance)
    donnees = json.loads(serializers.serialize('json', objets))
    return ObjetSupprime.objects.create(
        model_label=f"{instance._meta.app_label}.{instance._meta.model_name}",
        object_pk=str(instance.pk),
        object_repr=str(instance)[:250],
        donnees=donnees,
        supprime_par=utilisateur if getattr(utilisateur, 'is_authenticated', False) else None,
    )


class CorbeilleAdminMixin:
    """Envoie les suppressions de l'administration vers la corbeille."""

    @transaction.atomic
    def delete_model(self, request, obj):
        archiver_avant_suppression(obj, request.user)
        super().delete_model(request, obj)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        for obj in queryset:
            archiver_avant_suppression(obj, request.user)
        super().delete_queryset(request, queryset)


@admin.register(ObjetSupprime)
class ObjetSupprimeAdmin(admin.ModelAdmin):
    list_display = (
        'supprime_le', 'model_label', 'object_pk', 'object_repr',
        'supprime_par', 'restaure',
    )
    list_filter = ('model_label', 'restaure', 'supprime_le')
    search_fields = ('object_repr', 'object_pk', 'model_label')
    readonly_fields = (
        'model_label', 'object_pk', 'object_repr', 'donnees',
        'supprime_par', 'supprime_le', 'restaure', 'restaure_le',
    )
    date_hierarchy = 'supprime_le'
    actions = ('restaurer_objets',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description="Restaurer les objets sélectionnés")
    def restaurer_objets(self, request, queryset):
        restaures = 0
        erreurs = 0
        for archive in queryset:
            try:
                restaures += int(archive.restaurer())
            except Exception as exc:  # pragma: no cover - dépend des données
                erreurs += 1
                self.message_user(
                    request,
                    f"Restauration impossible pour {archive} : {exc}",
                    level='error',
                )
        self.message_user(request, f"{restaures} objet(s) restauré(s), {erreurs} en échec.")
