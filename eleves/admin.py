from django.contrib import admin
from django.utils.html import format_html
from .models import Ecole, Classe, GrilleTarifaire


@admin.register(Ecole)
class EcoleAdmin(admin.ModelAdmin):
    list_display = ("nom", "etat", "code_prefixe", "telephone", "email", "directeur", "censeur", "created_by", "logo_mini")
    list_filter = ("etat",)
    search_fields = ("nom", "directeur", "censeur", "telephone", "email")
    readonly_fields = ("logo_preview", "image_preview")
    fieldsets = (
        ("Identité", {
            "fields": ("nom", "directeur", "censeur", "etat", "created_by")
        }),
        ("Paramètres matricules", {
            "fields": ("code_prefixe",),
            "description": "Préfixe d'école pour les matricules (ex: AL-FUR/). Laissez vide pour ne pas utiliser de préfixe explicite."
        }),
        ("Coordonnées", {
            "fields": ("adresse", "telephone", "telephone2", "telephone3", "email")
        }),
        ("Logo & Image", {
            "fields": ("logo", "logo_preview", "image", "image_preview"),
            "description": "Logo pour filigrane et en-tetes. Photo de l'ecole pour le livret scolaire."
        }),
    )
    actions = ("valider_ecoles", "rejeter_ecoles")

    def delete_queryset(self, request, queryset):
        """Suppression en masse : passer par delete() de chaque instance pour
        neutraliser le suivi de synchronisation (cf. Ecole.delete)."""
        for ecole in queryset:
            ecole.delete()

    def valider_ecoles(self, request, queryset):
        updated = queryset.update(etat="VALIDE")
        self.message_user(request, f"{updated} école(s) validée(s).")
    valider_ecoles.short_description = "Valider les écoles sélectionnées"

    def rejeter_ecoles(self, request, queryset):
        updated = queryset.update(etat="REJETE")
        self.message_user(request, f"{updated} école(s) rejetée(s).")
    rejeter_ecoles.short_description = "Rejeter les écoles sélectionnées"

    def logo_preview(self, obj):
        if getattr(obj, 'logo', None) and getattr(obj.logo, 'url', None):
            return format_html('<img src="{}" style="max-height:80px; border:1px solid #ddd; padding:2px;" />', obj.logo.url)
        return "—"
    logo_preview.short_description = "Aperçu du logo"

    def logo_mini(self, obj):
        if getattr(obj, 'logo', None) and getattr(obj.logo, 'url', None):
            return format_html('<img src="{}" style="height:24px; width:auto;" />', obj.logo.url)
        return ""
    logo_mini.short_description = "Logo"

    def image_preview(self, obj):
        if getattr(obj, 'image', None) and getattr(obj.image, 'url', None):
            return format_html('<img src="{}" style="max-height:120px; border:1px solid #ddd; padding:2px;" />', obj.image.url)
        return "—"
    image_preview.short_description = "Apercu de l'image"


@admin.register(Classe)
class ClasseAdmin(admin.ModelAdmin):
    list_display = ("nom", "niveau", "annee_scolaire", "ecole")
    list_filter = ("ecole", "niveau", "annee_scolaire")
    search_fields = ("nom", "ecole__nom")


@admin.register(GrilleTarifaire)
class GrilleTarifaireAdmin(admin.ModelAdmin):
    list_display = (
        "ecole", "niveau", "annee_scolaire",
        "frais_inscription", "tranche_1", "tranche_2", "tranche_3",
    )
    list_filter = ("ecole", "niveau", "annee_scolaire")
    search_fields = ("ecole__nom",)
    fieldsets = (
        ("Ciblage", {
            "fields": ("ecole", "niveau", "annee_scolaire"),
        }),
        ("Montants", {
            "fields": (
                "frais_inscription", "frais_reinscription",
                "tranche_1", "tranche_2", "tranche_3",
            ),
        }),
        ("Périodes (texte)", {
            "classes": ("collapse",),
            "fields": ("periode_1", "periode_2", "periode_3"),
        }),
        ("Échéances par défaut (dates)", {
            "fields": (
                "date_echeance_inscription_defaut",
                "date_echeance_tranche_1_defaut",
                "date_echeance_tranche_2_defaut",
                "date_echeance_tranche_3_defaut",
            ),
            "description": "Si ces dates sont renseignées, elles seront utilisées pour initialiser les échéanciers des élèves de cette école/niveau/année."
        }),
    )
