from django.contrib import admin
from .models import AbonnementBus, AbonnementCantine

from administration.corbeille import CorbeilleAdminMixin

@admin.register(AbonnementBus)
class AbonnementBusAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('eleve', 'montant', 'periodicite', 'date_debut', 'date_expiration', 'statut', 'zone', 'point_arret')
    list_filter = ('statut', 'periodicite', 'zone')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule', 'zone', 'point_arret', 'contact_parent')


@admin.register(AbonnementCantine)
class AbonnementCantineAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('eleve', 'type_repas', 'montant', 'periodicite', 'date_debut', 'date_expiration', 'statut', 'jours_restants')
    list_filter = ('statut', 'periodicite', 'type_repas', 'regime_alimentaire')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule', 'contact_parent', 'regime_alimentaire')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations Élève', {
            'fields': ('eleve', 'contact_parent')
        }),
        ('Abonnement', {
            'fields': ('montant', 'periodicite', 'type_repas', 'date_debut', 'date_expiration', 'statut')
        }),
        ('Régime Alimentaire', {
            'fields': ('regime_alimentaire', 'allergies'),
            'classes': ('collapse',)
        }),
        ('Alertes', {
            'fields': ('alerte_avant_jours', 'derniere_relance')
        }),
        ('Observations', {
            'fields': ('observations',),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
