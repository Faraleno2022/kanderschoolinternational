from django.contrib import admin
from .forms import AbonnementBusForm, AbonnementCantineForm
from .models import (
    AbonnementBus,
    AbonnementCantine,
    TypePeriodiciteAbonnement,
    TypeRepasCantine,
)

from administration.corbeille import CorbeilleAdminMixin


@admin.register(TypePeriodiciteAbonnement)
class TypePeriodiciteAbonnementAdmin(admin.ModelAdmin):
    list_display = ('libelle', 'service', 'code', 'duree_mois', 'duree_jours', 'actif', 'ordre')
    list_editable = ('duree_mois', 'duree_jours', 'actif', 'ordre')
    list_filter = ('service', 'actif')
    search_fields = ('libelle', 'code')
    ordering = ('service', 'ordre', 'libelle')
    fieldsets = (
        ('Identification', {'fields': ('service', 'code', 'libelle')}),
        ('Calcul automatique de la fin', {'fields': ('duree_mois', 'duree_jours')}),
        ('Affichage', {'fields': ('actif', 'ordre')}),
    )


@admin.register(TypeRepasCantine)
class TypeRepasCantineAdmin(admin.ModelAdmin):
    list_display = ('libelle', 'code', 'heure_service', 'actif', 'ordre')
    list_editable = ('heure_service', 'actif', 'ordre')
    list_filter = ('actif',)
    search_fields = ('libelle', 'code')
    ordering = ('ordre', 'libelle')

@admin.register(AbonnementBus)
class AbonnementBusAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    form = AbonnementBusForm
    list_display = ('eleve', 'montant', 'reference_paiement', 'type_abonnement', 'date_debut', 'date_expiration', 'statut', 'zone', 'point_arret')
    list_filter = ('statut', 'periodicite', 'zone')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule', 'reference_paiement', 'zone', 'point_arret', 'contact_parent')
    list_select_related = ('eleve', 'eleve__classe')

    @admin.display(description="Type d'abonnement", ordering='periodicite')
    def type_abonnement(self, obj):
        return obj.get_periodicite_display()


@admin.register(AbonnementCantine)
class AbonnementCantineAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    form = AbonnementCantineForm
    list_display = ('eleve', 'repas', 'montant', 'reference_paiement', 'type_abonnement', 'date_debut', 'date_expiration', 'statut', 'jours_restants')
    list_filter = ('statut', 'periodicite', 'type_repas', 'regime_alimentaire')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule', 'reference_paiement', 'contact_parent', 'regime_alimentaire')
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('eleve', 'eleve__classe')
    
    fieldsets = (
        ('Informations Élève', {
            'fields': ('classe_filtre', 'eleve', 'contact_parent')
        }),
        ('Abonnement', {
            'fields': ('montant', 'reference_paiement', 'periodicite', 'type_repas', 'date_debut', 'date_expiration', 'statut')
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

    @admin.display(description="Type d'abonnement", ordering='periodicite')
    def type_abonnement(self, obj):
        return obj.get_periodicite_display()

    @admin.display(description='Type de repas', ordering='type_repas')
    def repas(self, obj):
        return obj.get_type_repas_display()
