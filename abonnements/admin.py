from django.contrib import admin
from .models import (
    TypeAbonnement, Itineraire, MenuCantine,
    Abonnement, AbonnementBus, AbonnementCantine,
    PresenceCantine
)

from administration.corbeille import CorbeilleAdminMixin


@admin.register(TypeAbonnement)
class TypeAbonnementAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('nom', 'tarif_mensuel', 'tarif_trimestriel', 'tarif_annuel', 'actif')
    list_filter = ('actif', 'nom')
    search_fields = ('nom', 'description')


@admin.register(Itineraire)
class ItineraireAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('nom', 'heure_depart_matin', 'heure_retour_soir', 'capacite', 'nombre_abonnes', 'actif')
    list_filter = ('actif',)
    search_fields = ('nom', 'quartiers')


@admin.register(MenuCantine)
class MenuCantineAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('jour', 'semaine', 'date_menu', 'plat_principal', 'actif')
    list_filter = ('jour', 'semaine', 'actif')
    search_fields = ('plat_principal', 'entree', 'dessert')
    date_hierarchy = 'date_menu'


@admin.register(Abonnement)
class AbonnementAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('eleve', 'type_abonnement', 'duree', 'date_debut', 'date_fin', 'montant', 'statut')
    list_filter = ('statut', 'duree', 'type_abonnement')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule')
    date_hierarchy = 'date_debut'
    raw_id_fields = ['eleve']


@admin.register(AbonnementBus)
class AbonnementBusAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('eleve', 'itineraire', 'duree', 'date_debut', 'date_fin', 'statut')
    list_filter = ('statut', 'duree', 'itineraire')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule', 'point_montee', 'point_descente')
    date_hierarchy = 'date_debut'
    raw_id_fields = ['eleve']


@admin.register(AbonnementCantine)
class AbonnementCantineAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('eleve', 'duree', 'regime_alimentaire', 'date_debut', 'date_fin', 'statut')
    list_filter = ('statut', 'duree', 'regime_alimentaire')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule')
    date_hierarchy = 'date_debut'
    raw_id_fields = ['eleve']


@admin.register(PresenceCantine)
class PresenceCantineAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ('abonnement', 'date', 'present', 'menu')
    list_filter = ('present', 'date')
    search_fields = ('abonnement__eleve__nom', 'abonnement__eleve__prenom')
    date_hierarchy = 'date'
