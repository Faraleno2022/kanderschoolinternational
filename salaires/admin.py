from django.contrib import admin
from django import forms
from .models import (
    Enseignant, TypeEnseignant, StatutEnseignant,
    AffectationClasse, AvanceSalaire, PeriodeSalaire, EtatSalaire,
    DetailHeuresClasse, PresenceEnseignant
)

from administration.corbeille import CorbeilleAdminMixin


class AvanceSalaireAdminForm(forms.ModelForm):
    class Meta:
        model = AvanceSalaire
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        enseignant = cleaned_data.get('enseignant')
        periode = cleaned_data.get('periode')
        montant = cleaned_data.get('montant')
        statut = cleaned_data.get('statut')
        if periode and periode.cloturee:
            self.add_error(
                'periode',
                'Une avance ne peut pas être affectée à une période clôturée.',
            )
        if enseignant and periode and EtatSalaire.objects.filter(
            enseignant=enseignant,
            periode=periode,
            valide=True,
        ).exists():
            self.add_error(
                'periode',
                'La paie de cette période est déjà validée.',
            )
        if (
            enseignant and periode and montant
            and statut == AvanceSalaire.Statut.APPROUVEE
        ):
            from .services import plafond_avance_disponible

            plafond = plafond_avance_disponible(
                enseignant,
                periode,
                exclure_avance=self.instance if self.instance.pk else None,
            )
            if montant > plafond:
                self.add_error(
                    'montant',
                    f"Le montant dépasse le salaire disponible ({plafond:,.0f} GNF).",
                )
        return cleaned_data


@admin.register(AvanceSalaire)
class AvanceSalaireAdmin(admin.ModelAdmin):
    form = AvanceSalaireAdminForm
    list_display = (
        'enseignant', 'periode', 'montant', 'date_avance',
        'mode_paiement', 'reference_paiement', 'statut',
    )
    list_filter = ('statut', 'mode_paiement', 'periode__annee', 'periode__mois', 'enseignant__ecole')
    search_fields = (
        'enseignant__nom', 'enseignant__prenoms', 'reference_paiement',
        'motif', 'observations',
    )
    date_hierarchy = 'date_avance'
    list_select_related = ('enseignant', 'enseignant__ecole', 'periode')
    readonly_fields = (
        'cree_par', 'approuvee_par', 'annulee_par', 'date_creation',
        'date_modification', 'date_approbation', 'date_deduction', 'date_annulation',
    )
    fieldsets = (
        ('Bénéficiaire et déduction', {'fields': ('enseignant', 'periode', 'montant', 'date_avance')}),
        ('Versement', {'fields': ('mode_paiement', 'reference_paiement', 'motif', 'observations')}),
        ('Suivi', {'fields': ('statut', 'motif_annulation')}),
        ('Traçabilité', {
            'fields': (
                'cree_par', 'approuvee_par', 'annulee_par', 'date_creation',
                'date_modification', 'date_approbation', 'date_deduction', 'date_annulation',
            ),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        from django.utils import timezone
        from .services import synchroniser_avances_etat

        ancienne_cible = None
        if change:
            ancienne_cible = AvanceSalaire.objects.filter(pk=obj.pk).values_list(
                'enseignant_id', 'periode_id'
            ).first()
        if not change:
            obj.cree_par = request.user
        if obj.statut == AvanceSalaire.Statut.APPROUVEE and not obj.date_approbation:
            obj.approuvee_par = request.user
            obj.date_approbation = timezone.now()
        if obj.statut == AvanceSalaire.Statut.ANNULEE and not obj.date_annulation:
            obj.annulee_par = request.user
            obj.date_annulation = timezone.now()
        super().save_model(request, obj, form, change)
        nouvelle_cible = (obj.enseignant_id, obj.periode_id)
        if ancienne_cible and ancienne_cible != nouvelle_cible:
            ancien_enseignant = Enseignant.objects.get(pk=ancienne_cible[0])
            ancienne_periode = PeriodeSalaire.objects.get(pk=ancienne_cible[1])
            synchroniser_avances_etat(ancien_enseignant, ancienne_periode)
        synchroniser_avances_etat(obj.enseignant, obj.periode)

    def delete_model(self, request, obj):
        from .services import synchroniser_avances_etat

        cible = (obj.enseignant, obj.periode)
        super().delete_model(request, obj)
        synchroniser_avances_etat(*cible)


@admin.register(PresenceEnseignant)
class PresenceEnseignantAdmin(CorbeilleAdminMixin, admin.ModelAdmin):
    list_display = ['enseignant', 'date', 'statut', 'heure_arrivee', 'heure_depart', 'heures_travaillees', 'justifie']
    list_filter = ['statut', 'date', 'justifie', 'enseignant__ecole']
    search_fields = ['enseignant__nom', 'enseignant__prenoms', 'observations']
    date_hierarchy = 'date'
    ordering = ['-date', 'enseignant__nom']
    
    fieldsets = (
        ('Informations principales', {
            'fields': ('enseignant', 'date', 'statut')
        }),
        ('Heures', {
            'fields': ('heure_arrivee', 'heure_depart', 'heures_travaillees')
        }),
        ('Détails', {
            'fields': ('observations', 'justifie')
        }),
        ('Métadonnées', {
            'fields': ('pointe_par', 'date_creation', 'date_modification'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['date_creation', 'date_modification']
    
    def save_model(self, request, obj, form, change):
        if not change:  # Nouveau pointage
            obj.pointe_par = request.user
        super().save_model(request, obj, form, change)
