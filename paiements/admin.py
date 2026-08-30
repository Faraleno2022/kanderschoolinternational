from django.contrib import admin
from django.db import transaction

from administration.corbeille import CorbeilleAdminMixin, archiver_avant_suppression

from .models import (
    TypePaiement, ModePaiement, Paiement, HistoriqueModificationPaiement,
    RemiseReduction, EcheancierPaiement, TwilioInboundMessage,
    ConfigurationPaiement,
)


@admin.register(TypePaiement)
class TypePaiementAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ("nom", "actif")
    search_fields = ("nom",)
    list_filter = ("actif",)


@admin.register(ModePaiement)
class ModePaiementAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ("nom", "frais_supplementaires", "actif")
    search_fields = ("nom",)
    list_filter = ("actif",)


@admin.register(Paiement)
class PaiementAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ("numero_recu", "eleve", "type_paiement", "mode_paiement", "montant", "date_paiement", "statut")
    search_fields = ("numero_recu", "eleve__nom", "eleve__prenom", "eleve__matricule")
    list_filter = ("statut", "type_paiement", "mode_paiement")
    date_hierarchy = "date_paiement"

    def save_model(self, request, obj, form, change):
        if change:
            obj._audit_user = request.user
            obj._audit_reason = "Modification depuis l'administration Django"
        super().save_model(request, obj, form, change)
        if change:
            from .soldes import recalculer_echeancier
            echeancier = EcheancierPaiement.objects.filter(
                eleve_id=obj.eleve_id,
                annee_scolaire=obj.annee_scolaire,
                ecole_reference_id=obj.ecole_encaissement_id,
            ).first()
            if echeancier:
                recalculer_echeancier(echeancier)

    @transaction.atomic
    def delete_model(self, request, obj):
        archiver_avant_suppression(obj, request.user)
        obj.supprimer_definitivement(
            utilisateur=request.user,
            motif='Suppression définitive depuis l’administration Django',
        )

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        for obj in queryset.select_related('eleve'):
            archiver_avant_suppression(obj, request.user)
            obj.supprimer_definitivement(
                utilisateur=request.user,
                motif='Suppression définitive en masse depuis l’administration Django',
            )


@admin.register(HistoriqueModificationPaiement)
class HistoriqueModificationPaiementAdmin(admin.ModelAdmin):
    list_display = (
        'date_modification', 'numero_recu', 'eleve', 'utilisateur', 'motif',
    )
    list_filter = ('date_modification', 'utilisateur')
    search_fields = ('numero_recu', 'eleve', 'motif', 'utilisateur__username')
    readonly_fields = (
        'paiement', 'numero_recu', 'eleve', 'utilisateur', 'motif',
        'champs_modifies', 'donnees_avant', 'donnees_apres', 'date_modification',
    )
    date_hierarchy = 'date_modification'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RemiseReduction)
class RemiseReductionAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ("nom", "type_remise", "valeur", "motif", "actif")
    search_fields = ("nom",)
    list_filter = ("type_remise", "motif", "actif")


@admin.register(EcheancierPaiement)
class EcheancierPaiementAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ("eleve", "annee_scolaire", "statut", "total_du", "total_paye")
    search_fields = ("eleve__nom", "eleve__prenom", "eleve__matricule")


@admin.register(TwilioInboundMessage)
class TwilioInboundMessageAdmin(admin.ModelAdmin):
    list_display = ("received_at", "channel", "from_number", "to_number", "message_sid", "delivery_status")
    list_filter = ("channel", "delivery_status")
    search_fields = ("from_number", "to_number", "message_sid", "body")
    date_hierarchy = "received_at"


@admin.register(ConfigurationPaiement)
class ConfigurationPaiementAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ("classe", "montant_inscription", "montant_scolarite", "nombre_tranches", "montant_total")
    search_fields = ("classe__nom", "classe__ecole__nom")
    list_filter = ("nombre_tranches", "classe__niveau")
    readonly_fields = ("montant_total", "montant_par_tranche", "repartition_tranches_affichage",
                       "date_creation", "date_modification")

    @admin.display(description="Répartition exacte des tranches (somme = scolarité)")
    def repartition_tranches_affichage(self, obj):
        if not obj or not obj.pk:
            return "-"
        tranches = obj.repartition_tranches()
        if not tranches:
            return "-"
        details = " + ".join(f"{t:,.0f}" for t in tranches)
        return f"{details} = {sum(tranches):,.0f} GNF"
