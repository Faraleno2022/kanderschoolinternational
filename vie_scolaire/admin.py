from django.contrib import admin

from .models import Presence, Devoir, RemiseDevoir


@admin.register(Presence)
class PresenceAdmin(admin.ModelAdmin):
    list_display = ('eleve', 'classe', 'date', 'statut', 'saisi_par')
    list_filter = ('statut', 'date', 'classe')
    search_fields = ('eleve__nom', 'eleve__prenom', 'eleve__matricule')
    date_hierarchy = 'date'
    raw_id_fields = ('eleve', 'classe')


class RemiseDevoirInline(admin.TabularInline):
    model = RemiseDevoir
    extra = 0
    raw_id_fields = ('eleve',)


@admin.register(Devoir)
class DevoirAdmin(admin.ModelAdmin):
    list_display = ('titre', 'matiere', 'classe', 'date_donne', 'date_remise', 'cree_par')
    list_filter = ('classe', 'date_remise')
    search_fields = ('titre', 'matiere', 'description')
    date_hierarchy = 'date_remise'
    raw_id_fields = ('classe',)
    inlines = [RemiseDevoirInline]


@admin.register(RemiseDevoir)
class RemiseDevoirAdmin(admin.ModelAdmin):
    list_display = ('devoir', 'eleve', 'statut', 'date_maj')
    list_filter = ('statut',)
    search_fields = ('eleve__nom', 'eleve__prenom', 'devoir__titre')
    raw_id_fields = ('eleve', 'devoir')
